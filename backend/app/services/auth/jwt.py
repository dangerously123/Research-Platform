"""JWT 令牌签发与验证。"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from jose import JWTError, jwt

from app.core.config import settings


def create_access_token(
    user_id: int,
    roles: list[int],
    expires_delta: timedelta | None = None,
) -> tuple[str, str]:
    """
    签发 JWT access token。

    Returns:
        tuple: (token_string, token_id) - token_id 用于会话管理
    """
    token_id = uuid4().hex

    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

    expire = datetime.now(timezone.utc) + expires_delta

    payload = {
        "sub": str(user_id),
        "roles": roles,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "jti": token_id,
    }

    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, token_id


def decode_access_token(token: str) -> dict | None:
    """
    解码并验证 JWT token。

    Returns:
        解码后的 payload dict，验证失败返回 None。
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except JWTError:
        return None
    except Exception:
        # 防止配置错误或非预期异常冒泡到认证之外
        return None
