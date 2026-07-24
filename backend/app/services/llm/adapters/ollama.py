"""Ollama 本地模型适配器。"""

import time
from typing import AsyncIterator

import httpx

from app.services.llm.adapters.base import (
    LLMResponse,
    ModelAdapter,
    ModelInvocationException,
)


class OllamaAdapter(ModelAdapter):
    """
    Ollama 适配器。
    对接 Ollama HTTP API，支持流式输出。
    """

    async def generate(
        self,
        endpoint: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        api_key: str | None = None,
    ) -> LLMResponse:
        """调用 Ollama /api/generate 接口。"""
        url = f"{endpoint.rstrip('/')}/api/generate"
        payload = {
            "model": self._extract_model_name(endpoint),
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()

                return LLMResponse(
                    content=data.get("response", ""),
                    input_tokens=data.get("prompt_eval_count", 0),
                    output_tokens=data.get("eval_count", 0),
                    finish_reason="stop",
                )
        except Exception as e:
            raise ModelInvocationException("ollama", str(e))

    async def stream_generate(
        self,
        endpoint: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        api_key: str | None = None,
    ) -> AsyncIterator[str]:
        """流式调用 Ollama。"""
        url = f"{endpoint.rstrip('/')}/api/generate"
        payload = {
            "model": self._extract_model_name(endpoint),
            "prompt": prompt,
            "stream": True,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream("POST", url, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line:
                            import json
                            data = json.loads(line)
                            token = data.get("response", "")
                            if token:
                                yield token
                            if data.get("done", False):
                                break
        except Exception as e:
            raise ModelInvocationException("ollama", str(e))

    async def health_check(self, endpoint: str, api_key: str | None = None) -> tuple[bool, int]:
        """检查 Ollama 服务是否可用。"""
        url = f"{endpoint.rstrip('/')}/api/tags"
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(url)
                latency = int((time.perf_counter() - start) * 1000)
                return response.status_code == 200, latency
        except Exception:
            latency = int((time.perf_counter() - start) * 1000)
            return False, latency

    def _extract_model_name(self, endpoint: str) -> str:
        """从 endpoint 配置中提取模型名。默认 qwen2。"""
        # endpoint 格式: http://localhost:11434#model_name
        if "#" in endpoint:
            return endpoint.split("#")[1]
        return "qwen2"
