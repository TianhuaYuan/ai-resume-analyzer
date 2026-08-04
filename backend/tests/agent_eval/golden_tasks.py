"""黄金任务集：instruction + script（假模型注入）+ gold_actions（期望行为）+ outputs。

三元组语义（tau-bench Task 对应物）：
- instruction：用户指令（agent 收到的 question）
- script：注入的假模型响应脚本，每轮一个 ToolCallSpec 列表，最后一轮无工具 → 直接回答
- gold_actions：期望【成功执行】的工具序列（坏调用不计入；契约化回灌后修正的才算）
- required_outputs：最终回答必须包含的信息子串（tau-bench outputs 判据）

script 故意注入的坏调用场景（验证 A3 契约化闭环）：
- ``bad_args_recovery``：缺必填参数 → ToolRetryError → 回灌 → 修正调用
- ``unknown_tool_recovery``：工具名不存在 → 附可用列表错误 → 回灌 → 修正
- ``converge_on_bad_calls``：连续坏调用达 MAX_TOOL_RETRIES → 强制收敛
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolCallSpec:
    """一次工具调用的期望/注入规格（name + 参数字典）。"""

    name: str
    args: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ScriptRound:
    """假模型一轮响应：本轮注入的工具调用（空 = 直接回答，content 即最终答案）。"""

    tool_calls: tuple[ToolCallSpec, ...] = ()
    content: str = ""


@dataclass(frozen=True)
class EvalTask:
    """黄金任务（tau-bench Task 三元组 + 脚本注入）。"""

    name: str
    instruction: str
    script: tuple[ScriptRound, ...]
    gold_actions: tuple[ToolCallSpec, ...]
    required_outputs: tuple[str, ...] = ()


# ── 黄金任务集 ──────────────────────────────────────────────────
# 覆盖：诊断/记忆写/记忆读/JD 匹配/简历直读/多工具链/坏参数恢复/未知工具恢复/坏调用收敛

DIAGNOSE_TASK = EvalTask(
    name="diagnose_resume",
    instruction="帮我诊断一下这份简历的整体质量",
    script=(
        ScriptRound(tool_calls=(ToolCallSpec("diagnose_resume", {"resume_id": 1}),)),
        ScriptRound(content="诊断完成：简历整体质量良好，建议补充量化成果。"),
    ),
    gold_actions=(ToolCallSpec("diagnose_resume", {"resume_id": 1}),),
    required_outputs=("诊断完成",),
)

SAVE_MEMORY_TASK = EvalTask(
    name="save_memory",
    instruction="记住我擅长 Python 后端开发",
    script=(
        ScriptRound(tool_calls=(ToolCallSpec("save_memory", {"snippet": "擅长 Python 后端开发"}),)),
        ScriptRound(content="已记住你的偏好。"),
    ),
    gold_actions=(ToolCallSpec("save_memory", {"snippet": "擅长 Python 后端开发"}),),
    required_outputs=("已记住",),
)

RECALL_MEMORY_TASK = EvalTask(
    name="recall_memory",
    instruction="我之前说过什么求职目标吗",
    script=(
        ScriptRound(tool_calls=(ToolCallSpec("recall_memory", {"query": "求职目标"}),)),
        ScriptRound(content="根据记忆：你的目标是成为后端工程师。"),
    ),
    gold_actions=(ToolCallSpec("recall_memory", {"query": "求职目标"}),),
    required_outputs=("后端工程师",),
)

JD_MATCH_TASK = EvalTask(
    name="jd_match",
    instruction="帮我匹配这份简历适合的岗位",
    script=(
        ScriptRound(tool_calls=(ToolCallSpec("jd_match", {"resume_id": 1}),)),
        ScriptRound(content="匹配完成：推荐后端开发岗位。"),
    ),
    gold_actions=(ToolCallSpec("jd_match", {"resume_id": 1}),),
    required_outputs=("匹配完成",),
)

READ_RESUME_TASK = EvalTask(
    name="get_resume_content",
    instruction="我的毕业院校是什么",
    script=(
        ScriptRound(tool_calls=(ToolCallSpec("get_resume_content", {"resume_id": 1}),)),
        ScriptRound(content="你的毕业院校是示例大学。"),
    ),
    gold_actions=(ToolCallSpec("get_resume_content", {"resume_id": 1}),),
    required_outputs=("示例大学",),
)

MULTI_TOOL_CHAIN_TASK = EvalTask(
    name="multi_tool_chain",
    instruction="搜索简历里关于项目经历的细节，并深入分析回答",
    script=(
        ScriptRound(
            tool_calls=(ToolCallSpec("search_resume", {"resume_id": 1, "query": "项目经历"}),)
        ),
        ScriptRound(tool_calls=(ToolCallSpec("answer_from_index", {"question": "项目经历总结"}),)),
        ScriptRound(content="深度分析完成。"),
    ),
    gold_actions=(
        ToolCallSpec("search_resume", {"resume_id": 1, "query": "项目经历"}),
        ToolCallSpec("answer_from_index", {"question": "项目经历总结"}),
    ),
    required_outputs=("深度分析完成",),
)

BAD_ARGS_RECOVERY_TASK = EvalTask(
    name="bad_args_recovery",
    instruction="帮我匹配简历适合的岗位",
    script=(
        # 第一轮注入坏调用：缺 resume_id → 工具层 ToolRetryError → 错误回灌
        ScriptRound(tool_calls=(ToolCallSpec("jd_match", {}),)),
        # 第二轮修正为合法调用
        ScriptRound(tool_calls=(ToolCallSpec("jd_match", {"resume_id": 1}),)),
        ScriptRound(content="匹配完成：已修正参数。"),
    ),
    # 期望成功序列只含修正后的合法调用（坏调用不计入）
    gold_actions=(ToolCallSpec("jd_match", {"resume_id": 1}),),
    required_outputs=("匹配完成",),
)

UNKNOWN_TOOL_RECOVERY_TASK = EvalTask(
    name="unknown_tool_recovery",
    instruction="帮我搜索简历里的技能",
    script=(
        # 第一轮注入不存在工具 → 附可用列表错误 → 回灌
        ScriptRound(tool_calls=(ToolCallSpec("nonexistent_tool", {"query": "技能"}),)),
        ScriptRound(tool_calls=(ToolCallSpec("search_resume", {"resume_id": 1, "query": "技能"}),)),
        ScriptRound(content="搜索完成。"),
    ),
    gold_actions=(ToolCallSpec("search_resume", {"resume_id": 1, "query": "技能"}),),
    required_outputs=("搜索完成",),
)

CONVERGE_ON_BAD_CALLS_TASK = EvalTask(
    name="converge_on_bad_calls",
    instruction="帮我诊断简历",
    script=(
        # 连续 3 轮坏调用（缺参）→ 触发 MAX_TOOL_RETRIES 收敛
        ScriptRound(tool_calls=(ToolCallSpec("diagnose_resume", {}),)),
        ScriptRound(tool_calls=(ToolCallSpec("diagnose_resume", {}),)),
        ScriptRound(tool_calls=(ToolCallSpec("diagnose_resume", {}),)),
        # 强制收敛轮（无工具）：返回答案
        ScriptRound(content="已达到工具重试上限，请稍后重试。"),
    ),
    # 期望成功序列为空：所有调用都失败，agent 应终止而非死循环
    gold_actions=(),
    required_outputs=("重试上限",),
)

ALL_TASKS: tuple[EvalTask, ...] = (
    DIAGNOSE_TASK,
    SAVE_MEMORY_TASK,
    RECALL_MEMORY_TASK,
    JD_MATCH_TASK,
    READ_RESUME_TASK,
    MULTI_TOOL_CHAIN_TASK,
    BAD_ARGS_RECOVERY_TASK,
    UNKNOWN_TOOL_RECOVERY_TASK,
    CONVERGE_ON_BAD_CALLS_TASK,
)
