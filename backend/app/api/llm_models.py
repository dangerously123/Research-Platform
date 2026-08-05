"""LLM model management API routes."""

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import get_redis
from app.models.llm import LLMModelConfig
from app.schemas.llm import AddModelRequest, HealthCheckResponse, ModelConfigResponse
from app.services.auth.dependencies import get_current_user
from app.services.llm.gateway import LLMGateway
from app.services.permission.middleware import require_admin

router = APIRouter()


def _to_response(model: LLMModelConfig) -> ModelConfigResponse:
    return ModelConfigResponse(
        model_id=model.model_id,
        model_name=model.model_name,
        provider=model.provider,
        status=model.status,
        priority=model.priority,
        avg_latency_ms=model.avg_latency_ms,
        last_health_check=model.last_health_check,
    )


async def _get_model(db: AsyncSession, model_id: str) -> LLMModelConfig | None:
    result = await db.execute(select(LLMModelConfig).where(LLMModelConfig.model_id == model_id))
    return result.scalar_one_or_none()


@router.get("", response_model=list[ModelConfigResponse])
async def list_models(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List configured LLM models."""
    result = await db.execute(select(LLMModelConfig).order_by(LLMModelConfig.priority, LLMModelConfig.model_id))
    return [_to_response(model) for model in result.scalars().all()]


@router.post("", response_model=ModelConfigResponse, status_code=201)
async def add_model(
    request: AddModelRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """Add a model configuration."""
    existing = await _get_model(db, request.model_id)
    if existing:
        raise HTTPException(status_code=409, detail="Model already exists")

    model = LLMModelConfig(
        model_id=request.model_id,
        model_name=request.model_name,
        provider=request.provider,
        endpoint_url=request.endpoint_url,
        api_key_ref=request.api_key,
        priority=request.priority,
        context_window=request.context_window,
        max_tokens=request.max_tokens,
        temperature=request.temperature,
        task_types=request.task_types,
    )
    db.add(model)
    await db.flush()
    return _to_response(model)


@router.post("/{model_id}/health-check", response_model=HealthCheckResponse)
async def health_check(
    model_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Run a model health check."""
    if not await _get_model(db, model_id):
        raise HTTPException(status_code=404, detail="Model not found")

    gateway = LLMGateway(db=db, redis=redis)
    result = await gateway.health_check_model(model_id)
    return HealthCheckResponse(
        model_id=result["model_id"],
        status=result["status"],
        latency_ms=result["latency_ms"],
        error_message=result.get("error_message"),
    )


@router.delete("/{model_id}", status_code=204)
async def delete_model(
    model_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """Delete a model configuration."""
    model = await _get_model(db, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    await db.delete(model)
