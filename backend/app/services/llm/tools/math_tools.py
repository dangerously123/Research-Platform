"""数学计算工具集：基础运算、统计函数、金融计算等。"""

import math
import statistics
from typing import Any

from app.services.llm.tools.registry import ToolDefinition, tool_registry


async def calculator(expression: str) -> dict[str, Any]:
    """
    安全的数学表达式计算器。
    支持加减乘除、幂运算、括号、常用数学函数。
    """
    # 安全限制：只允许数学相关字符和函数
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
        # 编译并安全执行
        code = compile(expression, "<calculator>", "eval")
        # 检查是否有非法名称
        for name in code.co_names:
            if name not in allowed_names:
                return {"error": f"不支持的函数或变量: {name}", "result": None}

        result = eval(code, {"__builtins__": {}}, allowed_names)
        return {"expression": expression, "result": result}
    except Exception as e:
        return {"error": str(e), "result": None}


async def sum_numbers(numbers: list[float]) -> dict[str, Any]:
    """求和。"""
    total = sum(numbers)
    return {"numbers": numbers, "sum": total, "count": len(numbers)}


async def mean_value(numbers: list[float]) -> dict[str, Any]:
    """计算算术平均值。"""
    if not numbers:
        return {"error": "列表不能为空", "result": None}
    avg = statistics.mean(numbers)
    return {"numbers": numbers, "mean": avg, "count": len(numbers)}


async def median_value(numbers: list[float]) -> dict[str, Any]:
    """计算中位数。"""
    if not numbers:
        return {"error": "列表不能为空", "result": None}
    med = statistics.median(numbers)
    return {"numbers": numbers, "median": med}


async def std_deviation(numbers: list[float]) -> dict[str, Any]:
    """计算标准差。"""
    if len(numbers) < 2:
        return {"error": "至少需要两个数据点", "result": None}
    std = statistics.stdev(numbers)
    return {"numbers": numbers, "std_deviation": std, "variance": std ** 2}


async def percentile(numbers: list[float], p: float = 50) -> dict[str, Any]:
    """计算百分位数。"""
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


async def percentage_change(old_value: float, new_value: float) -> dict[str, Any]:
    """计算变化百分比（环比/同比）。"""
    if old_value == 0:
        return {"error": "原始值不能为0", "result": None}
    change = ((new_value - old_value) / abs(old_value)) * 100
    return {
        "old_value": old_value,
        "new_value": new_value,
        "change_percent": round(change, 2),
        "direction": "增长" if change > 0 else "下降" if change < 0 else "持平",
    }


async def compound_growth(principal: float, rate: float, periods: int) -> dict[str, Any]:
    """复合增长计算（复利）。"""
    result = principal * ((1 + rate / 100) ** periods)
    return {
        "principal": principal,
        "rate_percent": rate,
        "periods": periods,
        "final_value": round(result, 2),
        "total_growth": round(result - principal, 2),
    }


async def linear_regression(x_values: list[float], y_values: list[float]) -> dict[str, Any]:
    """简单线性回归。"""
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

    # R² 计算
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


def register_math_tools():
    """注册所有数学工具到全局注册中心。"""
    tools = [
        ToolDefinition(
            name="calculator",
            description="数学表达式计算器，支持四则运算、幂、三角函数、对数等",
            category="math",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "数学表达式，如 '2**10 + sqrt(144)'"}
                },
                "required": ["expression"],
            },
            handler=calculator,
            examples=["[TOOL_CALL: calculator(expression='1024 * 768 / 1000')]"],
        ),
        ToolDefinition(
            name="sum",
            description="对一组数字求和",
            category="math",
            parameters={
                "type": "object",
                "properties": {
                    "numbers": {"type": "array", "items": {"type": "number"}, "description": "数字列表"}
                },
                "required": ["numbers"],
            },
            handler=sum_numbers,
            examples=["[TOOL_CALL: sum(numbers=[10, 20, 30, 40])]"],
        ),
        ToolDefinition(
            name="mean",
            description="计算一组数字的算术平均值",
            category="math",
            parameters={
                "type": "object",
                "properties": {
                    "numbers": {"type": "array", "items": {"type": "number"}, "description": "数字列表"}
                },
                "required": ["numbers"],
            },
            handler=mean_value,
            examples=["[TOOL_CALL: mean(numbers=[85, 92, 78, 90, 88])]"],
        ),
        ToolDefinition(
            name="median",
            description="计算一组数字的中位数",
            category="math",
            parameters={
                "type": "object",
                "properties": {
                    "numbers": {"type": "array", "items": {"type": "number"}, "description": "数字列表"}
                },
                "required": ["numbers"],
            },
            handler=median_value,
            examples=["[TOOL_CALL: median(numbers=[1, 3, 5, 7, 9])]"],
        ),
        ToolDefinition(
            name="std_deviation",
            description="计算一组数字的标准差和方差",
            category="math",
            parameters={
                "type": "object",
                "properties": {
                    "numbers": {"type": "array", "items": {"type": "number"}, "description": "数字列表"}
                },
                "required": ["numbers"],
            },
            handler=std_deviation,
            examples=["[TOOL_CALL: std_deviation(numbers=[10, 12, 23, 23, 16, 23, 21, 16])]"],
        ),
        ToolDefinition(
            name="percentile",
            description="计算百分位数（如P50中位数、P90、P99）",
            category="math",
            parameters={
                "type": "object",
                "properties": {
                    "numbers": {"type": "array", "items": {"type": "number"}, "description": "数字列表"},
                    "p": {"type": "number", "description": "百分位(0-100)，默认50"},
                },
                "required": ["numbers"],
            },
            handler=percentile,
            examples=["[TOOL_CALL: percentile(numbers=[1,2,3,4,5,6,7,8,9,10], p=90)]"],
        ),
        ToolDefinition(
            name="percentage_change",
            description="计算变化百分比（环比/同比增减幅度）",
            category="math",
            parameters={
                "type": "object",
                "properties": {
                    "old_value": {"type": "number", "description": "原始值（上期数据）"},
                    "new_value": {"type": "number", "description": "新值（本期数据）"},
                },
                "required": ["old_value", "new_value"],
            },
            handler=percentage_change,
            examples=["[TOOL_CALL: percentage_change(old_value=1000, new_value=1250)]"],
        ),
        ToolDefinition(
            name="compound_growth",
            description="复合增长计算（复利公式），适用于投资回报、年增长率等",
            category="math",
            parameters={
                "type": "object",
                "properties": {
                    "principal": {"type": "number", "description": "初始本金"},
                    "rate": {"type": "number", "description": "增长率(百分比)"},
                    "periods": {"type": "integer", "description": "期数"},
                },
                "required": ["principal", "rate", "periods"],
            },
            handler=compound_growth,
            examples=["[TOOL_CALL: compound_growth(principal=10000, rate=8, periods=5)]"],
        ),
        ToolDefinition(
            name="linear_regression",
            description="简单线性回归分析，拟合直线并返回斜率、截距和R²",
            category="math",
            parameters={
                "type": "object",
                "properties": {
                    "x_values": {"type": "array", "items": {"type": "number"}, "description": "自变量列表"},
                    "y_values": {"type": "array", "items": {"type": "number"}, "description": "因变量列表"},
                },
                "required": ["x_values", "y_values"],
            },
            handler=linear_regression,
            examples=["[TOOL_CALL: linear_regression(x_values=[1,2,3,4,5], y_values=[2,4,5,4,5])]"],
        ),
    ]

    for t in tools:
        tool_registry.register(t)
