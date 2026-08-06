"""公共面经/题库/范文检索入口（B3）。

三个公共语料集合（interview_hub / interview_qa / resume_samples）是全局只读知识库，
asset 以 ``user_id=0`` 写入，所有用户可检索。本模块提供跨整集合的语义检索：

- 集合名来自 ``clients.corpus_collection_name``（与 per-user ``knowledge_{user_id}`` 隔离）
- 显式 ``where={is_latest: True}`` 全量过滤（公共集合内 asset 均为 v1 最新快照）
- 复用 ``retrieval._vector_search`` / ``_keyword_search``（稠密 + BM25 双路）
- RRF 融合按 **(asset_id, chunk_index) 复合键** 去重：跨数百 asset 的集合里
  ``chunk_index`` 会跨 asset 重复，单用 ``chunk_index`` 会错配（个人集合单资产无此问题，
  故 ``hybrid_search_corpus`` 不必处理；公共集合必须处理）

为什么不用 ``hybrid_search_corpus(scope={})``：
空 scope 时 ``build_scope_where`` 会返回 ``{is_latest: True}`` 全量过滤（可行），但其内部
``_merge_results`` 按 ``chunk_index`` 合并，在跨 asset 集合里会碰撞错配，故自行复合键合并。

注意：本模块不注册 Agent 工具。接入方式建议（接 search_assets 或新建公共检索工具）
见实现报告，由主线程统一在 ``services/react_agent/tools/__init__.py`` 注册。
"""

import asyncio
from typing import Literal

from services.rag.clients import corpus_collection_name
from services.rag.metadata import META_IS_LATEST
from services.rag.retrieval import _keyword_search, _vector_search

# 公共语料类型（与 clients.CORPUS_KINDS 对齐）
CorpusKind = Literal["interview_hub", "interview_qa", "resume_samples"]

# RRF 平滑常数（与 retrieval._merge_results 保持一致，k 越小头部优势越大）
_RRF_K = 60
# 粗排窗口：稠密 / BM25 两路各取 top 20 → RRF 复合键合并精排 top_k
_CANDIDATE_K = 20


async def search_public_corpus(
    kind: CorpusKind,
    question: str,
    top_k: int = 5,
) -> list[dict]:
    """在指定公共语料集合全量检索（稠密 + BM25 → RRF 复合键合并）。

    Args:
        kind: 语料类型（interview_hub 公司面经 / interview_qa 算法题库 / resume_samples 简历范文）
        question: 检索查询词
        top_k: 返回条数

    Returns:
        按 RRF 综合得分降序的 ``[{text, section, score, source, asset_id, version}, ...]``：
        - ``text``: 命中段落原文
        - ``section``: 分节标题（公共 md 无简历节段标题时多为「正文」）
        - ``score``: RRF 综合得分
        - ``source``: dense（仅向量命中）/ sparse（仅 BM25 命中）/ hybrid（双路命中）
        - ``asset_id`` / ``version``: 来源资产（供溯源定位具体文件）
        集合为空或不存在时返回 ``[]``。
    """
    collection = corpus_collection_name(kind)
    where = {META_IS_LATEST: True}
    # BM25 缓存键：corpus 前缀命名空间，与个人集合（{user_id}:[..]）隔离
    store_key = f"corpus:{collection}:[]"

    dense, sparse = await asyncio.gather(
        _vector_search(collection, where, question, top_k=_CANDIDATE_K),
        _keyword_search(collection, where, store_key, question, top_k=_CANDIDATE_K),
    )
    return _rrf_merge_by_asset(dense, sparse, top_k)


def _rrf_merge_by_asset(
    dense: list[dict],
    sparse: list[dict],
    top_k: int,
) -> list[dict]:
    """RRF 融合，按 (asset_id, chunk_index) 复合键去重合并。

    - 复合键：跨 asset 的集合里 chunk_index 会重复，必须带上 asset_id 区分
    - 两路都命中的 chunk 得分叠加，source 标记为 hybrid
    - 返回的条目含 text/section/score/source/asset_id/version
    """
    merged: dict[tuple[int | None, int], dict] = {}
    for route, items in (("dense", dense), ("sparse", sparse)):
        for rank, item in enumerate(items):
            key = (item.get("asset_id"), item["chunk_index"])
            rrf = 1.0 / (_RRF_K + rank + 1)
            if key in merged:
                merged[key]["score"] += rrf
                merged[key]["source"] = "hybrid"
            else:
                merged[key] = {
                    "text": item["text"],
                    "section": item.get("section", ""),
                    "score": rrf,
                    "source": route,
                    "asset_id": item.get("asset_id"),
                    "version": item.get("version"),
                }
    ranked = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
    return ranked[:top_k]
