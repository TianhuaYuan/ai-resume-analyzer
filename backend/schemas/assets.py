"""知识资产 CRUD Schema（T3, D2 脏标记模式）。

JD / 面试记录 / 笔记三类求职知识资产的增删改查契约。
与 resumes 表同一套 content_hash / indexed_hash 脏标记：
``indexed = content_hash 非空 且 content_hash == indexed_hash``。
"""

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

# 合法资产类型白名单（resume 复用 resumes 表，不在此）
ASSET_TYPES = ("jd", "interview", "note")


class AssetCreate(BaseModel):
    asset_type: str
    title: str
    content: str
    is_draft: bool = False


class AssetUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    is_draft: bool | None = None


class AssetResponse(BaseModel):
    id: int
    asset_type: str
    title: str
    content: str
    is_draft: bool
    version: int
    index_version: int
    indexed_hash: str | None
    created_at: datetime
    updated_at: datetime
    # 派生字段：脏标记一致才认为已索引
    indexed: bool = False
    # 内部字段：仅用于计算 indexed，不进响应
    content_hash: str | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def _compute_indexed(self):
        self.indexed = bool(self.content_hash) and self.content_hash == self.indexed_hash
        return self

    model_config = {"from_attributes": True}


class AssetListResponse(BaseModel):
    items: list[AssetResponse]
    total: int
    page: int
    limit: int
