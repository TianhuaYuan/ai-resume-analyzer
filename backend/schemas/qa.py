from datetime import datetime
from pydantic import BaseModel, field_validator


class TokenUsage(BaseModel):
    """Token 消耗明细。"""
    total: int = 0
    prompt: int = 0
    completion: int = 0


class QuestionRequest(BaseModel):
    resume_id: int
    question: str

    @field_validator("resume_id")
    @classmethod
    def resume_id_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("resume_id 必须为正整数")
        return v

    @field_validator("question")
    @classmethod
    def question_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("问题不能为空")
        if len(v) > 500:
            raise ValueError("问题不超过500字")
        return v


class AnswerResponse(BaseModel):
    id: int
    question: str
    answer: str
    sources: list[str]
    created_at: datetime
    token_usage: TokenUsage = TokenUsage()
    degraded: bool = False

    model_config = {"from_attributes": True}


class QAHistoryResponse(BaseModel):
    items: list[AnswerResponse]
    total: int


class QADeleteResponse(BaseModel):
    """清空历史问答的响应：返回被删除的记录数。"""
    deleted_count: int
