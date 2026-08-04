"""爬虫管线基础设施（backend/services/crawler）。

本期只做基础设施，不实现具体招聘源。目标：为后续按 third_party/JobHunter 的
声明式 API 架构接入大厂官方招聘 API（GET/POST 直连 JSON，无浏览器，
适配 2C4G 服务器）提供通用骨架。

设计哲学（借鉴 JobHunter API_CONFIGS）：
    - 新增一个招聘源 = 填一份 ``APISourceConfig`` + ``declare_api_adapter(config)``；
      字段对齐 ``backend/models/market_asset.py`` 与 ``market_sync_service``。
    - 非标准源（复杂分页 / 字段结构 / 需要登录头） =
      继承 ``BaseSourceAdapter`` 覆写 ``build_page_params`` / ``parse_response`` / ``standardize``。

模块组成：
    utils.py    纯函数（parse_relative_date / clean_text / get_nested_value），无 I/O，
                可直接用于单元测试与同步归一化。
    adapters.py 声明式 API adapter（httpx 直连），输出统一 dict，自动分页。

数据落地路径（入库走 market_sync_service，本模块不触碰 DB）：

    1. 抓取
        adapter = declare_api_adapter(APISourceConfig(...))
        async with adapter:
            jobs = await adapter.fetch(params={"city": "北京"})   # list[统一 dict]

    2. 统一 dict（对齐 market_asset.py）：
        {source, external_id, title, company, location, salary, url,
         published_at, deadline, description}
        - location → MarketAsset.city
        - url      → MarketAsset.apply_url
        - description → MarketAsset.content（D2 脏标记全文唯一载体）
        - published_at / deadline → datetime（market_sync_service._parse_dt 转换）
        - source + external_id → 幂等 upsert 唯一键

    3. 喂给幂等 upsert（两条等价路径，二选一）：
        a) JSON 文件路径（现有模式）：
           jobs 写入 backend/data/jobs_*.json 的 records 数组（每条需带 _source
           标签以命中 market_sync_service._NORMALIZERS），然后触发
           POST /admin/market/sync（admin.py → sync_market(db, file=...)）。
        b) 直接调用路径：
           from services.market_sync_service import NormalizedAsset, sync_market
           用统一 dict 构造 NormalizedAsset，再 await sync_market(db, ...)
           —— 内部按 (source, external_id) 幂等 upsert，内容/过期变了才重索引。

    具体源的接线（写 JSON / 触发 sync / 定时调度）属后续实现，本期不落地。

约束：不新增依赖（仅 httpx，项目已有）；不建新表、不改 market_assets；
不修改 market_sync_service.py 现有逻辑。
"""

from services.crawler.adapters import (
    APISourceConfig,
    BaseSourceAdapter,
    GenericApiAdapter,
    SourceFetchError,
    declare_api_adapter,
)
from services.crawler.utils import clean_text, get_nested_value, parse_relative_date

__all__ = [
    # adapters
    "APISourceConfig",
    "BaseSourceAdapter",
    "GenericApiAdapter",
    "SourceFetchError",
    "declare_api_adapter",
    # utils
    "clean_text",
    "get_nested_value",
    "parse_relative_date",
]
