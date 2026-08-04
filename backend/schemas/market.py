"""市场数据（公共求职资产）相关 Pydantic schemas。

覆盖：岗位浏览/详情、Agent 岗位推荐。
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# job_type 合法枚举（数据层标准化）
JobType = Literal["campus", "social", "intern"]


class MarketJobItem(BaseModel):
    """岗位列表摘要（不含 content 全文，供浏览/筛选）。"""

    id: int
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
    apply_url: str | None = None
    published_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MarketJobStatsResponse(BaseModel):
    """岗位统计（校招页统计卡：总数 / 近3日 / 近7日 / Top 行业）。"""

    total: int
    count_3d: int
    count_7d: int
    top_industries: list[dict[str, Any]] = Field(default_factory=list)  # [{name, count}]


class MarketJobDetail(MarketJobItem):
    """岗位详情（含 content 全文）。"""

    content: str


class MarketJobListResponse(BaseModel):
    """岗位分页列表响应。"""

    items: list[MarketJobItem]
    total: int
    page: int
    limit: int
    total_pages: int


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
