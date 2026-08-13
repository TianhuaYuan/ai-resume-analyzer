"""A3 实体链接服务（借鉴 third_party/mem0 + graphiti，用户要求实施前参看源码）。

三表：``resume_entities`` / ``resume_entity_facts`` / ``resume_episodes``（见 models/resume_entity.py）

流程（对齐 graphiti ``resolve_extracted_nodes`` 的确定性快路径 + LLM 兜底两级消解）：
1. **提取**：L3 画像（summary + skills）→ episode 锚点；skills 直接成实体（确定性，零 LLM）；
   summary 用 LLM 提取实体三元组（name/entity_type/description），prompt 纪律照抄 graphiti
   extract_nodes（只提取显式提及、最具体形式、排除泛词、when in doubt do NOT extract）
2. **消解** resolve_entity：
   - 快路径 1：``name_normalized`` 精确匹配唯一命中 → 复用既有实体（零 LLM 成本）
   - 快路径 2：name embedding 相似度 ≥ 0.9 且唯一最高 → 复用（mem0 语义消解阈值 0.95 的放宽版，
     graphiti 候选阈值 0.6）
   - 兜底：候选打包 LLM 判定（graphiti dedupe_nodes："same real-world object or concept" 准则 +
     越界防御），-1 新建
3. **ADD-only 事实 + F1 矛盾失效**：``(entity_id, fact_text_norm)`` 唯一约束天然去重；每次新事实
   同步写一条 L4 记忆（save_memory 幂等，``fact.linked_memory_id`` 双向关联 → mem0 linked_memory_ids
   索引）。写入前检测同实体同属性值明确矛盾且仍有效的旧事实（graphiti invalid_at 双时态）→ 置
   ``invalid_at`` 并同步失效其 L4 记忆；只对明确矛盾的值生效，不误伤补充性事实（新增技能）
4. **recall boost（F2 三信号）**：query 命中实体（子串/语义双通道）→ 该实体有效事实
   （``invalid_at IS NULL``）与语义召回记忆做 向量 / 实体 / BM25 三信号加性融合（mem0 借鉴，
   权重默认 0.4/0.4/0.2），输出 ``score_details`` 供前端/调试 explain
"""

import json
import logging
import math
import re
import unicodedata
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.retry import with_retry
from models.resume_entity import ResumeEntity, ResumeEntityFact, ResumeEpisode
from services.memory.memory_store import (
    expire_memory,
    fuse_three_signals,
    recall_memory,
    save_memory,
    score_bm25,
)
from services.rag.pipeline import llm_generate
from services.rag.retrieval import get_embeddings

logger = logging.getLogger(__name__)

# ── 消解阈值（graphiti/mem0 参考值）────────────────────────────
# mem0 语义消解阈值 0.95；graphiti 候选召回 0.6 + LLM 兜底。取中间值：≥0.9 直接判同一实体
SIMILARITY_CONFIRM = 0.9
# embedding 候选与 query 的相似度阈值（recall boost 实体命中判定）
ENTITY_MATCH_THRESHOLD = 0.8
# 实体候选上限（同简历实体超限时截断，控制 LLM 兜底 prompt 体积）
MAX_CANDIDATES = 100

# ── 实体类型枚举（对齐 graphiti entity_types 上下文）────────────
ENTITY_TYPES = ("skill", "company", "school", "job_title", "person", "goal", "tool", "other")

# ── LLM prompt：summary 实体提取（graphiti extract_nodes 纪律）───
_EXTRACT_ENTITIES_SYSTEM = (
    "你是简历实体提取器。从用户简历总结文本中提取命名实体。\n"
    "要求：\n"
    "1. 只提取文本中【显式提及】的实体；代词必须消解为具体名字\n"
    "2. 用最具体的形式（如「后端开发」而非「开发」）\n"
    "3. 不提取抽象概念、感受、泛词、时间、数字、关系、动作\n"
    "4. 每个实体类型从以下枚举选择：skill / company / school / job_title / person / goal / tool / other\n"
    "5. When in doubt, do NOT extract（宁缺毋滥）\n"
    "6. description 是该实体的一句原子事实（自包含、可独立理解，不依赖上下文）\n"
    "严格返回 JSON 数组，不要包含其他文字：\n"
    '[{"name": "实体名", "entity_type": "skill", "description": "关于该实体的一句事实"}]'
)

