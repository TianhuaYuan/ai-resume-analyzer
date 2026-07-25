"""
测试基础设施：SQLite 内存数据库 + AsyncClient fixture。

注意：不再定义 session-scoped event_loop fixture，因为 Python 3.14+
将 asyncio.get_event_loop() 行为改为 raise RuntimeError 而非自动创建，
且 pytest-asyncio 0.25+ 已弃用该自定义 fixture。
使用默认的 function-scoped 事件循环，每个测试独立隔离。
"""

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.database import Base, get_db
from core.limiter import limiter
from main import app

# SQLite 内存数据库，每个测试函数独立
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine_test = create_async_engine(TEST_DATABASE_URL, echo=False)
AsyncSessionTest = async_sessionmaker(engine_test, class_=AsyncSession, expire_on_commit=False)


# P2-9: SQLite 默认关闭外键约束，CASCADE 不会生效。生产 MySQL 默认开启，
# 测试环境需通过 event listener 在每个连接建立时执行 PRAGMA foreign_keys=ON，
# 让测试 DB 行为接近生产，确保 ondelete=CASCADE 配置被真实验证。
@event.listens_for(engine_test.sync_engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_conn, conn_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture(autouse=True)
async def setup_db():
    """每个测试前建表，测试后清表。"""
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(autouse=True)
def disable_rate_limit():
    """测试中禁用限流，避免测试间互相影响。"""
    limiter.enabled = False
    yield
    limiter.enabled = True


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    """覆盖 FastAPI 的 get_db 依赖，指向测试数据库。"""
    async with AsyncSessionTest() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """异步 HTTP 测试客户端。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def registered_user(client: AsyncClient) -> dict:
    """注册一个测试用户并返回其信息。"""
    user_data = {
        "username": "testuser",
        "email": "test@example.com",
        "password": "Test1234!",
        "password_confirm": "Test1234!",
    }
    resp = await client.post("/api/v1/auth/register", json=user_data)
    assert resp.status_code == 201
    return {**user_data, "id": resp.json()["id"]}


@pytest.fixture
async def auth_headers(client: AsyncClient, registered_user: dict) -> dict:
    """登录并返回带 Authorization 的请求头。"""
    resp = await client.post(
        "/api/v1/auth/login",
        json={
            "email": registered_user["email"],
            "password": registered_user["password"],
        },
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
