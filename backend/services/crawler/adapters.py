"""声明式 API 源 adapter（借鉴 third_party/JobHunter/crawler/api_crawler.py，httpx 直连、无浏览器）。

设计目标：适配 2C4G 服务器的大厂官方招聘 API（GET/POST 直连 JSON），
不引入 playwright/browser 等重依赖，仅用项目已有的 httpx。

设计哲学（JobHunter API_CONFIGS 的 Python 化）：
    - 新增一个招聘源 = 填一份 ``APISourceConfig``，再 ``declare_api_adapter(config)`` 即可。
    - 非标准源（复杂分页 / 字段结构 / 需要登录头） = 继承 ``BaseSourceAdapter``
      覆写 ``build_page_params`` / ``parse_response`` / ``standardize`` 钩子。

统一输出 dict（对齐 ``backend/models/market_asset.py``，字段名见模块内映射表）：
    ``{source, external_id, title, company, location, salary, url,
      published_at, deadline, description}``

    ``field_mapping`` 的键即统一输出 dict 的键，值是源 JSON 里的点路径。

数据落地路径（入库走 market_sync_service，详见 ``crawler/__init__.py``）：
    ``adapter.fetch()`` → list[统一 dict] → 构造 ``NormalizedAsset`` 或写
    ``backend/data/jobs_*.json`` → ``sync_market(db, ...)`` → (source, external_id) 幂等 upsert。
"""

import hashlib
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx

from services.crawler.utils import clean_text, get_nested_value, parse_relative_date

logger = logging.getLogger(__name__)

# ── 统一输出 dict 的字段键（同时作为 field_mapping 的键） ─────────

K_SOURCE = "source"  # 源标识 → MarketAsset.source（幂等键之一）
K_EXTERNAL_ID = "external_id"  # 源内唯一 id → MarketAsset.external_id（幂等键）
K_TITLE = "title"  # → MarketAsset.title
K_COMPANY = "company"  # → MarketAsset.company
K_LOCATION = "location"  # → MarketAsset.city
K_SALARY = "salary"  # → MarketAsset.salary
K_URL = "url"  # → MarketAsset.apply_url（投递链接）
K_PUBLISHED_AT = "published_at"  # → MarketAsset.published_at（datetime 由 market_sync 转换）
K_DEADLINE = "deadline"  # → MarketAsset.deadline
K_DESCRIPTION = "description"  # → MarketAsset.content（D2 脏标记全文唯一载体）

# field_mapping 缺省值（JobHunter _parse_api_item 的默认路径对照）
_DEFAULT_FIELD_MAPPING: dict[str, str] = {
    K_TITLE: "name",
    K_COMPANY: "company",
    K_LOCATION: "location",
    K_SALARY: "salary",
    K_URL: "url",
    K_PUBLISHED_AT: "publishTime",
    K_DEADLINE: "deadline",
    K_DESCRIPTION: "description",
}

# 分页参数名自动检测候选（JobHunter _crawl_by_api 对照）
_PAGE_KEYS = ("pageIndex", "pageNo", "page", "offset", "pageNum", "currentPage")
_SIZE_KEYS = ("pageSize", "size", "limit", "count")

# 字段截断上限（对齐 market_sync_service._FIELD_LIMITS 的 DB 列长度，防 Data too long）
_FIELD_LIMITS = {
    K_EXTERNAL_ID: 100,
    K_TITLE: 255,
    K_COMPANY: 255,
    K_LOCATION: 255,
    K_SALARY: 100,
    K_URL: 2000,
    K_DESCRIPTION: 3000,
}


class SourceFetchError(Exception):
    """抓取源请求 / 响应解析失败（由调用方编排器决定重试或跳过）。"""


