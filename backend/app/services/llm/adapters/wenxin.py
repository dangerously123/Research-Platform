"""文心一言 ERNIE API 适配器。"""

import time
from typing import AsyncIterator

import httpx

from app.services.llm.adapters.base import (
    LLMResponse,
    ModelAdapter,
    ModelInvocationException,
)


class WenxinAdapter(ModelAdapter):
    """
    文心一言适配器。
    对接百度 ERNIE API。
    """

    async def generate(
        self,
        endpoint: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        api_key: str | None = None,
    ) -> LLMResponse:
        """调用文心一言接口。"""
        url = endpoint
        headers = {"Content-Type": "application/json"}
        # 文心一言使用 access_token 作为查询参数
        if api_key:
            url = f"{url}?access_token={api_key}"

        payload = {
            "messages": [{"role": "user", "content": prompt}],
            "max_output_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()

                if "error_code" in data:
                    raise ModelInvocationException("wenxin", data.get("error_msg", "Unknown error"))

                usage = data.get("usage", {})
                return LLMResponse(
                    content=data.get("result", ""),
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                    finish_reason="stop",
                )
        except ModelInvocationException:
            raise
        except Exception as e:
            raise ModelInvocationException("wenxin", str(e))

    async def stream_generate(
        self,
        endpoint: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        api_key: str | None = None,
    ) -> AsyncIterator[str]:
        """流式调用文心一言。"""
        url = endpoint
        if api_key:
            url = f"{url}?access_token={api_key}"

        headers = {"Content-Type": "application/json"}
        payload = {
            "messages": [{"role": "user", "content": prompt}],
            "max_output_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            import json
                            data_str = line[6:]
                            if not data_str:
                                continue
                            data = json.loads(data_str)
                            result = data.get("result", "")
                            if result:
                                yield result
                            if data.get("is_end", False):
                                break
        except Exception as e:
            raise ModelInvocationException("wenxin", str(e))

    async def health_check(self, endpoint: str, api_key: str | None = None) -> tuple[bool, int]:
        """健康检查。"""
        start = time.perf_counter()
        try:
            url = endpoint
            if api_key:
                url = f"{url}?access_token={api_key}"
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.post(
                    url,
                    json={"messages": [{"role": "user", "content": "hi"}], "max_output_tokens": 1},
                )
                latency = int((time.perf_counter() - start) * 1000)
                data = response.json()
                is_ok = "error_code" not in data
                return is_ok, latency
        except Exception:
            latency = int((time.perf_counter() - start) * 1000)
            return False, latency
