from sqlalchemy import event, text
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

# SQLite 默认关闭外键约束，账户删除时会留下 resumes/qa_history 等孤儿行，
# 进而使管理后台概况与真实数据不一致。开发/轻量部署也必须与生产数据库保持一致。
if settings.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

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
