"""工具系统单元测试。"""

import pytest

from app.services.llm.tools.registry import tool_registry


class TestToolRegistry:
    """测试工具注册中心。"""

    def test_tools_registered(self):
        """验证应用启动后工具已注册。"""
        tools = tool_registry.list_all()
        assert len(tools) > 0

    def test_calculator_registered(self):
        """验证 calculator 工具存在。"""
        calc = tool_registry.get("calculator")
        assert calc is not None
        assert calc.name == "calculator"
        assert calc.category == "math"

    def test_tool_has_schema(self):
        """验证工具有参数 schema。"""
        calc = tool_registry.get("calculator")
        assert "properties" in calc.parameters
        assert "expression" in calc.parameters["properties"]

    def test_categories_not_empty(self):
        """验证工具分类非空。"""
        categories = tool_registry.get_categories()
        assert len(categories) > 0
        assert "math" in categories


class TestCalculator:
    """测试 calculator 工具执行。"""

    @pytest.mark.asyncio
    async def test_simple_addition(self):
        calc = tool_registry.get("calculator")
        result = await calc.handler(expression="2 + 3")
        assert result["result"] == 5

    @pytest.mark.asyncio
    async def test_complex_expression(self):
        calc = tool_registry.get("calculator")
        result = await calc.handler(expression="sqrt(144) + 2**3")
        assert result["result"] == 20.0

    @pytest.mark.asyncio
    async def test_invalid_expression(self):
        calc = tool_registry.get("calculator")
        result = await calc.handler(expression="import os")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_division(self):
        calc = tool_registry.get("calculator")
        result = await calc.handler(expression="100 / 4")
        assert result["result"] == 25.0


class TestMathTools:
    """测试统计类工具。"""

    @pytest.mark.asyncio
    async def test_mean(self):
        tool = tool_registry.get("mean")
        result = await tool.handler(numbers=[10, 20, 30])
        assert result["mean"] == 20.0

    @pytest.mark.asyncio
    async def test_percentage_change(self):
        tool = tool_registry.get("percentage_change")
        result = await tool.handler(old_value=100, new_value=150)
        assert result["change_percent"] == 50.0
        assert result["direction"] == "增长"

    @pytest.mark.asyncio
    async def test_percentage_change_decrease(self):
        tool = tool_registry.get("percentage_change")
        result = await tool.handler(old_value=200, new_value=100)
        assert result["change_percent"] == -50.0
        assert result["direction"] == "下降"


class TestGeoTools:
    """测试地理工具。"""

    @pytest.mark.asyncio
    async def test_city_distance(self):
        tool = tool_registry.get("city_distance")
        result = await tool.handler(city1="北京", city2="上海")
        assert "distance_km" in result
        assert result["distance_km"] > 1000  # 北京到上海约1068公里

    @pytest.mark.asyncio
    async def test_get_city_location(self):
        tool = tool_registry.get("get_city_location")
        result = await tool.handler(city_name="北京")
        assert result["found"] is True
        assert result["lat"] == pytest.approx(39.9042, abs=0.01)


class TestDatetimeTools:
    """测试时间工具。"""

    @pytest.mark.asyncio
    async def test_date_difference(self):
        tool = tool_registry.get("date_difference")
        result = await tool.handler(date1="2024-01-01", date2="2024-01-31")
        assert result["days"] == 30

    @pytest.mark.asyncio
    async def test_add_days(self):
        tool = tool_registry.get("add_days")
        result = await tool.handler(date="2024-01-01", days=31)
        assert result["result_date"] == "2024-02-01"

    @pytest.mark.asyncio
    async def test_current_time(self):
        tool = tool_registry.get("current_time")
        result = await tool.handler(timezone_offset=8)
        assert "datetime" in result
        assert "weekday" in result
