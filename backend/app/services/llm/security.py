"""LLM input/output safety filter."""

import re

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import LLM_002, LLM_004, AppException, RateLimitException
from app.models.llm import LLMSecurityEvent


class LLMSecurityFilter:
    """Detect prompt injection, redact PII, and enforce per-user rate limits."""

    INJECTION_PATTERNS = [
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"ignore\s+above",
        r"forget\s+(everything|all)",
        r"system\s*prompt",
        r"disregard\s+(all|previous)",
        r"new\s+instructions?:",
        r"override\s+(system|safety)",
    ]

    PII_PATTERNS = {
        "phone": r"\b1[3-9]\d{9}\b",
        "id_card": r"\b\d{17}[\dXx]\b",
        "email": r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b",
        "bank_card": r"\b\d{16,19}\b",
    }

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self.db = db
        self.redis = redis

    async def check_prompt_injection(self, content: str, user_id: int) -> None:
        for pattern in self.INJECTION_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                self.db.add(
                    LLMSecurityEvent(
                        user_id=user_id,
                        event_type="prompt_injection",
                        severity="high",
                        input_content=content[:500],
                        detection_details={"pattern": pattern},
                        action_taken="blocked",
                    )
                )
                await self.db.flush()
                raise AppException(LLM_002, status_code=403)

    async def check_rate_limit(self, user_id: int) -> None:
        key = f"llm:rate:{user_id}"
        count = await self.redis.incr(key)
        if count == 1:
            await self.redis.expire(key, 3600)
        if count <= settings.LLM_RATE_LIMIT_PER_HOUR:
            return
        self.db.add(
            LLMSecurityEvent(
                user_id=user_id,
                event_type="rate_limited",
                severity="medium",
                detection_details={"count": count, "limit": settings.LLM_RATE_LIMIT_PER_HOUR},
                action_taken="blocked",
            )
        )
        await self.db.flush()
        raise RateLimitException(LLM_004)

    def sanitize_outbound(self, content: str) -> str:
        sanitized = content
        for pii_type, pattern in self.PII_PATTERNS.items():
            sanitized = re.sub(pattern, f"[{pii_type.upper()}_REDACTED]", sanitized)
        return self._filter_classified_content(sanitized)

    def filter_output(self, content: str) -> str:
        filtered = content
        for pii_type, pattern in self.PII_PATTERNS.items():
            filtered = re.sub(pattern, f"[{pii_type.upper()}_REDACTED]", filtered)
        return filtered

    def _filter_classified_content(self, content: str) -> str:
        lines = content.split("\n")
        filtered_lines: list[str] = []
        skip = False
        for line in lines:
            if any(marker in line.lower() for marker in ["[confidential]", "[secret]", "[classified]"]):
                skip = True
                filtered_lines.append("[REDACTED_CLASSIFIED_CONTENT]")
                continue
            if skip and not line.strip():
                skip = False
                continue
            if not skip:
                filtered_lines.append(line)
        return "\n".join(filtered_lines)
