"""数据报表 API 路由。"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis

from app.core.database import get_db
from app.core.redis import get_redis
from app.models.report import ReportConfig
from app.services.auth.dependencies import get_current_user
from app.services.permission.calculator import PermissionCalculator
from app.services.report.generator import ReportGenerator

router = APIRouter()


class ReportGenerateRequest(BaseModel):
    date_range: dict | None = None
    dimensions: list[str] | None = None
    filters: dict | None = None
    chart_type: str = "table"
    page: int = 1
    page_size: int = 50


class ReportExportRequest(BaseModel):
    format: str = Field(..., description="excel/pdf")


@router.get("")
async def list_reports(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户可访问的报表列表。"""
    generator = ReportGenerator(db=db)
    reports = await generator.get_accessible_reports(
        current_user.get("roles", [])
    )
    return {
        "reports": [
            {
                "id": r.id,
                "name": r.name,
                "report_type": r.report_type,
                "data_source": r.data_source,
            }
            for r in reports
        ],
        "total": len(reports),
    }


@router.post("/{report_id}/generate")
async def generate_report(
    report_id: int,
    request: ReportGenerateRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """生成报表数据。"""
    # 获取报表配置
    stmt = select(ReportConfig).where(ReportConfig.id == report_id)
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()
    if not config:
        from app.core.errors import REPORT_001, NotFoundException
        raise NotFoundException(REPORT_001)

    # 获取用户权限
    calculator = PermissionCalculator(db=db, redis=redis)
    permissions = await calculator.get_effective_permissions(
        current_user["user_id"]
    )

    generator = ReportGenerator(db=db)
    data = await generator.generate(
        report_config=config,
        date_range=request.date_range,
        dimensions=request.dimensions,
        filters=request.filters,
        chart_type=request.chart_type,
        page=request.page,
        page_size=request.page_size,
        user_permissions=permissions,
    )
    return data


@router.post("/{report_id}/export")
async def export_report(
    report_id: int,
    request: ReportExportRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """发起报表导出任务。"""
    generator = ReportGenerator(db=db)
    task = await generator.create_export_task(
        user_id=current_user["user_id"],
        report_config_id=report_id,
        format=request.format,
    )
    return {"task_id": task.id, "status": task.status}


@router.get("/export/{task_id}")
async def get_export_status(
    task_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """查询导出任务状态。"""
    generator = ReportGenerator(db=db)
    task = await generator.get_export_task(task_id)
    if not task:
        return {"task_id": task_id, "status": "not_found"}

    return {
        "task_id": task.id,
        "status": task.status,
        "download_url": f"/api/v1/reports/export/{task.id}/download" if task.status == "completed" else None,
        "error_message": task.error_message,
    }
