"""
意图匹配器：根据用户问题智能选择相关工具。

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
    keywords: list[str] = field(default_factory=list)       # 关键词列表（任一命中即触发）
    patterns: list[str] = field(default_factory=list)       # 正则模式列表
    priority: int = 0                                       # 优先级（越高越优先）
    requires_numbers: bool = False                          # 是否需要包含数字


# 工具触发规则配置
TOOL_TRIGGERS: list[ToolTrigger] = [
    # ===== 数学类 =====
    ToolTrigger(
        tool_name="calculator",
        keywords=["计算", "算一下", "等于多少", "求值", "运算", "乘以", "除以", "加上", "减去", "平方", "开根号", "次方"],
        patterns=[r"\d+\s*[\+\-\*\/\^]\s*\d+", r"(sin|cos|tan|sqrt|log)\("],
        priority=10,
        requires_numbers=True,
    ),
    ToolTrigger(
        tool_name="sum",
        keywords=["求和", "总和", "加起来", "合计", "总计", "累加"],
        patterns=[r"求.*和", r"加.*一起"],
        priority=8,
        requires_numbers=True,
    ),
    ToolTrigger(
        tool_name="mean",
        keywords=["平均", "均值", "平均值", "平均数"],
        patterns=[r"平均(值|数|分|成绩|工资|收入)"],
        priority=8,
        requires_numbers=True,
    ),
    ToolTrigger(
        tool_name="median",
        keywords=["中位数", "中位"],
        priority=8,
        requires_numbers=True,
    ),
    ToolTrigger(
        tool_name="std_deviation",
        keywords=["标准差", "方差", "离散程度", "波动"],
        priority=7,
        requires_numbers=True,
    ),
    ToolTrigger(
        tool_name="percentile",
        keywords=["百分位", "P90", "P95", "P99", "P50", "分位数"],
        patterns=[r"[Pp]\d{1,2}"],
        priority=7,
    ),
    ToolTrigger(
        tool_name="percentage_change",
        keywords=["增长率", "变化率", "环比", "同比", "增幅", "降幅", "涨了多少", "跌了多少", "变化百分比"],
        patterns=[r"从\d+.*到\d+", r"\d+.*变.*\d+"],
        priority=9,
        requires_numbers=True,
    ),
    ToolTrigger(
        tool_name="compound_growth",
        keywords=["复利", "复合增长", "年化", "投资回报", "年增长率"],
        patterns=[r"(复利|年化|年增长率).*\d+"],
        priority=7,
    ),
    ToolTrigger(
        tool_name="linear_regression",
        keywords=["线性回归", "回归分析", "趋势线", "拟合", "斜率"],
        priority=6,
    ),

    # ===== 地理类 =====
    ToolTrigger(
        tool_name="city_distance",
        keywords=["距离", "多远", "几公里", "多少公里"],
        patterns=[r"(北京|上海|广州|深圳|杭州|成都|武汉|南京|西安|重庆).*(到|离|距).*(北京|上海|广州|深圳|杭州|成都|武汉|南京|西安|重庆)"],
        priority=9,
    ),
    ToolTrigger(
        tool_name="get_city_location",
        keywords=["坐标", "经纬度", "位置", "在哪"],
        patterns=[r"(经度|纬度|坐标).*(是多少|是什么)"],
        priority=7,
    ),
    ToolTrigger(
        tool_name="haversine_distance",
        keywords=["坐标距离", "两点距离"],
        patterns=[r"\d+\.\d+.*\d+\.\d+"],  # 包含小数点坐标格式
        priority=6,
    ),
    ToolTrigger(
        tool_name="bearing",
        keywords=["方位", "方向", "朝向", "方位角"],
        priority=5,
    ),

    # ===== 时间类 =====
    ToolTrigger(
        tool_name="current_time",
        keywords=["现在几点", "当前时间", "今天日期", "今天星期几", "现在时间"],
        patterns=[r"(现在|当前|今天).*(几点|时间|日期|星期)"],
        priority=10,
    ),
    ToolTrigger(
        tool_name="date_difference",
        keywords=["相隔多少天", "间隔多少天", "距离多少天", "相差几天"],
        patterns=[r"\d{4}[-/]\d{1,2}[-/]\d{1,2}.*\d{4}[-/]\d{1,2}[-/]\d{1,2}"],
        priority=9,
    ),
    ToolTrigger(
        tool_name="add_days",
        keywords=["天之后", "天以后", "天后是", "天前是"],
        patterns=[r"\d+天(之?后|以后|前)"],
        priority=8,
    ),
    ToolTrigger(
        tool_name="is_workday",
        keywords=["工作日", "上班", "休息日", "周末"],
        patterns=[r"\d{4}[-/]\d{1,2}[-/]\d{1,2}.*(工作日|上班|休息)"],
        priority=7,
    ),
    ToolTrigger(
        tool_name="workdays_between",
        keywords=["几个工作日", "多少个工作日"],
        priority=7,
    ),
    ToolTrigger(
        tool_name="timestamp_convert",
        keywords=["时间戳", "timestamp"],
        patterns=[r"1[0-9]{9}"],  # 10位数字开头
        priority=8,
    ),

    # ===== 文本/单位类 =====
    ToolTrigger(
        tool_name="unit_convert",
        keywords=["转换", "换算", "等于多少", "是多少"],
        patterns=[
            r"\d+\s*(公里|千米|英里|km|mile)",
            r"\d+\s*(公斤|千克|磅|kg|lb)",
            r"\d+\s*(摄氏度|华氏度|℃|°F)",
            r"\d+\s*(GB|MB|TB|gb|mb|tb)",
            r"\d+\s*万",
        ],
        priority=8,
        requires_numbers=True,
    ),
    ToolTrigger(
        tool_name="word_count",
        keywords=["字数", "多少字", "字符数", "几个字"],
        priority=6,
    ),
    ToolTrigger(
        tool_name="hash_text",
        keywords=["MD5", "SHA", "哈希", "hash", "md5", "sha256"],
        priority=7,
    ),
    ToolTrigger(
        tool_name="json_format",
        keywords=["格式化JSON", "JSON格式化", "美化JSON"],
        patterns=[r'\{.*".*".*:.*\}'],
        priority=6,
    ),
]


class IntentMatcher:
    """
    意图匹配器。
    根据用户问题确定应该使用哪些工具。
    """

    def __init__(self):
        self._triggers = {t.tool_name: t for t in TOOL_TRIGGERS}

    def match_tools(self, query: str, max_tools: int = 5) -> list[ToolDefinition]:
        """
        根据用户问题匹配相关工具。

        Returns:
            按匹配度排序的工具列表（最多 max_tools 个）
        """
        scored_tools: list[tuple[int, str]] = []

        for trigger in TOOL_TRIGGERS:
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
            tool = tool_registry.get(name)
            if tool:
                result.append(tool)

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

        for tool in matched:
            params_desc = []
            for k, v in tool.parameters.get("properties", {}).items():
                required = k in tool.parameters.get("required", [])
                req_mark = "必填" if required else "可选"
                params_desc.append(f"    {k} ({req_mark}): {v.get('description', v.get('type', ''))}")

            lines.append(f"工具: {tool.name}")
            lines.append(f"  功能: {tool.description}")
            lines.append(f"  参数:")
            lines.extend(params_desc)
            if tool.examples:
                lines.append(f"  调用示例: {tool.examples[0]}")
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
            return 0  # 需要数字但没有数字，直接不匹配

        # 关键词匹配
        for keyword in trigger.keywords:
            if keyword.lower() in query.lower():
                score += trigger.priority
                break  # 一个关键词命中即可

        # 正则模式匹配
        for pattern in trigger.patterns:
            if re.search(pattern, query, re.IGNORECASE):
                score += trigger.priority + 2  # 正则匹配给额外分
                break

        return score


# 全局意图匹配器实例
intent_matcher = IntentMatcher()
