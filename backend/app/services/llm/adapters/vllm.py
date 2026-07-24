"""vLLM 高性能推理适配器（OpenAI-compatible API）。"""

import time
from typing import AsyncIterator

import httpx

from app.services.llm.adapters.base import (
    LLMResponse,
    ModelAdapter,
    ModelInvocationException,
)


class VLLMAdapter(ModelAdapter):
    """
    vLLM 适配器。
    对接 vLLM OpenAI-compatible API。
    """

    async def generate(
        self,
        endpoint: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        api_key: str | None = None,
    ) -> LLMResponse:
        """调用 vLLM /v1/completions 接口。"""
        url = f"{endpoint.rstrip('/')}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": "default",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()

                choice = data["choices"][0]
                usage = data.get("usage", {})

                return LLMResponse(
                    content=choice["message"]["content"],
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                    finish_reason=choice.get("finish_reason", "stop"),
                )
        except Exception as e:
            raise ModelInvocationException("vllm", str(e))

    async def stream_generate(
        self,
        endpoint: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        api_key: str | None = None,
    ) -> AsyncIterator[str]:
        """流式调用 vLLM。"""
        url = f"{endpoint.rstrip('/')}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": "default",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str.strip() == "[DONE]":
                                break
                            import json
                            data = json.loads(data_str)
                            delta = data["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
        except Exception as e:
            raise ModelInvocationException("vllm", str(e))

    async def health_check(self, endpoint: str, api_key: str | None = None) -> tuple[bool, int]:
        """检查 vLLM 服务是否可用。"""
        url = f"{endpoint.rstrip('/')}/v1/models"
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(url, headers=headers)
                latency = int((time.perf_counter() - start) * 1000)
                return response.status_code == 200, latency
        except Exception:
            latency = int((time.perf_counter() - start) * 1000)
            return False, latency
