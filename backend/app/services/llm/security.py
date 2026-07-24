"""LLM 安全模块：Prompt 注入检测、敏感信息脱敏、频率限制。"""

import re

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import LLM_002, LLM_004, AppException, RateLimitException
from app.models.llm import LLMSecurityEvent
from app.services.llm.adapters.base import LLMRequest, LLMResponse


class LLMSecurityFilter:
    """
    LLM 安全过滤器。
    - Prompt 注入检测
    - 敏感信息脱敏（PII）
    - 输出安全过滤
    - 频率限制
    """

    # Prompt 注入特征模式
    INJECTION_PATTERNS = [
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"ignore\s+above",
        r"你(现在)?是一个",
        r"forget\s+(everything|all)",
        r"system\s*prompt",
        r"disregard\s+(all|previous)",
        r"new\s+instructions?:",
        r"override\s+(system|safety)",
        r"忽略(之前|上面|以上)(的|所有)?(指令|提示|规则)",
        r"你的(新|真正)(身份|角色|任务)",
    ]

    # PII 检测模式
    PII_PATTERNS = {
        "phone": r"1[3-9]\d{9}",
        "id_card": r"\d{17}[\dXx]",
        "email": r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
        "bank_card": r"\d{16,19}",
    }

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self.db = db
        self.redis = redis

    async def check_prompt_injection(self, content: str, user_id: int) -> None:
        """
        Prompt 注入检测。
        高风险输入直接拒绝并记录安全事件。
        """
        for pattern in self.INJECTION_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                # 记录安全事件
                event = LLMSecurityEvent(
                    user_id=user_id,
                    event_type="prompt_injection",
                    severity="high",
                    input_content=content[:500],
                    detection_details={"pattern": pattern},
                    action_taken="blocked",
                )
                self.db.add(event)
                await self.db.flush()

                raise AppException(LLM_002, status_code=403)

    async def check_rate_limit(self, user_id: int) -> None:
        """
        LLM 调用频率限制。
        默认：单用户每小时 100 次。
        """
        key = f"llm:rate:{user_id}"
        count = await self.redis.incr(key)
        if count == 1:
            await self.redis.expire(key, 3600)  # 1 小时窗口

        if count > settings.LLM_RATE_LIMIT_PER_HOUR:
            # 记录安全事件
            event = LLMSecurityEvent(
                user_id=user_id,
                event_type="rate_limited",
                severity="medium",
                detection_details={"count": count, "limit": settings.LLM_RATE_LIMIT_PER_HOUR},
                action_taken="blocked",
            )
            self.db.add(event)
            await self.db.flush()

            raise RateLimitException(LLM_004)

    def sanitize_outbound(self, content: str) -> str:
        """
        出站内容安全过滤（发送至云端 LLM 前）。
        - 移除 PII
        - 过滤机密/绝密级别内容
        """
        sanitized = content

        # PII 脱敏
        for pii_type, pattern in self.PII_PATTERNS.items():
            sanitized = re.sub(pattern, f"[{pii_type.upper()}_REDACTED]", sanitized)

        # 过滤机密文档标记内容
        sanitized = self._filter_classified_content(sanitized)

        return sanitized

    def filter_output(self, content: str) -> str:
        """
        输出安全过滤（LLM 返回内容展示前）。
        检测并移除可能泄露的 PII。
        """
        filtered = content
        for pii_type, pattern in self.PII_PATTERNS.items():
            filtered = re.sub(pattern, "[已脱敏]", filtered)
        return filtered

    def _filter_classified_content(self, content: str) -> str:
        """过滤标记为机密或绝密级别的段落。"""
        lines = content.split("\n")
        filtered_lines = []
        skip = False

        for line in lines:
            if any(marker in line for marker in ["[机密]", "[绝密]", "[confidential]", "[secret]"]):
                skip = True
                filtered_lines.append("[此段内容因安全等级限制已移除]")
                continue
            if skip and line.strip() == "":
                skip = False
                continue
            if not skip:
                filtered_lines.append(line)

        return "\n".join(filtered_lines)
