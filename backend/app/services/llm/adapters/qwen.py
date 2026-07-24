"""通义千问 DashScope API 适配器。"""

import time
from typing import AsyncIterator

import httpx

from app.services.llm.adapters.base import (
    LLMResponse,
    ModelAdapter,
    ModelInvocationException,
)


class QwenAdapter(ModelAdapter):
    """
    通义千问适配器。
    对接阿里云 DashScope API。
    """

    DEFAULT_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"

    async def generate(
        self,
        endpoint: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        api_key: str | None = None,
    ) -> LLMResponse:
        """调用通义千问接口。"""
        url = endpoint or self.DEFAULT_ENDPOINT
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        payload = {
            "model": self._extract_model(endpoint),
            "input": {
                "messages": [{"role": "user", "content": prompt}]
            },
            "parameters": {
                "max_tokens": max_tokens,
                "temperature": temperature,
                "result_format": "message",
            },
        }

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()

                output = data.get("output", {})
                usage = data.get("usage", {})
                choices = output.get("choices", [{}])
                content = choices[0].get("message", {}).get("content", "") if choices else ""

                return LLMResponse(
                    content=content,
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    finish_reason=output.get("finish_reason", "stop"),
                )
        except Exception as e:
            raise ModelInvocationException("qwen", str(e))

    async def stream_generate(
        self,
        endpoint: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        api_key: str | None = None,
    ) -> AsyncIterator[str]:
        """流式调用通义千问。"""
        url = endpoint or self.DEFAULT_ENDPOINT
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "X-DashScope-SSE": "enable",
        }
        payload = {
            "model": self._extract_model(endpoint),
            "input": {
                "messages": [{"role": "user", "content": prompt}]
            },
            "parameters": {
                "max_tokens": max_tokens,
                "temperature": temperature,
                "result_format": "message",
                "incremental_output": True,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            import json
                            data_str = line[5:].strip()
                            if not data_str:
                                continue
                            data = json.loads(data_str)
                            output = data.get("output", {})
                            choices = output.get("choices", [{}])
                            if choices:
                                content = choices[0].get("message", {}).get("content", "")
                                if content:
                                    yield content
        except Exception as e:
            raise ModelInvocationException("qwen", str(e))

    async def health_check(self, endpoint: str, api_key: str | None = None) -> tuple[bool, int]:
        """简单健康检查（通义千问无专用 health 端点，发送轻量请求）。"""
        start = time.perf_counter()
        try:
            # 用一个简单请求测试连通性
            url = endpoint or self.DEFAULT_ENDPOINT
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.post(
                    url,
                    headers={**headers, "Content-Type": "application/json"},
                    json={
                        "model": self._extract_model(endpoint),
                        "input": {"messages": [{"role": "user", "content": "hi"}]},
                        "parameters": {"max_tokens": 1},
                    },
                )
                latency = int((time.perf_counter() - start) * 1000)
                return response.status_code == 200, latency
        except Exception:
            latency = int((time.perf_counter() - start) * 1000)
            return False, latency

    def _extract_model(self, endpoint: str) -> str:
        if "#" in endpoint:
            return endpoint.split("#")[1]
        return "qwen-plus"
