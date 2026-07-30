"""数学计算工具集：基础运算、统计函数、金融计算等。"""

import math
import re
import statistics
from typing import Any

from app.services.llm.tools.decorator import tool


# ============================================================
# 基础运算
# ============================================================

@tool(
    category="math",
    description="数学表达式计算器，支持四则运算、幂、三角函数、对数等",
    triggers=["计算", "算一下", "等于多少", "求值", "运算", "乘以", "除以", "加上", "减去", "平方", "开根号", "次方"],
    trigger_patterns=[r"\d+\s*[\+\-\*\/\^]\s*\d+", r"(sin|cos|tan|sqrt|log)\("],
    trigger_priority=10,
    requires_numbers=True,
    examples=["[TOOL_CALL: calculator(expression='1024 * 768 / 1000')]"],
    pre_execute_pattern=r"(?:计算|算|求)\s*[:：]?\s*(.+)",
    pre_execute_extractor=lambda m: {"expression": m.group(1).strip()},
    pre_execute_formatter=lambda r: f"{r.get('expression')} = {r.get('result')}",
)
async def calculator(expression: str) -> dict[str, Any]:
    """
    安全的数学表达式计算器。
    支持加减乘除、幂运算、括号、常用数学函数。

    Args:
        expression: 数学表达式，如 '2**10 + sqrt(144)'
    """
    allowed_names = {
        "abs": abs, "round": round, "min": min, "max": max,
        "pow": pow, "int": int, "float": float,
        "sqrt": math.sqrt, "log": math.log, "log2": math.log2, "log10": math.log10,
        "sin": math.sin, "cos": math.cos, "tan": math.tan,
        "asin": math.asin, "acos": math.acos, "atan": math.atan,
        "ceil": math.ceil, "floor": math.floor,
        "pi": math.pi, "e": math.e,
        "exp": math.exp, "factorial": math.factorial,
    }

    try:
        code = compile(expression, "<calculator>", "eval")
        for name in code.co_names:
            if name not in allowed_names:
                return {"error": f"不支持的函数或变量: {name}", "result": None}
        result = eval(code, {"__builtins__": {}}, allowed_names)
        return {"expression": expression, "result": result}
    except Exception as e:
        return {"error": str(e), "result": None}


# ============================================================
# 统计函数
# ============================================================

@tool(
    category="math",
    description="对一组数字求和",
    triggers=["求和", "总和", "加起来", "合计", "总计", "累加"],
    trigger_patterns=[r"求.*和", r"加.*一起"],
    trigger_priority=8,
    requires_numbers=True,
    examples=["[TOOL_CALL: sum_numbers(numbers=[10, 20, 30, 40])]"],
    name="sum",
)
async def sum_numbers(numbers: list[float]) -> dict[str, Any]:
    """
    对一组数字求和。

    Args:
        numbers: 数字列表
    """
    total = sum(numbers)
    return {"numbers": numbers, "sum": total, "count": len(numbers)}


@tool(
    category="math",
    description="计算一组数字的算术平均值",
    triggers=["平均", "均值", "平均值", "平均数"],
    trigger_patterns=[r"平均(值|数|分|成绩|工资|收入)"],
    trigger_priority=8,
    requires_numbers=True,
    examples=["[TOOL_CALL: mean(numbers=[85, 92, 78, 90, 88])]"],
)
async def mean(numbers: list[float]) -> dict[str, Any]:
    """
    计算算术平均值。

    Args:
        numbers: 数字列表
    """
    if not numbers:
        return {"error": "列表不能为空", "result": None}
    avg = statistics.mean(numbers)
    return {"numbers": numbers, "mean": avg, "count": len(numbers)}


@tool(
    category="math",
    description="计算一组数字的中位数",
    triggers=["中位数", "中位"],
    trigger_priority=8,
    requires_numbers=True,
    examples=["[TOOL_CALL: median(numbers=[1, 3, 5, 7, 9])]"],
)
async def median(numbers: list[float]) -> dict[str, Any]:
    """
    计算中位数。

    Args:
        numbers: 数字列表
    """
    if not numbers:
        return {"error": "列表不能为空", "result": None}
    med = statistics.median(numbers)
    return {"numbers": numbers, "median": med}


@tool(
    category="math",
    description="计算一组数字的标准差和方差",
    triggers=["标准差", "方差", "离散程度", "波动"],
    trigger_priority=7,
    requires_numbers=True,
    examples=["[TOOL_CALL: std_deviation(numbers=[10, 12, 23, 23, 16, 23, 21, 16])]"],
)
async def std_deviation(numbers: list[float]) -> dict[str, Any]:
    """
    计算标准差和方差。

    Args:
        numbers: 数字列表（至少2个数据点）
    """
    if len(numbers) < 2:
        return {"error": "至少需要两个数据点", "result": None}
    std = statistics.stdev(numbers)
    return {"numbers": numbers, "std_deviation": std, "variance": std ** 2}


