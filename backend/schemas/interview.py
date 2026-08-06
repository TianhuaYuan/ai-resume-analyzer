"""面试复盘闭环 Schema（G 功能，DeepInterview sessions/coach 契约对照）。"""

from datetime import datetime

from pydantic import BaseModel, Field


class InterviewCreate(BaseModel):
    company: str = Field(..., min_length=1, max_length=100, description="公司名")
    position: str = Field(..., min_length=1, max_length=100, description="面试岗位")
    resume_id: int | None = Field(None, description="关联简历 ID（可选）")
    job_application_id: int | None = Field(
        None, description="关联投递记录 ID（可选，未填 JD 时自动取该投递的 jd_text）"
    )
    jd_text: str | None = Field(None, description="岗位 JD 文本（可选）")
    questions: list | None = Field(None, description="面试问题列表（可选）")
    answers: list | None = Field(None, description="回答内容列表（可选）")
    notes: str | None = Field(None, description="复盘备注（可选）")
    scorecard: dict | None = Field(
        None, description="评分卡整块 JSON（可选，传了即视为已复盘 → status=reviewed）"
    )


class InterviewUpdate(BaseModel):
    """评分卡录入/更新：scorecard 整块 + 可选 notes。"""

    scorecard: dict = Field(
        ...,
        description="评分卡：{overall_score, competency_scores, weak_competencies, notes}",
    )
    notes: str | None = Field(None, description="复盘备注（可选）")


class InterviewListItem(BaseModel):
    """列表项（不含 answers/scorecard 大字段，供分页列表用）。"""

    id: int
    company: str
    position: str
    resume_id: int | None = None
    job_application_id: int | None = None
    jd_text: str | None = None
    questions: list | None = None
    notes: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InterviewResponse(InterviewListItem):
    """详情（含 answers/scorecard）。"""

    answers: list | None = None
    scorecard: dict | None = None


class InterviewListResponse(BaseModel):
    items: list[InterviewListItem]
    total: int
    page: int
    limit: int
    total_pages: int


class ScorecardUpdateResponse(BaseModel):
    """评分卡更新响应：返回派生的薄弱点（学习闭环入口）。"""

    interview_id: int
    status: str
    weak_competencies: list[str]
    scorecard: dict
    notes: str | None = None


class WeaknessItem(BaseModel):
    """高频薄弱点：competency + 出现次数。"""

    competency: str
    count: int


class TrainingModule(BaseModel):
    """单个训练推荐模块（DeepInterview StudyModule 对照，确定性模板）。"""

    id: str
    competency: str
    title: str
    rationale: str
    est_min: int


class TrainingPlan(BaseModel):
    """训练计划：一个薄弱点一个模块，最弱优先。"""

    modules: list[TrainingModule]
    summary: str
    total_min: int


class TrendPoint(BaseModel):
    """历史面试趋势点（按天聚合条数）。"""

    period: str
    count: int


class ReviewSummaryResponse(BaseModel):
    """复盘汇总：高频薄弱点 + 训练推荐 + 历史面试趋势。"""

    frequent_weaknesses: list[WeaknessItem]
    training_plan: TrainingPlan
    trend: list[TrendPoint]
