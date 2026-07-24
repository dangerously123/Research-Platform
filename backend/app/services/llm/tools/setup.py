"""工具系统初始化：注册所有工具到全局注册中心。"""

from app.services.llm.tools.math_tools import register_math_tools
from app.services.llm.tools.geo_tools import register_geo_tools
from app.services.llm.tools.datetime_tools import register_datetime_tools
from app.services.llm.tools.text_tools import register_text_tools
from app.services.llm.tools.registry import tool_registry


def setup_all_tools():
    """注册所有工具。应用启动时调用一次。"""
    register_math_tools()
    register_geo_tools()
    register_datetime_tools()
    register_text_tools()

    # 输出注册信息
    tools = tool_registry.list_all()
    categories = tool_registry.get_categories()
    print(f"[Tools] 已注册 {len(tools)} 个工具，分类: {categories}")


# 模块导入时自动注册
setup_all_tools()