@tool(
    category="math",
    description="计算百分位数（如P50中位数、P90、P99）",
    triggers=["百分位", "P90", "P95", "P99", "P50", "分位数"],
    trigger_patterns=[r"[Pp]\d{1,2}"],
    trigger_priority=7,
    examples=["[TOOL_CALL: percentile(numbers=[1,2,3,4,5,6,7,8,9,10], p=90)]"],
)
async def percentile(numbers: list[float], p: float = 50) -> dict[str, Any]:
    """
    计算百分位数。

    Args:
        numbers: 数字列表
        p: 百分位(0-100)，默认50
    """
    if not numbers:
        return {"error": "列表不能为空", "result": None}
    sorted_nums = sorted(numbers)
    k = (len(sorted_nums) - 1) * (p / 100)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        result = sorted_nums[int(k)]
    else:
        result = sorted_nums[f] * (c - k) + sorted_nums[c] * (k - f)
    return {"percentile": p, "value": result}


# ============================================================
# 变化率 / 金融计算
# ============================================================

@tool(
    category="math",
    description="计算变化百分比（环比/同比增减幅度）",
    triggers=["增长率", "变化率", "环比", "同比", "增幅", "降幅", "涨了多少", "跌了多少", "变化百分比"],
    trigger_patterns=[r"从\d+.*到\d+", r"\d+.*变.*\d+"],
    trigger_priority=9,
    requires_numbers=True,
    examples=["[TOOL_CALL: percentage_change(old_value=1000, new_value=1250)]"],
    pre_execute_pattern=r"从\s*(\d+\.?\d*)\s*(?:到|变为?|增[长加]到|降?[低到])\s*(\d+\.?\d*)",
    pre_execute_extractor=lambda m: {"old_value": float(m.group(1)), "new_value": float(m.group(2))},
    pre_execute_formatter=lambda r: f"从 {r.get('old_value')} 到 {r.get('new_value')}，{r.get('direction')} {abs(r.get('change_percent', 0))}%",
)
async def percentage_change(old_value: float, new_value: float) -> dict[str, Any]:
    """
    计算变化百分比（环比/同比）。

    Args:
        old_value: 原始值（上期数据）
        new_value: 新值（本期数据）
    """
    if old_value == 0:
        return {"error": "原始值不能为0", "result": None}
    change = ((new_value - old_value) / abs(old_value)) * 100
    return {
        "old_value": old_value,
        "new_value": new_value,
        "change_percent": round(change, 2),
        "direction": "增长" if change > 0 else "下降" if change < 0 else "持平",
    }


@tool(
    category="math",
    description="复合增长计算（复利公式），适用于投资回报、年增长率等",
    triggers=["复利", "复合增长", "年化", "投资回报", "年增长率"],
    trigger_patterns=[r"(复利|年化|年增长率).*\d+"],
    trigger_priority=7,
    examples=["[TOOL_CALL: compound_growth(principal=10000, rate=8, periods=5)]"],
)
async def compound_growth(principal: float, rate: float, periods: int) -> dict[str, Any]:
    """
    复合增长计算（复利）。

    Args:
        principal: 初始本金
        rate: 增长率(百分比)
        periods: 期数
    """
    result = principal * ((1 + rate / 100) ** periods)
    return {
        "principal": principal,
        "rate_percent": rate,
        "periods": periods,
        "final_value": round(result, 2),
        "total_growth": round(result - principal, 2),
    }


@tool(
    category="math",
    description="简单线性回归分析，拟合直线并返回斜率、截距和R²",
    triggers=["线性回归", "回归分析", "趋势线", "拟合", "斜率"],
    trigger_priority=6,
    examples=["[TOOL_CALL: linear_regression(x_values=[1,2,3,4,5], y_values=[2,4,5,4,5])]"],
)
async def linear_regression(x_values: list[float], y_values: list[float]) -> dict[str, Any]:
    """
    简单线性回归。

    Args:
        x_values: 自变量列表
        y_values: 因变量列表
    """
    if len(x_values) != len(y_values) or len(x_values) < 2:
        return {"error": "x和y长度必须相同且至少2个点", "result": None}

    n = len(x_values)
    sum_x = sum(x_values)
    sum_y = sum(y_values)
    sum_xy = sum(x * y for x, y in zip(x_values, y_values))
    sum_x2 = sum(x ** 2 for x in x_values)

    denominator = n * sum_x2 - sum_x ** 2
    if denominator == 0:
        return {"error": "无法计算（x值全部相同）", "result": None}

    slope = (n * sum_xy - sum_x * sum_y) / denominator
    intercept = (sum_y - slope * sum_x) / n

    y_mean = sum_y / n
    ss_tot = sum((y - y_mean) ** 2 for y in y_values)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(x_values, y_values))
    r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0

    return {
        "slope": round(slope, 4),
        "intercept": round(intercept, 4),
        "r_squared": round(r_squared, 4),
        "equation": f"y = {slope:.4f}x + {intercept:.4f}",
    }
