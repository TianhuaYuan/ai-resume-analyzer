"""A3 实体链接测试：消解（快路径/LLM 兜底）+ ADD-only 事实 + L3 画像提取 + recall boost。

参照：test_memory_expire.py 的 patch 模式（MockVectorStore/受控 embedding）。
向量与 LLM 全部 mock，不碰真实 Chroma/API。
"""

import pytest

from models.resume import Resume
from models.user import User
from services.memory import entity_link
from services.memory.entity_link import (
    add_fact,
    extract_entities_from_profile,
    list_entities,
    normalize_name,
    parse_skills_text,
    recall_with_entity_boost,
    resolve_entity,
)

ZERO_VEC = [0.0] * 8


@pytest.fixture
async def user_and_resume(db_session):
    user = User(username="entity_test_user", email="entity_test@example.com", password_hash="x")
    db_session.add(user)
    await db_session.flush()
    resume = Resume(
        user_id=user.id,
        filename="entity.txt",
        file_path="/tmp/entity.txt",
        parsed_text="测试简历",
        status="ready",
    )
    db_session.add(resume)
    await db_session.commit()
    return user, resume


@pytest.fixture(autouse=True)
def _no_external_calls():
    """隔离外部依赖：embedding / LLM / L4 记忆全部 mock。"""
    with pytest.MonkeyPatch.context() as mp:
        # 默认 embedding 返回零向量（无相似度）；单测内按需覆盖
        mp.setattr(entity_link, "get_embeddings", _zero_embeddings)
        mp.setattr(entity_link, "save_memory", _fake_save_memory)
        mp.setattr(entity_link, "llm_generate", _fake_llm_new)
        yield


async def _zero_embeddings(texts, resume_id=None):
    return [[0.0] * 8 for _ in texts]


_mem_counter = {"n": 0}


async def _fake_save_memory(**kwargs):
    _mem_counter["n"] += 1
    return f"mem_{_mem_counter['n']}"


def _make_recall_mock(*items):
    """生成 async 版 recall_memory mock（固定返回 items）。"""

    async def _recall(**kwargs):
        return list(items)

    return _recall


def _fake_llm_new(system, user, **kwargs):
    """默认 LLM：提取返回空数组、消解返回 -1（新建）。"""
    if "实体提取器" in system:
        return "[]"
    return '{"duplicate_candidate_id": -1}'


# ═══════════════════════════════════════════════════════════════
# normalize_name / parse_skills_text
# ═══════════════════════════════════════════════════════════════


class TestNormalizeName:
    def test_nfkc_fullwidth(self):
        assert normalize_name("Ｐｙｔｈｏｎ") == "python"  # 全角 → NFKC 半角 + 小写

    def test_case_and_whitespace(self):
        assert normalize_name("  ByteDance  跳动 ") == "bytedance 跳动"

    def test_empty(self):
        assert normalize_name("") == ""
        assert normalize_name(None) == ""


class TestParseSkillsText:
    def test_json_array(self):
        assert parse_skills_text('["Python", "Java"]') == ["Python", "Java"]

    def test_markdown_lines_with_category(self):
        text = "编程语言：\n- Python\n- Java\n框架/工具：\n1. FastAPI"
        assert parse_skills_text(text) == ["Python", "Java", "FastAPI"]

    def test_inline_comma_split(self):
        assert parse_skills_text("1. Python、Java,Go") == ["Python", "Java", "Go"]

    def test_empty(self):
        assert parse_skills_text("") == []
        assert parse_skills_text(None) == []


# ═══════════════════════════════════════════════════════════════
# resolve_entity：三路消解
# ═══════════════════════════════════════════════════════════════


