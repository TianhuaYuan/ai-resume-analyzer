"""T37: 产品分析相关 Pydantic schema。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AnalyticsEventRequest(BaseModel):
    """记录产品事件请求体。"""

    event_name: str = Field(..., min_length=1, max_length=50, description="事件名，如 user.register")
    source: str | None = Field(
        None, max_length=50, description="CTA 来源渠道，如 linkedin"
    )
    metadata: dict[str, Any] | None = Field(None, description="附加上下文，如 {format: pdf}")


class AnalyticsEventResponse(BaseModel):
    """单条事件响应。"""

    id: int
    event_name: str
    source: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AnalyticsEventListResponse(BaseModel):
    """事件列表分页响应。"""

    items: list[AnalyticsEventResponse]
    total: int


class FunnelItem(BaseModel):
    """漏斗单项：某事件的总次数与去重用户数。"""

    event_name: str
    count: int
    unique_users: int


class FunnelResponse(BaseModel):
    """漏斗聚合响应。"""

    events: list[FunnelItem]
    days: int


class TrendItem(BaseModel):
    """D3: 单日趋势（注册 / 活跃 / 事件）。"""

    day: str
    registrations: int = 0
    active_users: int = 0
    events: int = 0


class TrendResponse(BaseModel):
    """趋势统计响应。"""

    days: int
    items: list[TrendItem]


class LLMUsageItem(BaseModel):
    """D4: 单日 LLM 用量。"""

    date: str
    total_tokens: int = 0
    calls: int = 0


class LLMUsageResponse(BaseModel):
    """LLM 用量历史响应。"""

    days: int
    items: list[LLMUsageItem]
