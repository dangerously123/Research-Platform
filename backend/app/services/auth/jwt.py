"""JWT token signing and verification."""

from __future__ import annotations

import binascii
import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.core.config import settings


class JWTError(Exception):
    """Raised when a token cannot be decoded or verified."""


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _sign(message: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    return _b64url_encode(digest)


def create_access_token(
    user_id: int,
    roles: list[int],
    expires_delta: timedelta | None = None,
) -> tuple[str, str]:
    """Create a signed access token and its token ID."""
    token_id = uuid4().hex

    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

    now = datetime.now(timezone.utc)
    expire = now + expires_delta

    header = {"alg": settings.JWT_ALGORITHM, "typ": "JWT"}
    payload = {
        "sub": str(user_id),
        "roles": roles,
        "exp": int(expire.timestamp()),
        "iat": int(now.timestamp()),
        "jti": token_id,
    }

    if settings.JWT_ALGORITHM != "HS256":
        raise ValueError(f"Unsupported JWT algorithm: {settings.JWT_ALGORITHM}")

    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    signature = _sign(signing_input, settings.JWT_SECRET_KEY)
    return f"{header_b64}.{payload_b64}.{signature}", token_id


def decode_access_token(token: str) -> dict | None:
    """Decode and verify a JWT access token."""
    try:
        header_b64, payload_b64, signature = token.split(".")
    except ValueError:
        return None

    try:
        header = json.loads(_b64url_decode(header_b64))
        payload = json.loads(_b64url_decode(payload_b64))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError, binascii.Error):
        return None

    if header.get("alg") != settings.JWT_ALGORITHM or header.get("typ") != "JWT":
        return None
    if settings.JWT_ALGORITHM != "HS256":
        return None

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected_signature = _sign(signing_input, settings.JWT_SECRET_KEY)
    if not hmac.compare_digest(signature, expected_signature):
        return None

    exp = payload.get("exp")
    if exp is None:
        return None
    try:
        if int(exp) < int(datetime.now(timezone.utc).timestamp()):
            return None
    except (TypeError, ValueError):
        return None

    return payload
