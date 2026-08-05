"""Report generation and export helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.report import ExportTask, ReportConfig

EXPORT_ROOT = Path("exports/reports")


class ReportGenerator:
    """Core report query, chart config, and export task logic."""

    SUPPORTED_CHART_TYPES = ("table", "line_chart", "bar_chart", "pie_chart")
    MAX_PAGE_SIZE = 500
    MAX_EXPORT_ROWS = 10000

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_accessible_reports(self, user_roles: list[int]) -> list[ReportConfig]:
        stmt = select(ReportConfig)
        result = await self.db.execute(stmt)
        all_reports = result.scalars().all()

        accessible = []
        for report in all_reports:
            access_roles = report.access_roles
            if access_roles is None:
                accessible.append(report)
            elif any(role_id in (access_roles or []) for role_id in user_roles):
                accessible.append(report)
        return accessible

    async def generate(
        self,
        report_config: ReportConfig,
        date_range: dict | None = None,
        dimensions: list[str] | None = None,
        filters: dict | None = None,
        chart_type: str = "table",
        page: int = 1,
        page_size: int = 50,
        user_permissions: list[dict] | None = None,
    ) -> dict:
        allowed_dimensions = self._filter_dimensions(dimensions, user_permissions)
        safe_page_size = min(page_size, self.MAX_PAGE_SIZE)
        data = await self._execute_query(report_config, date_range, allowed_dimensions, filters, page, safe_page_size)
        total = await self._count_total(report_config, date_range, filters)
        chart_config = self._build_chart_config(data, chart_type)

        return {
            "data": data,
            "chart_config": chart_config,
            "pagination": {"page": page, "page_size": safe_page_size, "total": total},
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def create_export_task(self, user_id: int, report_config_id: int, format: str) -> ExportTask:
        task = ExportTask(user_id=user_id, report_config_id=report_config_id, format=format, status="pending")
        self.db.add(task)
        await self.db.flush()
        return task

    async def get_export_task(self, task_id: int) -> ExportTask | None:
        result = await self.db.execute(select(ExportTask).where(ExportTask.id == task_id))
        return result.scalar_one_or_none()

    async def run_export_task(self, task_id: int) -> ExportTask | None:
        """Generate a report export file and update task status."""
        task = await self.get_export_task(task_id)
        if not task:
            return None

        task.status = "processing"
        task.error_message = None
        await self.db.flush()

        try:
            config_result = await self.db.execute(select(ReportConfig).where(ReportConfig.id == task.report_config_id))
            report_config = config_result.scalar_one_or_none()
            if not report_config:
                raise ValueError("Report config not found")

            data = await self._execute_query(
                report_config,
                date_range=None,
                dimensions=None,
                filters=None,
                page=1,
                page_size=self.MAX_EXPORT_ROWS,
            )
            file_path = self._build_export_path(task)
            if task.format == "excel":
                self._write_excel(file_path, data)
            elif task.format == "pdf":
                self._write_pdf_placeholder(file_path, report_config, data)
            else:
                raise ValueError(f"Unsupported export format: {task.format}")

            task.status = "completed"
            task.file_path = str(file_path)
            task.completed_at = datetime.now(timezone.utc)
        except Exception as exc:
            task.status = "failed"
            task.error_message = str(exc)[:512]
            task.completed_at = datetime.now(timezone.utc)
        await self.db.flush()
        return task

    def _filter_dimensions(self, dimensions: list[str] | None, permissions: list[dict] | None) -> list[str] | None:
        if not dimensions or not permissions:
            return dimensions

        allowed = []
        is_admin = any(permission.get("access_level") == "admin" for permission in permissions)
        for dimension in dimensions:
            if is_admin:
                allowed.append(dimension)
                continue
            for permission in permissions:
                if permission.get("resource_type") == "data_dimension" and permission.get("resource_id") == dimension:
                    allowed.append(dimension)
                    break
        return allowed or dimensions

    async def _execute_query(
        self,
        config: ReportConfig,
        date_range: dict | None,
        dimensions: list[str] | None,
        filters: dict | None,
        page: int,
        page_size: int,
    ) -> list[dict]:
        query_template = self._validate_query_template(config.query_template)
        safe_page_size = min(page_size, self.MAX_EXPORT_ROWS)
        offset = (page - 1) * safe_page_size
        query = f"SELECT /*+ MAX_EXECUTION_TIME(30000) */ * FROM ({query_template}) _q LIMIT {safe_page_size} OFFSET {offset}"

        try:
            result = await self.db.execute(text(query))
            return [dict(row) for row in result.mappings().all()]
        except Exception as exc:
            raise RuntimeError(f"Report query failed: {str(exc)[:200]}") from exc

    async def _count_total(self, config: ReportConfig, date_range: dict | None, filters: dict | None) -> int:
        try:
            query_template = self._validate_query_template(config.query_template)
            result = await self.db.execute(text(f"SELECT COUNT(*) as cnt FROM ({query_template}) sub"))
            row = result.one()
            return int(row.cnt or 0)
        except Exception:
            return 0

    def _validate_query_template(self, query_template: str) -> str:
        query = query_template.strip().rstrip(";")
        normalized = query.upper()
        if ";" in query:
            raise ValueError("Report query must contain a single statement")
        if not normalized.startswith("SELECT"):
            raise ValueError("Report query must be a SELECT statement")
        forbidden = ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE", "GRANT", "EXEC")
        for keyword in forbidden:
            if keyword in normalized:
                raise ValueError(f"Report query cannot contain {keyword}")
        return query

    def _build_chart_config(self, data: list[dict], chart_type: str) -> dict:
        if not data:
            return {"type": chart_type, "series": []}
        keys = list(data[0].keys())
        if chart_type == "table":
            return {"type": "table", "columns": keys}
        if chart_type == "line_chart":
            return {
                "type": "line",
                "xAxis": {"type": "category", "data": [str(row.get(keys[0], "")) for row in data]},
                "series": [{"name": key, "type": "line", "data": [row.get(key, 0) for row in data]} for key in keys[1:]],
            }
        if chart_type == "bar_chart":
            return {
                "type": "bar",
                "xAxis": {"type": "category", "data": [str(row.get(keys[0], "")) for row in data]},
                "series": [{"name": key, "type": "bar", "data": [row.get(key, 0) for row in data]} for key in keys[1:]],
            }
        if chart_type == "pie_chart":
            return {
                "type": "pie",
                "series": [{
                    "type": "pie",
                    "data": [
                        {"name": str(row.get(keys[0], "")), "value": row.get(keys[1], 0) if len(keys) > 1 else 0}
                        for row in data
                    ],
                }],
            }
        return {"type": chart_type}

    def _build_export_path(self, task: ExportTask) -> Path:
        suffix = ".xlsx" if task.format == "excel" else ".pdf"
        now = datetime.now(timezone.utc)
        export_dir = (EXPORT_ROOT / f"{now.year}" / f"{now.month:02d}").resolve()
        export_dir.mkdir(parents=True, exist_ok=True)
        path = (export_dir / f"report_{task.user_id}_{task.id}{suffix}").resolve()
        path.relative_to(EXPORT_ROOT.resolve())
        return path

    def _write_excel(self, path: Path, data: list[dict]) -> None:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Report"
        if data:
            headers = list(data[0].keys())
            sheet.append(headers)
            for row in data:
                sheet.append([row.get(header) for header in headers])
        else:
            sheet.append(["No data"])
        workbook.save(path)

    def _write_pdf_placeholder(self, path: Path, report_config: ReportConfig, data: list[dict]) -> None:
        lines = [
            f"Report: {report_config.name}",
            f"Generated at: {datetime.now(timezone.utc).isoformat()}",
            f"Rows: {len(data)}",
            "",
        ]
        if data:
            headers = list(data[0].keys())
            lines.append(" | ".join(headers))
            for row in data[:200]:
                lines.append(" | ".join(str(row.get(header, "")) for header in headers))
        else:
            lines.append("No data")

        body = "\n".join(lines).encode("utf-8")
        # Minimal PDF-like placeholder is intentionally avoided; write a plain text payload with .pdf extension
        # until a real PDF renderer is introduced.
        path.write_bytes(body)
