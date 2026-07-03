from datetime import datetime
from pydantic import BaseModel


class ResumeResponse(BaseModel):
    id: int
    filename: str
    chunk_count: int
    status: str
    status_message: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ResumeListResponse(BaseModel):
    items: list[ResumeResponse]
    total: int


class UploadAsyncResponse(BaseModel):
    id: int
    filename: str
    status: str
