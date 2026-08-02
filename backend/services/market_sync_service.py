"""市场数据同步管线：爬虫 JSON → 归一化 → 幂等 upsert → 公共集合向量索引。

数据流：
  爬虫定期产出 JSON（backend/data/*.json）
    → POST /admin/market/sync 手动触发
    → sync_market()：按 source 读 JSON → 归一化 → (source, external_id) 幂等 upsert
    → content_hash 变更 / is_expired 变更才重索引（index_asset → market_public）
    → 写 indexed_hash / index_version

设计要点：
- 幂等：同一 JSON 跑两次第二次 unchanged 全量、零新索引
- 增量：content_hash（sha256）脏标记判断"内容是否变"，变了才重建向量
- 过期：deadline / endDate / expirationTime 已过 → is_expired=True（保留历史，默认过滤）
- 公共集合：market_public，user_id 传 None（metadata 不写 user_id），所有用户共享
- 并发：per-asset 分布式锁（user_id 哨兵 0 表示公共资产）
- 健壮：单行异常记 errors 不中断整批
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.distributed_lock import acquire_index_lock, release_index_lock
from models.market_asset import MarketAsset
from services.rag.clients import market_collection_name
from services.rag.indexer import index_asset
from services.rag.retrieval import clear_market_bm25
from services.sample_module_service import build_sample_payload

logger = logging.getLogger(__name__)

# ── 数据源常量 ──────────────────────────────────────────────

# 爬虫 JSON 文件所在目录（与 api/campus.py 一致）
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

SOURCE_CAMPUS = "campus"      # campus_recruitment.json（校招公告）
SOURCE_REFERRAL = "referral"  # referral_recruitment.json（内推）
SOURCE_UPCV = "upcv"          # upcv_jobs.json（upcv 真实 JD）
SOURCE_ALLJOBS = "alljobs"    # all_jobs.json（nowcoder 多平台岗位）
SOURCE_SAMPLE = "sample"      # fanwen_all.json（简历范文）
SOURCE_GUIDE = "guide"        # all_articles.json（求职攻略）

# source → 文件名
SOURCE_FILES: dict[str, str] = {
    SOURCE_CAMPUS: "campus_recruitment.json",
    SOURCE_REFERRAL: "referral_recruitment.json",
    SOURCE_UPCV: "upcv_jobs.json",
    SOURCE_ALLJOBS: "all_jobs.json",
    SOURCE_SAMPLE: "fanwen_all.json",
    SOURCE_GUIDE: "all_articles.json",
}

# 资产类型（RAG metadata）
ASSET_TYPE_JOB = "job"
ASSET_TYPE_SAMPLE = "sample"
ASSET_TYPE_GUIDE = "guide"

# job_type 标准化枚举
JOB_TYPE_CAMPUS = "campus"
JOB_TYPE_SOCIAL = "social"
JOB_TYPE_INTERN = "intern"


@dataclass
class NormalizedAsset:
    source: str
    external_id: str
    asset_type: str
    title: str
    content: str
    job_type: str | None = None
    company: str | None = None
    position: str | None = None
    city: str | None = None
    industry: str | None = None
    salary: str | None = None
    degree: str | None = None
    deadline: datetime | None = None
    payload: dict | None = None


@dataclass
class MarketSyncStats:
    total: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    expired: int = 0
    indexed: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "created": self.created,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "expired": self.expired,
            "indexed": self.indexed,
            "errors": self.errors[:20],
        }


# ── 通用工具 ────────────────────────────────────────────────


def _load_source_json(source: str) -> list[dict]:
    """读 source 对应 JSON 文件，兼容顶层 list / {"data":[...]} / {"articles":[...]} 三种形态。"""
    fpath = _DATA_DIR / SOURCE_FILES[source]
    if not fpath.exists():
        logger.warning("market data file not found: %s", fpath)
        return []
    with open(fpath, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, dict):
        for key in ("data", "articles", "items"):
            if key in raw and isinstance(raw[key], list):
                return raw[key]
        return []
    if isinstance(raw, list):
        return raw
    return []


def _parse_dt(value: Any) -> datetime | None:
    """解析多种日期形态：'2026-07-31 00:00:00' / '2026-08-01T00:00:00Z' / '2026-07-31'。"""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _resolve_deadline(record: dict) -> datetime | None:
    for key in ("deadline", "endDate", "expirationTime"):
        dt = _parse_dt(record.get(key))
        if dt:
            return dt
    return None


def _resolve_expired(deadline: datetime | None, now: datetime | None = None) -> bool:
    if deadline is None:
        return False
    now = now or datetime.now(timezone.utc)
    return deadline < now


def _compute_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fmt_labels(value: Any) -> str:
    """把 Chroma 式 label 数组（[{label:...}]）或 str 归一成逗号分隔字符串。"""
    if not value:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for e in value:
            if isinstance(e, dict):
                parts.append(e.get("label") or e.get("name") or "")
            else:
                parts.append(str(e))
        return "、".join(p for p in parts if p)
    return str(value)


def _resolve_job_type(record: dict, source: str) -> str | None:
    """跨源 job_type 标准化映射（campus / social / intern）。"""
    if source == SOURCE_UPCV:
        jt = record.get("jobType") or ""
        return {JOB_TYPE_CAMPUS.upper(): JOB_TYPE_CAMPUS,
                "INTERNSHIP": JOB_TYPE_INTERN}.get(jt, JOB_TYPE_SOCIAL)
    if source == SOURCE_ALLJOBS:
        # 华为 recruit_type / 腾讯 recruit_label / 牛客 platform / 智联 recruit_type
        # 优先级：社招 > 实习 > 校招/应届（"应届实习"含实习 → intern）
        for key in ("recruit_type", "recruit_label", "platform", "recruitType"):
            v = record.get(key) or ""
            if "社招" in v:
                return JOB_TYPE_SOCIAL
            if "实习" in v or "实习生" in v:
                return JOB_TYPE_INTERN
            if "校招" in v or "应届" in v:
                return JOB_TYPE_CAMPUS
        return None
    if source == SOURCE_CAMPUS:
        info_type = record.get("infoType") or ""
        if "内推" in info_type:
            return JOB_TYPE_SOCIAL
        return JOB_TYPE_CAMPUS
    if source == SOURCE_REFERRAL:
        return JOB_TYPE_SOCIAL
    return None


# ── 各源归一化器 ─────────────────────────────────────────────


def _normalize_upcv_jobs(r: dict) -> NormalizedAsset:
    c = r.get("company") or {}
    company = c.get("shortName") or c.get("name") or r.get("companyName") or ""
    degree = r.get("minEducation") or {}
    title = r.get("title") or r.get("position") or "未命名岗位"
    position = title
    content = _build_job_content(
        title=title, company=company,
        city=_fmt_labels(r.get("cities")),
        salary=r.get("salaryDisplay") or "",
        degree=degree.get("label", "") if isinstance(degree, dict) else "",
        body="\n".join(
            str(r.get(k) or "") for k in ("description", "requirements", "benefits")
            if r.get(k)
        ),
    )
    return NormalizedAsset(
        source=SOURCE_UPCV,
        external_id=str(r.get("id") or ""),
        asset_type=ASSET_TYPE_JOB,
        title=title,
        content=content,
        job_type=_resolve_job_type(r, SOURCE_UPCV),
        company=company,
        position=position,
        city=_fmt_labels(r.get("cities")),
        industry=_fmt_labels(r.get("industries")),
        salary=r.get("salaryDisplay") or "",
        degree=degree.get("label", "") if isinstance(degree, dict) else "",
        deadline=_resolve_deadline(r),
        payload={"work_mode": r.get("workMode"), "apply_url": r.get("detailUrl") or r.get("applyUrl")},
    )


def _normalize_all_jobs(r: dict) -> NormalizedAsset:
    title = r.get("position") or r.get("title") or "未命名岗位"
    # all_jobs 无 id，用 url（或合成 hash）作外部键
    external = r.get("url") or _compute_hash(f"{r.get('platform')}|{r.get('company')}|{title}")
    # platform 是来源平台/公司名（腾讯/华为/牛客-实习/智联招聘 等）。
    # company 为空且 platform 不像聚合平台时，回退为 company（修复历史错位：公司名被存进 industry）。
    company = (r.get("company") or "").strip()
    platform = (r.get("platform") or "").strip()
    if not company and platform and not any(
        k in platform for k in ("牛客", "智联", "招聘", "实习", "校招", "猎聘", "BOSS")
    ):
        company = platform
    # all_jobs 无真实行业字段，industry 不再取 platform（避免错位）。
    content = _build_job_content(
        title=title,
        company=company,
        city=r.get("city") or "",
        salary=r.get("salary") or "",
        degree=r.get("education") or "",
        body="\n".join(str(r.get(k) or "") for k in ("duty", "requirement") if r.get(k)),
    )
    return NormalizedAsset(
        source=SOURCE_ALLJOBS,
        external_id=external[:100],
        asset_type=ASSET_TYPE_JOB,
        title=title,
        content=content,
        job_type=_resolve_job_type(r, SOURCE_ALLJOBS),
        company=company,
        position=title,
        city=r.get("city") or "",
        industry="",
        salary=r.get("salary") or "",
        degree=r.get("education") or "",
        deadline=_resolve_deadline(r),
        payload={"platform": r.get("platform"), "apply_url": r.get("url")},
    )


def _normalize_campus(r: dict) -> NormalizedAsset:
    title = r.get("title") or r.get("company") or "未命名校招"
    parts = [r.get("positions"), r.get("industry"), r.get("workLocation"),
             r.get("remarks"), r.get("referralMethod")]
    body = "\n".join(str(p) for p in parts if p)
    content = _build_job_content(
        title=title, company=r.get("company") or "",
        city=r.get("workLocation") or "", salary="", degree="", body=body,
    )
    return NormalizedAsset(
        source=SOURCE_CAMPUS,
        external_id=str(r.get("id") or ""),
        asset_type=ASSET_TYPE_JOB,
        title=title,
        content=content,
        job_type=_resolve_job_type(r, SOURCE_CAMPUS),
        company=r.get("company") or "",
        position=r.get("positions") or "",
        city=r.get("workLocation") or "",
        industry=r.get("industry") or "",
        salary="",
        degree="",
        deadline=_resolve_deadline(r),
        payload={"referral_code": r.get("referralCode"), "apply_url": r.get("referralMethod")},
    )


def _normalize_referral(r: dict) -> NormalizedAsset:
    title = r.get("title") or r.get("company") or "未命名内推"
    parts = [r.get("positions"), r.get("industry"), r.get("workLocation"),
             r.get("remarks"), r.get("referralMethod")]
    body = "\n".join(str(p) for p in parts if p)
    content = _build_job_content(
        title=title, company=r.get("company") or "",
        city=r.get("workLocation") or "", salary="", degree="", body=body,
    )
    return NormalizedAsset(
        source=SOURCE_REFERRAL,
        external_id=str(r.get("id") or ""),
        asset_type=ASSET_TYPE_JOB,
        title=title,
        content=content,
        job_type=JOB_TYPE_SOCIAL,
        company=r.get("company") or "",
        position=r.get("positions") or "",
        city=r.get("workLocation") or "",
        industry=r.get("industry") or "",
        salary="",
        degree="",
        deadline=_resolve_deadline(r),
        payload={"referral_code": r.get("referralCode"), "apply_url": r.get("referralMethod")},
    )


def _normalize_fanwen(r: dict) -> NormalizedAsset:
    title = r.get("title") or f"范文{r.get('id')}"
    sections = []
    for key, label in (("summary", "个人总结"), ("work", "工作经历"),
                       ("projects", "项目经历"), ("education", "教育背景"),
                       ("skills", "技能")):
        v = r.get(key)
        if v:
            sections.append(f"## {label}\n{v}")
    content = "\n\n".join(sections)
    # 同步时一次性生成结构化 style+modules（与 get_sample 惰性生成结果一致），
    # 供范文页"快速套用结构"使用；build_sample_payload 内部降级，不会抛异常。
    payload = build_sample_payload(
        content,
        {"target_position": r.get("targetJob"), "category": r.get("category")},
    )
    return NormalizedAsset(
        source=SOURCE_SAMPLE,
        external_id=str(r.get("id") or ""),
        asset_type=ASSET_TYPE_SAMPLE,
        title=title,
        content=content,
        position=r.get("targetJob") or "",
        payload=payload,
    )


def _normalize_guide(r: dict) -> NormalizedAsset:
    """求职攻略归一化。正文未抓取前 content 用摘要；正文抓取后替换为全文。"""
    title = r.get("title") or f"攻略{r.get('article_id')}"
    content = r.get("summary") or title
    external = r.get("article_id") or _compute_hash(r.get("url") or title)
    return NormalizedAsset(
        source=SOURCE_GUIDE,
        external_id=str(external)[:100],
        asset_type=ASSET_TYPE_GUIDE,
        title=title,
        content=content,
        payload={
            "url": r.get("url"),
            "date": r.get("date") or r.get("datetime_iso"),
            "has_fulltext": bool(r.get("content")),
        },
    )


def _build_job_content(*, title, company, city, salary, degree, body) -> str:
    header = "、".join(p for p in (company, title, city, salary, degree) if p)
    return f"{header}\n\n{body}" if body else header


# ── 幂等 upsert + 索引 ───────────────────────────────────────

# 各 String 列长度上限（MySQL 严格模式 Data too long 保护）
_FIELD_LIMITS = {
    "title": 255, "company": 255, "position": 255, "city": 255,
    "industry": 255, "salary": 100, "degree": 100,
}


def _clip_fields(n: NormalizedAsset) -> NormalizedAsset:
    """截断超长字符串字段，防止 MySQL 严格模式 Data too long 报错（源数据不可控）。"""
    for field, limit in _FIELD_LIMITS.items():
        val = getattr(n, field)
        if isinstance(val, str) and len(val) > limit:
            setattr(n, field, val[:limit])
    return n


async def _upsert_asset(db: AsyncSession, n: NormalizedAsset, stats: MarketSyncStats):
    """单条归一化资产幂等 upsert：内容/过期变了才更新并标记待索引。"""
    n = _clip_fields(n)
    content_hash = _compute_hash(n.content)
    now = datetime.now(timezone.utc)
    is_expired = _resolve_expired(n.deadline, now)

    result = await db.execute(
        select(MarketAsset).where(
            MarketAsset.source == n.source,
            MarketAsset.external_id == n.external_id,
        )
    )
    row = result.scalar_one_or_none()

    if row is None:
        row = MarketAsset(
            source=n.source, external_id=n.external_id, asset_type=n.asset_type,
            job_type=n.job_type, title=n.title, company=n.company,
            position=n.position, city=n.city, industry=n.industry,
            salary=n.salary, degree=n.degree, deadline=n.deadline,
            is_expired=is_expired, payload=n.payload, content=n.content,
            content_hash=content_hash, is_published=True,
        )
        db.add(row)
        await db.flush()
        stats.created += 1
        return row, True

    dirty = (
        row.content_hash != content_hash
        or row.is_expired != is_expired
        or row.job_type != n.job_type
        or row.payload != n.payload
    )
    if not dirty:
        stats.unchanged += 1
        return row, False

    row.source = n.source
    row.asset_type = n.asset_type
    row.job_type = n.job_type
    row.title = n.title
    row.company = n.company
    row.position = n.position
    row.city = n.city
    row.industry = n.industry
    row.salary = n.salary
    row.degree = n.degree
    row.deadline = n.deadline
    row.is_expired = is_expired
    row.payload = n.payload
    row.content = n.content
    row.content_hash = content_hash
    await db.flush()
    stats.updated += 1
    return row, True


async def _index_asset(db: AsyncSession, row: MarketAsset, stats: MarketSyncStats) -> None:
    """对一条资产做 eager 向量索引（写 market_public 公共集合）。"""
    collection = market_collection_name()
    lock_id = await acquire_index_lock(0, row.asset_type, row.id)
    try:
        chunk_count = await index_asset(
            collection=collection,
            user_id=None,  # 公共资产：metadata 不写 user_id
            asset_id=row.id,
            asset_type=row.asset_type,
            text=row.content,
            version=row.index_version + 1,
            content_hash=row.content_hash,
        )
        await clear_market_bm25(collection, row.id)
        row.indexed_hash = row.content_hash
        row.index_version += 1
        row.version += 1
        await db.commit()
        if chunk_count:
            stats.indexed += 1
        logger.info(
            "market asset indexed source=%s id=%s chunks=%d",
            row.source, row.id, chunk_count,
        )
    finally:
        await release_index_lock(0, row.asset_type, row.id, lock_id)


_NORMALIZERS = {
    SOURCE_UPCV: _normalize_upcv_jobs,
    SOURCE_ALLJOBS: _normalize_all_jobs,
    SOURCE_CAMPUS: _normalize_campus,
    SOURCE_REFERRAL: _normalize_referral,
    SOURCE_SAMPLE: _normalize_fanwen,
    SOURCE_GUIDE: _normalize_guide,
}


async def sync_market(
    db: AsyncSession,
    *,
    source: str | None = None,
    limit_per_source: int | None = None,
) -> MarketSyncStats:
    """同步市场数据。source=None 同步所有可用源文件，否则只同步指定源。

    Args:
        source: 指定数据源（campus/referral/upcv/alljobs/sample/guide），None 同步全部
        limit_per_source: 每源最多同步条数（测试/抽样用），None 全量
    """
    stats = MarketSyncStats()
    sources = [source] if source else list(SOURCE_FILES.keys())

    for src in sources:
        if src not in SOURCE_FILES:
            stats.errors.append(f"未知数据源: {src}")
            continue
        records = _load_source_json(src)
        if limit_per_source:
            records = records[:limit_per_source]
        if not records:
            stats.errors.append(f"{src}: 无数据文件或为空")
            continue
        normalizer = _NORMALIZERS[src]
        for r in records:
            stats.total += 1
            try:
                n = normalizer(r)
                if not n.external_id:
                    continue
                row, need_index = await _upsert_asset(db, n, stats)
                if row.is_expired:
                    stats.expired += 1
                if need_index:
                    await _index_asset(db, row, stats)
            except Exception as e:  # noqa: BLE001 单行异常不中断整批
                logger.exception("market sync row failed source=%s", src)
                stats.errors.append(f"{src}: {e}")
        logger.info("market sync source=%s done, total=%d", src, len(records))

    await db.commit()
    return stats
