"""多轮模拟面试实时状态（H1-H3，DeepInterview prep/live/post 对照，阶段 5）。

与 InterviewSession（面后复盘）分离：本表只承载「进行中的多轮交互」——
QuestionPlan + cursor + followup_index + answers。面试完成时由
interview_coach.finalize_simulation 把评分卡写入 InterviewSession（公司=模拟面试），
自动流入现有复盘闭环（build_review_summary / weak_competencies 派生）。

plan 形状（每个元素为 Question dict，DeepInterview PlannedQuestion 简化对照）：
    {
      "id": "q1",
      "section": "行为面试" | "项目深挖" | "算法" | "系统设计" | "数据库" | ...,
      "text": "问题正文",
      "difficulty": 1-5,
      "rubric": [{"criterion": "...", "weight": 0.4, "description": "..."}],
      "followups": ["追问1", "追问2"],
      "target_competency": "算法"
    }

answers 形状（列表，一个元素记录一道题的全部回答）：
    {
      "question_id": "q1",
      "answer": "用户主要回答",
      "followups_asked": [{"prompt": "追问1", "answer": "..."}]
    }
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class InterviewSimulation(Base):
    """一场进行中的多轮模拟面试（一问一答推进，可中途退出，完成后自动评分）。"""

    __tablename__ = "interview_simulations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resume_id: Mapped[int | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    target_position: Mapped[str] = mapped_column(String(100), nullable=False)
    # 题单（Question dict 列表）
    plan: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 当前题目下标（0-based）
    cursor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 当前题目内追问下标（-1 = 无待追问，返回题目本身）
    followup_index: Mapped[int] = mapped_column(Integer, default=-1, nullable=False)
    # 已答记录（Answer dict 列表）
    answers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # active（进行中） / completed（已完成已评分）
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
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
