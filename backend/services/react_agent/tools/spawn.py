"""spawn — 子代理/多 agent 委派工具。

在主 agent 的回合内，把独立子任务委派给一个"子代理"执行并返回结果。
子代理是一个轻量 ReAct 循环：携带只读工具子集（不含 spawn，防递归），
在受限轮数内自主决定是否检索。适合把长任务拆给子代理并行思考，
主 agent 拿到结果后继续整合。

安全边界：
- 工具子集只读（检索类），排除 spawn / 写库 / 审批类工具 → 无递归、无副作用
- 子代理轮数受限（SUBAGENT_MAX_ROUNDS=2）
- 子代理不装配 L2/L3/L4 记忆（避免与主 agent 重复注入），只带角色指令
"""

import asyncio
import json
import logging

from pydantic import BaseModel, Field

from services.rag.pipeline import ToolCall, llm_generate_with_tools
from services.react_agent.tools.base import Tool

logger = logging.getLogger(__name__)

# 子代理只读工具子集（检索/直读类；排除 spawn 防递归、排除写库/审批类防副作用）
_SUBAGENT_READ_ONLY_TOOLS = (
    "search_resume",
    "search_assets",
    "get_resume_content",
    "search_corpus",
    "web_search",
    "recall_memory",
)

SUBAGENT_MAX_ROUNDS = 2
SUBAGENT_MAX_TOOL_RESULT_CHARS = 1500

_SUBAGENT_SYSTEM = (
    "你是主 Agent 委派的子代理，负责独立完成一个子任务。\n"
    "你可以调用检索类工具获取信息，然后基于结果给出简洁、结构化的回答。\n"
    "如果信息不足，明确说明缺什么，不要编造。\n"
    "不要调用与检索无关的工具，不要写任何数据。"
)


class SpawnArgs(BaseModel):
    task: str = Field(
        ...,
        description="委派给子代理的子任务描述（独立、自包含、可检索完成）。"
        "例如：『检索该简历的教育背景细节』『搜索某公司面经并总结』",
    )
    resume_id: int = Field(
        ..., description="当前简历 ID（子代理检索时的归属校验基础）"
    )


class SpawnTool(Tool):
    """ 委派子任务给子代理执行并返回结果（只读，多 agent 协作）。"""

    name = "spawn"
    description = (
        "把独立子任务委派给一个子代理执行并返回结果。"
        "适合需要深度检索/独立分析的长任务（如先单独调研某话题再整合）。"
        "子代理携带只读检索工具，不能写数据，不能无限递归。"
    )
    args_model = SpawnArgs
    category = "qa"

    async def _execute(self, **kwargs) -> str:
        task = (kwargs.get("task") or "").strip()
        resume_id = kwargs.get("resume_id")

        if not task:
            return "spawn 失败：task 为空。"

        try:
            return await self._run_subagent(task, resume_id)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("spawn 子代理执行失败: %s", e, exc_info=True)
            return f"spawn 子代理执行失败：{e}"

    async def _run_subagent(self, task: str, resume_id: int) -> str:
        """轻量 ReAct：只读工具子集 + 受限轮数，返回子代理结论。"""
        from services.react_agent.tools import get_tool_by_name

        # 构建子代理工具 schemas（只读子集）
        tool_classes = [
            get_tool_by_name(name)
            for name in _SUBAGENT_READ_ONLY_TOOLS
            if get_tool_by_name(name) is not None
        ]
        tool_schemas = [tc().to_openai_schema() for tc in tool_classes]

        messages: list[dict] = [
            {"role": "system", "content": _SUBAGENT_SYSTEM},
            {"role": "user", "content": task},
        ]

        rounds = 0
        while rounds < SUBAGENT_MAX_ROUNDS:
            rounds += 1
            response = await llm_generate_with_tools(
                messages=messages,
                tools=tool_schemas,
                temperature=0.1,
                max_tokens=1200,
                model=None,  # 主模型
                user_id=self.user_id,
            )

            if not response.tool_calls:
                return (response.content or "").strip() or "子代理未产出内容。"

            # 执行工具（只读，无审批门）
            messages.append(self._build_assistant_message(response))
            for tc in response.tool_calls:
                result = await self._execute_sub_tool(tc, tool_classes, resume_id)
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": result}
                )

        # 轮数耗尽，强制无工具收尾
        final = await llm_generate_with_tools(
            messages=messages,
            tools=None,
            temperature=0.1,
            max_tokens=1200,
            model=None,
            user_id=self.user_id,
        )
        return (final.content or "").strip() or "子代理未产出内容。"

    async def _execute_sub_tool(
        self, tc: ToolCall, tool_classes: list, resume_id: int
    ) -> str:
        """执行子代理的一个只读工具调用（归属校验 + 截断）。"""
        from services.react_agent.tools.base import ToolFailed

        try:
            args = json.loads(tc.arguments) if tc.arguments else {}
        except json.JSONDecodeError:
            return f"工具参数 JSON 解析失败: {tc.arguments}"

        tool_cls = next((t for t in tool_classes if t.name == tc.name), None)
        if tool_cls is None:
            return f"工具 '{tc.name}' 不可用于子代理（只读子集）。"
        # 归属校验：确保 resume_id 属于当前 user（复用基类）
        if args.get("resume_id") is None and resume_id is not None:
            args["resume_id"] = resume_id
        try:
            tool = tool_cls(db=self.db, user_id=self.user_id, emit=None)
            result = await tool.execute(**args)
        except ToolFailed as e:
            return f"[子代理工具失败] {e}"
        except Exception as e:
            logger.warning("子代理工具 %s 执行异常: %s", tc.name, e)
            return f"子代理工具 {tc.name} 执行失败：{e}"

        text = result if isinstance(result, str) else str(result)
        if len(text) > SUBAGENT_MAX_TOOL_RESULT_CHARS:
            text = text[: SUBAGENT_MAX_TOOL_RESULT_CHARS - 3] + "..."
        return text

    @staticmethod
    def _build_assistant_message(response) -> dict:
        return {
            "role": "assistant",
            "content": response.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.arguments},
                }
                for tc in response.tool_calls
            ],
        }