class TestResolveEntity:
    async def test_exact_match_fast_path(self, db_session, user_and_resume, _no_external_calls):
        """快路径 1：name_normalized 精确匹配唯一命中 → 复用，LLM 零调用。"""
        user, resume = user_and_resume
        e1, created = await resolve_entity(
            db_session, user_id=user.id, resume_id=resume.id, name="Python", entity_type="skill"
        )
        assert created is True

        with pytest.MonkeyPatch.context() as mp:
            calls = []
            mp.setattr(entity_link, "llm_generate", lambda *a, **k: calls.append(1) or "[]")
            e2, created2 = await resolve_entity(
                db_session, user_id=user.id, resume_id=resume.id, name="python", entity_type="skill"
            )
        assert created2 is False
        assert e2.id == e1.id
        assert calls == []  # 精确匹配不应触发 LLM

    async def test_semantic_fast_path(self, db_session, user_and_resume, _no_external_calls):
        """快路径 2：name embedding 相似度 ≥0.9 且明显领先 → 复用（mem0 语义消解）。"""
        user, resume = user_and_resume
        e1, _ = await resolve_entity(
            db_session, user_id=user.id, resume_id=resume.id, name="Python", entity_type="skill"
        )
        assert e1.id > 0

        async def similar(texts, resume_id=None):
            out = []
            for t in texts:
                if t == "Python3":
                    out.append([0.95] * 8)  # 查询：与 Python 高度相似
                elif t == "Python":
                    out.append([1.0] * 8)  # 候选：与查询余弦 1.0
                else:
                    out.append([-1.0] * 8)  # 其余候选：明显不同
            return out

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(entity_link, "get_embeddings", similar)
            e2, created = await resolve_entity(
                db_session,
                user_id=user.id,
                resume_id=resume.id,
                name="Python3",
                entity_type="skill",
            )
        assert created is False
        assert e2.id == e1.id  # 语义命中既有实体

    async def test_llm_fallback_duplicate(self, db_session, user_and_resume, _no_external_calls):
        """LLM 兜底：返回候选 id → 复用。"""
        user, resume = user_and_resume
        e1, _ = await resolve_entity(
            db_session, user_id=user.id, resume_id=resume.id, name="字节跳动", entity_type="company"
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(entity_link, "llm_generate", lambda *a, **k: '{"duplicate_candidate_id": 0}')
            e2, created = await resolve_entity(
                db_session,
                user_id=user.id,
                resume_id=resume.id,
                name="字节",
                entity_type="company",  # normalized 不同 → 跳过精确，embedding 零向量 → LLM
            )
        assert created is False
        assert e2.id == e1.id

    async def test_llm_fallback_new_and_guard(
        self, db_session, user_and_resume, _no_external_calls
    ):
        """LLM 返回 -1 / 越界 / 异常 → 一律新建（保守策略，宁建不误并）。"""
        user, resume = user_and_resume
        await resolve_entity(
            db_session, user_id=user.id, resume_id=resume.id, name="候选", entity_type="other"
        )
        # -1 → 新建
        e2, created = await resolve_entity(
            db_session, user_id=user.id, resume_id=resume.id, name="新实体A", entity_type="other"
        )
        assert created is True
        # 越界 id → 新建
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                entity_link, "llm_generate", lambda *a, **k: '{"duplicate_candidate_id": 99}'
            )
            e3, created3 = await resolve_entity(
                db_session,
                user_id=user.id,
                resume_id=resume.id,
                name="新实体B",
                entity_type="other",
            )
        assert created3 is True
        # LLM 抛异常 → 新建（不冒泡）
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                entity_link,
                "llm_generate",
                lambda *a, **k: (_ for _ in ()).throw(RuntimeError("llm down")),
            )
            e4, created4 = await resolve_entity(
                db_session,
                user_id=user.id,
                resume_id=resume.id,
                name="新实体C",
                entity_type="other",
            )
        assert created4 is True
        assert e2.id != e3.id != e4.id

    async def test_empty_name_raises(self, db_session, user_and_resume, _no_external_calls):
        user, resume = user_and_resume
        with pytest.raises(ValueError):
            await resolve_entity(
                db_session, user_id=user.id, resume_id=resume.id, name="  ", entity_type="skill"
            )


# ═══════════════════════════════════════════════════════════════
# add_fact：ADD-only + L4 双向关联
# ═══════════════════════════════════════════════════════════════


