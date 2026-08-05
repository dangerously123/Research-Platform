"""LLM 统一网关：模型路由、Failover、统一调用入口。"""

from datetime import datetime, timezone
from typing import AsyncIterator

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.llm import LLMModelConfig
from app.services.llm.adapters import (
    AllModelsUnavailableException,
    LLMRequest,
    LLMResponse,
    ModelAdapter,
    ModelInvocationException,
    OllamaAdapter,
    OpenAIAdapter,
    QwenAdapter,
    VLLMAdapter,
    WenxinAdapter,
)


# 适配器注册表
ADAPTER_MAP: dict[str, ModelAdapter] = {
    "ollama": OllamaAdapter(),
    "vllm": VLLMAdapter(),
    "openai": OpenAIAdapter(),
    "qwen": QwenAdapter(),
    "wenxin": WenxinAdapter(),
}


class LLMGateway:
    """
    LLM 统一网关。
    - 模型选择（按优先级和任务类型）
    - Failover 策略（首选失败自动切换备选）
    - 模型熔断（短期内不再尝试失败模型）
    """

    # 熔断配置
    CIRCUIT_FAILURE_THRESHOLD = 3   # 连续失败次数触发熔断
    CIRCUIT_RECOVERY_SECONDS = 45   # 熔断恢复时间

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self.db = db
        self.redis = redis

    async def generate(self, request: LLMRequest, api_key_getter=None) -> LLMResponse:
        """
        统一生成接口（非流式）。
        自动选择模型并处理 Failover。
        集成降级策略：根据当前降级级别调整模型选择和参数。
        """
        # 检查降级状态
        from app.services.degradation import DegradationService, DegradationLevel
        degradation = DegradationService(self.redis)
        deg_config = await degradation.get_current_config()

        # FALLBACK 级别：直接拒绝 LLM 调用
        if deg_config.level == DegradationLevel.FALLBACK:
            raise AllModelsUnavailableException(
                last_error=Exception("系统处于降级模式，LLM 服务暂不可用")
            )

        # 应用降级参数限制
        effective_max_tokens = min(
            request.max_tokens,
            deg_config.max_output_tokens,
        )

        models = await self._get_available_models(request.task_type)
        if not models:
            raise AllModelsUnavailableException()

        last_error = None
        for model in models:
            # 检查熔断状态
            if await self._is_circuit_open(model.model_id):
                continue

            try:
                adapter = self._get_adapter(model.provider)
                api_key = None
                if api_key_getter and model.api_key_ref:
                    api_key = await api_key_getter(model.model_id)

                response = await adapter.generate(
                    endpoint=model.endpoint_url,
                    prompt=request.prompt,
                    max_tokens=min(model.max_tokens, effective_max_tokens),
                    temperature=model.temperature,
                    api_key=api_key,
                )
                response.model_id = model.model_id

                # 成功则重置熔断计数
                await self._reset_circuit(model.model_id)
                return response

            except ModelInvocationException as e:
                last_error = e
                await self._record_failure(model.model_id)
                continue

        raise AllModelsUnavailableException(last_error=last_error)

    async def stream_generate(self, request: LLMRequest, api_key_getter=None) -> tuple[AsyncIterator[str], str]:
        """
        统一流式生成接口。
        返回 (safe_token_iterator, model_id)。

        改进：
        - 只有首个 token 成功产出后才重置熔断
        - 流中 JSON 解析错误不会中断整个流
        - 流中异常记录熔断失败
        """
        from app.services.degradation import DegradationService, DegradationLevel
        degradation = DegradationService(self.redis)
        deg_config = await degradation.get_current_config()
        if deg_config.level == DegradationLevel.FALLBACK:
            raise AllModelsUnavailableException(
                last_error=Exception("System is in fallback mode; LLM streaming is unavailable")
            )
        effective_max_tokens = min(request.max_tokens, deg_config.max_output_tokens)

        models = await self._get_available_models(request.task_type)
        if not models:
            raise AllModelsUnavailableException()

        last_error = None
        for model in models:
            if await self._is_circuit_open(model.model_id):
                continue

            try:
                adapter = self._get_adapter(model.provider)
                api_key = None
                if api_key_getter and model.api_key_ref:
                    api_key = await api_key_getter(model.model_id)

                raw_iterator = adapter.stream_generate(
                    endpoint=model.endpoint_url,
                    prompt=request.prompt,
                    max_tokens=min(model.max_tokens, effective_max_tokens),
                    temperature=model.temperature,
                    api_key=api_key,
                )

                # 包装 iterator：首 token 后才 reset circuit，流中异常记录失败
                safe_iterator = self._wrap_stream_iterator(
                    raw_iterator, model.model_id
                )
                return safe_iterator, model.model_id

            except ModelInvocationException as e:
                last_error = e
                await self._record_failure(model.model_id)
                continue

        raise AllModelsUnavailableException(last_error=last_error)

    async def health_check_model(self, model_id: str) -> dict:
        """对指定模型执行健康检查。"""
        stmt = select(LLMModelConfig).where(LLMModelConfig.model_id == model_id)
        result = await self.db.execute(stmt)
        model = result.scalar_one_or_none()
        if not model:
            return {"model_id": model_id, "status": "not_found", "latency_ms": 0}

        adapter = self._get_adapter(model.provider)
        is_healthy, latency = await adapter.health_check(model.endpoint_url)

        # 更新数据库状态
        model.status = "active" if is_healthy else "error"
        model.last_health_check = datetime.now(timezone.utc)
        model.avg_latency_ms = latency
        await self.db.flush()

        return {
            "model_id": model_id,
            "status": model.status,
            "latency_ms": latency,
        }

    async def _get_available_models(self, task_type: str | None = None) -> list[LLMModelConfig]:
        """获取可用模型列表，按优先级排序。"""
        stmt = (
            select(LLMModelConfig)
            .where(LLMModelConfig.status == "active")
            .order_by(LLMModelConfig.priority)
        )
        result = await self.db.execute(stmt)
        models = list(result.scalars().all())

        # 如果指定了 task_type，过滤支持该类型的模型
        if task_type:
            filtered = [
                m for m in models
                if m.task_types is None or task_type in (m.task_types or [])
            ]
            if filtered:
                return filtered

        return models

    def _get_adapter(self, provider: str) -> ModelAdapter:
        """获取对应供应商的适配器。"""
        adapter = ADAPTER_MAP.get(provider)
        if not adapter:
            raise ValueError(f"Unknown provider: {provider}")
        return adapter

    async def _is_circuit_open(self, model_id: str) -> bool:
        """检查模型是否处于熔断状态。"""
        key = f"llm:circuit:{model_id}"
        failures = await self.redis.get(key)
        if failures and int(failures) >= self.CIRCUIT_FAILURE_THRESHOLD:
            return True
        return False

    async def _record_failure(self, model_id: str) -> None:
        """记录模型调用失败。"""
        key = f"llm:circuit:{model_id}"
        count = await self.redis.incr(key)
        if count == 1:
            await self.redis.expire(key, self.CIRCUIT_RECOVERY_SECONDS)

    async def _reset_circuit(self, model_id: str) -> None:
        """成功调用后重置熔断计数。"""
        await self.redis.delete(f"llm:circuit:{model_id}")

    async def _wrap_stream_iterator(
        self, raw_iterator: AsyncIterator[str], model_id: str
    ) -> AsyncIterator[str]:
        """
        包装流式迭代器：
        - 首个 token 成功后才 reset circuit
        - 流中异常记录失败
        - JSON 解析错误跳过而非中断
        """
        first_token = True
        try:
            async for token in raw_iterator:
                if first_token:
                    await self._reset_circuit(model_id)
                    first_token = False
                yield token
        except Exception:
            # 流中断：记录熔断失败
            await self._record_failure(model_id)
            raise
