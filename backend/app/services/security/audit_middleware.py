"""审计日志 FastAPI 中间件：自动记录数据查询和导出操作。"""

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.database import async_session_factory
from app.services.security.audit import AuditLogger

# 需要记录审计日志的路径模式
AUDITED_PATHS = [
    "/api/v1/knowledge/search",
    "/api/v1/reports/",
    "/api/v1/llm/conversations/",
]


class AuditMiddleware(BaseHTTPMiddleware):
    """
    审计日志中间件。
    自动记录匹配路径的请求操作。
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)

        # 仅对成功的写操作和查询操作记录审计
        if response.status_code >= 400:
            return response

        # 检查是否需要审计
        path = request.url.path
        should_audit = any(path.startswith(p) for p in AUDITED_PATHS)

        if should_audit and hasattr(request.state, "user"):
            await self._record_audit(request, response)

        return response

    async def _record_audit(self, request: Request, response: Response) -> None:
        """记录审计日志。"""
        try:
            user_data = request.state.user
            user_id = user_data.get("user_id")
            if not user_id:
                return

            # 确定操作类型
            operation_type = "query"
            if "export" in request.url.path:
                operation_type = "export"

            async with async_session_factory() as session:
                logger = AuditLogger(db=session)
                await logger.log_operation(
                    user_id=user_id,
                    operation_type=operation_type,
                    resource_type=self._extract_resource_type(request.url.path),
                    resource_id=self._extract_resource_id(request.url.path),
                    ip_address=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent"),
                )
                await session.commit()
        except Exception:
            # 审计日志记录失败不应影响正常请求
            pass

    def _extract_resource_type(self, path: str) -> str:
        """从路径提取资源类型。"""
        if "/knowledge/" in path:
            return "knowledge_base"
        elif "/reports/" in path:
            return "report"
        elif "/llm/" in path:
            return "llm_model"
        return "unknown"

    def _extract_resource_id(self, path: str) -> str | None:
        """从路径提取资源 ID。"""
        parts = path.rstrip("/").split("/")
        # 尝试获取最后一个数字段作为 ID
        for part in reversed(parts):
            if part.isdigit():
                return part
        return None
