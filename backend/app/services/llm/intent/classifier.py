"""
意图分类器：多层意图识别系统。

设计原则：
1. 先分大类（闲聊/知识问答/工具计算/数据查询/操作指令）
2. 再细分子意图（具体工具或操作）
3. 输出置信度分数，低于阈值时走 LLM 兜底判断
4. 支持否定检测和多意图拆分
5. 上下文感知：结合对话历史消歧
"""

import re
from dataclasses import dataclass, field
from enum import Enum


class IntentCategory(str, Enum):
    """一级意图分类。"""
    CHAT = "chat"                  # 闲聊/寒暄
    KNOWLEDGE_QA = "knowledge_qa"  # 知识问答（需要 RAG）
    TOOL_CALL = "tool_call"        # 工具调用（需要计算/查询）
    DATA_QUERY = "data_query"      # 数据报表查询
    SYSTEM_CMD = "system_cmd"      # 系统操作指令（设置/管理）
    UNCLEAR = "unclear"            # 意图不清晰


class ConfidenceLevel(str, Enum):
    """置信度等级。"""
    HIGH = "high"        # >= 0.8  直接执行
    MEDIUM = "medium"    # 0.5-0.8 执行但附加确认
    LOW = "low"          # 0.3-0.5 需要 LLM 辅助判断
    NONE = "none"        # < 0.3   放弃工具调用


@dataclass
class IntentResult:
    """意图识别结果。"""
    category: IntentCategory
    confidence: float                              # 0-1 置信度
    confidence_level: ConfidenceLevel
    sub_intents: list[dict] = field(default_factory=list)  # 子意图列表
    matched_tools: list[str] = field(default_factory=list)
    extracted_params: dict = field(default_factory=dict)
    is_negated: bool = False                       # 是否被否定
    requires_context: bool = False                 # 是否需要上下文补充
    raw_query: str = ""
    rewritten_query: str = ""                      # 消歧后的查询


