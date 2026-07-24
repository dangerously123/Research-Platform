"""统一错误响应格式和错误代码常量。"""

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """统一错误响应结构。"""
    code: str
    message: str
    detail: str | None = None


# ============ 错误代码常量 ============

# 认证错误
AUTH_001 = ("AUTH_001", "用户名或密码错误")
AUTH_002 = ("AUTH_002", "账号已锁定，请稍后重试")
AUTH_003 = ("AUTH_003", "登录会话已过期，请重新登录")
AUTH_004 = ("AUTH_004", "无效的认证令牌")

# 权限错误
PERM_001 = ("PERM_001", "无权访问该资源")
PERM_002 = ("PERM_002", "角色不存在")
PERM_003 = ("PERM_003", "无法删除仍有用户关联的角色")

# 业务错误
RAG_001 = ("RAG_001", "知识库检索失败")
RAG_002 = ("RAG_002", "未找到匹配结果")
REPORT_001 = ("REPORT_001", "报表生成失败")
REPORT_002 = ("REPORT_002", "数据源连接失败")
REPORT_003 = ("REPORT_003", "导出任务失败")

# LLM 错误
LLM_001 = ("LLM_001", "LLM 服务暂时不可用，已降级为检索模式")
LLM_002 = ("LLM_002", "Prompt 注入检测：请求被拒绝")
LLM_003 = ("LLM_003", "Token 配额已用尽，请联系管理员")
LLM_004 = ("LLM_004", "LLM 调用频率超限，请稍后重试")
LLM_005 = ("LLM_005", "对话会话不存在或已归档")
LLM_006 = ("LLM_006", "模型配置验证失败")
LLM_007 = ("LLM_007", "所有模型均不可用")
LLM_008 = ("LLM_008", "回答相关度过低，建议调整问题")

# 系统错误
SYS_001 = ("SYS_001", "系统内部错误")
SYS_002 = ("SYS_002", "服务暂时不可用")


class AppException(HTTPException):
    """应用自定义异常基类。"""

    def __init__(
        self,
        error: tuple[str, str],
        status_code: int = 400,
        detail: str | None = None,
    ):
        self.error_code = error[0]
        self.error_message = error[1]
        self.error_detail = detail
        super().__init__(status_code=status_code, detail=error[1])


class AuthenticationException(AppException):
    """认证异常。"""

    def __init__(self, error: tuple[str, str], detail: str | None = None):
        super().__init__(error=error, status_code=401, detail=detail)


class AuthorizationException(AppException):
    """授权异常。"""

    def __init__(self, error: tuple[str, str] = PERM_001, detail: str | None = None):
        super().__init__(error=error, status_code=403, detail=detail)


class NotFoundException(AppException):
    """资源未找到异常。"""

    def __init__(self, error: tuple[str, str], detail: str | None = None):
        super().__init__(error=error, status_code=404, detail=detail)


class RateLimitException(AppException):
    """频率限制异常。"""

    def __init__(self, error: tuple[str, str] = LLM_004, detail: str | None = None):
        super().__init__(error=error, status_code=429, detail=detail)


class QuotaExceededException(AppException):
    """配额超限异常。"""

    def __init__(self, target_type: str, target_id: int):
        super().__init__(
            error=LLM_003,
            status_code=429,
            detail=f"{target_type}({target_id}) Token 配额已用尽",
        )


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """全局异常处理器。"""
    from app.core.config import settings

    content = ErrorResponse(
        code=exc.error_code,
        message=exc.error_message,
        detail=exc.error_detail if settings.DEBUG else None,
    ).model_dump()

    return JSONResponse(status_code=exc.status_code, content=content)
