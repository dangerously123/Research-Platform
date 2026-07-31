"""
测试公共 Fixtures。

提供：
- 异步数据库会话（使用 SQLite 内存库，无需外部 MySQL）
- FastAPI 测试客户端
- 模拟 Redis
- 认证 headers
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.core.redis import get_redis
from app.main import app


# ============================================================
# 事件循环
# ============================================================

@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """为整个测试 session 共享一个事件循环。"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ============================================================
# 数据库（SQLite 内存，无需外部依赖）
# ============================================================

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
test_session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    """每个测试前创建表，测试后清理。"""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """提供测试用数据库会话。"""
    async with test_session_factory() as session:
        yield session


# ============================================================
# 模拟 Redis
# ============================================================

class FakeRedis:
    """最小化的 Redis 模拟，覆盖测试中常用操作。"""

    def __init__(self):
        self._store: dict[str, str] = {}
        self._ttls: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, **kwargs) -> None:
        self._store[key] = value

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value
        self._ttls[key] = ttl

    async def delete(self, *keys: str) -> None:
        for k in keys:
            self._store.pop(k, None)

    async def incr(self, key: str) -> int:
        val = int(self._store.get(key, "0")) + 1
        self._store[key] = str(val)
        return val

    async def expire(self, key: str, ttl: int) -> None:
        self._ttls[key] = ttl

    async def exists(self, key: str) -> bool:
        return key in self._store


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


# ============================================================
# FastAPI 测试客户端
# ============================================================

@pytest_asyncio.fixture
async def client(db_session: AsyncSession, fake_redis: FakeRedis) -> AsyncGenerator[AsyncClient, None]:
    """提供已注入测试依赖的 HTTP 客户端。"""

    # 覆盖数据库依赖
    async def override_get_db():
        yield db_session

    # 覆盖 Redis 依赖
    async def override_get_redis():
        return fake_redis

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_redis] = override_get_redis

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ============================================================
# 认证辅助
# ============================================================

@pytest.fixture
def auth_headers() -> dict[str, str]:
    """生成测试用 JWT Token（跳过实际认证）。"""
    from app.services.auth.jwt import create_access_token

    token = create_access_token(data={"sub": "1", "username": "testuser", "department_id": 1})
    return {"Authorization": f"Bearer {token}"}
