"""A3 实体链接三表：简历实体 / 实体事实 / 来源情节。

机制参考：
- **graphiti 双时态**：fact 永不物理删除，矛盾/失效只标 ``invalid_at``（业务失效时间）
  + ``expired_at``（系统发现时间），查询一律 ``WHERE invalid_at IS NULL`` 取当前有效事实
- **graphiti 消解**：``name_normalized`` 精确匹配快路径 → 低可信（短名/模糊）升级 LLM 兜底判定；
  ``linked_memory_ids`` 为 mem0 的双向索引（实体 ⇄ L4 向量记忆）
- **ADD-only**：fact 以 ``(entity_id, fact_text_norm)`` 唯一约束天然去重，同事实重复提取自动跳过
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class ResumeEntity(Base):
    """简历中的命名实体（技能/公司/学校/岗位/人名/目标等）。

    name_normalized 是确定性消解快路径的索引键（NFKC + 小写 + 折叠空白）。
    同名不同实例（graphiti 例：Java 语言 vs Java 岛）允许存在多条，
    消解逻辑保证无歧义时合并、有歧义时升级 LLM 判定。
    """

    __tablename__ = "resume_entities"

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
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    name_normalized: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # mem0 双向索引：实体关联的 L4 向量记忆 id 列表（save_memory 返回的 mid）
    linked_memory_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
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


class ResumeEntityFact(Base):
    """关于实体的原子事实（ADD-only，graphiti 双时态）。

    - ``(entity_id, fact_text_norm)`` 唯一约束 → 同事实重复提取自动跳过（天然 ADD-only）
    - ``invalid_at``：业务失效时间（矛盾事实被推翻时标记；NULL = 当前有效）
    - ``expired_at``：系统发现失效的壁钟时间（与 invalid_at 分离是 graphiti 双时态精髓）
    - ``linked_memory_id``：该事实在 L4 向量库中的记忆 id（溯源与 boost 用）
    """

    __tablename__ = "resume_entity_facts"
    __table_args__ = (UniqueConstraint("entity_id", "fact_text_norm", name="uq_entity_fact_norm"),)

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
    entity_id: Mapped[int] = mapped_column(
        ForeignKey("resume_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    episode_id: Mapped[int] = mapped_column(
        ForeignKey("resume_episodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fact_text: Mapped[str] = mapped_column(Text, nullable=False)
    # 归一化后截断到 500（MySQL VARCHAR 上限内），作消解快路径
    fact_text_norm: Mapped[str] = mapped_column(String(500), nullable=False)
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    valid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    linked_memory_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class ResumeEpisode(Base):
    """实体/事实的来源情节（graphiti EpisodicNode 对应物）。

    一段原始输入（L3 画像 summary 文本 / skills 列表 / 对话片段），
    是所有提取内容的锚点：fact.episode_id 指向这里实现溯源。
    """

    __tablename__ = "resume_episodes"

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
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="l3_profile")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    valid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
