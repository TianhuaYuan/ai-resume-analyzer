"""search_jobs_live — 实时岗位搜索工具（M2）。

替代已删除的 RecommendJobsTool（静态爬虫数据管线 M1 已彻底移除）。
岗位能力由实时网络搜索承接，按「自带工具/MCP → 轻量 HTTP → 友好降级」三级递进：

1. **主引擎 open-websearch**（npm 成熟 MCP 工具，免 key，本地 npx 直接消费）
   - 多引擎内部 fallback：csdn（岗位招聘博文，实测最佳）→ sogou → bing
   - 内部已封装反爬/降级，Agent 不感知，直接消费 search 结果
   - 经 subprocess 调 CLI（--spawn 自动起 daemon），输出结构化 JSON
2. **兜底 360 轻量 HTTP 解析**（open-websearch 不可用时，免费无 key）
3. **全部失败/无结果 → 友好降级提示**

选型记录（实测 2026-08）：
- open-websearch（Aas-ee/open-webSearch, 1686★）：csdn 出真实岗位 / sogou 有招聘 / bing 泛 / baidu 反爬 → 主引擎 csdn+sogou
- DuckDuckGo：大陆被墙 → 弃用；搜狗网页：验证页 → 弃用（open-websearch 内部 sogou 可用）
"""

import asyncio
import json
import logging
import re
import shutil
import subprocess
from abc import ABC, abstractmethod
from typing import Literal
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from services.react_agent.tools.base import Tool

logger = logging.getLogger(__name__)

# open-websearch CLI（Windows 下 npx 为 npx.cmd，跨平台用 shutil.which 探测）
_NPX = shutil.which("npx") or shutil.which("npx.cmd") or "npx"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

JOB_TYPE_LABEL = {
    "campus": "校园招聘",
    "social": "社会招聘",
    "intern": "实习",
}

_TAG_RE = re.compile(r"<[^>]+>")


def _clean_html(text: str) -> str:
    """去除 HTML 标签 + 合并空白（open-websearch 结果 snippet 常含 <em> 等）。"""
    return re.sub(r"\s+", " ", _TAG_RE.sub("", text or "")).strip()


class SearchJobsLiveArgs(BaseModel):
    query: str = Field(..., description="岗位关键词，如：后端开发、Java、数据分析、产品经理")
    target_position: str | None = Field(
        None, description="目标岗位名称（可选，用于构造更精准的搜索词）"
    )
    city: str | None = Field(
        None, description="城市，如：深圳、北京、上海、杭州（可选）"
    )
    job_type: Literal["campus", "social", "intern"] | None = Field(
        "social",
        description="岗位类型：campus 校招 / social 社招 / intern 实习，默认 social",
    )
    resume_id: int | None = Field(
        None, description="简历 ID（可选，仅做归属校验，暂不参与结果排序）"
    )
    limit: int = Field(5, description="返回结果数量上限，默认 5，最大 10")


class _SearchEngine(ABC):
    """搜索引擎基类：统一输出 [{title, url, snippet, source}]。"""

    name: str = ""

    @abstractmethod
    def search_sync(self, query: str, limit: int) -> list[dict]:
        """同步执行搜索。异常可抛出，由上层捕获继续下一个引擎。"""


class OpenWebSearchEngine(_SearchEngine):
    """open-websearch 主引擎：npm 成熟 MCP 工具，免 key，多引擎 fallback。

    经 subprocess 调 CLI（--json --spawn 自动起本地 daemon），引擎顺序
    csdn（岗位博文，实测最佳）→ sogou（有招聘结果）→ bing（泛内容兜底）。
    """

    name = "open-websearch"
    _engines = ("csdn", "sogou", "bing")
    _timeout = 30

    def search_sync(self, query: str, limit: int) -> list[dict]:
        for engine in self._engines:
            # 偶发失败（daemon 首次 spawn 竞态等）重试一次；空结果不重试直接换引擎
            for attempt in range(2):
                try:
                    items = self._search_one(query, limit, engine)
                except Exception as e:
                    logger.warning(
                        "open-websearch %s 搜索异常(第%d次): %s", engine, attempt + 1, e
                    )
                    if attempt == 1:
                        break
                    continue
                if items:
                    return items
                break
        return []

    def _search_one(self, query: str, limit: int, engine: str) -> list[dict]:
        cmd = [
            _NPX, "-y", "open-websearch", "search",
            query, "--limit", str(limit), "--engine", engine,
            "--json", "--spawn",
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self._timeout,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"exit={proc.returncode} {proc.stderr[:200]}")
        data = json.loads(proc.stdout or "{}")
        results = data.get("results") or data.get("data") or []
        if isinstance(results, dict):
            results = results.get("results", []) or []

        out: list[dict] = []
        for r in results:
            title = _clean_html(r.get("title") or "")
            url = r.get("url") or ""
            snippet = _clean_html(
                r.get("snippet") or r.get("description") or r.get("content") or ""
            )
            if not title or not url:
                continue
            out.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": snippet[:300],
                    "source": f"open-websearch/{engine}",
                }
            )
            if len(out) >= limit:
                break
        return out


