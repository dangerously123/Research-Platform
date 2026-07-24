"""OpenAI API 适配器。"""

import time
from typing import AsyncIterator

import httpx

from app.services.llm.adapters.base import (
    LLMResponse,
    ModelAdapter,
    ModelInvocationException,
)


class OpenAIAdapter(ModelAdapter):
    """
    OpenAI 适配器。
    对接 OpenAI Chat Completions API。
    """

    DEFAULT_ENDPOINT = "https://api.openai.com"

    async def generate(
        self,
        endpoint: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        api_key: str | None = None,
    ) -> LLMResponse:
        """调用 OpenAI Chat Completions 接口。"""
        url = f"{endpoint.rstrip('/')}/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        payload = {
            "model": self._extract_model(endpoint),
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
            raise ModelInvocationException("openai", str(e))

    async def stream_generate(
        self,
        endpoint: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        api_key: str | None = None,
    ) -> AsyncIterator[str]:
        """流式调用 OpenAI。"""
        url = f"{endpoint.rstrip('/')}/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        payload = {
            "model": self._extract_model(endpoint),
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
            raise ModelInvocationException("openai", str(e))

    async def health_check(self, endpoint: str, api_key: str | None = None) -> tuple[bool, int]:
        """检查 OpenAI 服务可用性。"""
        url = f"{endpoint.rstrip('/')}/v1/models"
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(url, headers=headers)
                latency = int((time.perf_counter() - start) * 1000)
                return response.status_code == 200, latency
        except Exception:
            latency = int((time.perf_counter() - start) * 1000)
            return False, latency

    def _extract_model(self, endpoint: str) -> str:
        """从 endpoint 中提取模型名。"""
        if "#" in endpoint:
            return endpoint.split("#")[1]
        return "gpt-3.5-turbo"
