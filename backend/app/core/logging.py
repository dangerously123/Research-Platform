"""
结构化日志配置。

特性：
- JSON 格式输出（适配 ELK/Loki 等日志系统）
- 自动注入 trace_id（贯穿请求全链路）
- 按级别分离（INFO→stdout，ERROR→stderr）
- 支持开发模式（人类可读格式）
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings

# ============================================================
# Trace ID 上下文管理
# ============================================================

# 请求级 trace_id，通过 ContextVar 在协程间传递
_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")
_user_id_var: ContextVar[int] = ContextVar("user_id", default=0)


def get_trace_id() -> str:
    """获取当前请求的 trace_id。"""
    return _trace_id_var.get()


def set_trace_id(trace_id: str) -> None:
    """设置当前请求的 trace_id。"""
    _trace_id_var.set(trace_id)


def get_context_user_id() -> int:
    """获取当前请求的 user_id。"""
    return _user_id_var.get()


def set_context_user_id(user_id: int) -> None:
    """设置当前请求的 user_id。"""
    _user_id_var.set(user_id)


# ============================================================
# 结构化日志 Formatter
# ============================================================

class JSONFormatter(logging.Formatter):
    """JSON 格式化器，输出结构化日志。"""

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # 注入 trace_id
        trace_id = get_trace_id()
        if trace_id:
            log_data["trace_id"] = trace_id

        # 注入 user_id
        user_id = get_context_user_id()
        if user_id:
            log_data["user_id"] = user_id

        # 附加异常信息
        if record.exc_info and record.exc_info[1]:
            log_data["exception"] = {
                "type": type(record.exc_info[1]).__name__,
                "message": str(record.exc_info[1]),
            }

        # 附加 extra 字段
        for key in ("duration_ms", "status_code", "method", "path", "model_id",
                    "input_tokens", "output_tokens", "tool_name", "iteration"):
            if hasattr(record, key):
                log_data[key] = getattr(record, key)

        return json.dumps(log_data, ensure_ascii=False)


class DevFormatter(logging.Formatter):
    """开发模式人类可读格式化器。"""

    COLORS = {
        "DEBUG": "\033[36m",    # cyan
        "INFO": "\033[32m",     # green
        "WARNING": "\033[33m",  # yellow
        "ERROR": "\033[31m",    # red
        "CRITICAL": "\033[35m", # magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        trace_id = get_trace_id()
        trace_part = f" [{trace_id[:8]}]" if trace_id else ""

        prefix = f"{color}{record.levelname:8s}{self.RESET}{trace_part}"
        message = record.getMessage()

        # 附加耗时
        if hasattr(record, "duration_ms"):
            message += f" ({record.duration_ms:.0f}ms)"

        return f"{prefix} {record.name}: {message}"


# ============================================================
# 日志初始化
# ============================================================

def setup_logging() -> None:
    """
    初始化应用日志配置。
    DEBUG=True 时使用彩色可读格式，生产环境使用 JSON。
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)

    # 清除已有 handler（避免重复初始化）
    root_logger.handlers.clear()

    # 选择格式化器
    if settings.DEBUG:
        formatter = DevFormatter()
    else:
        formatter = JSONFormatter()

    # stdout handler（INFO 及以上）
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
    stdout_handler.setFormatter(formatter)
    stdout_handler.addFilter(lambda record: record.levelno < logging.ERROR)
    root_logger.addHandler(stdout_handler)

    # stderr handler（ERROR 及以上）
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.ERROR)
    stderr_handler.setFormatter(formatter)
    root_logger.addHandler(stderr_handler)

    # 降低第三方库噪音
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """获取带模块名的 logger（快捷函数）。"""
    return logging.getLogger(name)
