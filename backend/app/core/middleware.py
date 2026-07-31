"""
HTTP 中间件：请求追踪、耗时计量、上下文注入。

提供：
- TraceMiddleware: 为每个请求生成/提取 trace_id，注入 ContextVar
- TimingMiddleware: 记录请求耗时到响应头和日志
"""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger, set_trace_id, set_context_user_id

logger = get_logger(__name__)


class TraceMiddleware(BaseHTTPMiddleware):
    """
    请求追踪中间件。

    - 从请求头 X-Trace-ID 中提取 trace_id（上游网关传入）
    - 如果没有则自动生成 UUID
    - 注入到 ContextVar 中供全链路使用
    - 回写到响应头 X-Trace-ID
    """

    TRACE_HEADER = "X-Trace-ID"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # 提取或生成 trace_id
        trace_id = request.headers.get(self.TRACE_HEADER, "")
        if not trace_id:
            trace_id = uuid.uuid4().hex

        # 注入上下文
        set_trace_id(trace_id)

        # 执行请求
        response = await call_next(request)

        # 回写 trace_id 到响应头
        response.headers[self.TRACE_HEADER] = trace_id

        return response


class TimingMiddleware(BaseHTTPMiddleware):
    """
    请求耗时中间件。

    - 记录每个请求的处理耗时
    - 写入响应头 X-Response-Time
    - 慢请求（>3s）打 WARNING 日志
    """

    SLOW_REQUEST_THRESHOLD_MS = 3000

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.perf_counter()

        response = await call_next(request)

        duration_ms = (time.perf_counter() - start) * 1000

        # 写入响应头
        response.headers["X-Response-Time"] = f"{duration_ms:.0f}ms"

        # 日志记录
        status_code = response.status_code
        method = request.method
        path = request.url.path

        log_extra = {
            "duration_ms": duration_ms,
            "status_code": status_code,
            "method": method,
            "path": path,
        }

        if duration_ms > self.SLOW_REQUEST_THRESHOLD_MS:
            logger.warning(
                f"Slow request: {method} {path} → {status_code} ({duration_ms:.0f}ms)",
                extra=log_extra,
            )
        elif status_code >= 500:
            logger.error(
                f"Server error: {method} {path} → {status_code} ({duration_ms:.0f}ms)",
                extra=log_extra,
            )
        else:
            logger.info(
                f"{method} {path} → {status_code} ({duration_ms:.0f}ms)",
                extra=log_extra,
            )

        return response