@dataclass
class APISourceConfig:
    """声明式 API 源配置。

    Args:
        name: 源标识，写入 ``MarketAsset.source``（如 ``"bytedance_campus"``）。
        api_url: 接口地址。
        method: ``GET`` / ``POST``。
        headers: 请求头（含必要鉴权/来源头）。
        params: 查询参数（GET 拼到 URL；POST 时作为附加 query）。
        payload: POST 请求 JSON body。
        data_path: 点路径，指向返回列表（如 ``"data.job_post_list"``）。
        total_key: 点路径，指向总数（分页提前终止用）；可为 ``None``。
        field_mapping: 统一输出键 → 源 JSON 字段点路径。
        job_url_template: 用 item 字段 format 出岗位 URL（如
            ``"https://zhaopin.meituan.com/job-list/{jobUnionId}"``）。
        dedup_key: 每个 item 唯一 id 的点路径（幂等 ``external_id``）。
            缺省回退：item 的 ``id``/``positionId``/``jdId``，再回退 url。
        page_key / size_key: 分页参数名覆盖（缺省自动检测）。
        page_size: 每页条数（缺省从 params/payload 读取，再兜底 20）。
        timeout: 单次请求超时（秒）。
        max_pages: ``fetch()`` 最多翻页数（防死循环护栏）。
    """

    name: str
    api_url: str
    method: str = "GET"
    headers: dict[str, str] | None = None
    params: dict[str, Any] | None = None
    payload: dict[str, Any] | None = None
    data_path: str = "data"
    total_key: str | None = None
    field_mapping: dict[str, str] = field(default_factory=dict)
    job_url_template: str | None = None
    dedup_key: str | None = None
    page_key: str | None = None
    size_key: str | None = None
    page_size: int | None = None
    timeout: float = 15.0
    max_pages: int = 5


