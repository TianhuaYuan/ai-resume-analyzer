"""
Provenance 追踪系统 — 记忆来源分类与召回过滤

借鉴 OpenClaw 的 Provenance 机制：
- 写入时附带来源元数据（owner/agent/untrusted/system）
- 召回时按来源过滤（untrusted 不进入 curated core）
- 支持置信度和召回权重

使用场景：
1. 工具结果存储时：classify_tool_result() 分类来源
2. 记忆召回时：filter_for_recall() 过滤不可信来源
3. 记忆排序时：get_recall_weight() 计算召回权重
"""

from dataclasses import dataclass, field
from enum import Enum
import time


class OriginClass(str, Enum):
    """来源分类"""

    OWNER = "owner"  # 用户直接输入
    AGENT = "agent"  # Agent 推导
    UNTRUSTED = "untrusted"  # 外部内容（搜索结果等）
    SYSTEM = "system"  # 系统脚手架


class SessionKind(str, Enum):
    """会话类型"""

    INTERACTIVE = "interactive"  # 交互式
    BACKGROUND = "background"  # 后台任务


@dataclass
class MemoryProvenance:
    """记忆来源元数据"""

    origin_class: OriginClass
    session_kind: SessionKind = SessionKind.INTERACTIVE
    observed_at: float = field(default_factory=time.time)
    source_tool: str | None = None  # 来源工具名
    confidence: float = 1.0  # 置信度 0-1

    def to_dict(self) -> dict:
        return {
            "origin_class": self.origin_class.value,
            "session_kind": self.session_kind.value,
            "observed_at": self.observed_at,
            "source_tool": self.source_tool,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryProvenance":
        return cls(
            origin_class=OriginClass(data.get("origin_class", "agent")),
            session_kind=SessionKind(data.get("session_kind", "interactive")),
            observed_at=data.get("observed_at", time.time()),
            source_tool=data.get("source_tool"),
            confidence=data.get("confidence", 1.0),
        )


class ProvenanceTracker:
    """来源追踪器：写入时分类 + 召回时过滤"""

    # 召回优先级：owner > agent > untrusted（不召回） > system（不召回）
    RECALL_PRIORITY = {
        OriginClass.OWNER: 1.0,
        OriginClass.AGENT: 0.8,
        OriginClass.UNTRUSTED: 0.0,  # 不进入 curated core
        OriginClass.SYSTEM: 0.0,  # 不召回
    }

    def __init__(self) -> None:
        self.session_provenance: dict[str, MemoryProvenance] = {}

    def classify_tool_result(self, tool_name: str, result: str) -> OriginClass:
        """根据工具名和结果分类来源"""
        # 外部搜索工具的结果标记为 untrusted
        untrusted_tools = {
            "search_jobs_live",
            "web_search",
            "search_campus_jobs",
            "search_campus_recruitments",
            "get_job_detail",
        }
        if tool_name in untrusted_tools:
            return OriginClass.UNTRUSTED

        # 系统工具标记为 system
        system_tools = {"get_resume_content", "diagnose_resume"}
        if tool_name in system_tools:
            return OriginClass.SYSTEM

        # 默认为 agent 推导
        return OriginClass.AGENT

    def create_provenance(
        self,
        origin_class: OriginClass,
        source_tool: str | None = None,
        session_kind: SessionKind = SessionKind.INTERACTIVE,
    ) -> MemoryProvenance:
        """创建来源元数据"""
        return MemoryProvenance(
            origin_class=origin_class,
            session_kind=session_kind,
            source_tool=source_tool,
        )

    def should_recall(self, provenance: MemoryProvenance) -> bool:
        """判断是否应该召回此记忆"""
        return self.RECALL_PRIORITY.get(provenance.origin_class, 0) > 0

    def get_recall_weight(self, provenance: MemoryProvenance) -> float:
        """获取召回权重"""
        return self.RECALL_PRIORITY.get(provenance.origin_class, 0)

    def filter_for_recall(self, memories: list[dict]) -> list[dict]:
        """过滤记忆列表，只保留可召回的"""
        filtered = []
        for mem in memories:
            prov_data = mem.get("provenance")
            if prov_data:
                prov = MemoryProvenance.from_dict(prov_data)
                if self.should_recall(prov):
                    # 附加召回权重
                    mem["recall_weight"] = self.get_recall_weight(prov)
                    filtered.append(mem)
            else:
                # 无来源信息的记忆默认可召回（兼容旧数据）
                mem["recall_weight"] = 0.5
                filtered.append(mem)
        return filtered
