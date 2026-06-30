from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
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
    """开发用：启动时 create_all，生产用 alembic"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)