# ── LLM prompt：实体消解兜底（graphiti dedupe_nodes 准则）──────
_RESOLVE_SYSTEM = (
    "判断新实体与候选既有实体是否指代【同一个现实对象或概念】（refer to the same real-world "
    "object or concept）。\n"
    "准则：\n"
    "- 名称相同、或明显是同一对象的简称/别名（如「字节跳动」与「字节」）→ 判重复，返回候选 id\n"
    "- 名字相似但指代不同实例（如 Java 编程语言 vs Java 岛）→ 不判重复，返回 -1\n"
    "- 候选列表为空，或与任何候选都不同 → 返回 -1\n"
    '严格返回 JSON：{"duplicate_candidate_id": <候选 id 或 -1>}'
)


# ═══════════════════════════════════════════════════════════════
# 归一化与相似度
# ═══════════════════════════════════════════════════════════════


def normalize_name(name: str) -> str:
    """NFKC 归一化 + 小写 + 折叠空白（graphiti _normalize_string_exact 同款）。

    确定性消解快路径的索引键；同时兼容全角/半角（对齐 core/security._normalize_text）。
    """
    if not name:
        return ""
    normalized = unicodedata.normalize("NFKC", name).strip().lower()
    return " ".join(normalized.split())


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


def _shannon_entropy(s: str) -> float:
    """字符 Shannon 熵（graphiti _has_high_entropy 同款判定基础）。"""
    if not s:
        return 0.0
    counts: dict[str, int] = {}
    for c in s:
        counts[c] = counts.get(c, 0) + 1
    n = len(s)
    return -sum((cnt / n) * math.log2(cnt / n) for cnt in counts.values())


def _is_low_entropy_name(name: str) -> bool:
    """熵门控（graphiti _NAME_ENTROPY_THRESHOLD=1.5 对照）：低信息量名字不信任模糊匹配。

    过短（<2 字符）或 Shannon 熵 < 1.5 的名字（如「字节」「Java」的简称）embedding
    相似度高但极易误并（Java 编程语言 vs Java 岛）——跳过 embedding 快路径，直接升级
    LLM 兜底判定，由「same real-world object or concept」准则把关。
    """
    if len(name) < 2:
        return True
    return _shannon_entropy(name) < 1.5


def _promote_entity(entity: "ResumeEntity", entity_type: str, description: str | None) -> bool:
    """类型提升（graphiti _promote_resolved_node 对照）：消解命中时合并更具体信息。

    - ``other`` → 具体类型提升（保留既有更具体类型，不降级）
    - summary 为空时补新描述（增量累积，graphiti summary 语义）
    返回是否发生变更（供日志/测试观察）。
    """
    promoted = False
    if entity.entity_type == "other" and entity_type != "other":
        entity.entity_type = entity_type
        promoted = True
    if not entity.summary and description:
        entity.summary = description[:2000]
        promoted = True
    return promoted


def parse_skills_text(text: str) -> list[str]:
    """从 skills 分析文本解析技能名列表（宽松解析，容忍 LLM 输出格式漂移）。

    处理：JSON 数组 / markdown 行列表 / 分类标题（"1. 编程语言："）剥离 / 顿号逗号分隔。
    技能分类名本身（如"编程语言"）可能残留为噪声技能，实体提取对其容忍。
    """
    if not text or not text.strip():
        return []
    raw = text.strip()
    # 1. JSON 数组
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(s).strip() for s in data if str(s).strip()]
    except (json.JSONDecodeError, ValueError):
        pass
    # 2. 行列表
    out: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        # 分类标题行（"编程语言：" / "1. 框架/工具"）→ 剥离或跳过
        if "：" in line or ":" in line:
            head, rest = re.split(r"[：:]", line, maxsplit=1)
            if re.fullmatch(r"[一-鿿/·]+", head.strip()):
                line = rest.strip()
            if not line:
                continue
        # 去行首序号/markdown 列表符号（分两步：`- Python` 无数字 → 先剥符号；`1. Python` → 再剥序号）
        line = re.sub(r"^[-*•]\s*", "", line).strip()
        line = re.sub(r"^\d+[.、)）]\s*", "", line).strip()
        if not line:
            continue
        # 3. 顿号/逗号分隔多技能
        for part in re.split(r"[、，,;；]", line):
            part = part.strip().strip("`\"' ")
            if part and part not in out:
                out.append(part)
    return out


# ═══════════════════════════════════════════════════════════════
# 消解：resolve_entity（快路径 + LLM 兜底）
# ═══════════════════════════════════════════════════════════════


