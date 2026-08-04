from datetime import datetime
from pydantic import BaseModel, field_validator


class QAFeedbackRequest(BaseModel):
    """问答反馈请求：赞/踩。"""

    rating: str

    @field_validator("rating")
    @classmethod
    def rating_must_be_valid(cls, v: str) -> str:
        if v not in ("positive", "negative"):
            raise ValueError("rating 必须是 positive 或 negative")
        return v


class UserFeedbackRequest(BaseModel):
    """用户意见箱提交请求。"""

    content: str
    type: str

    @field_validator("content")
    @classmethod
    def content_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("内容不能为空")
        if len(v) > 2000:
            raise ValueError("内容不超过 2000 字")
        return v


class UserFeedbackItem(BaseModel):
    """单条用户意见箱反馈。"""

    id: int
    user_id: int
    content: str
    type: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class UserFeedbackListResponse(BaseModel):
    """意见箱列表响应（管理员用）。"""

    items: list[UserFeedbackItem]
    total: int


class PublicFeedbackItem(BaseModel):
    """公开反馈列表项（不含 user_id）。"""

    id: int
    content: str
    type: str
    status: str
    created_at: datetime
    user_display: str
    likes_count: int
    is_liked: bool

    model_config = {"from_attributes": True}


class PublicFeedbackListResponse(BaseModel):
    """公开反馈列表响应。"""

    items: list[PublicFeedbackItem]
    total: int


class LikeResponse(BaseModel):
    """点赞响应。"""

    likes_count: int
    is_liked: bool


# ═══════════════════════════════════════════════════════════
# QA 反馈统计（管理员问答质量看板）
# ═══════════════════════════════════════════════════════════


class QAStatsResumeItem(BaseModel):
    """按简历聚合的问答反馈统计。"""

    resume_id: int
    resume_title: str
    positive: int
    negative: int
    negative_rate: float


class QANegativeSample(BaseModel):
    """一条 negative 反馈样本（含 process_trace，用于复盘回答短板）。"""

    qa_id: int
    question: str
    answer_excerpt: str
    resume_id: int
    created_at: datetime
    process_trace: dict | None = None


class QAStatsResponse(BaseModel):
    """QA 反馈总览：正负比例 + 简历维度排行 + negative 样本。"""

    total_feedback: int
    positive: int
    negative: int
    negative_rate: float
    by_resume: list[QAStatsResumeItem]
    recent_negative: list[QANegativeSample]
