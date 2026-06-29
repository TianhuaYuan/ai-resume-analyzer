from datetime import datetime
from pydantic import BaseModel


class ResumeResponse(BaseModel):
    id: int
    filename: str
    chunk_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ResumeListResponse(BaseModel):
    items: list[ResumeResponse]
    total: int


class UploadResponse(BaseModel):
    id: int
    filename: str
    preview: str
    chunk_count: int
