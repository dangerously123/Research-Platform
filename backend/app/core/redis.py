"""Redis 异步连接池配置。"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

_redis_server_process: subprocess.Popen | None = None
_redis_start_lock = asyncio.Lock()


def _normalize_redis_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    if host == "localhost" or host == "::1":
        host = "127.0.0.1"
    port = parsed.port or 6379
    username = parsed.username or ""
    password = parsed.password or ""
    auth = ""
    if username:
        auth = username
        if password:
            auth += f":{password}"
        auth += "@"
    path = parsed.path or "/0"
    return f"{parsed.scheme or 'redis'}://{auth}{host}:{port}{path}"


def _redis_host_port() -> tuple[str, int]:
    parsed = urlparse(_normalize_redis_url(settings.REDIS_URL))
    return parsed.hostname or "127.0.0.1", parsed.port or 6379


def _is_local_redis_enabled() -> bool:
    return settings.AUTO_START_LOCAL_REDIS and _redis_host_port()[0] in {"127.0.0.1", "localhost"}


def _is_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _candidate_redis_servers() -> list[Path]:
    candidates: list[Path] = []
    if settings.REDIS_SERVER_PATH:
        candidates.append(Path(settings.REDIS_SERVER_PATH))

    project_root = Path(__file__).resolve().parents[3]
    workspace_root = Path(__file__).resolve().parents[4]
    candidates.extend(
        [
            project_root / "tools" / "Redis-x64-3.2.100" / "redis-server.exe",
            project_root / "tools" / "redis" / "redis-server.exe",
            workspace_root / "tools" / "Redis-x64-3.2.100" / "redis-server.exe",
            workspace_root / "tools" / "redis" / "redis-server.exe",
        ]
    )
    return candidates


def _find_redis_server() -> Path | None:
    for candidate in _candidate_redis_servers():
        if candidate.exists():
            return candidate
    return None


def _start_local_redis(server_path: Path, host: str, port: int) -> bool:
    global _redis_server_process

    if _redis_server_process and _redis_server_process.poll() is None:
        return True

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    cmd = [
        str(server_path),
        "--port",
        str(port),
        "--bind",
        host,
        "--appendonly",
        "no",
    ]
    _redis_server_process = subprocess.Popen(
        cmd,
        cwd=str(server_path.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    return True


async def ensure_redis_running() -> None:
    """确保本机 Redis 可用，必要时自动拉起。"""
    if not _is_local_redis_enabled():
        return

    host, port = _redis_host_port()
    if _is_port_open(host, port):
        return

    async with _redis_start_lock:
        if _is_port_open(host, port):
            return

        server_path = _find_redis_server()
        if not server_path:
            logger.warning(
                "Local Redis is not reachable and no redis-server.exe was found. "
                "Set REDIS_SERVER_PATH or start Redis manually."
            )
            return

        logger.info("Starting local Redis from %s", server_path)
        _start_local_redis(server_path, host, port)

    for _ in range(30):
        if _is_port_open(host, port):
            return
        await asyncio.sleep(0.2)

    logger.warning("Local Redis started but port %s:%s is still not ready.", host, port)


_redis_url = _normalize_redis_url(settings.REDIS_URL)
redis_pool = aioredis.ConnectionPool.from_url(
    _redis_url,
    max_connections=settings.REDIS_MAX_CONNECTIONS,
    decode_responses=True,
    protocol=2,
)
redis_client = aioredis.Redis(connection_pool=redis_pool)


async def get_redis() -> aioredis.Redis:
    """FastAPI 依赖注入：获取 Redis 客户端。"""
    await ensure_redis_running()
    return redis_client


async def close_redis():
    """关闭 Redis 连接池，并停止自动拉起的本地 Redis。"""
    await redis_client.aclose()

    global _redis_server_process
    if _redis_server_process and _redis_server_process.poll() is None:
        _redis_server_process.terminate()
        try:
            _redis_server_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _redis_server_process.kill()
    _redis_server_process = None
