"""web_search — 通用联网搜索工具（v2 阶段 1 A1）。

用途：面经 / 薪资 / 公司评价 / 招聘资讯等求职相关信息的通用联网搜索。
实现：httpx 直调博查 Web Search API（https://open.bochaai.com），
      header `Authorization: Bearer {BOCHA_API_KEY}`，
      body `{"query", "count", "freshness": "oneMonth"}`（时效策略：最近一个月）。

降级策略（不抛异常，均返回友好提示文本）：
1. BOCHA_API_KEY 为空 → 提示配置缺失
2. 非 200 / 超时 / 网络异常 → 捕获返回「稍后重试」
3. 无结果 → 提示更换关键词

响应解析：主结构 `resp["data"]["web_results"]`（计划指定），
          兜底兼容 `resp["data"]["webPages"]["value"]`（博查营销页示例结构），
          字段名容错 title/name、content/summary/snippet、site_name/siteName。
"""

import logging
import re
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from core.config import settings
from services.react_agent.tools.base import Tool

logger = logging.getLogger(__name__)

BOCHA_SEARCH_URL = "https://api.bocha.cn/v1/web-search"  # 官方接口域名（文档：https://open.bocha.cn）
_BOCHA_TIMEOUT = 15  # 秒

# 平台名 → 域名（site 参数限定搜索范围时映射为博查 include 参数）
_SITE_DOMAINS: dict[str, str] = {
    "牛客": "nowcoder.com",
    "nowcoder": "nowcoder.com",
    "boss": "zhipin.com",
    "boss直聘": "zhipin.com",
    "直聘": "zhipin.com",
    "拉勾": "lagou.com",
    "lagou": "lagou.com",
    "智联": "zhaopin.com",
    "zhaopin": "zhaopin.com",
    "前程无忧": "51job.com",
    "51job": "51job.com",
    "猎聘": "liepin.com",
    "liepin": "liepin.com",
    "csdn": "csdn.net",
    "知乎": "zhihu.com",
    "掘金": "juejin.cn",
    "脉脉": "maimai.cn",
    "看准": "kanzhun.com",
}


def _resolve_site_domains(site: str) -> str:
    """平台名/域名 → 博查 include 参数值（| 分隔，去重）。

    已是域名（含 .）直接透传；否则查平台名映射表，未命中则原样保留（交给博查自然匹配）。
    """
    parts = [p.strip() for p in re.split(r"[|,，、]", site) if p.strip()]
    domains: list[str] = []
    for p in parts:
        key = p.lower()
        resolved = p if "." in p else _SITE_DOMAINS.get(key, p)
        if resolved and resolved not in domains:
            domains.append(resolved)
    return "|".join(domains)


# time_range → 博查 freshness（信息时效范围）
_TIME_RANGE_FRESHNESS: dict[str, str] = {
    "day": "oneDay",
    "week": "oneWeek",
    "month": "oneMonth",
    "year": "oneYear",
}


class WebSearchArgs(BaseModel):
    query: str = Field(
        ..., description="搜索关键词，如：字节跳动 后端 面经、某公司 薪资待遇、某公司 工作氛围"
    )
    count: int = Field(10, ge=1, le=50, description="返回结果数量，默认 10，范围 1-50（博查单次最多 50）")
    time_range: Literal["day", "week", "month", "year"] | None = Field(
        None,
        description="信息时效范围：day 近一天 / week 近一周 / month 近一月 / year 近一年（默认 month）。"
        "按用户问题中的时间意图选择，如「最近」「最新」→ week/day，行业行情 → month/year",
    )
    site: str = Field(
        "",
        description="限定搜索的平台/网站，如：牛客、boss直聘、拉勾、智联、csdn、知乎；"
        "多个用逗号或|分隔；也可直接传域名（如 nowcoder.com）。空则不限定",
    )


