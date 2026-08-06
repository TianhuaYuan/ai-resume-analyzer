"""I3: 谈薪简报工具 NegotiationBriefTool（category: qa）。

输入目标岗位/城市/年限/当前薪资，输出：
- 总包锚定（基于当前薪资 + 年限的经验涨幅区间）
- 地理折扣（城市生活成本/薪酬系数，一线 1.0 → 二线 ~0.8）
- 谈薪话术（面试前锚定 / 收到口头 offer 后 / 被压低时的应对）

LLM 生成（JSON 契约）+ 确定性模板兜底（LLM 失败也不空手返回）。

设计（fieldwork 谈薪模块 + JobMcp Block D 薪酬市场对照）：
- 锚定数字来自用户真实输入（current_comp），不编造市场数据
- 兜底模板用保守区间，明确标注是估算
"""

from __future__ import annotations

import json
import logging
import re

from pydantic import BaseModel, Field

from services.rag.pipeline import llm_generate
from services.react_agent.tools.base import Tool

logger = logging.getLogger(__name__)


class NegotiationBriefArgs(BaseModel):
    """谈薪简报参数。"""

    target_position: str = Field(..., max_length=100, description="目标岗位")
    city: str | None = Field(None, max_length=50, description="工作城市")
    years: int | None = Field(None, ge=0, le=50, description="工作年限")
    current_comp: str | None = Field(
        None, max_length=100, description="当前薪资/总包，如 '40w' / '总包40万'"
    )

# 确定性地理折扣系数（兜底用；一线 1.0 → 二线 0.8）
_GEO_DISCOUNT: dict[str, tuple[float, str]] = {
    "北京": (1.0, "一线城市，薪酬基准高"),
    "上海": (1.0, "一线城市，薪酬基准高"),
    "深圳": (1.0, "一线城市，薪酬基准高"),
    "广州": (0.95, "一线城市，略低于北上深"),
    "杭州": (0.95, "新一线，互联网薪酬接近一线"),
    "南京": (0.9, "新一线"),
    "苏州": (0.9, "新一线"),
    "成都": (0.85, "新一线，薪酬系数低于一线"),
    "武汉": (0.85, "新一线"),
    "西安": (0.8, "二线"),
    "重庆": (0.8, "二线"),
    "长沙": (0.8, "二线"),
}

# 年限 → 经验涨幅系数（兜底锚定）
_YEARS_MULTIPLIER = [
    (2, 1.05),
    (5, 1.15),
    (10, 1.3),
]


def _parse_total_wan(current_comp: str) -> float | None:
    """从 '总包 40w' / '40万' / '400k' 等解析总包（单位：万人民币）。"""
    if not current_comp:
        return None
    text = current_comp.strip().lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*(w|万|k|k/年|k\\/年)?", text)
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2) or ""
    if unit in ("w", "万"):
        return num
    if unit.startswith("k"):
        # 月薪 k 估算年总包 ≈ k * 12 * 0.9（奖金系数，保守）
        return round(num * 12 * 0.9, 1)
    # 无单位：按"万"处理（用户习惯写 40）
    return num


def _year_multiplier(years: int | None) -> float:
    if not years or years < 0:
        return 1.0
    for threshold, mult in _YEARS_MULTIPLIER:
        if years <= threshold:
            return mult
    return 1.5


def _geo(city: str | None) -> dict:
    if not city:
        return {"city": "未指定", "factor": 1.0, "note": "未指定城市，按一线基准估算"}
    factor, note = _GEO_DISCOUNT.get(city, (1.0, f"{city}（无本地数据，按一线基准估算）"))
    return {"city": city, "factor": factor, "note": note}


def _deterministic_brief(
    target_position: str,
    city: str | None,
    years: int | None,
    current_comp: str | None,
) -> dict:
    """确定性模板兜底（LLM 失败时）。"""
    total = _parse_total_wan(current_comp)
    geo = _geo(city)

    if total:
        base = total * _year_multiplier(years) * geo["factor"]
        anchor_low = round(base * 1.0, 1)
        anchor_high = round(base * 1.15, 1)
        anchor_text = f"{anchor_low}–{anchor_high} 万（当前 {total} 万 × 年限系数 {_year_multiplier(years)} × 城市系数 {geo['factor']}）"
        floor_text = f"不低于 {round(base * 0.95, 1)} 万"
    else:
        anchor_text = "（未提供当前薪资，无法量化锚定；建议参考目标岗位市场区间）"
        floor_text = "（未提供当前薪资，无法给出底线）"

    scripts = [
        "【面试前】" + (
            f"我目前总包 {total} 万。基于我 {years or 'N'} 年经验与目标岗位，"
            "期望总包在您给的区间内再上浮 10-15%，更贴近市场水平。"
            if total else
            f"基于我 {years or 'N'} 年经验与目标岗位，希望先了解该岗位的预算区间，再对齐双方预期。"
        ),
        "【收到口头 offer】" + (
            f"感谢团队认可。我当前的包是 {total} 万，贵司方案与我的期望还有一定差距，"
            "能否在总包上再争取 X，或用签字费/期权做补充？"
            if total else
            "感谢团队认可。想确认一下总包的构成（月薪/年终/期权），方便我对齐预期。"
        ),
        "【被压低时】可以接受与市场持平的方案，但希望约定 6 个月后的绩效复审，并明确涨薪标准。",
    ]

    return {
        "target_position": target_position,
        "anchor": anchor_text,
        "anchor_floor": floor_text,
        "geo": geo,
        "scripts": scripts,
        "rationale": "LLM 生成失败，此为确定性估算模板，仅供讨论参考。",
        "generated_by": "template",
    }


