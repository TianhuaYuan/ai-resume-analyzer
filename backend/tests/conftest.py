"""
测试基础设施：SQLite 内存数据库 + AsyncClient fixture。

注意：不再定义 session-scoped event_loop fixture，因为 Python 3.14+
将 asyncio.get_event_loop() 行为改为 raise RuntimeError 而非自动创建，
且 pytest-asyncio 0.25+ 已弃用该自定义 fixture。
使用默认的 function-scoped 事件循环，每个测试独立隔离。
"""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.database import Base, get_db
from core.limiter import limiter
from main import app
# Explicitly register newly introduced runtime models before create_all.  The
# application imports these models lazily from the streaming path, while the
# test database is created earlier during fixture setup.
import models.agent_proposal  # noqa: F401
import models.agent_run  # noqa: F401

# SQLite 文件数据库（测试期间共享同一文件，测试后自动清理）
import tempfile
import os

_test_db_file = tempfile.mktemp(suffix=".db")
TEST_DATABASE_URL = f"sqlite+aiosqlite:///{_test_db_file}"

engine_test = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
    pool_size=32,
    max_overflow=32,
    pool_timeout=60,
)
AsyncSessionTest = async_sessionmaker(engine_test, class_=AsyncSession, expire_on_commit=False)

# RunLifecycle resolves its default session factory lazily.  Point it at the
# same isolated database used by the HTTP fixtures; otherwise a stream test
# would persist AgentRun rows into the application's separate test database.
import services.react_agent.run_lifecycle as _run_lifecycle

_run_lifecycle.AsyncSessionLocal = AsyncSessionTest


def _cleanup_test_db():
    """清理临时测试数据库文件。"""
    try:
        if os.path.exists(_test_db_file):
            os.unlink(_test_db_file)
    except Exception:
        pass


import atexit
atexit.register(_cleanup_test_db)


# SQLite 默认关闭外键约束，CASCADE 不会生效。生产 MySQL 默认开启，
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
async def reset_global_llm_breakers():
    """每个用例隔离全局 LLM 熔断器，避免失败用例污染后续 mock 调用。"""
    from services.rag import clients as rag_clients

    for breaker in (rag_clients.get_chat_breaker(), rag_clients.get_judge_breaker()):
        if breaker is not None:
            async with breaker._lock:
                breaker.state = breaker.CLOSED
                breaker.failure_count = 0
                breaker.last_failure_time = None
                breaker._half_open_calls = 0
    yield


@pytest.fixture(autouse=True)
def disable_rate_limit():
    """测试中禁用限流，避免测试间互相影响。"""
    limiter.enabled = False
    yield
    limiter.enabled = True


class _FakeToolAsyncSession:
    """模拟 AsyncSessionLocal() 返回的独立 session（async context manager）。

    不能直接 mock 成 AsyncMock 实例：AsyncMock 的 __call__ 是 async 的，
    `AsyncSessionLocal()` 会返回 coroutine 而不是支持 `async with` 的对象。
    """

    def __init__(self) -> None:
        self.session = AsyncMock()

    async def __aenter__(self) -> AsyncMock:
        return self.session

    async def __aexit__(self, *exc_info) -> bool:
        return False


@pytest.fixture(autouse=True)
def _mock_loop_tool_db():
    """react_loop 工具执行的独立 session 用 mock 替代，避免测试连真实 MySQL。

    loop._execute_tool_call_with_limit 为每个工具开独立 AsyncSessionLocal，
    测试中不需要真实 DB，全局 mock 掉该工厂。
    """
    with patch("services.react_agent.loop.AsyncSessionLocal", new=_FakeToolAsyncSession):
        yield


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    """覆盖 FastAPI 的 get_db 依赖，指向测试数据库。"""
    async with AsyncSessionTest() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """提供直接操作测试数据库的会话。"""
    async with AsyncSessionTest() as session:
        yield session


@pytest.fixture
async def test_user(client, registered_user, db_session: AsyncSession):
    """与 auth_headers 同一用户（registered_user）的 ORM 对象。

    保证依赖 test_user 建的数据与 auth_headers 的归属一致（避免 404）。
    """
    from models.user import User

    return await db_session.get(User, registered_user["id"])


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """异步 HTTP 测试客户端。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def registered_user(client: AsyncClient) -> dict:
    """注册一个测试用户并返回其信息。
    
    流程：先调用 /send-code 获取验证码，再调用 /register 完成注册。
    """
    user_data = {
        "username": "testuser",
        "email": "test@example.com",
        "password": "Test1234!",
        "password_confirm": "Test1234!",
    }
    
    await client.post("/api/v1/auth/send-code", json={"email": user_data["email"]})
    
    from services.verification_service import _in_memory_codes, _CODE_KEY_PREFIX
    
    code_key = f"{_CODE_KEY_PREFIX}{user_data['email']}"
    code_entry = _in_memory_codes.get(code_key)
    verification_code = code_entry["code"] if code_entry else "123456"
    
    register_data = {**user_data, "verification_code": verification_code}
    resp = await client.post("/api/v1/auth/register", json=register_data)
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
