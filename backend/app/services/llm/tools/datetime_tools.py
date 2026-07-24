"""日期时间工具集：时间计算、格式转换、工作日等。"""

import calendar
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.llm.tools.registry import ToolDefinition, tool_registry


async def current_time(timezone_offset: int = 8) -> dict[str, Any]:
    """获取当前时间（默认东八区）。"""
    tz = timezone(timedelta(hours=timezone_offset))
    now = datetime.now(tz)
    return {
        "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "weekday": ["周一","周二","周三","周四","周五","周六","周日"][now.weekday()],
        "timestamp": int(now.timestamp()),
        "timezone": f"UTC+{timezone_offset}",
    }


async def date_difference(date1: str, date2: str) -> dict[str, Any]:
    """计算两个日期之间的天数差。格式: YYYY-MM-DD。"""
    try:
        d1 = datetime.strptime(date1, "%Y-%m-%d")
        d2 = datetime.strptime(date2, "%Y-%m-%d")
        diff = abs((d2 - d1).days)
        return {
            "date1": date1, "date2": date2,
            "days": diff,
            "weeks": round(diff / 7, 1),
            "months_approx": round(diff / 30.44, 1),
        }
    except ValueError as e:
        return {"error": f"日期格式错误: {e}"}


async def add_days(date: str, days: int) -> dict[str, Any]:
    """在日期上加/减天数。"""
    try:
        d = datetime.strptime(date, "%Y-%m-%d")
        result = d + timedelta(days=days)
        return {
            "original_date": date,
            "days_added": days,
            "result_date": result.strftime("%Y-%m-%d"),
            "weekday": ["周一","周二","周三","周四","周五","周六","周日"][result.weekday()],
        }
    except ValueError as e:
        return {"error": f"日期格式错误: {e}"}


async def is_workday(date: str) -> dict[str, Any]:
    """判断日期是否为工作日（不含法定假日）。"""
    try:
        d = datetime.strptime(date, "%Y-%m-%d")
        is_work = d.weekday() < 5
        return {
            "date": date,
            "weekday": ["周一","周二","周三","周四","周五","周六","周日"][d.weekday()],
            "is_workday": is_work,
        }
    except ValueError as e:
        return {"error": f"日期格式错误: {e}"}


async def workdays_between(date1: str, date2: str) -> dict[str, Any]:
    """计算两个日期之间的工作日数量。"""
    try:
        d1 = datetime.strptime(date1, "%Y-%m-%d")
        d2 = datetime.strptime(date2, "%Y-%m-%d")
        if d1 > d2:
            d1, d2 = d2, d1
        count = 0
        current = d1
        while current <= d2:
            if current.weekday() < 5:
                count += 1
            current += timedelta(days=1)
        return {"date1": date1, "date2": date2, "workdays": count}
    except ValueError as e:
        return {"error": f"日期格式错误: {e}"}


async def timestamp_convert(timestamp: int) -> dict[str, Any]:
    """Unix时间戳转可读日期时间。"""
    tz = timezone(timedelta(hours=8))
    dt = datetime.fromtimestamp(timestamp, tz)
    return {
        "timestamp": timestamp,
        "datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
        "date": dt.strftime("%Y-%m-%d"),
        "timezone": "UTC+8",
    }


async def month_calendar(year: int, month: int) -> dict[str, Any]:
    """获取指定月份的日历信息。"""
    try:
        cal = calendar.monthcalendar(year, month)
        _, days_in_month = calendar.monthrange(year, month)
        first_weekday = calendar.weekday(year, month, 1)
        return {
            "year": year, "month": month,
            "days_in_month": days_in_month,
            "first_day_weekday": ["周一","周二","周三","周四","周五","周六","周日"][first_weekday],
            "weeks": len(cal),
        }
    except Exception as e:
        return {"error": str(e)}


def register_datetime_tools():
    """注册所有日期时间工具。"""
    tools = [
        ToolDefinition(
            name="current_time",
            description="获取当前日期和时间（含星期几）",
            category="datetime",
            parameters={
                "type": "object",
                "properties": {
                    "timezone_offset": {"type": "integer", "description": "时区偏移(小时)，默认8(北京)"},
                },
            },
            handler=current_time,
            examples=["[TOOL_CALL: current_time(timezone_offset=8)]"],
        ),
        ToolDefinition(
            name="date_difference",
            description="计算两个日期之间相隔多少天/周/月",
            category="datetime",
            parameters={
                "type": "object",
                "properties": {
                    "date1": {"type": "string", "description": "日期1 (YYYY-MM-DD)"},
                    "date2": {"type": "string", "description": "日期2 (YYYY-MM-DD)"},
                },
                "required": ["date1", "date2"],
            },
            handler=date_difference,
            examples=["[TOOL_CALL: date_difference(date1='2024-01-01', date2='2024-12-31')]"],
        ),
        ToolDefinition(
            name="add_days",
            description="在指定日期上加减天数，得到新日期",
            category="datetime",
            parameters={
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "起始日期 (YYYY-MM-DD)"},
                    "days": {"type": "integer", "description": "加减天数(负数为减)"},
                },
                "required": ["date", "days"],
            },
            handler=add_days,
            examples=["[TOOL_CALL: add_days(date='2024-03-01', days=90)]"],
        ),
        ToolDefinition(
            name="is_workday",
            description="判断指定日期是否为工作日",
            category="datetime",
            parameters={
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "日期 (YYYY-MM-DD)"},
                },
                "required": ["date"],
            },
            handler=is_workday,
            examples=["[TOOL_CALL: is_workday(date='2024-10-01')]"],
        ),
        ToolDefinition(
            name="workdays_between",
            description="计算两个日期之间有多少个工作日",
            category="datetime",
            parameters={
                "type": "object",
                "properties": {
                    "date1": {"type": "string", "description": "起始日期"},
                    "date2": {"type": "string", "description": "结束日期"},
                },
                "required": ["date1", "date2"],
            },
            handler=workdays_between,
            examples=["[TOOL_CALL: workdays_between(date1='2024-01-01', date2='2024-01-31')]"],
        ),
        ToolDefinition(
            name="timestamp_convert",
            description="将Unix时间戳转换为可读的日期时间",
            category="datetime",
            parameters={
                "type": "object",
                "properties": {
                    "timestamp": {"type": "integer", "description": "Unix时间戳(秒)"},
                },
                "required": ["timestamp"],
            },
            handler=timestamp_convert,
            examples=["[TOOL_CALL: timestamp_convert(timestamp=1700000000)]"],
        ),
    ]
    for t in tools:
        tool_registry.register(t)