async def _exact_match_entity(
    db: AsyncSession, *, user_id: int, resume_id: int, name_normalized: str
) -> ResumeEntity | None:
    """快路径 1：name_normalized 精确匹配。唯一命中返回；多候选（同名不同实例）返回 None 升级 LLM。"""
    result = await db.execute(
        select(ResumeEntity).where(
            ResumeEntity.user_id == user_id,
            ResumeEntity.resume_id == resume_id,
            ResumeEntity.name_normalized == name_normalized,
        )
    )
    rows = result.scalars().all()
    if len(rows) == 1:
        return rows[0]
    return None  # 0 或 ≥2：0 走下一步，≥2 有歧义（graphiti：多个候选同名 → 升级 LLM）


async def _semantic_match_entity(
    db: AsyncSession, *, user_id: int, resume_id: int, name: str
) -> tuple[ResumeEntity | None, list[ResumeEntity]]:
    """快路径 2：候选实体 name embedding 相似度。

    返回 (唯一最高且 ≥ SIMILARITY_CONFIRM 的实体 | None, 候选列表)。
    候选列表供 LLM 兜底复用，避免二次查询。
    """
    result = await db.execute(
        select(ResumeEntity)
        .where(ResumeEntity.user_id == user_id, ResumeEntity.resume_id == resume_id)
        .limit(MAX_CANDIDATES)
    )
    candidates = list(result.scalars().all())
    if not candidates:
        return None, []

    try:
        vectors = await get_embeddings([name] + [c.name for c in candidates], resume_id)
    except Exception as e:
        logger.warning("实体语义消解 embedding 失败（跳过快路径 2）: %s", e)
        return None, candidates
    query_vec, name_vecs = vectors[0], vectors[1:]
    best, best_sim, second = None, 0.0, 0.0
    for cand, vec in zip(candidates, name_vecs):
        sim = _cosine(query_vec, vec)
        if sim > best_sim:
            second = best_sim
            best, best_sim = cand, sim
        elif sim > second:
            second = sim
    if best is not None and best_sim >= SIMILARITY_CONFIRM and best_sim - second >= 0.05:
        return best, candidates
    return None, candidates


async def _llm_resolve_entity(
    db: AsyncSession,
    *,
    user_id: int,
    resume_id: int,
    name: str,
    entity_type: str,
    candidates: list[ResumeEntity],
) -> int:
    """LLM 兜底消解（graphiti dedupe_nodes：返回 duplicate_candidate_id，-1 = 新建）。

    LLM 不可用/解析失败 → 新建（保守策略，宁建不误并）。
    """
    if not candidates:
        return -1
    cand_lines = []
    for i, c in enumerate(candidates):
        summary = (c.summary or "")[:120]
        cand_lines.append(f"{i}: {{name: {c.name}, type: {c.entity_type}, summary: {summary}}}")
    user_prompt = f"新实体：{{name: {name}, type: {entity_type}}}\n候选既有实体：\n" + "\n".join(
        cand_lines
    )
    try:
        raw = await with_retry(
            llm_generate,
            system=_RESOLVE_SYSTEM,
            user=user_prompt,
            temperature=0.0,
            max_tokens=50,
            user_id=user_id,
            fallback='{"duplicate_candidate_id": -1}',
            max_retries=1,
        )
        data = json.loads(raw.strip())
        dup_id = int(data.get("duplicate_candidate_id", -1))
        # 越界防御（graphiti 同款）：非法 id 一律按新建处理
        if 0 <= dup_id < len(candidates):
            return dup_id
        return -1
    except Exception as e:
        logger.warning("LLM 实体消解失败（按新建处理）: %s", e)
        return -1