class TestAddFact:
    async def test_add_only_dedup(self, db_session, user_and_resume, _no_external_calls):
        """同 (entity_id, fact_text_norm) 重复 → 跳过；新事实 → 新增 + L4 记忆关联。"""
        user, resume = user_and_resume
        entity, _ = await resolve_entity(
            db_session, user_id=user.id, resume_id=resume.id, name="Python", entity_type="skill"
        )
        episode = entity_link.ResumeEpisode(
            user_id=user.id, resume_id=resume.id, source_type="test", content="片段"
        )
        db_session.add(episode)
        await db_session.flush()

        f1 = await add_fact(
            db_session,
            user_id=user.id,
            resume_id=resume.id,
            entity=entity,
            episode=episode,
            fact_text="掌握技能：Python",
        )
        assert f1 is not None
        assert f1.linked_memory_id == "mem_1"  # 同步写 L4 记忆并记录 id

        # 重复（大小写/空白不同 → normalized 相同）→ ADD-only 跳过
        f2 = await add_fact(
            db_session,
            user_id=user.id,
            resume_id=resume.id,
            entity=entity,
            episode=episode,
            fact_text="掌握技能： python ",
        )
        assert f2 is None

        # 实体 linked_memory_ids 双向索引已建立
        await db_session.refresh(entity)
        assert "mem_1" in (entity.linked_memory_ids or [])

        # 新事实 → 新增，第二个记忆 id
        f3 = await add_fact(
            db_session,
            user_id=user.id,
            resume_id=resume.id,
            entity=entity,
            episode=episode,
            fact_text="用 Python 写过爬虫",
        )
        assert f3 is not None and f3.id != f1.id
        assert f3.linked_memory_id == "mem_2"

    async def test_empty_fact_skipped(self, db_session, user_and_resume, _no_external_calls):
        user, resume = user_and_resume
        entity, _ = await resolve_entity(
            db_session, user_id=user.id, resume_id=resume.id, name="Java", entity_type="skill"
        )
        episode = entity_link.ResumeEpisode(
            user_id=user.id, resume_id=resume.id, source_type="test", content="x"
        )
        db_session.add(episode)
        await db_session.flush()
        assert (
            await add_fact(
                db_session,
                user_id=user.id,
                resume_id=resume.id,
                entity=entity,
                episode=episode,
                fact_text="  ",
            )
            is None
        )


# ═══════════════════════════════════════════════════════════════
# extract_entities_from_profile：L3 画像 ADD-only 提取
# ═══════════════════════════════════════════════════════════════


class TestExtractProfile:
    async def test_full_flow_and_idempotent(self, db_session, user_and_resume, _no_external_calls):
        """skills 确定性提取 + summary LLM 提取；重复调用幂等（facts 不重复）。"""
        user, resume = user_and_resume

        def llm(system, user, **kwargs):
            if "实体提取器" in system:
                return (
                    '[{"name": "字节跳动", "entity_type": "company",'
                    ' "description": "曾在字节跳动实习"}]'
                )
            return '{"duplicate_candidate_id": -1}'

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(entity_link, "llm_generate", llm)
            stats1 = await extract_entities_from_profile(
                db_session,
                user_id=user.id,
                resume_id=resume.id,
                summary="熟练掌握 Python 和 Java，曾在字节跳动实习，目标成为后端工程师",
                skills=["Python", "Java", "FastAPI"],
            )

        assert stats1["entities"] >= 4  # Python/Java/FastAPI/字节跳动
        assert stats1["facts"] >= 4
        assert stats1["skills"] == 3
        assert stats1["episode_id"] is not None

        # 幂等：再次提取 → facts 不新增（ADD-only 唯一约束），实体数不变
        _mem_counter["n"] = 0
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(entity_link, "llm_generate", llm)
            stats2 = await extract_entities_from_profile(
                db_session,
                user_id=user.id,
                resume_id=resume.id,
                summary="熟练掌握 Python 和 Java，曾在字节跳动实习，目标成为后端工程师",
                skills=["Python", "Java", "FastAPI"],
            )
        assert stats2["facts"] == 0  # 全部去重跳过
        assert stats2["entities"] == stats1["entities"]

        entities = await list_entities(db_session, user_id=user.id, resume_id=resume.id)
        by_name = {e["name"]: e for e in entities}
        assert by_name["Python"]["entity_type"] == "skill"
        assert by_name["Python"]["fact_count"] == 1
        assert by_name["字节跳动"]["entity_type"] == "company"

    async def test_empty_profile_noop(self, db_session, user_and_resume, _no_external_calls):
        user, resume = user_and_resume
        stats = await extract_entities_from_profile(
            db_session, user_id=user.id, resume_id=resume.id, summary=None, skills=None
        )
        assert stats["episode_id"] is None
        assert stats["entities"] == 0

    async def test_skills_text_input(self, db_session, user_and_resume, _no_external_calls):
        """skills 传原始分析文本 → 内部 parse_skills_text 解析。"""
        user, resume = user_and_resume
        stats = await extract_entities_from_profile(
            db_session,
            user_id=user.id,
            resume_id=resume.id,
            summary=None,
            skills="编程语言：\n- Python\n框架：FastAPI",
        )
        assert stats["skills"] == 2
        entities = await list_entities(db_session, user_id=user.id, resume_id=resume.id)
        assert {e["name"] for e in entities} == {"Python", "FastAPI"}

    async def test_llm_extract_failure_degrades(
        self, db_session, user_and_resume, _no_external_calls
    ):
        """summary LLM 提取失败 → 只落 skills 实体，不抛异常。"""
        user, resume = user_and_resume
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                entity_link,
                "llm_generate",
                lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
            )
            stats = await extract_entities_from_profile(
                db_session,
                user_id=user.id,
                resume_id=resume.id,
                summary="有一段总结",
                skills=["Python"],
            )
        assert stats["entities"] == 1  # 只有 Python
        assert stats["facts"] == 1


