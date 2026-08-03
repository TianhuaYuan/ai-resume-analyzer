"""Tool 基类 — Agent 工具的统一接口。

T11 实现：
- db / user_id 构造器注入
- args pydantic 校验（execute 入口）
- 注入检测（detect_prompt_injection 对文本参数）
- 归属校验（resume_id(s) 归属当前 user）
- OpenAI function calling schema 生成
"""

from abc import ABC, abstractmethod

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import detect_prompt_injection


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

    async def execute(self, **kwargs) -> str:
        """入口：args 校验 → 注入检测 → 归属校验 → 执行。"""
        # 1. args pydantic 校验
        validated = self.args_model(**kwargs)

        # 2. 注入检测（对文本类参数）
        for _field, value in validated.model_dump().items():
            if isinstance(value, str) and value:
                is_suspicious, reason = detect_prompt_injection(value)
                if is_suspicious:
                    return f"⚠️ 检测到潜在提示注入（{reason}），请提供正常的内容。"

        # 3. 归属校验（对 resume_id 类参数）
        resume_ids = self._extract_resume_ids(validated)
        if resume_ids and self.db is not None and self.user_id is not None:
            for rid in resume_ids:
                if not await self._verify_ownership(rid):
                    return f"⚠️ 简历 {rid} 不存在或无权访问。"

        # 4. 执行
        return await self._execute(**validated.model_dump())

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
