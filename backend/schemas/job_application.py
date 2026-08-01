"""T33: 求职申请（Job Application）相关 Pydantic schemas。

覆盖看板（Kanban）CRUD + 聚合统计接口的请求/响应结构。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# 标准看板列状态
JobApplicationStatus = Literal[
    "wishlist",      # 意向
    "applied",       # 已投递
    "interview",     # 面试中
    "offer",         # Offer
    "rejected",      # 已拒绝
    "accepted",      # 已接受
]

VALID_STATUSES = ("wishlist", "applied", "interview", "offer", "rejected", "accepted")


class JobApplicationCreate(BaseModel):
    """创建求职申请请求。company / position 必填，其余可选。"""

    company: str = Field(..., min_length=1, max_length=100, description="公司名称")
    position: str = Field(..., min_length=1, max_length=100, description="职位名称")
    city: str | None = Field(default=None, max_length=50, description="城市")
    salary_range: str | None = Field(default=None, max_length=50, description="薪资范围")
    status: str = Field(default="wishlist", description="申请状态")
    resume_id: int | None = Field(default=None, description="关联简历 ID")
    applied_at: datetime | None = Field(default=None, description="投递时间")

    @field_validator("status")
    @classmethod
    def status_must_be_valid(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(f"status 必须是 {VALID_STATUSES} 之一")
        return v

    @field_validator("company", "position")
    @classmethod
    def strip_required(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("不能为空")
        return v


class JobApplicationUpdate(BaseModel):
    """更新求职申请请求（部分更新，所有字段可选）。"""

    company: str | None = Field(default=None, min_length=1, max_length=100)
    position: str | None = Field(default=None, min_length=1, max_length=100)
    city: str | None = Field(default=None, max_length=50)
    salary_range: str | None = Field(default=None, max_length=50)
    status: str | None = Field(default=None)
    resume_id: int | None = Field(default=None)
    applied_at: datetime | None = Field(default=None)

    @field_validator("status")
    @classmethod
    def status_must_be_valid(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_STATUSES:
            raise ValueError(f"status 必须是 {VALID_STATUSES} 之一")
        return v


class JobApplicationResponse(BaseModel):
    """单条求职申请完整响应。"""

    id: int
    user_id: int
    resume_id: int | None
    company: str
    position: str
    city: str | None
    salary_range: str | None
    status: str
    applied_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class JobApplicationListResponse(BaseModel):
    """求职申请分页列表响应。"""

    items: list[JobApplicationResponse]
    total: int


# ── 看板统计子模型 ──────────────────────────────────────────


class CompanyCount(BaseModel):
    company: str
    count: int


class CityCount(BaseModel):
    city: str
    count: int


class TrendPoint(BaseModel):
    date: str
    count: int


class KanbanStatsResponse(BaseModel):
    """看板聚合统计响应（供 recharts 图表消费）。"""

    by_status: dict[str, int]
    by_company: list[CompanyCount]
    by_city: list[CityCount]
    trend: list[TrendPoint]
    total: int
