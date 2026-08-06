"""Session management: login authentication, session validation, and session refresh."""

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
    浼氳瘽绠＄悊鍣ㄣ€?
    - 澶勭悊鐢ㄦ埛鐧诲綍璁よ瘉
    - 绠＄悊 Redis 浼氳瘽瀛樺偍
    - 澶勭悊浼氳瘽瓒呮椂鍜屽埛鏂?
    """

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self.db = db
        self.redis = redis

    async def authenticate(self, username: str, password: str) -> dict:
        """
        鐢ㄦ埛璁よ瘉娴佺▼锛?
        1. 妫€鏌ョ敤鎴锋槸鍚﹀瓨鍦?
        2. 妫€鏌ヨ处鍙烽攣瀹氱姸鎬?
        3. 楠岃瘉瀵嗙爜
        4. 妫€鏌ョ櫥褰曞け璐ユ鏁帮紙閿佸畾閫昏緫锛?
        5. 绛惧彂 Token 骞跺瓨鍌ㄤ細璇?

        Returns:
            dict: {"access_token": str, "token_type": str, "expires_in": int, "user": dict}
        """
        # 鏌ヨ鐢ㄦ埛
        stmt = (
            select(User)
            .options(selectinload(User.user_roles).selectinload(UserRole.role))
            .where(User.username == username)
        )
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        # 妫€鏌ラ攣瀹氱姸鎬?
        if user and user.locked_until:
            if user.locked_until > datetime.now(timezone.utc):
                raise AuthenticationException(AUTH_002)

        # 楠岃瘉瀵嗙爜
        if not user or not verify_password(password, user.password_hash):
            # 璁板綍澶辫触娆℃暟
            if user:
                await self._record_failed_attempt(user)
            raise AuthenticationException(AUTH_001)

        # 妫€鏌ョ敤鎴风姸鎬?
        if user.status == "disabled":
            raise AuthenticationException(AUTH_001)

        # 鐧诲綍鎴愬姛锛岄噸缃け璐ヨ鏁?
        await self._reset_failed_attempts(user)

        # 鑾峰彇鐢ㄦ埛瑙掕壊 ID 鍒楄〃
        role_ids = [ur.role_id for ur in user.user_roles]

        # 绛惧彂 Token
        token, token_id = create_access_token(user_id=user.id, roles=role_ids)

        # 瀛樺偍浼氳瘽鍒?Redis
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
        楠岃瘉浼氳瘽鏈夋晥鎬э細
        1. 瑙ｇ爜 JWT
        2. 妫€鏌?Redis 涓細璇濇槸鍚﹀瓨鍦?
        3. 妫€鏌ヤ細璇濇槸鍚﹁秴鏃?
        4. 鍒锋柊娲昏穬鏃堕棿

        Returns:
            浼氳瘽鏁版嵁 dict 鎴?None
        """
        # 瑙ｇ爜 Token
        payload = decode_access_token(token)
        if not payload:
            return None

        token_id = payload.get("jti")
        if not token_id:
            return None

        # 妫€鏌?Redis 浼氳瘽
        session_key = f"session:{token_id}"
        session_data = await self.redis.get(session_key)
        if not session_data:
            return None

        try:
            session = json.loads(session_data)
        except (TypeError, json.JSONDecodeError):
            # 浼氳瘽鏁版嵁鎹熷潖锛岃涓烘棤鏁堜細璇?
            await self.redis.delete(session_key)
            return None

        # 妫€鏌ヤ細璇濊秴鏃讹紙30 鍒嗛挓鏃犳搷浣滐級
        last_active = datetime.fromisoformat(session["last_active"])
        timeout = timedelta(minutes=settings.SESSION_TIMEOUT_MINUTES)
        if datetime.now(timezone.utc) - last_active > timeout:
            await self.redis.delete(session_key)
            return None

        # 鍒锋柊娲昏穬鏃堕棿
        session["last_active"] = datetime.now(timezone.utc).isoformat()
        await self.redis.setex(
            session_key,
            settings.SESSION_TIMEOUT_MINUTES * 60,
            json.dumps(session),
        )

        return session

    async def logout(self, token: str) -> None:
        """Log out by deleting the Redis session."""
        payload = decode_access_token(token)
        if payload:
            token_id = payload.get("jti")
            if token_id:
                await self.redis.delete(f"session:{token_id}")

    async def _store_session(self, token_id: str, user: User) -> None:
        """Store the session data in Redis."""
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
        """Track failed login attempts and lock the account when needed."""
        key = f"login:attempts:{user.username}"
        count = await self.redis.incr(key)
        if count == 1:
            await self.redis.expire(key, 60)  # 1 鍒嗛挓绐楀彛

        if count >= settings.MAX_LOGIN_ATTEMPTS:
            # 閿佸畾璐﹀彿
            user.locked_until = datetime.now(timezone.utc) + timedelta(
                minutes=settings.LOCKOUT_MINUTES
            )
            user.status = "locked"
            user.failed_login_count = count
            await self.db.flush()

    async def _reset_failed_attempts(self, user: User) -> None:
        """Reset failed login counters after a successful login."""
        key = f"login:attempts:{user.username}"
        await self.redis.delete(key)
        if user.failed_login_count > 0:
            user.failed_login_count = 0
        if user.status == "locked":
            user.status = "active"
            user.locked_until = None
        await self.db.flush()

