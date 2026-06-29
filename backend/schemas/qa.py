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

    model_config = {"from_attributes": True}


class QAHistoryResponse(BaseModel):
    items: list[AnswerResponse]
    total: int
