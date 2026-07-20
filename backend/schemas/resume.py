from datetime import datetime
from typing import Literal
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


class AnalyzeRequest(BaseModel):
    analysis_type: Literal["summary", "skills", "experience"]


class AnalyzeResponse(BaseModel):
    resume_id: int
    analysis_type: str
    analysis: str


class ChunkItem(BaseModel):
    """单个分块的结构。

    字段对齐 services/rag/chunking.py 的 _make_chunk 输出，
    数据源是 ChromaDB collection resume_{id} 的 metadata + document。
    """

    chunk_index: int
    section: str
    text: str
    start_char: int
    end_char: int


class ChunksResponse(BaseModel):
    resume_id: int
    total: int
    chunks: list[ChunkItem]
