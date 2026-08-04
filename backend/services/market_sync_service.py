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

logger = logging.getLogger(__name__)

# ── 数据源常量 ──────────────────────────────────────────────

# 爬虫 JSON 文件所在目录（与 api/campus.py 一致）
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

SOURCE_CAMPUS = "campus"              # campus_recruitment.json（校招公告）
SOURCE_REFERRAL = "referral"          # referral_recruitment.json（内推）
SOURCE_UPCV = "upcv"                  # upcv_jobs.json（upcv 真实 JD）
SOURCE_ALLJOBS = "alljobs"            # all_jobs.json（nowcoder 多平台岗位）
SOURCE_UPCV_RECRUITMENTS = "upcv_recruitments"  # upcv 校招项目

# 岗位分类 JSON（backend/data/ 真源，爬虫重爬后由整理脚本重新生成）
MARKET_FILES: dict[str, str] = {
    "jobs_campus": "jobs_campus.json",  # 校招岗位（campus公告/upcv岗位/校招项目/all_jobs校招）
    "jobs_social": "jobs_social.json",  # 社招岗位（all_jobs社招实习/内推）
}

# 资产类型（RAG metadata）
ASSET_TYPE_JOB = "job"

# job_type 标准化枚举
JOB_TYPE_CAMPUS = "campus"
JOB_TYPE_SOCIAL = "social"
JOB_TYPE_INTERN = "intern"


@dataclass
class NormalizedAsset:
    source: str
    external_id: str
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
    apply_url: str | None = None
    published_at: datetime | None = None


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


def _load_market_records(name: str) -> list[dict]:
    """读岗位分类 JSON 的 records 数组。"""
    fpath = _DATA_DIR / MARKET_FILES[name]
    if not fpath.exists():
        logger.warning("market data file not found: %s", fpath)
        return []
    with open(fpath, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, dict) and isinstance(raw.get("records"), list):
        return raw["records"]
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


def _same_dt(a: datetime | None, b: datetime | None) -> bool:
    """忽略 tzinfo 比较 datetime（SQLite/MySQL DATETIME 读回为 naive，写时为 aware）。"""
    if a is None or b is None:
        return a is b
    return a.replace(tzinfo=None) == b.replace(tzinfo=None)


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
        apply_url=r.get("detailUrl") or r.get("applyUrl"),
        published_at=_parse_dt(r.get("publishedAt")),
    )


def _normalize_upcv_recruitments(r: dict) -> NormalizedAsset:
    """upcv 校招项目归一化（job 资产，校招向）。"""
    c = r.get("company") or {}
    company = c.get("shortName") or c.get("name") or r.get("rawCompanyName") or ""
    title = r.get("programName") or f"校招项目{r.get('id')}"
    sections = []
    for key, label in (("targetGraduates", "面向对象"), ("targetDegrees", "学历要求"),
                       ("targetMajors", "专业要求"), ("cities", "工作城市"),
                       ("schedule", "招聘安排"), ("benefits", "福利待遇")):
        v = r.get(key)
        if v:
            text = _fmt_labels(v) if isinstance(v, list) else str(v)
            if text:
                sections.append(f"## {label}\n{text}")
    content = _build_job_content(
        title=title, company=company, city=_fmt_labels(r.get("cities")),
        salary="", degree="", body="\n".join(sections),
    )
    return NormalizedAsset(
        source=SOURCE_UPCV_RECRUITMENTS,
        external_id=str(r.get("id") or ""),
        title=title,
        content=content,
        job_type=JOB_TYPE_CAMPUS,
        company=company,
        position="",
        city=_fmt_labels(r.get("cities")),
        deadline=_resolve_deadline(r),
        apply_url=r.get("recruitUrl"),
        published_at=_parse_dt(r.get("createTime") or r.get("recordTime")),
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
        apply_url=r.get("url"),
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
        apply_url=r.get("referralMethod"),
        published_at=_parse_dt(r.get("recordTime")),
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
        apply_url=r.get("referralMethod"),
        published_at=_parse_dt(r.get("recordTime")),
    )