async def resolve_entity(
    db: AsyncSession,
    *,
    user_id: int,
    resume_id: int,
    name: str,
    entity_type: str,
    description: str | None = None,
) -> tuple[ResumeEntity, bool]:
    """消解实体名 → 复用既有实体或新建。返回 (entity, created)。

    - 快路径 1：name_normalized 精确匹配唯一命中 → 复用（零 LLM）
    - 快路径 2：name embedding 相似度 ≥ 0.9 且明显领先 → 复用（mem0 语义消解）；
      熵门控（graphiti）：短名/低熵名不信任模糊匹配，直接升级 LLM
    - 兜底：LLM 判定（graphiti dedupe_nodes 准则 + 越界防御）
    - 命中复用时做类型提升（graphiti _promote_resolved_node：other→具体类型、补 summary）
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("实体名不能为空")
    name_norm = normalize_name(name)

    entity = await _exact_match_entity(
        db, user_id=user_id, resume_id=resume_id, name_normalized=name_norm
    )
    if entity is not None:
        _promote_entity(entity, entity_type, description)
        return entity, False

    # 熵门控：低信息量名字跳过 embedding 快路径（防「Java 语言 vs Java 岛」误并）
    if _is_low_entropy_name(name):
        candidates_result = await db.execute(
            select(ResumeEntity)
            .where(ResumeEntity.user_id == user_id, ResumeEntity.resume_id == resume_id)
            .limit(MAX_CANDIDATES)
        )
        candidates = list(candidates_result.scalars().all())
    else:
        matched, candidates = await _semantic_match_entity(
            db, user_id=user_id, resume_id=resume_id, name=name
        )
        if matched is not None:
            _promote_entity(matched, entity_type, description)
            return matched, False

    dup_idx = await _llm_resolve_entity(
        db,
        user_id=user_id,
        resume_id=resume_id,
        name=name,
        entity_type=entity_type,
        candidates=candidates,
    )
    if dup_idx >= 0 and dup_idx < len(candidates):
        _promote_entity(candidates[dup_idx], entity_type, description)
        return candidates[dup_idx], False

    entity = ResumeEntity(
        user_id=user_id,
        resume_id=resume_id,
        name=name[:128],
        name_normalized=name_norm[:128],
        entity_type=entity_type if entity_type in ENTITY_TYPES else "other",
        summary=description[:2000] if description else None,
        linked_memory_ids=[],
    )
    db.add(entity)
    await db.flush()  # 取 id
    logger.info(
        "实体新建: user=%d resume=%d name=%s type=%s", user_id, resume_id, name, entity_type
    )
    return entity, True


# ═══════════════════════════════════════════════════════════════
# 事实写入（ADD-only）
# ═══════════════════════════════════════════════════════════════


def _fact_norm(fact_text: str) -> str:
    """事实归一化键（截断到 500 匹配 VARCHAR 列）。

    相比实体名归一化更严格：删除全部空白（「掌握技能： python」与「掌握技能：Python」
    视为同一事实），避免标点后空格差异导致重复累积。
    """
    norm = normalize_name(fact_text)
    return re.sub(r"\s+", "", norm)[:500]


# ═══════════════════════════════════════════════════════════════
# F1 矛盾型时序失效（graphiti invalid_at 双时态借鉴）
# ═══════════════════════════════════════════════════════════════
# 单值谓词：同一时刻一个值，值变化即矛盾（如职业/求职意向/所在城市）
_SINGLE_VALUE_PREDICATES = frozenset(
    {
        "职业方向", "求职意向", "目标岗位", "当前职业", "所在城市", "意向城市",
        "目标城市", "目标公司", "就职公司", "学校", "毕业院校", "最高学历",
        "学历", "姓名", "性别", "当前状态",
    }
)
# 多值/补充性谓词：新增值不视为矛盾（技能、经历、项目等可共存）
_ADDITIVE_PREDICATES = frozenset(
    {
        "技能", "掌握技能", "掌握", "熟悉", "了解", "会", "使用", "用过",
        "工具", "框架", "参与", "做过", "负责", "经历", "项目", "成绩",
        "证书", "获奖", "荣誉", "兴趣", "爱好",
    }
)
# 单值实体类型：值变化即矛盾（skill 是明显多值类型，永不判矛盾）
_SINGLE_VALUE_ENTITY_TYPES = frozenset(
    {"job_title", "goal", "school", "company", "person", "city"}
)


def _split_predicate_value(fact_text: str) -> tuple[str, str] | None:
    """拆「谓词：值」：按首个全/半角冒号。无冒号 → None（无法确认同属性，不判矛盾）。

    事实若不带「谓词：值」结构（如纯描述「五年后端经验」），无法确定属性是否同一，
    保守跳过，避免误伤补充性描述。
    """
    text = (fact_text or "").strip()
    m = re.split(r"[:：]", text, maxsplit=1)
    if len(m) == 2 and m[0].strip() and m[1].strip():
        return m[0].strip(), m[1].strip()
    return None


def _value_norm(value: str) -> str:
    """值归一化：NFKC + 去空白/标点，用于「明确矛盾」判定。"""
    return re.sub(
        r"[\s，,。.、；;：:！!？?（）()【】\[\]\"'`《》<>~～\-—]",
        "",
        normalize_name(value or ""),
    )


def _values_conflict(new_value: str, old_value: str) -> bool:
    """值是否【明确矛盾】：非空、不相同、且不互为子串（互为子串视为补充细节/简称）。

    例：「前端开发」vs「后端开发」→ 矛盾；「北京市」vs「北京」→ 不矛盾（补充/简称）。
    """
    a, b = _value_norm(new_value), _value_norm(old_value)
    if not a or not b:
        return False
    if a == b:
        return False
    if a in b or b in a:
        return False
    return True


def _find_conflicting_facts(new_fact: dict, existing_facts: list[dict]) -> list[dict]:
    """F1：找出与 new_fact 明确矛盾且仍有效的旧事实（供调用方置 invalid_at）。

    冲突判定 = 同实体 + 同谓词/同属性 + 值明确矛盾，且谓词/实体类型非补充性（多值共存）。
    保守策略（宁漏勿伤）：任一条件不确定即不判，绝不对技能等补充性事实误失效。

    Args:
        new_fact: ``{"entity_id": int|None, "entity_type": str, "fact_text": str}``
        existing_facts: ``[{"id": int, "entity_id": int|None, "entity_type": str,
                            "fact_text": str, ...}]``

    Returns:
        ``existing_facts`` 中与 ``new_fact`` 明确矛盾的子集。
    """
    new_entity = new_fact.get("entity_id")
    new_type = (new_fact.get("entity_type") or "").strip()
    if new_type == "skill":
        return []  # 技能实体多值共存，新增技能永不视为矛盾

    parsed_new = _split_predicate_value(new_fact.get("fact_text", ""))
    if parsed_new is None:
        return []
    new_pred, new_val = parsed_new
    if new_pred in _ADDITIVE_PREDICATES:
        return []  # 补充性谓词：多值共存（新增技能/经历不算矛盾）
    if new_pred not in _SINGLE_VALUE_PREDICATES and new_type not in _SINGLE_VALUE_ENTITY_TYPES:
        return []  # 未知谓词且实体非单值类型：无法确认同属性，保守不判

    conflicts: list[dict] = []
    for old in existing_facts:
        if new_entity is not None and old.get("entity_id") not in (None, new_entity):
            continue
        if (old.get("entity_type") or "") == "skill":
            continue
        parsed_old = _split_predicate_value(old.get("fact_text", ""))
        if parsed_old is None:
            continue
        old_pred, old_val = parsed_old
        if old_pred != new_pred:
            continue  # 不同属性 → 补充性事实，不判
        if old_pred in _ADDITIVE_PREDICATES:
            continue
        if _values_conflict(new_val, old_val):
            conflicts.append(old)
    return conflicts


async def add_fact(
    db: AsyncSession,
    *,
    user_id: int,
    resume_id: int,
    entity: ResumeEntity,
    episode: ResumeEpisode,
    fact_text: str,
    importance: float = 0.5,
) -> ResumeEntityFact | None:
    """ADD-only 写事实：同 (entity_id, fact_text_norm) 已存在 → 跳过（返回 None）。

    F1 矛盾失效：写入前检测同实体同属性值明确矛盾的旧事实（invalid_at IS NULL）→ 置
    invalid_at 并同步失效其 L4 记忆（graphiti 双时态），保守不误伤技能等补充性事实。
    新事实同步写一条 L4 记忆（save_memory 幂等，同内容不重复），
    并双向关联：fact.linked_memory_id ↔ entity.linked_memory_ids（mem0 索引）。
    """
    fact_text = (fact_text or "").strip()
    if not fact_text:
        return None
    norm = _fact_norm(fact_text)
    existing = await db.execute(
        select(ResumeEntityFact).where(
            ResumeEntityFact.entity_id == entity.id,
            ResumeEntityFact.fact_text_norm == norm,
            ResumeEntityFact.invalid_at.is_(None),
        )
    )
    if existing.scalar_one_or_none() is not None:
        return None  # ADD-only：同事实重复提取自动跳过

    # F1 矛盾型时序失效（graphiti 双时态）：同实体同属性值明确矛盾且仍有效的旧事实 → 置 invalid_at。
    # 只对明确矛盾的值失效（技能等补充性事实由 _find_conflicting_facts 保守排除）。
    # skill 实体多值共存（技能清单累积），整个跳过省一次查询。
    valid_rows: list[ResumeEntityFact] = []
    if entity.entity_type != "skill":
        valid_rows = (
            await db.execute(
                select(ResumeEntityFact).where(
                    ResumeEntityFact.entity_id == entity.id,
                    ResumeEntityFact.invalid_at.is_(None),
                )
            )
        ).scalars().all()
    if valid_rows:
        now = datetime.now(timezone.utc)
        existing_dicts = [
            {
                "id": f.id,
                "entity_id": f.entity_id,
                "entity_type": entity.entity_type,
                "fact_text": f.fact_text,
                "linked_memory_id": f.linked_memory_id,
            }
            for f in valid_rows
        ]
        conflicting = _find_conflicting_facts(
            {
                "entity_id": entity.id,
                "entity_type": entity.entity_type,
                "fact_text": fact_text,
            },
            existing_dicts,
        )
        for old in conflicting:
            row = next((f for f in valid_rows if f.id == old["id"]), None)
            if row is None:
                continue
            row.invalid_at = now
            row.expired_at = now  # graphiti 双时态：expired_at = 系统发现失效的壁钟时间
            if row.linked_memory_id:
                try:
                    await expire_memory(user_id, row.linked_memory_id)
                except Exception as e:
                    logger.warning("矛盾事实 L4 记忆失效失败（不影响 SQL）: %s", e)
            logger.info(
                "事实矛盾失效: user=%d entity=%s 旧=%s 新=%s",
                user_id, entity.name, row.fact_text, fact_text,
            )

    # L4 记忆同步（memory_type="entity_fact" 便于与对话提炼区分）
    memory_id = None
    try:
        memory_id = await save_memory(
            user_id=user_id,
            snippet=fact_text,
            memory_type="entity_fact",
            importance=importance,
        )
    except Exception as e:
        logger.warning("实体事实 L4 记忆写入失败（不影响 SQL 落库）: %s", e)

    fact = ResumeEntityFact(
        user_id=user_id,
        resume_id=resume_id,
        entity_id=entity.id,
        episode_id=episode.id,
        fact_text=fact_text,
        fact_text_norm=norm,
        importance=importance,
        linked_memory_id=memory_id,
    )
    db.add(fact)

    # 双向索引：实体 ⇄ L4 记忆（mem0 linked_memory_ids）
    if memory_id:
        linked = list(entity.linked_memory_ids or [])
        if memory_id not in linked:
            entity.linked_memory_ids = linked + [memory_id]
    await db.flush()
    return fact


# ═══════════════════════════════════════════════════════════════
# L3 画像 → 实体提取（ADD-only）
# ═══════════════════════════════════════════════════════════════


async def _extract_entities_from_summary(user_id: int, summary: str) -> list[dict]:
    """LLM 提取 summary 中的实体三元组（name/entity_type/description）。

    失败返回空列表（不阻塞画像构建）；JSON 解析带降级（抗 ```json 包裹与截断）。
    """
    if not summary or not summary.strip():
        return []
    try:
        raw = await with_retry(
            llm_generate,
            system=_EXTRACT_ENTITIES_SYSTEM,
            user=summary[:4000],
            temperature=0.2,
            max_tokens=400,
            user_id=user_id,
            fallback="[]",
            max_retries=1,
        )
        data = json.loads(raw.strip())
        if not isinstance(data, list):
            return []
        out: list[dict] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            etype = str(item.get("entity_type", "other")).strip()
            desc = str(item.get("description", "")).strip()
            out.append(
                {
                    "name": name,
                    "entity_type": etype if etype in ENTITY_TYPES else "other",
                    "description": desc,
                }
            )
        return out
    except Exception as e:
        logger.warning("summary 实体提取 LLM 失败（跳过）: %s", e)
        return []


async def extract_entities_from_profile(
    db: AsyncSession,
    *,
    user_id: int,
    resume_id: int,
    summary: str | None = None,
    skills: list[str] | str | None = None,
) -> dict:
    """从 L3 画像（summary + skills）提取实体与事实（ADD-only，重复调用幂等）。

    触发点：build_l3_profile_background 完成后调用（memory.py）。
    skills 支持 list 或原始分析文本（内部 parse_skills_text 宽松解析）。

    Returns:
        {"episode_id": int, "entities": int, "facts": int, "memories": int, "skills": int}
    """
    if isinstance(skills, str):
        skills = parse_skills_text(skills)
    skills = skills or []

    # 1. episode 锚点（graphiti：episode 是所有提取的锚点）
    episode_content = summary or ""
    if skills:
        episode_content += "\n技能列表：" + "、".join(skills)
    if not episode_content.strip():
        return {"episode_id": None, "entities": 0, "facts": 0, "memories": 0, "skills": 0}

    episode = ResumeEpisode(
        user_id=user_id,
        resume_id=resume_id,
        source_type="l3_profile",
        content=episode_content[:5000],
    )
    db.add(episode)
    await db.flush()

    stats = {"episode_id": episode.id, "entities": 0, "facts": 0, "memories": 0, "skills": 0}
    fact_count = 0

    # 2. skills → 确定性实体（零 LLM）：每个技能一个实体 + 一条事实
    for skill in skills or []:
        skill = (skill or "").strip()
        if not skill:
            continue
        try:
            entity, _created = await resolve_entity(
                db,
                user_id=user_id,
                resume_id=resume_id,
                name=skill,
                entity_type="skill",
                description=f"简历技能：{skill}",
            )
            fact = await add_fact(
                db,
                user_id=user_id,
                resume_id=resume_id,
                entity=entity,
                episode=episode,
                fact_text=f"掌握技能：{skill}",
            )
            stats["entities"] += 1
            if fact is not None:
                fact_count += 1
            stats["skills"] += 1
        except Exception as e:
            logger.warning("技能实体提取失败（跳过）: %s %s", skill, e)

    # 3. summary → LLM 提取实体（graphiti extract_nodes 纪律）
    for item in await _extract_entities_from_summary(user_id, summary):
        try:
            entity, _created = await resolve_entity(
                db,
                user_id=user_id,
                resume_id=resume_id,
                name=item["name"],
                entity_type=item["entity_type"],
                description=item.get("description"),
            )
            fact_text = item.get("description") or f"{item['name']}（{item['entity_type']}）"
            fact = await add_fact(
                db,
                user_id=user_id,
                resume_id=resume_id,
                entity=entity,
                episode=episode,
                fact_text=fact_text,
            )
            stats["entities"] += 1
            if fact is not None:
                fact_count += 1
        except Exception as e:
            logger.warning("summary 实体落库失败（跳过）: %s", e)

    await db.commit()
    stats["facts"] = fact_count
    stats["memories"] = fact_count
    logger.info(
        "实体提取完成: user=%d resume=%d entities=%d facts=%d",
        user_id,
        resume_id,
        stats["entities"],
        stats["facts"],
    )
    return stats


# ═══════════════════════════════════════════════════════════════
# recall boost：实体命中 → 有效事实与语义召回 RRF 融合
# ═══════════════════════════════════════════════════════════════


async def _find_entities_in_query(
    db: AsyncSession, *, user_id: int, resume_id: int, query: str
) -> list[ResumeEntity]:
    """双通道实体命中：① 子串匹配（实体名出现在 query 中）② embedding 相似度 ≥ 阈值。

    通道②一次批量 embedding 调用（有缓存），失败静默降级为仅子串匹配。
    """
    q_norm = normalize_name(query)
    result = await db.execute(
        select(ResumeEntity)
        .where(
            ResumeEntity.user_id == user_id,
            ResumeEntity.resume_id == resume_id,
        )
        .limit(MAX_CANDIDATES)
    )
    entities = list(result.scalars().all())
    if not entities:
        return []

    hits: list[ResumeEntity] = []
    # 通道 ① 子串匹配（实体名出现在 query 中，如「我在字节的经历」命中「字节」）
    # 加英文词边界检查：防 "java" 误命中 "javascript"（英文字母/数字两侧才算独立词）
    for e in entities:
        name = e.name_normalized or ""
        if len(name) < 2:
            continue
        start = q_norm.find(name)
        if start < 0:
            continue

        def _ascii_alnum(ch: str) -> bool:
            return ch.isascii() and ch.isalnum()

        before = q_norm[start - 1] if start > 0 else ""
        after = (
            q_norm[start + len(name)]
            if start + len(name) < len(q_norm)
            else ""
        )
        if not _ascii_alnum(before) and not _ascii_alnum(after):
            hits.append(e)
    if hits:
        return hits

    # 通道 ② embedding 相似度（中文歧义时子串失败，靠语义）
    try:
        vectors = await get_embeddings([query] + [e.name for e in entities], resume_id)
    except Exception as e:
        logger.debug("实体命中 embedding 失败（降级子串匹配）: %s", e)
        return hits
    query_vec = vectors[0]
    for e, vec in zip(entities, vectors[1:]):
        if _cosine(query_vec, vec) >= ENTITY_MATCH_THRESHOLD:
            hits.append(e)
    return hits


async def recall_with_entity_boost(
    db: AsyncSession,
    *,
    user_id: int,
    resume_id: int,
    query: str,
    top_k: int = 5,
) -> list[dict]:
    """语义召回 + 实体链接增强（F2 三信号加性融合，mem0 借鉴）。

    三信号：
    - **vector**：recall_memory 的 embedding 余弦相似度原值（clamp 0-1）
    - **entity**：query 命中实体 → 该实体有效事实（``invalid_at IS NULL``），
      信号 = ``0.5 + 0.5*importance``（直接命中即强相关，最低 0.5）
    - **bm25**：候选池内 BM25 关键词分（复用 retrieval.py 同款 rank_bm25 + jieba 分词，
      池内按最大值归一化）
    加性融合权重默认 0.4/0.4/0.2（memory_store.W_VECTOR/W_ENTITY/W_BM25，可调常量）；
    某信号缺失时权重在剩余信号间重归一化。输出新增 ``score_details``（各信号分 + 融合分 + 权重）
    供前端/调试 explain；
    返回结构保持 ``[{memory_id, text, score, metadata}]`` 兼容（仅新增字段）。

    无实体命中时退化为纯语义召回（行为与现状一致，不改动返回结构）。
    """
    # 扩展候选池（BM25 重排需要足够候选）
    memories = await recall_memory(user_id=user_id, query=query, top_k=max(top_k * 4, 20))

    entities = await _find_entities_in_query(db, user_id=user_id, resume_id=resume_id, query=query)
    if not entities:
        return memories[:top_k]

    entity_ids = [e.id for e in entities]
    result = await db.execute(
        select(ResumeEntityFact)
        .where(
            ResumeEntityFact.user_id == user_id,
            ResumeEntityFact.resume_id == resume_id,
            ResumeEntityFact.entity_id.in_(entity_ids),
            ResumeEntityFact.invalid_at.is_(None),  # graphiti 双时态：只取当前有效事实
        )
        .order_by(ResumeEntityFact.importance.desc())
    )
    facts = result.scalars().all()
    if not facts:
        return memories[:top_k]

    # 候选池（按 text 去重）：entity 事实与其 L4 记忆同文本同 hash id，合并为同一候选
    fact_by_text: dict[str, ResumeEntityFact] = {}
    for f in facts:
        fact_by_text.setdefault(f.fact_text, f)

    pool: dict[str, dict] = {}
    for m in memories:
        pool.setdefault(
            m["text"],
            {
                "text": m["text"],
                "memory_id": m["memory_id"],
                "metadata": dict(m.get("metadata") or {}),
                "vector": m["score"],
                "entity": None,
                "bm25": None,
            },
        )
    for text, f in fact_by_text.items():
        entry = pool.get(text)
        entity_signal = 0.5 + 0.5 * float(f.importance)  # 直接实体命中：强相关，最低 0.5
        if entry is None:
            pool[text] = {
                "text": text,
                "memory_id": f.linked_memory_id or f"fact_{f.id}",
                "metadata": {
                    "source": "entity_fact",
                    "entity_id": f.entity_id,
                    "fact_id": f.id,
                },
                "vector": None,
                "entity": entity_signal,
                "bm25": None,
            }
        else:
            entry["entity"] = entity_signal
            entry["metadata"]["source"] = "entity_fact"
            entry["metadata"]["entity_id"] = f.entity_id
            entry["metadata"]["fact_id"] = f.id

    # BM25 第三信号（候选集重排模式，复用 retrieval.py 同款 BM25Okapi + jieba 分词）
    candidates = list(pool.values())
    bm25_scores = score_bm25(query, [c["text"] for c in candidates])
    for c, s in zip(candidates, bm25_scores):
        c["bm25"] = s

    fused = fuse_three_signals(candidates)
    out: list[dict] = []
    for item in fused:
        out.append(
            {
                "memory_id": item["memory_id"],
                "text": item["text"],
                "score": item["score"],
                "metadata": item["metadata"],
                "score_details": item["score_details"],
            }
        )
    return out[:top_k]


# ═══════════════════════════════════════════════════════════════
# 查询辅助（供测试与管理端复用）
# ═══════════════════════════════════════════════════════════════


async def list_entities(
    db: AsyncSession, *, user_id: int, resume_id: int, limit: int = 100
) -> list[dict]:
    """列出简历实体（含有效事实数）。"""
    result = await db.execute(
        select(ResumeEntity)
        .where(ResumeEntity.user_id == user_id, ResumeEntity.resume_id == resume_id)
        .order_by(ResumeEntity.id.asc())
        .limit(limit)
    )
    entities = result.scalars().all()
    out: list[dict] = []
    for e in entities:
        facts = await db.execute(
            select(ResumeEntityFact).where(
                ResumeEntityFact.entity_id == e.id,
                ResumeEntityFact.invalid_at.is_(None),
            )
        )
        out.append(
            {
                "id": e.id,
                "name": e.name,
                "entity_type": e.entity_type,
                "summary": e.summary,
                "fact_count": len(facts.scalars().all()),
            }
        )
    return out
