"""校招求职状态机（对齐 third_party/Job/tools/recruit.py：STATUSES + STATUS_FLOW + TERMINAL_STATUSES）。

校招版 10 态：
  pending（待投递）→ applied（已投递）→ pending_written（笔试中）→ written_passed（笔试通过）
  → first_round（一面）→ second_round（二面）→ third_round（三面）→ offer（Offer）
  以及 rejected（已拒）/ cancelled（已取消）两个旁路终态。

规则：
  - 面试轮次可跳过（一面可直接到三面/Offer）
  - 终态（offer/rejected/cancelled）不能再转出
  - 同状态视为合法 no-op（不产生事件）
"""

STATUSES: list[str] = [
    "pending",
    "applied",
    "pending_written",
    "written_passed",
    "first_round",
    "second_round",
    "third_round",
    "offer",
    "rejected",
    "cancelled",
]

TERMINAL_STATUSES: set[str] = {"offer", "rejected", "cancelled"}

# 合法状态转换表：old -> 允许的 new（面试轮次可跳过；终态为空集）
STATUS_FLOW: dict[str, set[str]] = {
    "pending": {"applied", "cancelled"},
    "applied": {"pending_written", "first_round", "rejected", "cancelled"},
    "pending_written": {"written_passed", "first_round", "rejected", "cancelled"},
    "written_passed": {"first_round", "rejected", "cancelled"},
    "first_round": {"second_round", "third_round", "offer", "rejected", "cancelled"},
    "second_round": {"third_round", "offer", "rejected", "cancelled"},
    "third_round": {"offer", "rejected", "cancelled"},
    "offer": set(),
    "rejected": set(),
    "cancelled": set(),
}


def assert_valid_status(s: str) -> None:
    """校验状态合法，非法抛 ValueError（调用方转 400）。"""
    if s not in STATUSES:
        raise ValueError(f"无效状态: {s}（合法值: {', '.join(STATUSES)}）")


def can_transition(old: str, new: str) -> bool:
    """old → new 是否为合法状态转换（同状态视为合法 no-op）。"""
    if old == new:
        return True
    if old not in STATUS_FLOW:
        return False
    return new in STATUS_FLOW[old]


def next_statuses(old: str) -> list[str]:
    """从 old 状态可达的新状态列表（按 STATUSES 顺序，不含自身）。"""
    allowed = STATUS_FLOW.get(old, set())
    return [s for s in STATUSES if s in allowed]
