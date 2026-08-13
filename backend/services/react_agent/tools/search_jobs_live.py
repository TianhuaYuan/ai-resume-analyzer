"""search_jobs_live — 实时岗位搜索工具（M2）。

替代已删除的 RecommendJobsTool（静态爬虫数据管线 M1 已彻底移除）。
岗位能力由实时网络搜索承接，按「API 直调 → 自带工具/MCP → 轻量 HTTP → 友好降级」四级递进：

1. **主引擎博查 Bocha**（v2 A2/K，API 直调，需 .env 配置 BOCHA_API_KEY）
   - key 为空/请求失败 → 返回空列表，降级链继续（不抛异常）
2. **open-websearch**（npm 成熟 MCP 工具，免 key，本地 npx 直接消费）
   - 多引擎内部 fallback：csdn（岗位招聘博文，实测最佳）→ sogou → bing
   - 内部已封装反爬/降级，Agent 不感知，直接消费 search 结果
   - 经 subprocess 调 CLI（--spawn 自动起 daemon），输出结构化 JSON
3. **兜底 360 轻量 HTTP 解析**（博查/open-websearch 不可用时，免费无 key）
4. **全部失败/无结果 → 友好降级提示**

统一 Job schema（A2/K）：各引擎结果归一化为
{title, company, salary, city, url, deadline, source, snippet}，缺字段空串，
薪资从「标题+摘要」正则提取，渲染前按 url 去重。

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
from urllib.parse import quote, urlparse

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from core.config import settings
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

# time_range → 博查 freshness（发布时间范围）
_TIME_RANGE_FRESHNESS: dict[str, str] = {
    "day": "oneDay",
    "week": "oneWeek",
    "month": "oneMonth",
    "year": "oneYear",
}

# time_range → 展示标签
_TIME_RANGE_LABEL: dict[str, str] = {
    "day": "近一天",
    "week": "近一周",
    "month": "近一月",
    "year": "近一年",
}

# 招聘平台名 → 域名（site 参数限定搜索范围时映射为博查 include 参数）
_JOB_SITE_DOMAINS: dict[str, str] = {
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
}


def _resolve_site_domains(site: str) -> str:
    """平台名/域名 → 博查 include 参数值（| 分隔，去重）。"""
    parts = [p.strip() for p in re.split(r"[|,，、]", site) if p.strip()]
    domains: list[str] = []
    for p in parts:
        key = p.lower()
        resolved = p if "." in p else _JOB_SITE_DOMAINS.get(key, p)
        if resolved and resolved not in domains:
            domains.append(resolved)
    return "|".join(domains)


# 默认限定渠道：各大知名招聘平台（用户要求「范围限定在招聘平台 + 公司官网」，
# 公司官网域名无法穷举，先保证来自可靠招聘渠道；用户显式传 site 时叠加）。
_DEFAULT_JOB_SITE_DOMAINS = [
    "nowcoder.com",  # 牛客
    "zhipin.com",    # BOSS直聘
    "lagou.com",     # 拉勾
    "zhaopin.com",   # 智联招聘
    "51job.com",     # 前程无忧
    "liepin.com",    # 猎聘
    "kanzhun.com",   # 看准网
    "maimai.cn",     # 脉脉
    "csdn.net",      # CSDN
]


def _clean_html(text: str) -> str:
    """去除 HTML 标签 + 合并空白（open-websearch 结果 snippet 常含 <em> 等）。"""
    return re.sub(r"\s+", " ", _TAG_RE.sub("", text or "")).strip()


# 薪资正则：20-40K / 15k-25k / 20万-40万 等区间格式
_SALARY_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[Kk万]\s*(?:-|–|—|~|至)\s*(\d+(?:\.\d+)?)\s*[Kk万]?"
)


def _extract_salary(text: str) -> str:
    """从文本简单正则提取薪资区间（如 20-40K），没有返回空串。"""
    m = _SALARY_RE.search(text or "")
    if not m:
        return ""
    return re.sub(r"\s+", "", m.group(0)).upper()


def _filter_by_site(items: list[dict], include: str) -> list[dict]:
    """按渠道域名白名单过滤（对全部引擎统一生效，含兜底引擎）。

    博查 ``include`` 只在搜索前限定且仅博查引擎生效；open-websearch / 360 等
    兜底引擎完全不做渠道过滤，结果可能来自新闻/就业中心等非招聘渠道。
    本函数在结果层兜底：只保留主域名/子域名命中白名单的结果。
    include 形如 ``"zhipin.com|nowcoder.com"``（来自 _DEFAULT_JOB_SITE_DOMAINS 或用户 site）。
    URL 缺失或不在白名单一律丢弃；宁可少而准，不混入非招聘渠道。
    """
    allowed = {d for d in (include or "").split("|") if d.strip()}
    if not allowed:
        return items
    kept = []
    for it in items:
        url = (it.get("url") or "").strip()
        if not url:
            continue
        host = (urlparse(url).hostname or "").lower()
        if any(host == d or host.endswith("." + d) for d in allowed):
            kept.append(it)
    return kept


def _job_schema(*, title, url, snippet, source, company="", city="", deadline="") -> dict:
    """统一 Job schema：{title, company, salary, city, url, deadline, source, snippet}。

    field_mapping 归一化思路（各引擎原始字段不一，统一收敛为结构化输出）：
    各引擎原始字段不一，统一收敛为结构化输出；缺字段用空串，
    薪资从「标题 + 摘要」文本正则提取（没有则空）。
    """
    return {
        "title": title,
        "company": company,
        "salary": _extract_salary(f"{title} {snippet}"),
        "city": city,
        "url": url,
        "deadline": deadline,
        "source": source,
        "snippet": (snippet or "")[:300],
    }


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
    time_range: Literal["day", "week", "month", "year"] | None = Field(
        None,
        description="发布时间范围：day 近一天 / week 近一周 / month 近一月 / year 近一年（默认 year）。"
        "按用户问题中的时间意图选择，如「最近一周」→ week",
    )
    site: str | None = Field(
        None,
        description="限定招聘平台/网站（如：牛客、boss直聘、拉勾、智联、前程无忧、猎聘、csdn），"
        "多个用逗号或|分隔；也可直接传域名。空则不限定（注意：仅博查引擎生效，未配置博查 key 时忽略）",
    )
    resume_id: int | None = Field(
        None, description="简历 ID（可选，仅做归属校验，暂不参与结果排序）"
    )
    limit: int = Field(10, description="返回结果数量上限，默认 10，最大 20（超出自动截断）")


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
                _job_schema(
                    title=title,
                    url=url,
                    snippet=snippet,
                    source=f"open-websearch/{engine}",
                )
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
                _job_schema(
                    title=a.get_text(strip=True),
                    url=a.get("href", ""),
                    snippet=(p.get_text(strip=True) if p and p.text else ""),
                    source=site.get_text(strip=True) if site else "360搜索",
                )
            )
            if len(results) >= limit:
                break
        return results


class BochaEngine(_SearchEngine):
    """博查 Web Search 主引擎（v2 A2/K）：API 直调，质量与稳定性优于免 key 抓取。

    需在 .env 配置 BOCHA_API_KEY（未配置或请求失败 → 返回空列表 []，不抛异常，
    让降级链继续 OpenWebSearch / 360 兜底）。httpx 同步调用（httpx.Client 顶层便捷函数）。
    """

    name = "bocha"

    _url = "https://api.bocha.cn/v1/web-search"  # 博查官方接口域名
    _timeout = 15

    def search_sync(
        self,
        query: str,
        limit: int,
        freshness: str | None = None,
        include: str = "",
    ) -> list[dict]:
        api_key = getattr(settings, "BOCHA_API_KEY", "") or ""
        if not api_key.strip():
            logger.info("BOCHA_API_KEY 未配置，BochaEngine 降级跳过（走兜底引擎）")
            return []
        try:
            payload: dict = {
                "query": query,
                "count": limit,
                "freshness": freshness or "oneYear",  # 时间范围（默认近一年）
                "summary": True,  # 取文本摘要
            }
            if include:
                payload["include"] = include  # 渠道限制（招聘平台域名）
            resp = httpx.post(
                self._url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self._timeout,
                # BOCHA_PROXY：网络环境直连超时需显式代理（httpx 不走 Windows 注册表代理）
                proxy=getattr(settings, "BOCHA_PROXY", "") or None,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("BochaEngine 搜索异常: %s", e)
            return []
        return self._parse(data)

    def _parse(self, data: dict) -> list[dict]:
        # 官方响应主结构 data.webPages.value；兼容兜底 data["web_results"]（防回归）
        web_pages = ((data or {}).get("data") or {}).get("webPages") or {}
        web_results = web_pages.get("value") or []
        if not web_results:
            web_results = ((data or {}).get("data") or {}).get("web_results") or []

        out: list[dict] = []
        for item in web_results:
            if not isinstance(item, dict):
                continue
            title = _clean_html(item.get("title") or item.get("name") or "")
            url = (item.get("url") or "").strip()
            if not title or not url:
                continue
            snippet = _clean_html(
                item.get("content") or item.get("summary") or item.get("snippet") or ""
            )
            source = (item.get("site_name") or item.get("siteName") or "").strip()
            # 博查结果可能无 company/city/deadline，统一缺省空串；薪资由 _job_schema 正则提取
            out.append(
                _job_schema(
                    title=title,
                    url=url,
                    snippet=snippet,
                    source=source or "博查搜索",
                )
            )
        return out


class SearchJobsLiveTool(Tool):
    """实时岗位搜索：主引擎博查 Bocha（API，需 key）→ open-websearch → 360 兜底 → 友好降级。

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

    _engines: list[_SearchEngine] = [BochaEngine(), OpenWebSearchEngine(), So360Engine()]

    async def _execute(self, **kwargs) -> str:
        query = kwargs.get("query") or ""
        target_position = kwargs.get("target_position")
        city = kwargs.get("city")
        job_type = kwargs.get("job_type") or "social"
        limit = min(kwargs.get("limit", 10) or 10, 20)
        # 时间/渠道限制（仅博查引擎生效；open-websearch / 360 不支持时忽略）
        time_range = kwargs.get("time_range")
        freshness = _TIME_RANGE_FRESHNESS.get(time_range or "year", "oneYear")
        site = (kwargs.get("site") or "").strip()
        # 渠道限制：用户显式指定优先；否则默认限定各大知名招聘平台（含公司官网渠道的招聘页）
        if site:
            include = _resolve_site_domains(site)
        else:
            include = "|".join(_DEFAULT_JOB_SITE_DOMAINS)
        render_site = site or "知名招聘平台"
        # resume_id 仅做归属校验（base.execute 已自动完成），本阶段不参与排序

        search_query = self._build_query(query, target_position, city, job_type)

        # 引擎顺序尝试：主引擎内部多引擎 fallback，失败继续下一个引擎
        for engine in self._engines:
            try:
                if isinstance(engine, BochaEngine):
                    items = await asyncio.to_thread(
                        engine.search_sync, search_query, limit, freshness, include
                    )
                    # include 限定过严导致空结果 → 去掉渠道限定重试一次，避免空结果
                    if not items and include:
                        items = await asyncio.to_thread(
                            engine.search_sync, search_query, limit, freshness, ""
                        )
                else:
                    items = await asyncio.to_thread(engine.search_sync, search_query, limit)
            except Exception as e:
                logger.warning("search_jobs_live %s 搜索异常: %s", engine.name, e)
                continue
            if not items:
                continue
            # 渠道白名单过滤：对所有引擎统一生效（含兜底引擎），只保留招聘平台结果
            filtered = _filter_by_site(items, include)
            if not filtered:
                logger.info(
                    "search_jobs_live %s 返回 %d 条均不在渠道白名单内，试下一引擎",
                    engine.name, len(items),
                )
                continue
            return self._render(
                filtered, engine.name, search_query,
                time_range=time_range, site=render_site,
            )

        # 全部引擎失败或无结果 → 友好降级提示
        return (
            f"⚠️ 实时岗位搜索暂时没有找到「{search_query}」相关的结果，"
            "可稍后重试，或更换关键词、城市、岗位类型再试。"
        )

    def _render(
        self,
        items: list[dict],
        engine: str,
        search_query: str,
        time_range: str | None = None,
        site: str = "",
    ) -> str:
        # URL 去重（按 url，去重后渲染）
        seen: set[str] = set()
        uniq: list[dict] = []
        for it in items:
            url = (it.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            uniq.append(it)

        self.sources = [
            {"title": it["title"], "url": it["url"], "text": it.get("snippet", "")}
            for it in uniq
        ]
        scope_parts = []
        if time_range:
            scope_parts.append(_TIME_RANGE_LABEL.get(time_range, time_range))
        if site:
            scope_parts.append(f"限定 {site}")
        scope_str = f"（{'｜'.join(scope_parts)}）" if scope_parts else ""
        lines = [f"「{search_query}」实时岗位搜索结果{scope_str}（{engine}，共 {len(uniq)} 条）："]
        for i, it in enumerate(uniq, 1):
            lines.append(f"\n{i}. {it.get('title') or ''}")
            extra = []
            if it.get("company"):
                extra.append(f"公司：{it['company']}")
            if it.get("salary"):
                extra.append(f"薪资：{it['salary']}")
            if it.get("city"):
                extra.append(f"城市：{it['city']}")
            if it.get("deadline"):
                extra.append(f"截止：{it['deadline']}")
            if extra:
                lines.append("   " + " | ".join(extra))
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
