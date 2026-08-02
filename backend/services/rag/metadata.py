"""向量 chunk 元数据标准（D9 可移植性边界之一）。

所有写入 Chroma 的 chunk metadata 统一走本模块的字段常量与构造函数：
- 字段名跨实现稳定（Qdrant/Milvus 同样支持 dict metadata，字段名不绑 Chroma）
- 避免业务代码手拼字符串字段名造成漂移
- 为 T5 版本化（version / is_latest）与 T7 每用户集合（user_id / asset_id）预埋字段，
  本次仅写入、读取路径不动（T2 收缩方案）。
"""

from typing import Any

# --- 标准字段名 ---
META_USER_ID = "user_id"
META_ASSET_TYPE = "asset_type"
META_ASSET_ID = "asset_id"
META_VERSION = "version"
META_IS_LATEST = "is_latest"
# T8：索引时快照的 content_hash，兜底校验 chunk 是否与当前内容一致
META_CONTENT_HASH = "content_hash"
META_CHUNK_INDEX = "chunk_index"
META_SECTION = "section"
META_START_CHAR = "start_char"
META_END_CHAR = "end_char"

# --- 资产类型 ---
ASSET_TYPE_RESUME = "resume"

# 默认版本：首次索引即 v1 并标记为最新
DEFAULT_VERSION = 1
DEFAULT_IS_LATEST = True


def build_chunk_metadata(
    *,
    asset_id: int,
    chunk: dict[str, Any],
    user_id: int | None = None,
    asset_type: str = ASSET_TYPE_RESUME,
    version: int = DEFAULT_VERSION,
    is_latest: bool = DEFAULT_IS_LATEST,
    content_hash: str | None = None,
) -> dict[str, Any]:
    """构造标准 chunk metadata。

    兼容性：保留既有字段（chunk_index/section/start_char/end_char/resume_id），
    读取路径（chunks_service / retrieval）无需改动即可识别。

    注意：Chroma metadata 值只允许 str/int/float/bool，
    ``user_id`` / ``content_hash`` 仅在提供时写入（None 会报错）。
    """
    meta: dict[str, Any] = {
        META_ASSET_TYPE: asset_type,
        META_ASSET_ID: asset_id,
        META_VERSION: version,
        META_IS_LATEST: is_latest,
        META_CHUNK_INDEX: chunk["chunk_index"],
        META_SECTION: chunk["section"],
        META_START_CHAR: chunk["start_char"],
        META_END_CHAR: chunk["end_char"],
        # 兼容既有读取路径（resume 的 asset_id 即 resume_id）
        "resume_id": asset_id,
    }
    if user_id is not None:
        meta[META_USER_ID] = user_id
    if content_hash is not None:
        meta[META_CONTENT_HASH] = content_hash
    return meta
