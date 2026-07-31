"""
管理后台 API：系统状态、成本面板、降级控制。
所有接口需要 admin 角色。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis

from app.core.database import get_db
from app.core.redis import get_redis
from app.services.auth.dependencies import get_current_user
from app.services.permission.middleware import require_admin

router = APIRouter()


@router.get("/status")
async def system_status(
    current_user: dict = Depends(get_current_user),
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """获取系统运行状态。"""
    from app.services.degradation import DegradationService
    from app.services.llm.tools.registry import tool_registry

    degradation = DegradationService(redis)
    deg_status = await degradation.get_status()

    # Redis 连通性
    try:
        await redis.ping()
        redis_ok = True
    except Exception:
        redis_ok = False

    return {
        "status": "running",
        "redis_connected": redis_ok,
        "degradation": deg_status,
        "registered_tools": len(tool_registry.list_all()),
        "tool_categories": tool_registry.get_categories(),
    }


@router.get("/cost/dashboard")
async def cost_dashboard(
    days: int = Query(default=30, ge=1, le=365),
    current_user: dict = Depends(get_current_user),
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """获取成本监控面板数据。"""
    from app.services.cost_monitor import CostMonitorService

    service = CostMonitorService(db=db, redis=redis)
    return await service.get_cost_dashboard(days=days)


@router.post("/degradation/set")
async def set_degradation_level(
    level: int = Query(..., ge=0, le=3, description="降级级别: 0=正常 1=轻度 2=重度 3=兜底"),
    current_user: dict = Depends(get_current_user),
    _admin=Depends(require_admin),
    redis: aioredis.Redis = Depends(get_redis),
):
    """手动设置降级级别（管理员）。"""
    from app.services.degradation import DegradationLevel, DegradationService

    service = DegradationService(redis)
    await service.set_manual_level(DegradationLevel(level))
    status = await service.get_status()
    return {"message": "降级级别已设置", "status": status}


@router.post("/degradation/reset")
async def reset_degradation(
    current_user: dict = Depends(get_current_user),
    _admin=Depends(require_admin),
    redis: aioredis.Redis = Depends(get_redis),
):
    """解除手动降级，恢复正常模式。"""
    from app.services.degradation import DegradationLevel, DegradationService

    service = DegradationService(redis)
    await service.set_manual_level(DegradationLevel.NORMAL)
    return {"message": "降级已解除，恢复正常模式"}


@router.get("/tools/permissions")
async def list_tool_permissions(
    current_user: dict = Depends(get_current_user),
    _admin=Depends(require_admin),
):
    """查看工具权限配置。"""
    from app.services.llm.tools.permission import tool_permission_manager

    return {"rules": tool_permission_manager.list_rules()}


@router.post("/tools/{tool_name}/blacklist")
async def blacklist_tool(
    tool_name: str,
    current_user: dict = Depends(get_current_user),
    _admin=Depends(require_admin),
):
    """将工具加入黑名单。"""
    from app.services.llm.tools.permission import tool_permission_manager

    tool_permission_manager.blacklist_tool(tool_name)
    return {"message": f"工具 {tool_name} 已加入黑名单"}


@router.delete("/tools/{tool_name}/blacklist")
async def remove_tool_blacklist(
    tool_name: str,
    current_user: dict = Depends(get_current_user),
    _admin=Depends(require_admin),
):
    """将工具移出黑名单。"""
    from app.services.llm.tools.permission import tool_permission_manager

    tool_permission_manager.whitelist_tool(tool_name)
    return {"message": f"工具 {tool_name} 已移出黑名单"}
