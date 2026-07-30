"""
意图匹配器：根据用户问题智能选择相关工具。

改造后：触发规则从 @tool 装饰器元数据自动生成，
无需手动维护 TOOL_TRIGGERS 列表。

策略：
1. 关键词规则匹配（快速、确定性高）
2. 意图分类（将问题归类到工具类别）
3. 只向 LLM 注入相关工具描述（减少噪音，提高准确性）
"""

import re
from dataclasses import dataclass, field

from app.services.llm.tools.registry import ToolDefinition, tool_registry


@dataclass
class ToolTrigger:
    """工具触发规则。"""
    tool_name: str
    keywords: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)
    priority: int = 0
    requires_numbers: bool = False


class IntentMatcher:
    """
    意图匹配器。
    根据用户问题确定应该使用哪些工具。

    触发规则自动从 @tool 装饰器元数据加载，
    也支持通过 add_trigger() 手动补充规则。
    """

    def __init__(self):
        self._triggers: list[ToolTrigger] = []
        self._loaded = False

    def _ensure_loaded(self):
        """确保触发规则已从装饰器元数据加载。"""
        if self._loaded:
            return
        self._loaded = True
        self._load_from_decorator_metadata()

    def _load_from_decorator_metadata(self):
        """从 @tool 装饰器收集的元数据中加载触发规则。"""
        try:
            from app.services.llm.tools.decorator import get_trigger_rules
            rules = get_trigger_rules()
            for rule in rules:
                trigger = ToolTrigger(
                    tool_name=rule["tool_name"],
                    keywords=rule.get("keywords", []),
                    patterns=rule.get("patterns", []),
                    priority=rule.get("priority", 5),
                    requires_numbers=rule.get("requires_numbers", False),
                )
                self._triggers.append(trigger)
        except ImportError:
            pass

    def add_trigger(self, trigger: ToolTrigger) -> None:
        """手动添加触发规则（向后兼容或动态补充）。"""
        self._triggers.append(trigger)

    def match_tools(self, query: str, max_tools: int = 5) -> list[ToolDefinition]:
        """
        根据用户问题匹配相关工具。

        Returns:
            按匹配度排序的工具列表（最多 max_tools 个）
        """
        self._ensure_loaded()

        scored_tools: list[tuple[int, str]] = []

        for trigger in self._triggers:
            score = self._calculate_match_score(query, trigger)
            if score > 0:
                scored_tools.append((score, trigger.tool_name))

        # 按得分降序排序
        scored_tools.sort(key=lambda x: x[0], reverse=True)

        # 取前 N 个
        matched_names = [name for _, name in scored_tools[:max_tools]]

        # 获取工具定义
        result = []
        for name in matched_names:
            tool_def = tool_registry.get(name)
            if tool_def:
                result.append(tool_def)

        return result

    def get_relevant_tools_prompt(self, query: str) -> str:
        """
        生成仅包含相关工具的 Prompt 描述。
        比注入全部工具更精准，减少 LLM 困惑。
        """
        matched = self.match_tools(query)

        if not matched:
            return ""

        lines = [
            "根据用户的问题，以下工具可能有用。如果需要计算或查询，请使用工具。",
            "调用格式: [TOOL_CALL: tool_name(param1=value1, param2=value2)]",
            "重要规则：",
            "- 只在确实需要计算/查询时才调用工具",
            "- 参数值必须从用户问题中准确提取",
            "- 一次回答中可以调用多个工具",
            "- 如果不需要工具，直接回答即可",
            "",
        ]

        for tool_def in matched:
            params_desc = []
            for k, v in tool_def.parameters.get("properties", {}).items():
                required = k in tool_def.parameters.get("required", [])
                req_mark = "必填" if required else "可选"
                params_desc.append(f"    {k} ({req_mark}): {v.get('description', v.get('type', ''))}")

            lines.append(f"工具: {tool_def.name}")
            lines.append(f"  功能: {tool_def.description}")
            lines.append(f"  参数:")
            lines.extend(params_desc)
            if tool_def.examples:
                lines.append(f"  调用示例: {tool_def.examples[0]}")
            lines.append("")

        return "\n".join(lines)

    def should_use_tools(self, query: str) -> bool:
        """快速判断问题是否可能需要工具。"""
        matched = self.match_tools(query, max_tools=1)
        return len(matched) > 0

    def _calculate_match_score(self, query: str, trigger: ToolTrigger) -> int:
        """计算问题与工具触发规则的匹配分数。"""
        score = 0

        # 数字检查
        has_numbers = bool(re.search(r'\d', query))
        if trigger.requires_numbers and not has_numbers:
            return 0

        # 关键词匹配
        for keyword in trigger.keywords:
            if keyword.lower() in query.lower():
                score += trigger.priority
                break

        # 正则模式匹配
        for pattern in trigger.patterns:
            try:
                if re.search(pattern, query, re.IGNORECASE):
                    score += trigger.priority + 2
                    break
            except re.error:
                continue

        return score


# 全局意图匹配器实例
intent_matcher = IntentMatcher()
