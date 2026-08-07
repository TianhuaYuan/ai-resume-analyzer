"""Tool 基类 — Agent 工具的统一接口。

T11 实现：
- db / user_id 构造器注入
- args pydantic 校验（execute 入口）
- 注入检测（detect_prompt_injection 对文本参数）
- 归属校验（resume_id(s) 归属当前 user）
- OpenAI function calling schema 生成

A3 工具契约化（借鉴 pydantic-ai 的 ModelRetry/ToolFailed 双通道）：
- ToolRetryError：可重试错误（参数格式错/暂时不可用）→ loop 累计坏调用，LLM 可修复重试
- ToolFailed：终端失败（业务确定性失败，如简历不存在/无权访问）→ loop 不累计坏调用
- args 校验失败格式化为逐字段错误回灌（替代 str(e) 黑盒，模型可自愈）
"""

import json
from abc import ABC, abstractmethod

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import detect_prompt_injection


class ToolRetryError(Exception):
    """工具可重试错误（A3，借鉴 pydantic-ai ModelRetry）。

    语义：参数格式错误 / 资源暂时不可用——LLM 收到结构化错误后可修复参数重试，
    loop 会累计该工具的失败次数（per-tool 重试预算）。
    """


class ToolFailed(Exception):
    """工具终端失败（A3，借鉴 pydantic-ai ToolFailed）。

    语义：业务确定性失败（简历不存在/无权访问/草稿未就绪）——重试也不会成功，
    loop 不累计坏调用；错误文本回灌给 LLM 让其换路径。
    """


class ApprovalRequired:
    """工具执行被审批门拦截的特殊结果（D1，借鉴 pydantic-ai Deferred tools）。

    命中 ``requires_approval`` 的工具在 ``execute()`` 中不实际执行，返回本对象：
    - 携带待审批信息（工具名 + 参数 + 摘要），由 react_agent.loop 发射
      ``approval_request`` SSE 事件等待用户确认
    - 用户批准后 loop 调用 ``mark_approval_granted()`` 重新执行；拒绝则把
      「用户拒绝」文本回灌 LLM（不累计坏调用，区别于 ToolRetryError / ToolFailed）
    """

    __slots__ = ("tool_name", "arguments", "summary")

    def __init__(self, tool_name: str, arguments: dict, summary: str) -> None:
        self.tool_name = tool_name
        self.arguments = arguments
        self.summary = summary


def format_validation_error(e: ValidationError) -> str:
    """把 pydantic ValidationError 压缩为逐字段错误文本（A3 契约化回灌）。

    借鉴 pydantic-ai _format_error_details：逐字段输出 loc + type + msg，
    让 LLM 能精确定位哪个参数错了、怎么改。
    """
    lines = []
    for err in e.errors():
        loc = ".".join(str(p) for p in err.get("loc", []))
        lines.append(f"- {loc}: {err.get('msg', '')} [type={err.get('type', '')}]")
    return f"{len(lines)} 个参数校验错误:\n" + "\n".join(lines)


# D1 集中审批映射：写类/有副作用工具按名命中即需用户确认后才执行。
# 优先放这里而不是逐个改 tools/ 子类（避免与阶段 1 对子类文件的改动冲突）。
# 子类也可直接置 requires_approval=True 覆盖/补充。
_APPROVAL_REQUIRED: dict[str, bool] = {
    "save_memory": True,        # L4 长期记忆写入
    "modify_module": True,      # builder 模块修改（写库）
    "rewrite_resume": True,     # 整份简历重写（写库）
    "rewrite_star": True,       # STAR 改写（写库）
    "translate": True,          # 翻译重写（写库）
    "search_jobs_live": True,   # 实时联网搜索（外部请求）
}


