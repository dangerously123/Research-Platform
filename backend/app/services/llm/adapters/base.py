"""LLM 模型适配器抽象基类。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass
class LLMRequest:
    """LLM 调用请求。"""
    prompt: str
    max_tokens: int = 4096
    temperature: float = 0.7
    stream: bool = True
    task_type: str | None = None


@dataclass
class LLMResponse:
    """LLM 调用响应。"""
    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    model_id: str = ""
    finish_reason: str = "stop"


class ModelAdapter(ABC):
    """
    LLM 模型适配器抽象基类。
    所有适配器必须实现 generate 和 stream_generate 方法。
    """

    @abstractmethod
    async def generate(
        self,
        endpoint: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        api_key: str | None = None,
    ) -> LLMResponse:
        """同步生成（等待完整响应）。"""
        ...

    @abstractmethod
    async def stream_generate(
        self,
        endpoint: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        api_key: str | None = None,
    ) -> AsyncIterator[str]:
        """流式生成（逐 Token 返回）。"""
        ...

    @abstractmethod
    async def health_check(self, endpoint: str, api_key: str | None = None) -> tuple[bool, int]:
        """
        健康检查。

        Returns:
            tuple: (is_healthy, latency_ms)
        """
        ...


class ModelInvocationException(Exception):
    """模型调用异常。"""

    def __init__(self, model_id: str, message: str):
        self.model_id = model_id
        super().__init__(f"Model {model_id}: {message}")


class AllModelsUnavailableException(Exception):
    """所有模型不可用异常。"""

    def __init__(self, last_error: Exception | None = None):
        self.last_error = last_error
        super().__init__("所有 LLM 模型均不可用")
