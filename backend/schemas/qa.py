from datetime import datetime
from pydantic import BaseModel, field_validator


class QuestionRequest(BaseModel):
    resume_id: int
    question: str

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
    # 阶段4 错误透传：本次回答是否基于「部分信息」（检索/重排等工具存在失败）。
    # 前端可据此提示用户「答案基于部分信息，可能不完整」。默认 False 表示全链路正常。
    degraded: bool = False

    model_config = {"from_attributes": True}


class QAHistoryResponse(BaseModel):
    items: list[AnswerResponse]
    total: int


class QADeleteResponse(BaseModel):
    """清空历史问答的响应：返回被删除的记录数。"""
    deleted_count: int