# ═══════════════════════════════════════════════════════════════
# recall_with_entity_boost：实体命中 → RRF 融合
# ═══════════════════════════════════════════════════════════════


class TestRecallBoost:
    @pytest.fixture(autouse=True)
    async def _seed(self, db_session, user_and_resume, _no_external_calls):
        user, resume = user_and_resume
        entity, _ = await resolve_entity(
            db_session, user_id=user.id, resume_id=resume.id, name="Python", entity_type="skill"
        )
        episode = entity_link.ResumeEpisode(
            user_id=user.id, resume_id=resume.id, source_type="test", content="片段"
        )
        db_session.add(episode)
        await db_session.flush()
        await add_fact(
            db_session,
            user_id=user.id,
            resume_id=resume.id,
            entity=entity,
            episode=episode,
            fact_text="掌握技能：Python",
        )
        await db_session.commit()
        return user, resume

    async def test_entity_hit_boosts_facts(self, db_session, _seed):
        """query 子串命中实体名 → 实体事实 RRF 融合进结果且排前。"""
        user, resume = _seed
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                entity_link,
                "recall_memory",
                _make_recall_mock(
                    {"memory_id": "m1", "text": "之前学过 Go", "score": 0.7, "metadata": {}}
                ),
            )
            out = await recall_with_entity_boost(
                db_session,
                user_id=user.id,
                resume_id=resume.id,
                query="我想了解 Python 的经验",
                top_k=3,
            )
        texts = [o["text"] for o in out]
        assert "掌握技能：Python" in texts  # 实体事实被召回
        assert texts[0] == "掌握技能：Python"  # RRF：实体事实 rank1 最高
        assert out[0]["metadata"]["source"] == "entity_fact"
        assert out[0]["metadata"]["entity_id"] is not None

    async def test_no_entity_hit_falls_back(self, db_session, _seed):
        """无实体命中 → 退化为纯语义召回（行为与现状一致）。"""
        user, resume = _seed
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                entity_link,
                "recall_memory",
                _make_recall_mock(
                    {"memory_id": "m1", "text": "回忆A", "score": 0.6, "metadata": {}}
                ),
            )
            out = await recall_with_entity_boost(
                db_session,
                user_id=user.id,
                resume_id=resume.id,
                query="今天天气如何",
                top_k=3,
            )
        assert [o["text"] for o in out] == ["回忆A"]  # 原样透传

    async def test_embedding_entity_hit(self, db_session, _seed):
        """子串未命中但 embedding 相似 → 语义通道命中（中文歧义场景）。"""
        user, resume = _seed

        async def similar(texts, resume_id=None):
            out = []
            for t in texts:
                if t == "我在字节的经历":
                    out.append([0.9] * 8)
                else:
                    out.append([1.0] * 8)
            return out

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(entity_link, "get_embeddings", similar)
            mp.setattr(
                entity_link,
                "recall_memory",
                _make_recall_mock(
                    {"memory_id": "m1", "text": "旧记忆", "score": 0.5, "metadata": {}}
                ),
            )
            out = await recall_with_entity_boost(
                db_session,
                user_id=user.id,
                resume_id=resume.id,
                query="我在字节的经历",
                top_k=5,
            )
        assert any(o["metadata"].get("source") == "entity_fact" for o in out)
