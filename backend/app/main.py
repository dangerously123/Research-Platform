"""FastAPI 应用主入口。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.errors import AppException, app_exception_handler
from app.core.logging import setup_logging
from app.core.middleware import TimingMiddleware, TraceMiddleware
from app.core.redis import close_redis

# 启动时注册所有 LLM 工具
import app.services.llm.tools.setup  # noqa: F401

# 初始化结构化日志
setup_logging()


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

    # 中间件（注意顺序：先注册的后执行，Trace 应最外层）
    app.add_middleware(TimingMiddleware)
    app.add_middleware(TraceMiddleware)

    # CORS（生产环境使用白名单）
    from app.core.security import get_cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册全局异常处理器
    app.add_exception_handler(AppException, app_exception_handler)

    # 注册路由（聚合在 api/__init__.py 中）
    from app.api import api_router
    app.include_router(api_router)

    return app


app = create_app()