class BaseSourceAdapter(ABC):
    """API 源 adapter 基类：``fetch`` 模板流程 + 可覆写钩子。

    模板流程（``fetch`` → ``fetch_page``）：
        请求 → 解析 JSON → ``parse_response`` 取列表 → 逐条 ``standardize`` → 统一 dict 列表。

    子类最小实现：``standardize(item)``。
    非标准源按需覆写钩子：
        ``build_page_params``  分页参数构造（offset/limit 型源必须覆写）
        ``parse_response``     data_path 不适用时的列表提取
        ``standardize``        field_mapping 不适用时的逐条标准化

    生命周期：
        ``async with adapter: ...`` 自动管理 httpx.AsyncClient；
        或手动 ``await adapter.aclose()``。

    统一输出 dict 字段 ↔ MarketAsset 映射：
        location → city；url → apply_url；description → content；
        published_at / deadline → datetime（market_sync_service._parse_dt 转换）；
        source + external_id → 幂等 upsert 唯一键。
    """

    def __init__(self, config: APISourceConfig):
        self.config = config
        self._client: httpx.AsyncClient | None = None

    # ── 生命周期 ──────────────────────────────────────────────

    async def __aenter__(self) -> "BaseSourceAdapter":
        await self._ensure_client()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def _ensure_client(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.config.timeout,
                headers=self.config.headers,
                follow_redirects=True,
            )

    async def aclose(self) -> None:
        """释放底层 httpx.AsyncClient（幂等，可重复调用）。"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── 模板流程 ──────────────────────────────────────────────

    async def fetch(
        self,
        params: dict[str, Any] | None = None,
        max_pages: int | None = None,
    ) -> list[dict[str, Any]]:
        """抓取全量（自动分页），返回统一 dict 列表。

        Args:
            params: 追加到源配置的查询/载荷参数（如 ``{"city": "北京"}``）。
            max_pages: 覆盖配置的翻页上限（护栏，默认取 ``config.max_pages``）。

        Returns:
            统一输出 dict 列表（字段见模块 docstring）。请求失败抛
            ``SourceFetchError``；单条解析失败仅记 debug 日志并跳过。
        """
        await self._ensure_client()
        page_key, size_key = self._detect_pagination_keys()
        base_params = {**(self.config.params or {}), **(params or {})}
        page_size = (
            self.config.page_size
            or base_params.get(size_key)
            or 20
        )
        max_pages = max_pages or self.config.max_pages

        collected: list[dict[str, Any]] = []
        for page_index in range(1, max_pages + 1):
            response = await self._request(
                page_index=page_index,
                base_params=base_params,
                page_key=page_key,
                size_key=size_key,
                page_size=page_size,
            )
            items = self.parse_response(response)
            if not items:
                break
            for item in items:
                try:
                    standardized = self.standardize(item)
                except Exception as e:  # noqa: BLE001 单条异常不中断整批
                    logger.debug(
                        "crawler standardize failed source=%s item=%s: %s",
                        self.config.name,
                        item,
                        e,
                    )
                    continue
                if standardized:
                    collected.append(standardized)
            # 提前终止：本页不足 / 已收满总数
            if len(items) < page_size:
                break
            total = self._extract_total(response)
            if total is not None and len(collected) >= total:
                break
        return collected

    # ── 可覆写钩子 ────────────────────────────────────────────

    async def _request(
        self,
        *,
        page_index: int,
        base_params: dict[str, Any],
        page_key: str,
        size_key: str,
        page_size: int,
    ) -> dict[str, Any]:
        """构造并发起一次分页请求，返回解析后的 JSON dict。"""
        page_params = self.build_page_params(
            page_index=page_index,
            base_params=base_params,
            page_key=page_key,
            size_key=size_key,
            page_size=page_size,
        )
        method = self.config.method.upper()
        try:
            if method == "GET":
                resp = await self._client.get(
                    self.config.api_url,
                    params={**base_params, **page_params},
                )
            else:
                resp = await self._client.post(
                    self.config.api_url,
                    params=self.config.params,
                    json={**(self.config.payload or {}), **page_params},
                )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            logger.warning("crawler source %s request failed: %s", self.config.name, e)
            raise SourceFetchError(f"{self.config.name}: request failed: {e}") from e
        except ValueError as e:  # resp.json() 解析失败
            logger.warning("crawler source %s bad json: %s", self.config.name, e)
            raise SourceFetchError(f"{self.config.name}: invalid json response") from e

    def build_page_params(
        self,
        *,
        page_index: int,
        base_params: dict[str, Any],
        page_key: str,
        size_key: str,
        page_size: int,
    ) -> dict[str, Any]:
        """构造第 ``page_index`` 页的参数。

        默认 ``{page_key: page_index, size_key: page_size}``。
        offset/limit 型源（如字节 ``offset=0, limit=10``）应覆写为
        ``{"offset": (page_index - 1) * page_size, "limit": page_size}``。
        """
        return {page_key: page_index, size_key: page_size}

    def parse_response(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        """从响应中取出岗位列表（默认按 ``config.data_path`` 取）。

        非列表（dict 包裹 / 直接是 dict）时返回 ``[]``，由调用方决定是否继续。
        """
        data = get_nested_value(response, self.config.data_path)
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
        return []

    @abstractmethod
    def standardize(self, item: dict[str, Any]) -> dict[str, Any] | None:
        """把源 item 标准化为统一输出 dict（必须实现）。

        返回 ``None`` 表示该条无效（跳过）。
        """

    def _extract_total(self, response: dict[str, Any]) -> int | None:
        """按 ``config.total_key`` 取总数；未配置或非数字返回 ``None``。"""
        if not self.config.total_key:
            return None
        value = get_nested_value(response, self.config.total_key)
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return int(value)
        return None

    # ── 内部工具 ──────────────────────────────────────────────

    def _detect_pagination_keys(self) -> tuple[str, str]:
        """检测分页参数名：配置覆盖优先，否则在 params/payload 里找已知候选。"""
        page_key = self.config.page_key
        size_key = self.config.size_key
        if page_key and size_key:
            return page_key, size_key
        combined = {**(self.config.params or {}), **(self.config.payload or {})}
        if not page_key:
            page_key = next((k for k in _PAGE_KEYS if k in combined), "pageIndex")
        if not size_key:
            size_key = next((k for k in _SIZE_KEYS if k in combined), "pageSize")
        return page_key, size_key


class GenericApiAdapter(BaseSourceAdapter):
    """field_mapping 驱动的通用声明式 adapter（JobHunter _parse_api_item 对照）。

    仅需一份 ``APISourceConfig`` 即可工作；非标准源再继承覆写钩子。
    """

    #: 时间戳形如 "2026-07-31 13:39:08" / "2026-07-31T00:00:00Z"（需保留时分秒给截止判定）
    _FULL_TS_RE = re.compile(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}[ T]\d{1,2}:\d{2}")

    def standardize(self, item: dict[str, Any]) -> dict[str, Any] | None:
        mapping = {**_DEFAULT_FIELD_MAPPING, **self.config.field_mapping}
        title = self._extract(item, mapping, K_TITLE, "未命名岗位")
        company = self._extract(item, mapping, K_COMPANY, "")
        location = self._join(self._extract(item, mapping, K_LOCATION, ""), "、")
        salary = self._extract(item, mapping, K_SALARY, "")
        url = self._extract(item, mapping, K_URL, "")
        description = clean_text(self._join(self._extract(item, mapping, K_DESCRIPTION, ""), "\n"))

        # 岗位 URL：field_mapping 命中 > job_url_template 填充 > 常见 id 拼接
        if not url and self.config.job_url_template:
            try:
                url = self.config.job_url_template.format(**item)
            except (KeyError, ValueError, AttributeError):
                pass

        # 幂等 external_id：dedup_key > 常见 id 键 > url（再兜底合成 hash）
        external_id = ""
        if self.config.dedup_key:
            external_id = str(get_nested_value(item, self.config.dedup_key) or "")
        if not external_id:
            external_id = str(
                item.get("id")
                or item.get("positionId")
                or item.get("jdId")
                or url
                or ""
            )
        if not external_id:
            external_id = hashlib.sha1(f"{self.config.name}|{title}|{company}".encode()).hexdigest()[:16]

        if not title and not description:
            return None

        return self._clip(
            {
                K_SOURCE: self.config.name,
                K_EXTERNAL_ID: external_id[: _FIELD_LIMITS[K_EXTERNAL_ID]],
                K_TITLE: title,
                K_COMPANY: company,
                K_LOCATION: location,
                K_SALARY: salary,
                K_URL: url,
                K_PUBLISHED_AT: self._normalize_date(self._extract(item, mapping, K_PUBLISHED_AT, "")),
                K_DEADLINE: self._normalize_date(self._extract(item, mapping, K_DEADLINE, "")),
                K_DESCRIPTION: description,
            }
        )

    # ── 内部工具 ──────────────────────────────────────────────

    def _extract(self, item: dict[str, Any], mapping: dict[str, str], key: str, default: str) -> Any:
        path = mapping.get(key)
        if not path:
            return default
        value = get_nested_value(item, path)
        return default if value is None else value

    @staticmethod
    def _join(value: Any, sep: str) -> str:
        """列表拍平：dict 元素取 ``name``，其余转 str，空元素丢弃。"""
        if value is None:
            return ""
        if isinstance(value, list):
            return sep.join(
                str(v.get("name") or v) if isinstance(v, dict) else str(v)
                for v in value
                if v
            )
        return str(value)

    def _normalize_date(self, raw: Any) -> str | None:
        """把源日期字段归一为字符串：
        - 完整时间戳（带时分秒）原样保留，交给 market_sync_service._parse_dt 完整解析
          （保证 deadline 到期判定不丢时刻）。
        - 相对日期 / 纯日期 → ``parse_relative_date`` 得 ``YYYY-MM-DD``。
        - epoch 数字（秒/毫秒）保留数字串（后续源若需要可扩展解析）。
        """
        if raw is None or raw == "":
            return None
        if isinstance(raw, (int, float)):
            return str(raw)
        s = str(raw).strip()
        if not s:
            return None
        if self._FULL_TS_RE.search(s):
            return s
        return parse_relative_date(s) or s

    @staticmethod
    def _clip(d: dict[str, Any]) -> dict[str, Any]:
        """按字段上限截断字符串，防 MySQL 严格模式 Data too long。"""
        for key, limit in _FIELD_LIMITS.items():
            val = d.get(key)
            if isinstance(val, str) and len(val) > limit:
                d[key] = val[:limit]
        return d


def declare_api_adapter(config: APISourceConfig) -> GenericApiAdapter:
    """从纯配置构造通用 adapter（新增招聘源只需加一份配置，参照 JobHunter 设计哲学）。

    Args:
        config: 声明式源配置（``name`` 与 ``api_url`` 必填）。

    Returns:
        一个可用的 ``GenericApiAdapter`` 实例（尚未发起任何请求）。

    Raises:
        ValueError: 缺 ``name`` / ``api_url``。
    """
    if not config.name or not config.api_url:
        raise ValueError("APISourceConfig.name / api_url 必填")
    return GenericApiAdapter(config)
