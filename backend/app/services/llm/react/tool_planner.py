"""
工具规划器：在 ReAct 循环中智能选择和编排工具。

核心能力：
1. 动态工具推荐：每轮根据当前状态推荐最相关的工具
2. 工具链规划：识别多步骤问题，预先规划工具调用序列
3. 参数辅助提取：预先从查询中提取结构化参数
4. 失败重试策略：工具失败时推荐替代方案
5. 结果验证：检查工具返回是否合理
"""

import re
from dataclasses import dataclass, field

from app.services.llm.tools.registry import ToolDefinition, tool_registry


@dataclass
class ToolSuggestion:
    """工具建议。"""
    tool_name: str
    reason: str                     # 为什么推荐这个工具
    confidence: float               # 推荐置信度 0-1
    pre_extracted_params: dict = field(default_factory=dict)
    depends_on: str | None = None   # 依赖前一个工具的结果


@dataclass
class ToolChainPlan:
    """工具链规划。"""
    steps: list[ToolSuggestion]
    description: str
    is_sequential: bool = True      # 是否必须顺序执行


class ToolPlanner:
    """
    工具规划器。
    在 ReAct 每轮循环中提供智能工具选择支持。
    """

    # 工具链模式识别：常见的多步骤问题模式
    CHAIN_PATTERNS = [
        {
            "pattern": r"(.+)(到|离|距)(.+)(多远|距离).*(多[久长]|需要|小时|分钟)",
            "chain": ["city_distance", "calculator"],
            "description": "先查距离，再算时间",
        },
        {
            "pattern": r"(平均|均值).*(环比|同比|变化|增长|对比)",
            "chain": ["mean", "percentage_change"],
            "description": "先算平均值，再算变化率",
        },
        {
            "pattern": r"(\d{4}[-/]\d{1,2}[-/]\d{1,2}).*(工作日|上班天)",
            "chain": ["date_difference", "workdays_between"],
            "description": "先算总天数，再算工作日",
        },
        {
            "pattern": r"(总|合计|求和).*(平均|均值|每)",
            "chain": ["sum", "calculator"],
            "description": "先求和，再计算平均",
        },
    ]

    # 工具间的依赖关系（输出→输入映射）
    TOOL_DEPENDENCIES = {
        ("city_distance", "calculator"): {
            "output_field": "distance_km",
            "description": "将距离结果用于后续计算",
        },
        ("mean", "percentage_change"): {
            "output_field": "mean",
            "description": "将平均值作为变化率计算的输入",
        },
        ("sum", "calculator"): {
            "output_field": "sum",
            "description": "将求和结果用于后续计算",
        },
    }

    def plan_tool_chain(self, query: str) -> ToolChainPlan | None:
        """
        分析查询，识别是否需要多步工具链。

        Returns:
            ToolChainPlan 或 None（不需要链式调用）
        """
        for pattern_info in self.CHAIN_PATTERNS:
            if re.search(pattern_info["pattern"], query, re.IGNORECASE):
                steps = []
                for i, tool_name in enumerate(pattern_info["chain"]):
                    tool = tool_registry.get(tool_name)
                    if not tool:
                        continue
                    suggestion = ToolSuggestion(
                        tool_name=tool_name,
                        reason=f"步骤{i+1}: {tool.description}",
                        confidence=0.85,
                        depends_on=pattern_info["chain"][i-1] if i > 0 else None,
                    )
                    steps.append(suggestion)

                if steps:
                    return ToolChainPlan(
                        steps=steps,
                        description=pattern_info["description"],
                        is_sequential=True,
                    )
        return None

    def suggest_next_tool(
        self,
        query: str,
        completed_tools: list[dict],
        last_observation: str = "",
        failed_tools: list[str] | None = None,
    ) -> list[ToolSuggestion]:
        """
        根据当前状态推荐下一步应该使用的工具。

        Args:
            query: 原始查询
            completed_tools: 已执行的工具记录 [{"tool": name, "result": ...}]
            last_observation: 上一步的观察结果
            failed_tools: 已失败的工具列表

        Returns:
            按推荐度排序的工具建议列表
        """
        failed = set(failed_tools or [])
        completed_names = {t["tool"] for t in completed_tools}
        suggestions = []

        # 1. 检查是否有预规划的工具链
        chain = self.plan_tool_chain(query)
        if chain:
            for step in chain.steps:
                if step.tool_name not in completed_names and step.tool_name not in failed:
                    # 检查依赖是否满足
                    if step.depends_on is None or step.depends_on in completed_names:
                        # 尝试从上一步结果中提取参数
                        if step.depends_on and last_observation:
                            params = self._extract_params_from_observation(
                                last_observation, step.tool_name
                            )
                            step.pre_extracted_params = params
                        suggestions.append(step)
                        break  # 只推荐链中的下一步

        # 2. 如果链式规划没有命中，做通用推荐
        if not suggestions:
            suggestions = self._general_recommend(
                query, completed_names, failed, last_observation
            )

        # 3. 对失败工具推荐替代方案
        if failed:
            alternatives = self._get_alternatives(failed, query)
            suggestions.extend(alternatives)

        return suggestions[:3]  # 最多推荐3个

    def validate_tool_result(
        self, tool_name: str, params: dict, result: dict
    ) -> tuple[bool, str]:
        """
        验证工具执行结果是否合理。

        Returns:
            (is_valid, reason)
        """
        if "error" in result and result["error"]:
            return False, f"工具执行报错: {result['error']}"

        # 数值合理性检查
        if tool_name == "calculator":
            value = result.get("result")
            if value is not None and (abs(value) > 1e15 or (isinstance(value, float) and value != value)):
                return False, "计算结果异常（数值过大或NaN）"

        if tool_name == "haversine_distance" or tool_name == "city_distance":
            dist = result.get("distance_km", 0)
            if dist > 20100:  # 地球周长一半
                return False, "距离超过地球半周长，结果不合理"
            if dist <= 0:
                return False, "距离为0或负数，结果不合理"

        if tool_name == "percentage_change":
            pct = result.get("change_percent", 0)
            if abs(pct) > 10000:
                return False, "变化率超过10000%，请确认数据"

        return True, "结果有效"

    def format_tool_guidance(
        self,
        suggestions: list[ToolSuggestion],
        iteration: int,
        completed_tools: list[dict],
    ) -> str:
        """
        生成当前轮次的工具使用引导，注入 Prompt。
        """
        if not suggestions:
            return ""

        lines = [f"\n[第{iteration}轮工具建议]"]

        if completed_tools:
            lines.append(f"已完成的工具: {', '.join(t['tool'] for t in completed_tools)}")

        for i, sug in enumerate(suggestions, 1):
            tool = tool_registry.get(sug.tool_name)
            if not tool:
                continue

            lines.append(f"\n推荐工具{i}: {sug.tool_name} (置信度:{sug.confidence:.0%})")
            lines.append(f"  原因: {sug.reason}")
            lines.append(f"  功能: {tool.description}")

            # 参数描述
            params_desc = []
            for k, v in tool.parameters.get("properties", {}).items():
                pre_val = sug.pre_extracted_params.get(k)
                if pre_val:
                    params_desc.append(f"    {k} = {pre_val} (已提取)")
                else:
                    params_desc.append(f"    {k}: {v.get('description', '')}")
            if params_desc:
                lines.append("  参数:")
                lines.extend(params_desc)

            if tool.examples:
                lines.append(f"  示例: {tool.examples[0]}")

        return "\n".join(lines)

    def _general_recommend(
        self,
        query: str,
        completed: set[str],
        failed: set[str],
        observation: str,
    ) -> list[ToolSuggestion]:
        """通用工具推荐（非链式场景）。"""
        from app.services.llm.tools.intent_matcher import intent_matcher

        matched = intent_matcher.match_tools(query, max_tools=5)
        suggestions = []

        for tool in matched:
            if tool.name not in completed and tool.name not in failed:
                # 从查询中尝试提取参数
                params = self._try_extract_params(query, tool.name)
                suggestions.append(ToolSuggestion(
                    tool_name=tool.name,
                    reason=tool.description,
                    confidence=0.7,
                    pre_extracted_params=params,
                ))

        return suggestions

    def _get_alternatives(self, failed: set[str], query: str) -> list[ToolSuggestion]:
        """为失败的工具推荐替代方案。"""
        alternatives_map = {
            "city_distance": ["haversine_distance"],
            "calculator": [],
            "mean": ["calculator"],
        }
        suggestions = []
        for failed_tool in failed:
            alts = alternatives_map.get(failed_tool, [])
            for alt in alts:
                tool = tool_registry.get(alt)
                if tool:
                    suggestions.append(ToolSuggestion(
                        tool_name=alt,
                        reason=f"{failed_tool}失败，替代方案: {tool.description}",
                        confidence=0.5,
                    ))
        return suggestions

    def _extract_params_from_observation(self, observation: str, tool_name: str) -> dict:
        """从上一步的 Observation 中提取可用于下一步的参数。"""
        params = {}

        # 提取数值结果
        numbers = re.findall(r'[\d.]+', observation)

        if tool_name == "calculator" and numbers:
            # 将上一步的数值结果用于计算表达式
            params["_available_values"] = [float(n) for n in numbers[:5]]

        return params

    def _try_extract_params(self, query: str, tool_name: str) -> dict:
        """尝试从查询中预提取工具参数。"""
        params = {}

        if tool_name == "calculator":
            match = re.search(r'(?:计算|算)\s*[:：]?\s*(.+?)(?:[？?。]|$)', query)
            if match:
                params["expression"] = match.group(1).strip()

        elif tool_name == "city_distance":
            match = re.search(r'([\u4e00-\u9fff]{2,4})\s*(?:到|离|距)\s*([\u4e00-\u9fff]{2,4})', query)
            if match:
                params["city1"] = match.group(1)
                params["city2"] = match.group(2)

        elif tool_name in ("mean", "sum", "median", "std_deviation"):
            numbers = re.findall(r'\d+\.?\d*', query)
            if len(numbers) >= 2:
                params["numbers"] = [float(n) for n in numbers]

        elif tool_name == "percentage_change":
            match = re.search(r'从\s*(\d+\.?\d*)\s*(?:到|变)\s*(\d+\.?\d*)', query)
            if match:
                params["old_value"] = float(match.group(1))
                params["new_value"] = float(match.group(2))

        elif tool_name == "date_difference":
            dates = re.findall(r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})', query)
            if len(dates) >= 2:
                params["date1"] = dates[0].replace("/", "-")
                params["date2"] = dates[1].replace("/", "-")

        elif tool_name == "unit_convert":
            match = re.search(r'(\d+\.?\d*)\s*(公里|千米|英里|公斤|千克|磅|摄氏度|华氏度|GB|MB|TB|万)', query)
            if match:
                params["value"] = float(match.group(1))
                params["from_unit"] = match.group(2)

        return params
