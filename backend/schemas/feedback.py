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
    """意见箱列表响应。"""

    items: list[UserFeedbackItem]
    total: int