class So360Engine(_SearchEngine):
    """360 搜索（www.so.com）— 兜底：实测能返回招聘岗位结果。"""

    name = "360"

    def search_sync(self, query: str, limit: int) -> list[dict]:
        url = f"https://www.so.com/s?q={quote(query)}"
        resp = httpx.get(url, headers=_HEADERS, timeout=10, follow_redirects=True)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        results: list[dict] = []
        for li in soup.select("li.res-list"):
            h3 = li.find("h3")
            a = h3.find("a") if h3 else None
            if not a:
                continue
            p = li.find("p", class_="res-desc") or li.find("p")
            site = li.find("span", class_="res-site")
            results.append(
                {
                    "title": a.get_text(strip=True),
                    "url": a.get("href", ""),
                    "snippet": (p.get_text(strip=True)[:300] if p and p.text else ""),
                    "source": site.get_text(strip=True) if site else "360搜索",
                }
            )
            if len(results) >= limit:
                break
        return results


class SearchJobsLiveTool(Tool):
    """实时岗位搜索：主引擎 open-websearch（MCP 成熟工具）→ 360/Bing 兜底 → 友好降级。

    用途：回答「有哪些岗位」「帮我找/推荐岗位」「xx城市有没有xx岗位」等
    需要实时数据的岗位类问题。区别于简历内检索，本工具检索全网。
    不做爬虫/反爬对抗，全部引擎失败时友好降级提示。
    """

    name = "search_jobs_live"
    description = (
        "实时搜索互联网上的招聘岗位信息（校招/社招/实习），"
        "返回岗位标题、公司、来源链接与简介。"
        "用于回答岗位推荐、招聘机会、某城市某类型岗位等需要实时数据的问题。"
    )
    args_model = SearchJobsLiveArgs
    category = "qa"

    _engines: list[_SearchEngine] = [OpenWebSearchEngine(), So360Engine()]

    async def _execute(self, **kwargs) -> str:
        query = kwargs.get("query") or ""
        target_position = kwargs.get("target_position")
        city = kwargs.get("city")
        job_type = kwargs.get("job_type") or "social"
        limit = min(kwargs.get("limit", 5) or 5, 10)
        # resume_id 仅做归属校验（base.execute 已自动完成），本阶段不参与排序

        search_query = self._build_query(query, target_position, city, job_type)

        # 引擎顺序尝试：主引擎内部多引擎 fallback，失败继续下一个引擎
        for engine in self._engines:
            try:
                items = await asyncio.to_thread(engine.search_sync, search_query, limit)
            except Exception as e:
                logger.warning("search_jobs_live %s 搜索异常: %s", engine.name, e)
                continue
            if items:
                return self._render(items, engine.name, search_query)

        # 全部引擎失败或无结果 → 友好降级提示
        return (
            f"⚠️ 实时岗位搜索暂时没有找到「{search_query}」相关的结果，"
            "可稍后重试，或更换关键词、城市、岗位类型再试。"
        )

    def _render(self, items: list[dict], engine: str, search_query: str) -> str:
        self.sources = [
            {"title": it["title"], "url": it["url"], "text": it.get("snippet", "")}
            for it in items
        ]
        lines = [f"「{search_query}」实时岗位搜索结果（{engine}，共 {len(items)} 条）："]
        for i, it in enumerate(items, 1):
            lines.append(f"\n{i}. {it['title']}")
            if it.get("snippet"):
                lines.append(f"   简介：{it['snippet'][:120]}")
            lines.append(f"   来源：{it['source']} | {it['url']}")
        lines.append(
            "\n注：以上为公开网页搜索到的岗位信息，具体以招聘方发布为准，建议点开来源核实。"
        )
        return "\n".join(lines)

    def _build_query(
        self,
        query: str,
        target_position: str | None,
        city: str | None,
        job_type: str | None,
    ) -> str:
        parts = [target_position or query]
        if city:
            parts.append(city)
        parts.append(JOB_TYPE_LABEL.get(job_type or "social", "招聘"))
        return " ".join(parts)