class WebSearchTool(Tool):
    """通用联网搜索：面经/薪资/公司评价/招聘资讯等求职相关信息。

    与 search_jobs_live（岗位搜索）互补：本工具覆盖面更广，回答行业/公司/岗位的
    面试经验、薪资待遇、口碑评价、招聘资讯等需要实时资讯的问题。
    未配置博查 API Key 或请求失败时友好降级，不抛异常。
    """

    name = "web_search"
    description = (
        "联网搜索互联网上的面经/薪资/公司评价/招聘资讯等求职相关信息，"
        "返回标题、链接、摘要与来源站点。"
        "用于回答行业/公司/岗位的面试经验、薪资待遇、口碑评价、招聘行情等需要实时资讯的问题。"
    )
    args_model = WebSearchArgs
    category = "qa"

    async def _execute(self, **kwargs) -> str:
        query = (kwargs.get("query") or "").strip()
        count = min(kwargs.get("count", 10) or 10, 50)
        site = (kwargs.get("site") or "").strip()
        time_range = kwargs.get("time_range")

        if not settings.BOCHA_API_KEY.strip():
            return (
                "未配置博查联网搜索 API Key，无法联网。"
                "请在 backend/.env.dev 配置 BOCHA_API_KEY 后重试。"
            )

        try:
            items = await self._search(query, count, site, time_range)
            # include 严格限定目标平台 0 条 → 去掉平台限定降级重试（标注来源），避免空结果
            degraded_site = False
            if not items and site:
                items = await self._search(query, count, "", time_range)
                degraded_site = True
        except Exception as e:
            logger.warning("web_search 搜索异常: %s", e)
            return "⚠️ 联网搜索暂时失败，请稍后重试。"

        if not items:
            scope_note = f"（限定 {site}）" if site else ""
            return (
                f"⚠️ 未找到「{query}」{scope_note}相关的联网结果，"
                "可更换关键词、调整平台范围或取消平台限定再试。"
            )

        return self._render(items, query, site, degraded_site=degraded_site)

    async def _search(
        self,
        query: str,
        count: int,
        site: str = "",
        time_range: str | None = None,
    ) -> list[dict]:
        """调博查 Web Search API，返回归一化的搜索结果列表（异常向上抛由 _execute 兜底）。"""
        headers = {
            "Authorization": f"Bearer {settings.BOCHA_API_KEY}",
            "Content-Type": "application/json",
        }
        # 时效策略：按用户问题的时间意图映射 freshness，默认最近一个月
        # summary=true：博查返回文本摘要字段（文档：summary 属性当 summary=true 时显示）
        freshness = _TIME_RANGE_FRESHNESS.get(time_range or "month", "oneMonth")
        payload = {"query": query, "count": count, "freshness": freshness, "summary": True}
        include = _resolve_site_domains(site)
        if include:
            payload["include"] = include
        async with httpx.AsyncClient(timeout=_BOCHA_TIMEOUT) as client:
            resp = await client.post(BOCHA_SEARCH_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        return self._parse_results(data)

    def _parse_results(self, data: dict) -> list[dict]:
        """把博查响应解析为统一结构 [{title, url, snippet, source}]。

        官方响应主结构 `data.webPages.value`（name/url/snippet/summary/siteName/datePublished）；
        兼容兜底 `data.web_results`（历史猜测结构，实际接口不返回，保留防回归）。
        """
        web_results = ((data or {}).get("data") or {}).get("webPages") or {}
        web_results = web_results.get("value") or []
        if not web_results:
            web_results = ((data or {}).get("data") or {}).get("web_results") or []

        results: list[dict] = []
        for item in web_results:
            if not isinstance(item, dict):
                continue
            title = (item.get("title") or item.get("name") or "").strip()
            url = (item.get("url") or "").strip()
            if not title or not url:
                continue
            snippet = (
                item.get("summary")
                or item.get("content")
                or item.get("snippet")
                or ""
            ).strip()
            source = (item.get("siteName") or item.get("site_name") or "").strip()
            results.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": snippet[:300],
                    "source": source or "博查搜索",
                }
            )
        return results

    def _render(self, items: list[dict], query: str, site: str = "", degraded_site: bool = False) -> str:
        # 侧信道：结构化来源供 agent_done.sources 聚合（Spec A#10）
        self.sources = [
            {"title": it["title"], "url": it["url"], "text": it.get("snippet", "")}
            for it in items
        ]
        if site and not degraded_site:
            scope = f"（限定 {site}）"
        elif degraded_site:
            scope = f"（限定 {site} 结果较少，已展示其他平台）"
        else:
            scope = ""
        lines = [f"「{query}」联网搜索结果{scope}（博查，共 {len(items)} 条）："]
        for i, it in enumerate(items, 1):
            lines.append(f"\n{i}. {it['title']}")
            if it.get("snippet"):
                lines.append(f"   摘要：{it['snippet'][:120]}")
            lines.append(f"   来源：{it['source']} | {it['url']}")
        lines.append(
            "\n注：以上为公开网页搜索到的信息，具体以原站发布为准，建议点开来源核实。"
        )
        return "\n".join(lines)
