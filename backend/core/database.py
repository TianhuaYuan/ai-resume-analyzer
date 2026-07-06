from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,  # 主动回收空闲连接，防止 MySQL wait_timeout 断开
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # commit 后对象还能用
)


class Base(DeclarativeBase):
    pass


async def get_db():
    """每个请求拿一个 session，用完还回连接池"""
    async with AsyncSessionLocal() as session:
            yield session


async def init_db():
    """启动时验证数据库连通性，表迁移由 alembic 管理"""
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))