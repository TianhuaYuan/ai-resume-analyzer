"""投递状态机 Schema（J 功能，阶段 5，third_party/Job STATUS_FLOW 契约对照）。"""

from datetime import date, datetime

from pydantic import BaseModel, Field


class JobApplicationCreate(BaseModel):
    company: str = Field(..., min_length=1, max_length=120, description="公司名")
    position: str = Field(..., min_length=1, max_length=120, description="岗位名")
    url: str | None = Field(None, max_length=500, description="招聘链接（可粘贴 JD 页面 URL）")
    status: str = Field("待投递", description="初始状态，默认待投递")
    priority: str = Field("中", description="优先级：高/中/低")
    deadline: date | None = Field(None, description="截止日期（YYYY-MM-DD）")
    notes: str | None = Field(None, description="备注")
    jd_text: str | None = Field(None, description="JD 文本（可粘贴）")
    generate_scorecard: bool = Field(False, description="是否生成 JD 评分卡（需 jd_text）")


class JobApplicationUpdate(BaseModel):
    company: str | None = Field(None, max_length=120)
    position: str | None = Field(None, max_length=120)
    url: str | None = Field(None, max_length=500)
    priority: str | None = Field(None, description="优先级：高/中/低")
    deadline: date | None = Field(None)
    notes: str | None = Field(None)
    jd_text: str | None = Field(None)
    generate_scorecard: bool = Field(False)


class JobApplicationStatusUpdate(BaseModel):
    new_status: str = Field(..., description="目标状态（校验 STATUS_FLOW 合法性，轮次可跳过）")
    note: str | None = Field(None, max_length=300, description="流转备注（自动追加到时间线）")


class DuplicateItem(BaseModel):
    """新建/更新时检测到的已有近似记录。"""

    id: int
    company: str
    position: str
    status: str


class JobApplicationResponse(BaseModel):
    """单条投递详情。"""

    id: int
    company: str
    position: str
    url: str | None = None
    status: str
    priority: str
    deadline: date | None = None
    notes: str | None = None
    jd_text: str | None = None
    jd_scorecard: dict | None = None
    timeline: list | None = None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    # 派生字段（看板/列表用）
    stay_days: int | None = None
    deadline_status: str = "none"

    model_config = {"from_attributes": True}


class JobApplicationCreateResult(BaseModel):
    application: JobApplicationResponse
    duplicates: list[DuplicateItem] = Field(default_factory=list, description="检测到的已有近似记录（去重提示）")


class JobApplicationListResponse(BaseModel):
    items: list[JobApplicationResponse]
    total: int
    page: int
    limit: int
    total_pages: int


class QueueItem(BaseModel):
    """今日队列项：kind 为 thank_you（致谢）/ nudge（催办）/ ghost（失联）。"""

    kind: str
    headline: str
    detail: str
    application_id: int
    company: str
    position: str
    priority: str
    status: str
    stay_days: int | None = None


class DashboardResponse(BaseModel):
    timing: dict
    stats: dict
    deadline_counts: dict
    queue: list[QueueItem]
