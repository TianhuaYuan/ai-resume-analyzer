"""
测试基础设施：SQLite 内存数据库 + AsyncClient fixture。
"""
import asyncio
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.database import Base, get_db
from main import app

# SQLite 内存数据库，每个测试函数独立
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine_test = create_async_engine(TEST_DATABASE_URL, echo=False)
AsyncSessionTest = async_sessionmaker(engine_test, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope="session")
def event_loop():
    """pytest-asyncio 需要一个全局 event loop。"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def setup_db():
    """每个测试前建表，测试后清表。"""
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


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
    resp = await client.post("/api/auth/register", json=user_data)
    assert resp.status_code == 201
    return {**user_data, "id": resp.json()["id"]}


@pytest.fixture
async def auth_headers(client: AsyncClient, registered_user: dict) -> dict:
    """登录并返回带 Authorization 的请求头。"""
    resp = await client.post("/api/auth/login", json={
        "email": registered_user["email"],
        "password": registered_user["password"],
    })
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
