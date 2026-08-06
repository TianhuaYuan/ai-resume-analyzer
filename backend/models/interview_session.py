"""面试复盘记录（DeepInterview supabase sessions 对照，G 功能）。

一次面试记录 = 面后信息（company/position/resume_id/jd_text/questions/answers）一次写入，
scorecard 评分卡整块 JSON 事后录入（status: recorded → reviewed），可重复评分。
scorecard.weak_competencies 是学习闭环的消费契约：派生薄弱点 → 训练推荐。
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class InterviewSession(Base):
    """一次面试的完整复盘记录。"""

    __tablename__ = "interview_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company: Mapped[str] = mapped_column(String(100), nullable=False)
    position: Mapped[str] = mapped_column(String(100), nullable=False)
    resume_id: Mapped[int | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL"),
        nullable=True,
    )
    # 关联投递记录（投递看板的某面次）；复盘可挂到投递，关联时自动取投递 JD
    job_application_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_applications.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    jd_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    questions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    answers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 评分卡整块 JSON：{overall_score, competency_scores, weak_competencies, notes}
    scorecard: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # recorded（已记录未评分） / reviewed（已录入评分卡，可出复盘）
    status: Mapped[str] = mapped_column(String(20), default="recorded")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
