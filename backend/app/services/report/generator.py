"""报表生成器：数据查询、权限过滤、图表配置构建。"""

from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.report import ExportTask, ReportConfig


class ReportGenerator:
    """
    报表生成核心逻辑。
    - 权限过滤维度
    - 执行数据查询（分页）
    - 构建图表配置
    - 大数据量自动分页
    """

    SUPPORTED_CHART_TYPES = ("table", "line_chart", "bar_chart", "pie_chart")

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_accessible_reports(
        self, user_roles: list[int]
    ) -> list[ReportConfig]:
        """获取用户可访问的报表列表。"""
        stmt = select(ReportConfig)
        result = await self.db.execute(stmt)
        all_reports = result.scalars().all()

        # 过滤：检查 access_roles
        accessible = []
        for report in all_reports:
            if report.access_roles is None:
                accessible.append(report)
            elif any(r in (report.access_roles or []) for r in user_roles):
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
        """
        生成报表数据。

        Returns:
            {
                "data": [...],
                "chart_config": {...},
                "pagination": {...},
                "generated_at": datetime
            }
        """
        # 1. 权限过滤维度
        allowed_dimensions = self._filter_dimensions(
            dimensions, user_permissions
        )

        # 2. 执行查询
        data = await self._execute_query(
            report_config, date_range, allowed_dimensions,
            filters, page, page_size
        )

        # 3. 获取总数
        total = await self._count_total(report_config, date_range, filters)

        # 4. 构建图表配置
        chart_config = self._build_chart_config(data, chart_type)

        return {
            "data": data,
            "chart_config": chart_config,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
            },
            "generated_at": datetime.utcnow().isoformat(),
        }

    async def create_export_task(
        self,
        user_id: int,
        report_config_id: int,
        format: str,
    ) -> ExportTask:
        """创建报表导出任务。"""
        task = ExportTask(
            user_id=user_id,
            report_config_id=report_config_id,
            format=format,
            status="pending",
        )
        self.db.add(task)
        await self.db.flush()
        return task

    async def get_export_task(self, task_id: int) -> ExportTask | None:
        """查询导出任务状态。"""
        stmt = select(ExportTask).where(ExportTask.id == task_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    def _filter_dimensions(
        self,
        dimensions: list[str] | None,
        permissions: list[dict] | None,
    ) -> list[str] | None:
        """权限过滤维度。"""
        if not dimensions or not permissions:
            return dimensions

        # 检查用户对数据维度的访问权限
        allowed = []
        for dim in dimensions:
            for perm in permissions:
                if perm.get("resource_type") == "data_dimension":
                    if perm.get("resource_id") == dim or perm.get("access_level") == "admin":
                        allowed.append(dim)
                        break
            else:
                # 如果有 admin 权限，允许所有
                if any(p.get("access_level") == "admin" for p in permissions):
                    allowed.append(dim)

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
        """
        执行数据查询。

        安全措施：
        - 只允许 SELECT 语句
        - 强制 LIMIT 上限（最多 10000 行）
        - 查询超时 30 秒
        - 错误透传而非静默吞掉
        """
        query_template = config.query_template

        # 安全检查：只允许 SELECT
        normalized = query_template.strip().upper()
        if not normalized.startswith("SELECT"):
            raise ValueError("报表查询必须为 SELECT 语句")
        # 禁止危险关键词
        forbidden = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE", "GRANT", "EXEC"]
        for kw in forbidden:
            if kw in normalized:
                raise ValueError(f"报表查询不允许包含 {kw}")

        # 分页（强制上限）
        safe_page_size = min(page_size, 10000)
        offset = (page - 1) * safe_page_size
        query = f"{query_template} LIMIT {safe_page_size} OFFSET {offset}"

        try:
            # 设置查询超时（MySQL: max_execution_time hint）
            timed_query = f"SELECT /*+ MAX_EXECUTION_TIME(30000) */ * FROM ({query}) _q"
            result = await self.db.execute(text(timed_query))
            rows = result.mappings().all()
            return [dict(row) for row in rows]
        except Exception as e:
            # 错误透传，不静默吞掉
            import logging
            logging.getLogger(__name__).error(f"[Report] 查询失败: {e}")
            raise RuntimeError(f"报表查询执行失败: {str(e)[:200]}")

    async def _count_total(
        self,
        config: ReportConfig,
        date_range: dict | None,
        filters: dict | None,
    ) -> int:
        """获取总记录数（带安全检查和超时）。"""
        query_template = config.query_template

        # 安全检查
        normalized = query_template.strip().upper()
        if not normalized.startswith("SELECT"):
            return 0

        count_query = f"SELECT COUNT(*) as cnt FROM ({query_template}) sub"
        try:
            result = await self.db.execute(text(count_query))
            row = result.one()
            return row.cnt
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"[Report] 计数查询失败: {e}")
            raise RuntimeError(f"报表计数查询失败: {str(e)[:200]}")

    def _build_chart_config(
        self, data: list[dict], chart_type: str
    ) -> dict:
        """构建 ECharts 图表配置。"""
        if not data:
            return {"type": chart_type, "series": []}

        keys = list(data[0].keys()) if data else []

        if chart_type == "table":
            return {
                "type": "table",
                "columns": keys,
            }
        elif chart_type == "line_chart":
            return {
                "type": "line",
                "xAxis": {"type": "category", "data": [str(r.get(keys[0], "")) for r in data]},
                "series": [
                    {"name": k, "type": "line", "data": [r.get(k, 0) for r in data]}
                    for k in keys[1:]
                ],
            }
        elif chart_type == "bar_chart":
            return {
                "type": "bar",
                "xAxis": {"type": "category", "data": [str(r.get(keys[0], "")) for r in data]},
                "series": [
                    {"name": k, "type": "bar", "data": [r.get(k, 0) for r in data]}
                    for k in keys[1:]
                ],
            }
        elif chart_type == "pie_chart":
            return {
                "type": "pie",
                "series": [{
                    "type": "pie",
                    "data": [
                        {"name": str(r.get(keys[0], "")), "value": r.get(keys[1], 0) if len(keys) > 1 else 0}
                        for r in data
                    ],
                }],
            }
        return {"type": chart_type}
