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
    """T19: 可选对比简历 ID 列表，Agent 调 compare_resumes 工具时使用。"""
    compare_ids: list[int] | None = None
    """可选：指定对话会话 ID，将问答归入该会话下。不传则归入默认流。"""
    conversation_id: int | None = None
    # v2: Builder 上下文参数（可选，用于条目级 AI 操作）
    """工具模式：agent（默认）/ builder（builder 意图直达优化）。"""
    tool_mode: str | None = None
    """目标模块类型（builder 场景下指定操作哪个模块）。"""
    module_type: str | None = None
    """目标条目 ID（builder 场景下指定操作哪个条目）。"""
    entry_id: str | None = None
    """AI 操作类型：optimize/check/rewrite/expand（builder 场景）。"""
    action: str | None = None

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

    @field_validator("compare_ids")
    @classmethod
    def compare_ids_validate(cls, v: list[int] | None) -> list[int] | None:
        if v is None:
            return None
        if len(v) < 1:
            raise ValueError("compare_ids 至少 1 个")
        if len(v) > 5:
            raise ValueError("compare_ids 最多 5 个")
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


# ── 对话会话 Schema ──────────────────────────────────────


class ConversationCreateRequest(BaseModel):
    """创建新对话。title 可选，默认"新对话"。"""
    title: str | None = None

    @field_validator("title")
    @classmethod
    def title_not_too_long(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if len(v) > 100:
            raise ValueError("对话标题不超过100字")
        return v


class ConversationRenameRequest(BaseModel):
    """重命名对话。"""
    title: str

    @field_validator("title")
    @classmethod
    def title_valid(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("标题不能为空")
        if len(v) > 100:
            raise ValueError("对话标题不超过100字")
        return v


class ConversationResponse(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0

    model_config = {"from_attributes": True}


class ConversationListResponse(BaseModel):
    items: list[ConversationResponse]
    total: int


class ConversationDeleteResponse(BaseModel):
    """删除对话的响应：返回被删除的问答记录数。"""
    deleted_count: int
