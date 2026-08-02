"""临时脚本：清理旧的无正文 guide 资产，重新同步有正文的 369 篇攻略。"""
import asyncio

from sqlalchemy import delete, func, select

from core.database import AsyncSessionLocal
from models.market_asset import MarketAsset
from services.rag.clients import market_collection_name
from services.market_sync_service import SOURCE_GUIDE, sync_market
from services.vector_store import get_vector_store


async def main():
    vs = get_vector_store()
    async with AsyncSessionLocal() as db:
        # 1. 删 DB 旧 guide 行
        old_count = await db.scalar(
            select(func.count()).select_from(MarketAsset).where(MarketAsset.source == SOURCE_GUIDE)
        )
        await db.execute(delete(MarketAsset).where(MarketAsset.source == SOURCE_GUIDE))
        await db.commit()
        print(f"已删除旧 guide 资产: {old_count} 条")

        # 2. 删 Chroma 里 asset_type=guide 的旧向量
        await vs.delete(market_collection_name(), {"asset_type": "guide"})
        print("已清理 Chroma guide 向量")

        # 3. 重新同步有正文的攻略
        stats = await sync_market(db, source=SOURCE_GUIDE)
        d = stats.to_dict()
        print(f"=== 攻略重同步完成 ===")
        print(f"total={d['total']} created={d['created']} updated={d['updated']} "
              f"unchanged={d['unchanged']} indexed={d['indexed']}")
        if d["errors"]:
            print("errors:", d["errors"][:5])


if __name__ == "__main__":
    asyncio.run(main())