def _build_job_content(*, title, company, city, salary, degree, body) -> str:
    header = "、".join(p for p in (company, title, city, salary, degree) if p)
    return f"{header}\n\n{body}" if body else header


# ── 幂等 upsert + 索引 ───────────────────────────────────────

# 各 String 列长度上限（MySQL 严格模式 Data too long 保护）
_FIELD_LIMITS = {
    "title": 255, "company": 255, "position": 255, "city": 255,
    "industry": 255, "salary": 100, "degree": 100, "apply_url": 2000,
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
            source=n.source, external_id=n.external_id,
            job_type=n.job_type, title=n.title, company=n.company,
            position=n.position, city=n.city, industry=n.industry,
            salary=n.salary, degree=n.degree, deadline=n.deadline,
            is_expired=is_expired, apply_url=n.apply_url, published_at=n.published_at,
            content=n.content, content_hash=content_hash,
        )
        db.add(row)
        await db.flush()
        stats.created += 1
        return row, True

    dirty = (
        row.content_hash != content_hash
        or row.is_expired != is_expired
        or row.job_type != n.job_type
        or row.apply_url != n.apply_url
        or not _same_dt(row.published_at, n.published_at)
    )
    if not dirty:
        stats.unchanged += 1
        return row, False

    row.source = n.source
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
    row.apply_url = n.apply_url
    row.published_at = n.published_at
    row.content = n.content
    row.content_hash = content_hash
    await db.flush()
    stats.updated += 1
    return row, True


async def _index_asset(db: AsyncSession, row: MarketAsset, stats: MarketSyncStats) -> None:
    """对一条资产做 eager 向量索引（写 market_public 公共集合）。"""
    collection = market_collection_name()
    lock_id = await acquire_index_lock(0, ASSET_TYPE_JOB, row.id)
    try:
        chunk_count = await index_asset(
            collection=collection,
            user_id=None,  # 公共资产：metadata 不写 user_id
            asset_id=row.id,
            asset_type=ASSET_TYPE_JOB,
            text=row.content,
            version=row.index_version + 1,
            content_hash=row.content_hash,
        )
        await clear_market_bm25(collection, row.id)
        row.indexed_hash = row.content_hash
        row.index_version += 1
        await db.commit()
        if chunk_count:
            stats.indexed += 1
        logger.info(
            "market asset indexed source=%s id=%s chunks=%d",
            row.source, row.id, chunk_count,
        )
    finally:
        await release_index_lock(0, ASSET_TYPE_JOB, row.id, lock_id)


# 各 JSON 记录里的 _source 标签 → 归一化器
_NORMALIZERS: dict[str, callable] = {
    "campus_recruitment": _normalize_campus,
    "upcv_jobs": _normalize_upcv_jobs,
    "upcv_recruitments": _normalize_upcv_recruitments,
    "all_jobs": _normalize_all_jobs,
    "referral": _normalize_referral,
}


async def sync_market(
    db: AsyncSession,
    *,
    file: str | None = None,
    limit_per_source: int | None = None,
) -> MarketSyncStats:
    """同步市场数据。file=None 同步全部岗位 JSON，否则只同步指定文件。

    Args:
        file: 指定岗位数据文件（jobs_campus/jobs_social），None 全部
        limit_per_source: 每条记录最多同步条数（测试/抽样用），None 全量
    """
    stats = MarketSyncStats()
    files = [file] if file else list(MARKET_FILES.keys())

    for name in files:
        if name not in MARKET_FILES:
            stats.errors.append(f"未知数据文件: {name}")
            continue
        records = _load_market_records(name)
        if limit_per_source:
            records = records[:limit_per_source]
        if not records:
            stats.errors.append(f"{name}: 无数据或为空")
            continue
        for r in records:
            stats.total += 1
            tag = r.get("_source")
            normalizer = _NORMALIZERS.get(tag)
            if normalizer is None:
                stats.errors.append(f"{name}: 未知 _source={tag}")
                continue
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
                logger.exception("market sync row failed file=%s tag=%s", name, tag)
                stats.errors.append(f"{name}/{tag}: {e}")
        logger.info("market sync file=%s done, total=%d", name, len(records))

    await db.commit()
    return stats