class IntentClassifier:
    """
    多层意图分类器。

    识别流程：
    1. 否定检测 → 如果是否定意图，标记并调整策略
    2. 一级分类 → 确定大类（chat/knowledge/tool/data/system）
    3. 多意图拆分 → 检测是否包含多个独立意图
    4. 上下文消歧 → 结合历史对话解决代词/省略
    5. 子意图匹配 → 对 tool_call 类确定具体工具和参数
    6. 置信度评估 → 综合多个信号输出置信度
    """

    # ===== 一级分类规则 =====

    # 闲聊特征
    CHAT_PATTERNS = [
        r"^(你好|hi|hello|嗨|hey|早上好|晚上好|下午好)",
        r"^(谢谢|感谢|辛苦了|好的|ok|明白了|知道了|收到)",
        r"^(再见|拜拜|bye|结束|退出)",
        r"(你是谁|你叫什么|你能做什么|你会什么)",
        r"^(哈哈|嗯|哦|噢|呃)$",
    ]

    # 数据查询特征
    DATA_QUERY_PATTERNS = [
        r"(本月|上月|本周|上周|今年|去年|本季度|上季度).*(数据|销售额|营收|利润|订单)",
        r"(报表|图表|统计|汇总|明细).*(看|查|展示|显示|导出)",
        r"(查看|打开|展示|显示|生成).*报表",
        r"(KPI|指标|数据|dashboard|仪表盘)",
    ]

    # 系统指令特征
    SYSTEM_CMD_PATTERNS = [
        r"(设置|配置|修改|更改|调整).*(角色|权限|密码|模型|模板)",
        r"(添加|删除|创建|移除).*(用户|角色|文档|模板)",
        r"(上传|导入|导出).*文档",
        r"(清空|重置|清除).*(记忆|会话|缓存)",
    ]

    # 否定词
    NEGATION_PATTERNS = [
        r"不[要用需]",
        r"别[算查]",
        r"不必",
        r"无需",
        r"不用.*(计算|查询|工具|调用)",
        r"直接(告诉|回答|说)",
    ]

    # 多意图连接词
    MULTI_INTENT_MARKERS = [
        "另外", "顺便", "还有", "同时", "以及",
        "然后", "接着", "再", "并且",
    ]

    def classify(
        self,
        query: str,
        conversation_history: list[dict] | None = None,
    ) -> IntentResult:
        """
        对用户查询进行意图分类。

        Args:
            query: 用户原始问题
            conversation_history: 最近对话历史

        Returns:
            IntentResult 包含分类、置信度、子意图等
        """
        result = IntentResult(
            category=IntentCategory.UNCLEAR,
            confidence=0.0,
            confidence_level=ConfidenceLevel.NONE,
            raw_query=query,
            rewritten_query=query,
        )

        # 1. 否定检测
        result.is_negated = self._detect_negation(query)

        # 2. 上下文消歧
        if conversation_history:
            rewritten = self._resolve_context(query, conversation_history)
            if rewritten != query:
                result.rewritten_query = rewritten
                result.requires_context = True

        working_query = result.rewritten_query

        # 3. 一级分类
        category, category_confidence = self._classify_category(working_query)
        result.category = category

        # 4. 多意图拆分
        sub_intents = self._detect_multi_intents(working_query)
        if len(sub_intents) > 1:
            result.sub_intents = sub_intents

        # 5. 如果是工具调用类，进行细粒度匹配
        if category == IntentCategory.TOOL_CALL and not result.is_negated:
            tools, params, tool_confidence = self._match_tools_detailed(working_query)
            result.matched_tools = tools
            result.extracted_params = params
            # 综合置信度
            result.confidence = min(1.0, (category_confidence + tool_confidence) / 2)
        else:
            result.confidence = category_confidence

        # 6. 否定意图降权
        if result.is_negated and category == IntentCategory.TOOL_CALL:
            result.confidence *= 0.2  # 大幅降低置信度
            result.category = IntentCategory.KNOWLEDGE_QA  # 降级为知识问答

        # 7. 确定置信度等级
        result.confidence_level = self._get_confidence_level(result.confidence)

        return result

    def _detect_negation(self, query: str) -> bool:
        """检测否定意图。"""
        for pattern in self.NEGATION_PATTERNS:
            if re.search(pattern, query):
                return True
        return False

    def _classify_category(self, query: str) -> tuple[IntentCategory, float]:
        """一级意图分类，返回 (类别, 置信度)。"""
        scores: dict[IntentCategory, float] = {
            IntentCategory.CHAT: 0.0,
            IntentCategory.KNOWLEDGE_QA: 0.3,  # 默认基础分（知识问答是最常见的）
            IntentCategory.TOOL_CALL: 0.0,
            IntentCategory.DATA_QUERY: 0.0,
            IntentCategory.SYSTEM_CMD: 0.0,
        }

        # 闲聊检测
        for pattern in self.CHAT_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                scores[IntentCategory.CHAT] += 0.8
                break

        # 数据查询检测
        for pattern in self.DATA_QUERY_PATTERNS:
            if re.search(pattern, query):
                scores[IntentCategory.DATA_QUERY] += 0.7
                break

        # 系统指令检测
        for pattern in self.SYSTEM_CMD_PATTERNS:
            if re.search(pattern, query):
                scores[IntentCategory.SYSTEM_CMD] += 0.7
                break

        # 工具调用检测（利用已有的 IntentMatcher 分数）
        from app.services.llm.tools.intent_matcher import intent_matcher
        if intent_matcher.should_use_tools(query):
            matched = intent_matcher.match_tools(query, max_tools=3)
            if matched:
                # 根据匹配数量和质量打分
                tool_score = min(0.9, 0.5 + len(matched) * 0.15)
                scores[IntentCategory.TOOL_CALL] = tool_score

        # 取最高分的类别
        best_category = max(scores, key=scores.get)
        best_score = scores[best_category]

        # 如果最高分太低，标记为 unclear
        if best_score < 0.3:
            return IntentCategory.UNCLEAR, best_score

        return best_category, best_score

    def _detect_multi_intents(self, query: str) -> list[dict]:
        """检测多意图：用户一句话中包含多个独立请求。"""
        intents = []

        # 按多意图标记词分割
        parts = [query]
        for marker in self.MULTI_INTENT_MARKERS:
            new_parts = []
            for part in parts:
                splits = part.split(marker)
                new_parts.extend(s.strip() for s in splits if s.strip())
            parts = new_parts

        if len(parts) <= 1:
            return [{"query": query, "index": 0}]

        # 对每个部分单独分类
        for i, part in enumerate(parts):
            if len(part) >= 4:  # 至少4字才算有效子意图
                intents.append({
                    "query": part,
                    "index": i,
                })

        return intents if len(intents) > 1 else [{"query": query, "index": 0}]

    def _resolve_context(self, query: str, history: list[dict]) -> str:
        """
        上下文消歧：解决代词指代和省略。

        示例：
        - 历史: "北京到上海多远" → 当前: "那到广州呢" → 改写: "北京到广州多远"
        - 历史: "帮我算85+92的平均值" → 当前: "加上78呢" → 改写: "85 92 78的平均值"
        """
        # 检测是否需要上下文
        needs_context = False

        # 代词指代
        reference_words = ["那", "它", "这个", "那个", "上面", "之前", "呢", "也", "换成"]
        if any(w in query for w in reference_words):
            needs_context = True

        # 过短查询（可能省略了主语）
        if len(query) < 10:
            needs_context = True

        if not needs_context:
            return query

        # 获取最近的用户消息作为上下文
        recent_user_msg = ""
        for msg in reversed(history[-6:]):
            if msg.get("role") == "user":
                recent_user_msg = msg.get("content", "")
                break

        if not recent_user_msg:
            return query

        # 策略 1：当前含"呢"/"也"，拼接上文主题
        if query.endswith("呢") or query.endswith("也") or "换成" in query:
            # 提取上文核心名词
            nouns = re.findall(r'[\u4e00-\u9fff]{2,4}', recent_user_msg)
            if nouns:
                # 将上文主题 + 当前修饰组合
                return f"{' '.join(nouns[:2])} {query}"

        # 策略 2：当前查询过短，直接拼接
        if len(query) < 8:
            return f"{recent_user_msg} {query}"

        return query

    def _match_tools_detailed(self, query: str) -> tuple[list[str], dict, float]:
        """
        细粒度工具匹配：确定具体工具和提取参数。

        Returns:
            (工具名列表, 提取的参数, 工具匹配置信度)
        """
        from app.services.llm.tools.intent_matcher import intent_matcher

        # 确保触发规则已加载
        intent_matcher._ensure_loaded()
        triggers = intent_matcher._triggers

        matched_tools = []
        all_params = {}
        max_score = 0

        for trigger in triggers:
            score = self._score_trigger(query, trigger)
            if score > 0:
                matched_tools.append(trigger.tool_name)
                max_score = max(max_score, score)

                # 尝试提取参数
                params = self._extract_params_for_tool(query, trigger.tool_name)
                if params:
                    all_params[trigger.tool_name] = params

        # 置信度：基于最高分和匹配数量
        if not matched_tools:
            return [], {}, 0.0

        # 只匹配到一个工具 → 高置信度
        # 匹配到多个 → 需要进一步判断
        if len(matched_tools) == 1:
            confidence = min(1.0, max_score / 15)
        else:
            confidence = min(0.8, max_score / 15)

        return matched_tools[:3], all_params, confidence

    def _score_trigger(self, query: str, trigger) -> int:
        """计算触发规则的匹配分数（增强版）。"""
        score = 0
        query_lower = query.lower()

        # 数字检查
        has_numbers = bool(re.search(r'\d', query))
        if trigger.requires_numbers and not has_numbers:
            return 0

        # 关键词匹配（支持多关键词叠加）
        keyword_hits = 0
        for keyword in trigger.keywords:
            if keyword.lower() in query_lower:
                keyword_hits += 1
        if keyword_hits > 0:
            score += trigger.priority + (keyword_hits - 1) * 2  # 多关键词命中加分

        # 正则模式匹配
        for pattern in trigger.patterns:
            if re.search(pattern, query, re.IGNORECASE):
                score += trigger.priority + 3
                break

        return score

    def _extract_params_for_tool(self, query: str, tool_name: str) -> dict:
        """针对特定工具从查询中提取参数。"""
        params = {}

        if tool_name == "calculator":
            # 提取数学表达式
            match = re.search(r'(?:计算|算|求)\s*[:：]?\s*(.+?)(?:[？?。]|$)', query)
            if match:
                params["expression"] = match.group(1).strip()

        elif tool_name == "city_distance":
            # 提取两个城市
            match = re.search(r'([\u4e00-\u9fff]{2,4})\s*(?:到|离|距)\s*([\u4e00-\u9fff]{2,4})', query)
            if match:
                params["city1"] = match.group(1)
                params["city2"] = match.group(2)

        elif tool_name in ("mean", "sum", "median", "std_deviation"):
            # 提取数字列表
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
            match = re.search(
                r'(\d+\.?\d*)\s*(公里|千米|英里|公斤|千克|磅|摄氏度|华氏度|GB|MB|TB|万)',
                query
            )
            if match:
                params["value"] = float(match.group(1))
                params["from_unit"] = match.group(2)

        return params

    def _get_confidence_level(self, confidence: float) -> ConfidenceLevel:
        """将数值置信度转为等级。"""
        if confidence >= 0.8:
            return ConfidenceLevel.HIGH
        elif confidence >= 0.5:
            return ConfidenceLevel.MEDIUM
        elif confidence >= 0.3:
            return ConfidenceLevel.LOW
        return ConfidenceLevel.NONE
