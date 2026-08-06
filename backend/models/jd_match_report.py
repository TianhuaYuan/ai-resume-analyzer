"""I1: JD 匹配 6-block 评估报告落库（JdMatchReport 存储模型）。

JDMatchTool 生成的分块报告（角色摘要 / CV 匹配 / 级别策略 / 薪酬市场 /
个性化计划 / 面试故事映射 / 岗位可信度）持久化，供前端历史回看与趋势分析。
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class JdMatchReport(Base):
    __tablename__ = "jd_match_reports"
    __table_args__ = (
        UniqueConstraint("user_id", "resume_id", "jd_text_hash", name="uq_jd_report_user_resume_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resume_id: Mapped[int] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # JD 原文 sha256（同 (user, resume, jd) 幂等，重复匹配覆盖更新）
    jd_text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    jd_text: Mapped[str] = mapped_column(Text, nullable=False)
    # 6-block 报告结构（JSON）：role_summary/cv_match/level_strategy/comp_market/
    # personalization_plan/interview_stories/job_credibility + 汇总字段
    report: Mapped[dict] = mapped_column(JSON, nullable=False)
    overall: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    band: Mapped[str] = mapped_column(String(20), default="needsWork", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
