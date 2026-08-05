"""Report API routes."""

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis

from app.core.database import async_session_factory, get_db
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
    chart_type: Literal["table", "line_chart", "bar_chart", "pie_chart"] = "table"
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=500)


class ReportExportRequest(BaseModel):
    format: Literal["excel", "pdf"]


async def _get_report_or_404(db: AsyncSession, report_id: int) -> ReportConfig:
    stmt = select(ReportConfig).where(ReportConfig.id == report_id)
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()
    if not config:
        from app.core.errors import REPORT_001, NotFoundException
        raise NotFoundException(REPORT_001)
    return config


async def _ensure_report_access(db: AsyncSession, current_user: dict, report_id: int) -> ReportConfig:
    config = await _get_report_or_404(db, report_id)
    generator = ReportGenerator(db=db)
    accessible = await generator.get_accessible_reports(current_user.get("roles", []))
    if report_id not in {report.id for report in accessible}:
        raise HTTPException(status_code=403, detail="Report access denied")
    return config


async def _run_report_export_task(task_id: int) -> None:
    async with async_session_factory() as session:
        generator = ReportGenerator(db=session)
        await generator.run_export_task(task_id)
        await session.commit()


@router.get("")
async def list_reports(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List reports accessible to the current user."""
    generator = ReportGenerator(db=db)
    reports = await generator.get_accessible_reports(current_user.get("roles", []))
    return {
        "reports": [
            {
                "id": report.id,
                "name": report.name,
                "report_type": report.report_type,
                "data_source": report.data_source,
            }
            for report in reports
        ],
        "total": len(reports),
    }


@router.get("/export/{task_id}")
async def get_export_status(
    task_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Query export task status for the task owner only."""
    generator = ReportGenerator(db=db)
    task = await generator.get_export_task(task_id)
    if not task:
        return {"task_id": task_id, "status": "not_found"}
    if task.user_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="Export task access denied")

    return {
        "task_id": task.id,
        "status": task.status,
        "download_url": f"/api/v1/reports/export/{task.id}/download" if task.status == "completed" else None,
        "error_message": task.error_message,
    }


@router.get("/export/{task_id}/download")
async def download_export_file(
    task_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Download a completed export file for the task owner only."""
    generator = ReportGenerator(db=db)
    task = await generator.get_export_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Export task not found")
    if task.user_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="Export task access denied")
    if task.status != "completed" or not task.file_path:
        raise HTTPException(status_code=409, detail="Export file is not ready")

    file_path = Path(task.file_path).resolve()
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Export file not found")

    suffix = file_path.suffix.lower()
    media_type = "application/pdf" if suffix == ".pdf" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    filename = file_path.name
    return FileResponse(path=str(file_path), media_type=media_type, filename=filename)


@router.post("/{report_id}/generate")
async def generate_report(
    report_id: int,
    request: ReportGenerateRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Generate report data."""
    config = await _ensure_report_access(db, current_user, report_id)

    calculator = PermissionCalculator(db=db, redis=redis)
    permissions = await calculator.get_effective_permissions(current_user["user_id"])

    generator = ReportGenerator(db=db)
    return await generator.generate(
        report_config=config,
        date_range=request.date_range,
        dimensions=request.dimensions,
        filters=request.filters,
        chart_type=request.chart_type,
        page=request.page,
        page_size=request.page_size,
        user_permissions=permissions,
    )


@router.post("/{report_id}/export")
async def export_report(
    report_id: int,
    request: ReportExportRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a report export task."""
    await _ensure_report_access(db, current_user, report_id)

    generator = ReportGenerator(db=db)
    task = await generator.create_export_task(
        user_id=current_user["user_id"],
        report_config_id=report_id,
        format=request.format,
    )
    await db.commit()
    background_tasks.add_task(_run_report_export_task, task.id)
    return {"task_id": task.id, "status": task.status}