_SYSTEM = (
    "你是一位资深谈薪顾问。基于候选人提供的目标岗位/城市/年限/当前薪资，"
    "生成谈薪简报。严格输出 JSON 对象（不要 Markdown，不要 ```json 包裹）：\n"
    '{"anchor": "<总包锚定区间，如 40-45 万，附一句依据>",\n'
    ' "anchor_floor": "<谈判底线，不低于 X>",\n'
    ' "geo": {"city": "<城市>", "factor": <0.7-1.1 数值>, "note": "<一句话> "},\n'
    ' "scripts": ["面试前锚定话术", "收到口头 offer 后话术", "被压低时的应对话术"],\n'
    ' "rationale": "<2-3 句依据>"}\n'
    "要求：\n"
    "1. 锚定基于用户提供的当前薪资与年限，不要编造市场数字；无当前薪资时如实说明；\n"
    "2. 地理折扣反映城市生活成本/薪酬系数（一线≈1.0，二线≈0.8）；\n"
    "3. 话术具体、可照说，中文。"
)


def _extract_brief_json(raw: str) -> dict | None:
    """抗截断 JSON 提取。"""
    try:
        data = json.loads(raw.strip())
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None


async def build_negotiation_brief(
    target_position: str,
    city: str | None,
    years: int | None,
    current_comp: str | None,
    user_id: int,
) -> dict:
    """LLM 生成 + 确定性模板兜底。"""
    fallback = _deterministic_brief(target_position, city, years, current_comp)
    try:
        user_prompt = (
            f"目标岗位：{target_position or '未指定'}\n"
            f"城市：{city or '未指定'}\n"
            f"工作年限：{years if years is not None else '未指定'} 年\n"
            f"当前薪资：{current_comp or '未提供'}\n\n"
            "请按 JSON 契约生成谈薪简报。"
        )
        raw = await llm_generate(
            system=_SYSTEM,
            user=user_prompt,
            temperature=0.3,
            user_id=user_id,
        )
        data = _extract_brief_json(raw)
        if not data:
            return fallback
        # 逐字段兜底（缺字段用模板）
        result = dict(fallback)
        for k in ("anchor", "anchor_floor", "rationale"):
            if isinstance(data.get(k), str) and data[k].strip():
                result[k] = data[k].strip()
        if isinstance(data.get("geo"), dict):
            result["geo"] = {
                "city": data["geo"].get("city", fallback["geo"]["city"]),
                "factor": data["geo"].get("factor", fallback["geo"]["factor"]),
                "note": data["geo"].get("note", ""),
            }
        if isinstance(data.get("scripts"), list):
            scripts = [str(s).strip() for s in data["scripts"] if str(s).strip()]
            if scripts:
                result["scripts"] = scripts[:5]
        result["generated_by"] = "llm"
        return result
    except Exception as e:
        logger.warning("谈薪简报 LLM 生成失败（使用模板兜底）: %s", e)
        return fallback


def _render_brief(brief: dict) -> str:
    """brief dict → 可读文本（loop 返回字符串用）。"""
    lines = [
        f"## 谈薪简报：{brief.get('target_position') or '目标岗位'}",
        "",
        f"**总包锚定**：{brief.get('anchor', '—')}",
        f"**谈判底线**：{brief.get('anchor_floor', '—')}",
        "",
        "**地理折扣**：",
        f"- {brief.get('geo', {}).get('city', '未指定')} 系数 {brief.get('geo', {}).get('factor', 1.0)}"
        f"（{brief.get('geo', {}).get('note', '')}）",
        "",
        "**谈薪话术**：",
    ]
    for i, s in enumerate(brief.get("scripts", []), 1):
        lines.append(f"{i}. {s}")
    if brief.get("rationale"):
        lines += ["", f"依据：{brief['rationale']}"]
    return "\n".join(lines)


async def negotiation_brief_execute(
    *,
    target_position: str,
    city: str | None,
    years: int | None,
    current_comp: str | None,
    user_id: int,
) -> str:
    """NegotiationBriefTool._execute 的纯逻辑（便于单测与复用）。

    Returns:
        Markdown 简报文本 + <negotiation_brief> JSON 块（供前端提取渲染）
    """
    brief = await build_negotiation_brief(
        target_position, city, years, current_comp, user_id
    )
    block = "\n\n<negotiation_brief>" + json.dumps(brief, ensure_ascii=False) + "</negotiation_brief>"
    return _render_brief(brief) + block


class NegotiationBriefTool(Tool):
    """I3: 谈薪简报工具（category: qa）。"""

    name = "negotiation_brief"
    description = (
        "生成谈薪简报：总包锚定区间 / 地理折扣 / 谈薪话术"
        "（基于目标岗位、城市、年限、当前薪资；LLM 生成 + 模板兜底）"
    )
    args_model = NegotiationBriefArgs
    category = "qa"

    async def _execute(self, **kwargs) -> str:
        return await negotiation_brief_execute(
            target_position=kwargs["target_position"],
            city=kwargs.get("city"),
            years=kwargs.get("years"),
            current_comp=kwargs.get("current_comp"),
            user_id=self.user_id or 0,
        )
