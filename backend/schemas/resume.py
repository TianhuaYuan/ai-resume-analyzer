from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, model_validator


class ResumeResponse(BaseModel):
    id: int
    filename: str
    parsed_text: str
    chunk_count: int
    status: str
    status_message: str
    created_at: datetime
    updated_at: datetime
    # T17：索引新鲜度（脏标记 content_hash != indexed_hash → 需要懒重建）
    content_hash: str | None = None
    indexed_hash: str | None = None
    is_indexed: bool = False
    is_stale: bool = False
    # 简历列表卡片预览：modules + style（不传时前端兜底灰色占位）
    modules_data: ResumeModulesData | None = None

    @model_validator(mode="after")
    def _compute_index_state(self):
        self.is_indexed = self.indexed_hash is not None
        self.is_stale = bool(self.content_hash) and self.content_hash != self.indexed_hash
        return self

    model_config = {"from_attributes": True}


class ResumeModuleLite(BaseModel):
    """列表预览用的精简模块信息。"""

    id: int = 0
    resume_id: int = 0
    module_type: str
    content: dict
    sort_order: int


class ResumeModulesData(BaseModel):
    """简历卡片预览用：模块列表 + 样式配置。"""

    modules: list[ResumeModuleLite]
    style: dict | None = None


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
    cached: bool = False  # True 表示来自 Redis 缓存（供前端提示用）


class FullAnalyzeResponse(BaseModel):
    """完整分析结果：4 种类型一次性返回。

    对比功能和前端"完整分析"按钮使用此接口，
    数据优先从 Redis 缓存返回，缺失的类型自动调用 LLM 补齐。
    """

    resume_id: int
    summary: AnalyzeResponse
    skills: AnalyzeResponse
    experience: AnalyzeResponse
    score: AnalyzeResponse


# ── 对比功能扩展 ───────────────────────────────────────────

# 合法对比维度：扩展到 4 种分析结果 + 原有项目维度
CompareDimension = Literal["summary", "skills", "experience", "score", "projects"]


class CompareRequest(BaseModel):
    """多简历对比请求。"""

    resume_ids: list[int] = Field(..., min_length=2, max_length=5, description="简历 ID 列表，2-5 个")
    dimensions: list[CompareDimension] = Field(
        default_factory=lambda: ["summary", "skills", "experience", "score", "projects"],
        description="对比维度，默认全部",
    )


class ResumeBrief(BaseModel):
    """简历简要信息。"""

    id: int
    filename: str


# 单个维度的值：summary/skills/experience 是 Markdown 文本字符串，
# score 是结构化评分 dict，projects 是项目名列表
DimensionValue = str | dict | list[str]


class CompareResponse(BaseModel):
    """多简历对比响应。

    dimensions 结构: {dimension_name: {resume_id_str: value}}
    例如:
      "skills": {"1": "技能分析Markdown", "2": "技能分析Markdown"}
      "score":  {"1": {"overall":80,...},  "2": {"overall":75,...}}
      "projects": {"1": ["项目A","项目B"], "2": ["项目C"]}
    """

    resumes: list[ResumeBrief]
    dimensions: dict[str, dict[str, DimensionValue]]


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


class AnalysisStatusResponse(BaseModel):
    """简历分析缓存状态。"""

    resume_id: int
    has_cache: bool
    cached_types: list[str]


class BackgroundAnalyzeResponse(BaseModel):
    """后台分析任务提交响应。"""

    status: str
    resume_id: int
    message: str
