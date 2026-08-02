"""存量数据迁移：resume_{id} 集合 → knowledge_{user_id} 集合（T19）。

背景：T7 把向量集合从"每简历一个（resume_{id}）"改为"每用户一个（knowledge_{user_id}）"，
chunk metadata 需补 asset_type/asset_id/version/is_latest/content_hash。

本脚本：
- 遍历 DB 中所有简历，取其 user_id
- 对每个存在 resume_{id} 集合的简历：读取 documents + embeddings（复用不重算）+ 旧 metadata
- 用 build_chunk_metadata 构造新 metadata，写入 knowledge_{user_id}（chunk id 带资产前缀防跨简历碰撞）
- 默认 dry-run；加 --apply 实跑；加 --delete-old 迁移成功后删除旧集合

用法：
    cd backend
    python scripts/migrate_collections.py              # dry-run
    python scripts/migrate_collections.py --apply      # 实跑
    python scripts/migrate_collections.py --apply --delete-old
"""

import asyncio
import hashlib
import logging
import sys

from sqlalchemy import select

from core.database import AsyncSessionLocal
from models.resume import Resume
from services.rag.clients import get_chroma_client, knowledge_collection_name
from services.rag.metadata import ASSET_TYPE_RESUME, build_chunk_metadata
from services.vector_store import get_vector_store

logging.basicConfig(level=logging.INFO, format="%(levelname)-5.5s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


async def migrate(*, apply: bool, delete_old: bool) -> int:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(Resume))).scalars().all()

    client = get_chroma_client()
    store = get_vector_store()
    migrated = 0

    for r in rows:
        old_name = f"resume_{r.id}"
        try:
            coll = client.get_collection(old_name)
        except Exception:
            continue  # 无旧集合（懒索引后从未索引过），跳过

        data = coll.get(include=["documents", "embeddings", "metadatas"])
        docs = data.get("documents", []) or []
        embs = data.get("embeddings", []) or []
        metas = data.get("metadatas", []) or []
        if not docs:
            continue

        content_hash = hashlib.sha256((r.parsed_text or "").encode("utf-8")).hexdigest()
        new_metas = [
            build_chunk_metadata(
                asset_id=r.id,
                chunk={
                    "chunk_index": int(m.get("chunk_index", i)),
                    "section": m.get("section", ""),
                    "start_char": m.get("start_char", 0),
                    "end_char": m.get("end_char", 0),
                },
                user_id=r.user_id,
                asset_type=ASSET_TYPE_RESUME,
                version=1,
                is_latest=True,
                content_hash=content_hash,
            )
            for i, m in enumerate(metas)
        ]
        ids = [
            f"{ASSET_TYPE_RESUME}_{r.id}_v1_{int(m.get('chunk_index', i))}"
            for i, m in enumerate(metas)
        ]

        collection = knowledge_collection_name(r.user_id)
        if apply:
            await store.upsert(
                collection, ids=ids, documents=docs, embeddings=embs, metadatas=new_metas
            )
            if delete_old:
                try:
                    await store.delete_collection(old_name)
                    logger.info("已删除旧集合 %s", old_name)
                except Exception as e:
                    logger.warning("删除旧集合 %s 失败: %s", old_name, e)
        migrated += 1
        logger.info(
            "migrate resume_%d → %s（%d chunks, user=%d）",
            r.id, collection, len(docs), r.user_id,
        )

    logger.info("迁移完成：%d 份简历（apply=%s, delete_old=%s）", migrated, apply, delete_old)
    return migrated


def main() -> None:
    apply = "--apply" in sys.argv
    delete_old = "--delete-old" in sys.argv
    asyncio.run(migrate(apply=apply, delete_old=delete_old))


if __name__ == "__main__":
    main()
