from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class ResumeResponse(BaseModel):
    id: int
    filename: str
    parsed_text: str
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
    analysis_type: Literal["summary", "skills", "experience", "score"]


class ScoreDetail(BaseModel):
    """量化评分维度。"""
    ats_match: int
    keyword_coverage: int
    skill_density: int
    overall: int


class AnalyzeResponse(BaseModel):
    resume_id: int
    analysis_type: str
    analysis: str
    scores: ScoreDetail | None = None


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


class MatchJDRequest(BaseModel):
    # P1-17: schema 层长度校验，防止空文本和恶意超长输入撑爆 LLM token
    # service 层的 strip() 校验仍保留，拦截纯空格字符串（如 "   "）
    jd_text: str = Field(..., min_length=1, max_length=5000, description="JD 文本，1-5000 字符")


class MatchJDResponse(BaseModel):
    resume_id: int
    analysis: str
