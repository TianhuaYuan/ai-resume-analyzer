"""市场数据（公共求职资产）相关 Pydantic schemas。

覆盖：岗位浏览/详情、范文列表/详情、攻略、简历模板画廊、Agent 岗位推荐。
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# job_type 合法枚举（数据层标准化）
JobType = Literal["campus", "social", "intern"]


class MarketJobItem(BaseModel):
    """岗位列表摘要（不含 content 全文，供浏览/筛选）。"""

    id: int
    source: str
    job_type: str | None
    title: str
    company: str | None
    position: str | None
    city: str | None
    industry: str | None
    salary: str | None
    degree: str | None
    deadline: datetime | None
    is_expired: bool
    created_at: datetime
    payload: dict[str, Any] | None = None

    model_config = ConfigDict(from_attributes=True)


class MarketJobStatsResponse(BaseModel):
    """岗位统计（校招页统计卡：总数 / 近3日 / 近7日 / Top 行业）。"""

    total: int
    count_3d: int
    count_7d: int
    top_industries: list[dict[str, Any]] = Field(default_factory=list)  # [{name, count}]


class MarketJobDetail(MarketJobItem):
    """岗位详情（含 content 全文 + 结构化 payload）。"""

    content: str
    payload: dict[str, Any] | None = None


class MarketJobListResponse(BaseModel):
    """岗位分页列表响应。"""

    items: list[MarketJobItem]
    total: int
    page: int
    limit: int
    total_pages: int


class MarketSampleItem(BaseModel):
    """范文列表摘要（不含 payload / content 原文——合规：范文含个人信息不外露）。"""

    id: int
    title: str
    position: str | None = Field(None, description="targetJob 目标岗位")
    category: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MarketSampleDetail(MarketSampleItem):
    """范文详情（含原文 content + 结构化 payload，供展示/快速套用 / AI 改写）。"""

    content: str = ""
    payload: dict[str, Any] | None = None


class MarketSampleListResponse(BaseModel):
    items: list[MarketSampleItem]
    total: int
    page: int
    limit: int
    total_pages: int


class MarketGuideItem(BaseModel):
    """攻略列表摘要（title/summary，正文未抓取时跳原文链接）。"""

    id: int
    title: str
    summary: str = ""
    date: str | None = None
    url: str | None = None
    has_fulltext: bool = False


class MarketGuideDetail(MarketGuideItem):
    """攻略详情（content 为正文；未抓取时为摘要）。"""

    content: str = ""


class MarketGuideListResponse(BaseModel):
    items: list[MarketGuideItem]
    total: int
    page: int
    limit: int
    total_pages: int


# ── 简历模板画廊（公开） ─────────────────────────────────────


class MarketTemplateInfo(BaseModel):
    """简历模板摘要（含零数据渲染的预览 HTML）。"""

    id: str
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    layout: str = ""
    preview_html: str = ""


class MarketTemplateListResponse(BaseModel):
    items: list[MarketTemplateInfo]


# ── Agent 岗位推荐 ───────────────────────────────────────────


class MarketRecommendRequest(BaseModel):
    resume_id: int = Field(..., description="简历 ID（归属校验）")
    top_k: int = Field(default=5, ge=1, le=10, description="返回岗位数")
    job_type: JobType | None = Field(default=None, description="限定校招/社招/实习")


class MarketRecommendItem(BaseModel):
    id: int
    title: str
    company: str | None
    position: str | None
    city: str | None
    salary: str | None
    job_type: str | None
    score: int
    matched: list[str] = []
    gaps: list[str] = []
    reason: str = ""


class MarketRecommendResponse(BaseModel):
    items: list[MarketRecommendItem]