class Tool(ABC):
    """Agent 工具基类。

    子类需定义类属性：
        name: 工具名（唯一，用于 function calling）
        description: 工具描述（给 LLM 看的）
        args_model: pydantic BaseModel，定义工具参数 schema
        category: 工具分类 ("qa" / "builder" / "workbench")

    子类需实现：
        async _execute(**kwargs) -> str: 具体工具逻辑

    execute() 入口流程：
        1. args pydantic 校验（非法 → raise ValidationError）
        2. 注入检测（文本参数 → detect_prompt_injection）
        3. 归属校验（resume_id(s) → DB 查 user_id 匹配）
        4. 调用 _execute()
    """

    name: str = ""
    description: str = ""
    args_model: type[BaseModel]
    category: str = ""

    # D1 审批门（借鉴 pydantic-ai Deferred tools）：命中 requires_approval 的工具
    # 执行前需用户确认。子类可直接置 True，或通过下方集中映射 _APPROVAL_REQUIRED
    # 按工具名命中（优先用映射，避免逐个改 tools/ 下子类文件与阶段 1 冲突）。
    requires_approval: bool = False

    def __init__(
        self,
        db: AsyncSession | None = None,
        user_id: int | None = None,
        emit=None,
    ) -> None:
        self.db = db
        self.user_id = user_id
        # 可选事件回调：工具内部 LLM 流式 token 经此推给前端（tool_stream 事件）。
        # 由 react_agent.loop 在实例化工具时注入；缺省为 None（工具退化为非流式内部 LLM）。
        self.emit = emit
        self.sources: list[dict] = []  # 侧信道：工具执行后可填充结构化来源（Spec A#10）
        self.last_usage: dict = {"prompt_tokens": 0, "completion_tokens": 0}  # 工具内部 LLM 调用的 token 消耗

    @abstractmethod
    async def _execute(self, **kwargs) -> str:
        """子类实现具体工具逻辑。"""
        ...

    async def execute(self, **kwargs) -> str | ApprovalRequired:
        """入口：args 校验 → 注入检测 → D1 审批拦截 → 归属校验 → 执行。

        A3 契约化：校验失败抛 ToolRetryError（结构化错误文本由 loop 回灌），
        业务确定性失败（归属校验不过）抛 ToolFailed（不累计坏调用）。

        D1 审批门：命中 ``requires_approval``（类属性或集中映射）的工具在此拦截，
        不实际执行，返回 ``ApprovalRequired`` 交给 loop 发起用户确认；
        ``mark_approval_granted()`` 后再次调用才会真正执行。
        """
        # 1. args pydantic 校验（失败 → 结构化错误回灌，模型可自愈）
        try:
            validated = self.args_model(**kwargs)
        except ValidationError as e:
            raise ToolRetryError(format_validation_error(e)) from e

        # 2. 注入检测（对文本类参数）
        for _field, value in validated.model_dump().items():
            if isinstance(value, str) and value:
                is_suspicious, reason = detect_prompt_injection(value)
                if is_suspicious:
                    return f"⚠️ 检测到潜在提示注入（{reason}），请提供正常的内容。"

        # 2.5 D1 审批拦截钩子：命中 requires_approval 的工具不实际执行。
        #     参数已校验；返回 ApprovalRequired 携带待审批信息，由 loop 走审批门。
        #     仅在存在前端通道（emit 非 None）时拦截；emit=None（测试/直接调用/无前端）
        #     退化为直接执行，保持旧行为不破坏既有工具单测。
        if (
            self.is_approval_required()
            and not getattr(self, "_approval_granted", False)
            and self.emit is not None
        ):
            return ApprovalRequired(
                tool_name=self.name,
                arguments=validated.model_dump(),
                summary=self._build_approval_summary(validated),
            )

        # 3. 归属校验（对 resume_id 类参数）——确定性失败 → ToolFailed 不累计坏调用
        resume_ids = self._extract_resume_ids(validated)
        if resume_ids and self.db is not None and self.user_id is not None:
            for rid in resume_ids:
                if not await self._verify_ownership(rid):
                    raise ToolFailed(f"简历 {rid} 不存在或无权访问，请先确认简历 ID。")

        # 4. 执行（子类可抛 ToolRetryError / ToolFailed 表达业务语义）
        return await self._execute(**validated.model_dump())

    def is_approval_required(self) -> bool:
        """D1: 工具是否需要用户审批。类属性或集中映射命中即返回 True。"""
        return self.requires_approval or bool(_APPROVAL_REQUIRED.get(self.name, False))

    def mark_approval_granted(self) -> None:
        """D1: 用户已批准本次调用——放行 execute()（跳过审批拦截钩子）。

        由 react_agent.loop 在收到前端 approved 决议后调用，随后重新 execute()。
        """
        self._approval_granted = True

    def _build_approval_summary(self, validated: BaseModel) -> str:
        """D1: 生成审批弹窗展示摘要 = 工具描述首句 + 关键参数（供用户判断是否放行）。"""
        data = validated.model_dump()
        parts: list[str] = []
        for key, value in data.items():
            if value in (None, "", [], {}):
                continue
            if isinstance(value, (dict, list)):
                # 结构化参数（模块内容 / 简历 ID 列表等）：直接 str() 会输出原始 JSON，
                # 用户看不懂。改为紧凑 JSON 摘要并截断，保留"操作对象/要改什么"的辨识度。
                try:
                    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                except (TypeError, ValueError):
                    text = str(value)
                if len(text) > 60:
                    text = text[:60] + "…"
                parts.append(f"{key}={text}")
                continue
            text = str(value)
            if len(text) > 80:
                text = text[:80] + "…"
            parts.append(f"{key}={text}")
        args_str = "，".join(parts) if parts else "无参数"
        headline = (self.description or self.name).split("。")[0]
        return f"{headline}｜参数：{args_str}"

    def _extract_resume_ids(self, validated: BaseModel) -> list[int]:
        """从 validated args 中提取 resume_id / resume_ids。子类可覆盖。"""
        ids: list[int] = []
        for field_name in ("resume_id", "resume_ids"):
            val = getattr(validated, field_name, None)
            if isinstance(val, int):
                ids.append(val)
            elif isinstance(val, list):
                ids.extend(v for v in val if isinstance(v, int))
        return ids

    async def _get_resume(self, resume_id: int):
        """获取简历对象（校验归属）。None = 不存在或无权访问。"""
        from models.resume import Resume

        result = await self.db.execute(
            select(Resume).where(Resume.id == resume_id, Resume.user_id == self.user_id)
        )
        return result.scalar_one_or_none()

    async def _verify_ownership(self, resume_id: int) -> bool:
        """检查 resume_id 是否属于当前 user。"""
        return await self._get_resume(resume_id) is not None

    def to_openai_schema(self) -> dict:
        """生成 OpenAI function calling 格式的工具定义。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_model.model_json_schema(),
            },
        }
