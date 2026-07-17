"""阶段7 — 基于 DeepSeek 的 LLM-as-Judge 评估客户端（OpenAI 兼容协议）。

为什么单独一个客户端、单独的 JUDGE_* 配置？
- 业务问答用的是 Xiaomi MiMo（settings.CHAT_*），而 Judge 用 DeepSeek（settings.JUDGE_*）。
- 让「同一个人既答题又改卷」会天然产生自偏好偏差：模型倾向给自己的答案打高分。
  把答题与打分拆成两个不同家族的模型，才能让分数可信（详见阶段7复盘笔记）。

对外只暴露一个核心协程：
    await judge(question, answer, reference, sources) -> JudgeResult
返回三维度 0~1 分：completeness(完整性) / accuracy(准确性) / source_credibility(来源可信度)，
以及 rationale 理由。JudgeResult.composite 与 needs_reflexion 由权重自动算出。

测试友好：
- 真实 HTTP 调用被抽成 _call_deepseek()，测试直接 monkeypatch 它即可，绝不触网。
- 解析逻辑是纯函数 _parse_judge_response()，可单独测 DeepSeek 返回的 JSON 鲁棒性。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from typing import Any, Optional

from openai import AsyncOpenAI

from core.config import settings

logger = logging.getLogger(__name__)

# ── 三维度权重（权威口径，来自 MEMORY.md）──
# 完整性 40%：答案是否覆盖参考答案的关键点（有没有漏）。
# 准确性 40%：答案陈述与参考答案/事实是否一致（有没有错、有没有编）。
# 来源可信度 20%：答案是否能追溯到检索到的简历片段（有没有凭空捏造）。
WEIGHTS: dict[str, float] = {
    "completeness": 0.4,
    "accuracy": 0.4,
    "source_credibility": 0.2,
}

# composite 低于该阈值即认为答案不达标，需要走 Reflexion 自纠正闭环。
REFLEXION_THRESHOLD = 0.6

_JUDGE_SYSTEM_PROMPT = (
    "你是一个严谨的简历问答评审专家。你会拿到：候选人的问题、系统给出的答案、"
    "标准参考答案、以及系统作答时检索到的简历原文片段（来源）。\n"
    "请只依据上述材料，从以下三个维度给系统答案打分，每个维度 0~1 之间的浮点数"
    "（可保留两位），并在 rationale 中给出简明依据：\n"
    "1. completeness（完整性）：答案是否覆盖了参考答案中的关键信息点，有无明显遗漏。\n"
    "2. accuracy（准确性）：答案陈述与参考答案/事实是否一致，有无错误或编造。\n"
    "3. source_credibility（来源可信度）：答案中的关键事实是否能对应到提供的检索来源片段，"
    "若答案出现来源中根本不存在的关键信息，此项应给低分。\n"
    "只输出一个 JSON 对象，格式严格如下，不要任何额外说明或 Markdown 代码块：\n"
    '{"completeness": <float>, "accuracy": <float>, "source_credibility": <float>, "rationale": "<string>"}'
)


@dataclass
class JudgeResult:
    """单条答案的 Judicial 评估结果（三维度 + 理由）。"""

    completeness: float
    accuracy: float
    source_credibility: float
    rationale: str
    model: str
    raw: Optional[str] = None  # DeepSeek 原始返回，便于排查

    @property
    def composite(self) -> float:
        """三维度加权综合分（0~1）。"""
        return (
            self.completeness * WEIGHTS["completeness"]
            + self.accuracy * WEIGHTS["accuracy"]
            + self.source_credibility * WEIGHTS["source_credibility"]
        )

    @property
    def needs_reflexion(self) -> bool:
        """composite < 阈值 → 需要 Reflexion 自纠正。"""
        return self.composite < REFLEXION_THRESHOLD

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["composite"] = round(self.composite, 4)
        d["needs_reflexion"] = self.needs_reflexion
        d["weights"] = WEIGHTS
        d["reflexion_threshold"] = REFLEXION_THRESHOLD
        return d


# ── 客户端（懒初始化，避免 import 期就建连）──
_client: Optional[AsyncOpenAI] = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.JUDGE_API_KEY,
            base_url=settings.JUDGE_BASE_URL,
            timeout=60.0,
        )
    return _client


def _build_user_prompt(
    question: str,
    answer: str,
    reference: str,
    sources: list[dict],
) -> str:
    """拼装给 Judge 的 user prompt：把来源片段一并喂进去，便于它校验可信度。"""
    src_lines = []
    for i, s in enumerate(sources or [], start=1):
        text = s.get("text") or s.get("content") or ""
        section = s.get("section") or ""
        src_lines.append(f"[来源{i}]{('（' + section + '）') if section else ''}{text}")
    src_block = "\n".join(src_lines) if src_lines else "（无检索来源）"
    return (
        f"【问题】\n{question}\n\n"
        f"【标准参考答案】\n{reference}\n\n"
        f"【系统答案】\n{answer}\n\n"
        f"【检索到的来源片段】\n{src_block}\n"
    )


async def _call_deepseek(prompt: str) -> str:
    """真实调用 DeepSeek（OpenAI 兼容）。可被测试 monkeypatch，避免触网与泄露密钥。

    deepseek-reasoner 不支持 response_format 与自定义 temperature，需特殊处理。
    """
    if not settings.JUDGE_ENABLED:
        raise RuntimeError("Judge 未启用（JUDGE_ENABLED=false），请先启用或显式注入 judge 函数。")
    if not settings.JUDGE_API_KEY:
        raise RuntimeError("缺少 JUDGE_API_KEY，无法调用 DeepSeek Judge。")

    is_reasoner = "reasoner" in settings.JUDGE_MODEL.lower()
    client = _get_client()
    kwargs: dict[str, Any] = {
        "model": settings.JUDGE_MODEL,
        "messages": [
            {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 800,
    }
    # reasoner 模型忽略 temperature 且不支持 json 模式，普通模型请求 JSON 输出更稳
    if not is_reasoner:
        kwargs["temperature"] = settings.JUDGE_TEMPERATURE
        kwargs["response_format"] = {"type": "json_object"}

    resp = await client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


def _parse_judge_response(text: str) -> JudgeResult:
    """把 DeepSeek 的返回解析成 JudgeResult。对代码块围栏、前后缀噪声都做兜底。"""
    if text is None:
        raise ValueError("Judge 返回为空")
    raw = text.strip()

    # 去掉 ```json ... ``` 这类围栏
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL | re.IGNORECASE)
    if fence:
        raw = fence.group(1).strip()

    # 截取第一个 { 到最后一个 } 之间的内容，容忍前后多余文本
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"Judge 返回中找不到 JSON 对象：{text!r}")
    payload = raw[start : end + 1]

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        raise ValueError(f"Judge 返回 JSON 解析失败：{e} | 原文：{text!r}") from e

    def _to_float(v: Any) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    completeness = _clamp01(_to_float(data.get("completeness")))
    accuracy = _clamp01(_to_float(data.get("accuracy")))
    source_credibility = _clamp01(_to_float(data.get("source_credibility")))
    rationale = str(data.get("rationale", "")).strip()

    return JudgeResult(
        completeness=completeness,
        accuracy=accuracy,
        source_credibility=source_credibility,
        rationale=rationale,
        model=settings.JUDGE_MODEL,
        raw=text,
    )


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


async def judge(
    question: str,
    answer: str,
    reference: str,
    sources: list[dict] | None = None,
) -> JudgeResult:
    """阶段7 核心入口：对一条 (问题, 答案, 参考答案, 来源) 打三维度分。

    测试可 monkeypatch 本函数，或 monkeypatch _call_deepseek 返回假 JSON，从而不触网。
    """
    prompt = _build_user_prompt(question, answer, reference, sources or [])
    raw = await _call_deepseek(prompt)
    return _parse_judge_response(raw)
