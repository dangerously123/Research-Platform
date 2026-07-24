"""FastAPI 应用主入口。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.errors import AppException, app_exception_handler
from app.core.redis import close_redis

# 启动时注册所有 LLM 工具
import app.services.llm.tools.setup  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。"""
    # 启动时
    yield
    # 关闭时
    await close_redis()


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例。"""
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        lifespan=lifespan,
    )

    # CORS 中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 生产环境应限制
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册全局异常处理器
    app.add_exception_handler(AppException, app_exception_handler)

    # 注册路由
    _register_routers(app)

    return app


def _register_routers(app: FastAPI):
    """注册所有 API 路由。"""
    from app.api.auth import router as auth_router
    from app.api.roles import router as roles_router
    from app.api.permissions import router as permissions_router
    from app.api.knowledge import router as knowledge_router
    from app.api.reports import router as reports_router
    from app.api.llm_conversations import router as llm_conversations_router
    from app.api.llm_models import router as llm_models_router
    from app.api.prompts import router as prompts_router
    from app.api.tokens import router as tokens_router
    from app.api.audit import router as audit_router
    from app.api.memories import router as memories_router
    from app.api.tools import router as tools_router

    prefix = settings.API_V1_PREFIX

    app.include_router(auth_router, prefix=f"{prefix}/auth", tags=["认证"])
    app.include_router(roles_router, prefix=f"{prefix}/roles", tags=["角色管理"])
    app.include_router(permissions_router, prefix=f"{prefix}/users", tags=["权限管理"])
    app.include_router(knowledge_router, prefix=f"{prefix}/knowledge", tags=["知识检索"])
    app.include_router(reports_router, prefix=f"{prefix}/reports", tags=["数据报表"])
    app.include_router(llm_conversations_router, prefix=f"{prefix}/llm/conversations", tags=["LLM对话"])
    app.include_router(llm_models_router, prefix=f"{prefix}/llm/models", tags=["LLM模型管理"])
    app.include_router(prompts_router, prefix=f"{prefix}/prompts/templates", tags=["Prompt模板"])
    app.include_router(tokens_router, prefix=f"{prefix}/tokens", tags=["Token监控"])
    app.include_router(audit_router, prefix=f"{prefix}/audit", tags=["审计日志"])
    app.include_router(memories_router, prefix=f"{prefix}/memories", tags=["记忆管理"])
    app.include_router(tools_router, prefix=f"{prefix}/tools", tags=["工具"])


app = create_app()
