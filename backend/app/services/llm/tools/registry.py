"""工具注册中心：管理所有可用工具的注册和发现。"""

from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable


@dataclass
class ToolDefinition:
    """工具定义。"""
    name: str                          # 工具名称（唯一标识）
    description: str                   # 工具描述（给 LLM 看）
    category: str                      # 分类: math / geo / datetime / text / data / network
    parameters: dict                   # 参数 JSON Schema
    handler: Callable[..., Awaitable[Any]]  # 实际执行函数
    examples: list[str] = field(default_factory=list)  # 使用示例


class ToolRegistry:
    """
    工具注册中心。
    所有工具通过此注册中心注册和发现。
    """

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """注册工具。"""
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition | None:
        """获取指定工具。"""
        return self._tools.get(name)

    def list_all(self) -> list[ToolDefinition]:
        """列出所有已注册工具。"""
        return list(self._tools.values())

    def list_by_category(self, category: str) -> list[ToolDefinition]:
        """按分类列出工具。"""
        return [t for t in self._tools.values() if t.category == category]

    def get_tools_prompt(self) -> str:
        """
        生成工具描述文本，用于注入 LLM Prompt。
        格式便于 LLM 理解如何调用工具。
        """
        lines = ["你可以使用以下工具来辅助回答问户的问题。需要时请按格式调用：",
                 "调用格式: [TOOL_CALL: tool_name(param1=value1, param2=value2)]",
                 ""]
        for tool in self._tools.values():
            params_desc = ", ".join(
                f"{k}: {v.get('description', v.get('type', ''))}"
                for k, v in tool.parameters.get("properties", {}).items()
            )
            lines.append(f"- **{tool.name}**: {tool.description}")
            lines.append(f"  参数: {params_desc}")
            if tool.examples:
                lines.append(f"  示例: {tool.examples[0]}")
            lines.append("")

        return "\n".join(lines)

    def get_categories(self) -> list[str]:
        """获取所有工具分类。"""
        return list(set(t.category for t in self._tools.values()))


# 全局工具注册中心实例
tool_registry = ToolRegistry()
