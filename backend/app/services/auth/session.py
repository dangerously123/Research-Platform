"""会话管理器：登录认证、会话验证、活跃时间刷新。"""

import json
from datetime import datetime, timedelta, timezone

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.errors import (
    AUTH_001,
    AUTH_002,
    AUTH_003,
    AUTH_004,
    AuthenticationException,
)
from app.models.user import User, UserRole
from app.services.auth.jwt import create_access_token, decode_access_token
from app.services.auth.password import verify_password


class SessionManager:
    """
    会话管理器。
    - 处理用户登录认证
    - 管理 Redis 会话存储
    - 处理会话超时和刷新
    """

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self.db = db
        self.redis = redis

    async def authenticate(self, username: str, password: str) -> dict:
        """
        用户认证流程：
        1. 检查用户是否存在
        2. 检查账号锁定状态
        3. 验证密码
        4. 检查登录失败次数（锁定逻辑）
        5. 签发 Token 并存储会话

        Returns:
            dict: {"access_token": str, "token_type": str, "expires_in": int, "user": dict}
        """
        # 查询用户
        stmt = (
            select(User)
            .options(selectinload(User.user_roles).selectinload(UserRole.role))
            .where(User.username == username)
        )
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        # 检查锁定状态
        if user and user.locked_until:
            if user.locked_until > datetime.now(timezone.utc):
                raise AuthenticationException(AUTH_002)

        # 验证密码
        if not user or not verify_password(password, user.password_hash):
            # 记录失败次数
            if user:
                await self._record_failed_attempt(user)
            raise AuthenticationException(AUTH_001)

        # 检查用户状态
        if user.status == "disabled":
            raise AuthenticationException(AUTH_001)

        # 登录成功，重置失败计数
        await self._reset_failed_attempts(user)

        # 获取用户角色 ID 列表
        role_ids = [ur.role_id for ur in user.user_roles]

        # 签发 Token
        token, token_id = create_access_token(user_id=user.id, roles=role_ids)

        # 存储会话到 Redis
        await self._store_session(token_id, user)

        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "department_id": user.department_id,
                "position": user.position,
                "roles": role_ids,
            },
        }

    async def validate_session(self, token: str) -> dict | None:
        """
        验证会话有效性：
        1. 解码 JWT
        2. 检查 Redis 中会话是否存在
        3. 检查会话是否超时
        4. 刷新活跃时间

        Returns:
            会话数据 dict 或 None
        """
        # 解码 Token
        payload = decode_access_token(token)
        if not payload:
            return None

        token_id = payload.get("jti")
        if not token_id:
            return None

        # 检查 Redis 会话
        session_key = f"session:{token_id}"
        session_data = await self.redis.get(session_key)
        if not session_data:
            return None

        session = json.loads(session_data)

        # 检查会话超时（30 分钟无操作）
        last_active = datetime.fromisoformat(session["last_active"])
        timeout = timedelta(minutes=settings.SESSION_TIMEOUT_MINUTES)
        if datetime.now(timezone.utc) - last_active > timeout:
            await self.redis.delete(session_key)
            return None

        # 刷新活跃时间
        session["last_active"] = datetime.now(timezone.utc).isoformat()
        await self.redis.setex(
            session_key,
            settings.SESSION_TIMEOUT_MINUTES * 60,
            json.dumps(session),
        )

        return session

    async def logout(self, token: str) -> None:
        """登出：删除 Redis 中的会话。"""
        payload = decode_access_token(token)
        if payload:
            token_id = payload.get("jti")
            if token_id:
                await self.redis.delete(f"session:{token_id}")

    async def _store_session(self, token_id: str, user: User) -> None:
        """将会话信息存入 Redis。"""
        session_data = {
            "user_id": user.id,
            "username": user.username,
            "department_id": user.department_id,
            "roles": [ur.role_id for ur in user.user_roles],
            "last_active": datetime.now(timezone.utc).isoformat(),
        }
        await self.redis.setex(
            f"session:{token_id}",
            settings.SESSION_TIMEOUT_MINUTES * 60,
            json.dumps(session_data),
        )

    async def _record_failed_attempt(self, user: User) -> None:
        """
        记录登录失败次数。
        使用 Redis 计数器（1 分钟窗口），达到上限后锁定账号。
        """
        key = f"login:attempts:{user.username}"
        count = await self.redis.incr(key)
        if count == 1:
            await self.redis.expire(key, 60)  # 1 分钟窗口

        if count >= settings.MAX_LOGIN_ATTEMPTS:
            # 锁定账号
            user.locked_until = datetime.now(timezone.utc) + timedelta(
                minutes=settings.LOCKOUT_MINUTES
            )
            user.status = "locked"
            user.failed_login_count = count
            await self.db.flush()

    async def _reset_failed_attempts(self, user: User) -> None:
        """登录成功，重置失败计数。"""
        key = f"login:attempts:{user.username}"
        await self.redis.delete(key)
        if user.failed_login_count > 0:
            user.failed_login_count = 0
        if user.status == "locked":
            user.status = "active"
            user.locked_until = None
        await self.db.flush()
