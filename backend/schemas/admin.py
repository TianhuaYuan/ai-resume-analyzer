"""T34: 管理员后台相关 Pydantic schema。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditLogResponse(BaseModel):
    """单条审计日志。"""

    id: int
    user_id: int | None
    action: str
    target_type: str | None
    target_id: str | None
    detail: dict[str, Any] | None
    ip: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditLogListResponse(BaseModel):
    """审计日志分页响应。"""

    items: list[AuditLogResponse]
    total: int


class AdminUserItem(BaseModel):
    """管理员视角的用户信息（仅暴露安全字段，不含 password_hash）。"""

    id: int
    username: str
    email: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminUserListResponse(BaseModel):
    """用户列表分页响应。"""

    items: list[AdminUserItem]
    total: int


class TemplateInfoResponse(BaseModel):
    """单套简历模板信息。"""

    id: str
    name: str
    description: str


class TemplateListResponse(BaseModel):
    """模板列表响应。"""

    templates: list[TemplateInfoResponse]


class SystemStatsResponse(BaseModel):
    """系统级统计数据。"""

    total_users: int
    total_resumes: int
    total_qa_history: int
    total_feedback: int
    total_job_applications: int
    total_interviews: int
