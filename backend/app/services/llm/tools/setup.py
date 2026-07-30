"""
工具系统初始化：自动扫描并注册所有工具。

使用 @tool 装饰器的模块会在导入时自动注册到 tool_registry，
本模块负责触发导入（自动发现）并输出注册摘要。
"""

from app.services.llm.tools.decorator import auto_discover_tools, get_all_tool_metadata
from app.services.llm.tools.registry import tool_registry


def setup_all_tools():
    """
    自动扫描 tools 目录下所有 *_tools.py 模块，
    触发 @tool 装饰器完成注册。应用启动时调用一次。
    """
    # 自动发现并导入所有工具模块
    auto_discover_tools("app.services.llm.tools")

    # 输出注册信息
    tools = tool_registry.list_all()
    categories = tool_registry.get_categories()
    print(f"[Tools] 已注册 {len(tools)} 个工具，分类: {categories}")


# 模块导入时自动注册
setup_all_tools()
