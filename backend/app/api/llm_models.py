"""LLM 模型管理 API 路由。"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis

from app.core.database import get_db
from app.core.redis import get_redis
from app.models.llm import LLMModelConfig
from app.schemas.llm import (
    AddModelRequest,
    HealthCheckResponse,
    ModelConfigResponse,
)
from app.services.auth.dependencies import get_current_user
from app.services.llm.gateway import LLMGateway
from app.services.permission.middleware import require_admin

router = APIRouter()


@router.get("", response_model=list[ModelConfigResponse])
async def list_models(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取已配置模型列表。"""
    stmt = select(LLMModelConfig).order_by(LLMModelConfig.priority)
    result = await db.execute(stmt)
    models = result.scalars().all()
    return [
        ModelConfigResponse(
            model_id=m.model_id,
            model_name=m.model_name,
            provider=m.provider,
            status=m.status,
            priority=m.priority,
            avg_latency_ms=m.avg_latency_ms,
            last_health_check=m.last_health_check,
        )
        for m in models
    ]


@router.post("", status_code=201)
async def add_model(
    request: AddModelRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """添加新模型配置（管理员）。"""
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
    return {"model_id": model.model_id, "message": "模型配置添加成功"}


@router.post("/{model_id}/health-check", response_model=HealthCheckResponse)
async def health_check(
    model_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """手动触发健康检查。"""
    gateway = LLMGateway(db=db, redis=redis)
    result = await gateway.health_check_model(model_id)
    return HealthCheckResponse(
        model_id=result["model_id"],
        status=result["status"],
        latency_ms=result["latency_ms"],
    )


@router.delete("/{model_id}", status_code=204)
async def delete_model(
    model_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """移除模型配置（管理员）。"""
    stmt = select(LLMModelConfig).where(LLMModelConfig.model_id == model_id)
    result = await db.execute(stmt)
    model = result.scalar_one_or_none()
    if model:
        await db.delete(model)
