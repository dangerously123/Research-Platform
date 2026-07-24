"""
意图解析器：将分类结果转化为执行策略。

根据 IntentResult 决定：
- 走哪条处理路径（RAG/工具/报表/纯对话）
- 如何构建 Prompt
- 是否需要预执行工具
- 多意图如何编排
"""

from dataclasses import dataclass, field
from enum import Enum

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm.intent.classifier import (
    ConfidenceLevel,
    IntentCategory,
    IntentClassifier,
    IntentResult,
)


class ExecutionPath(str, Enum):
    """执行路径。"""
    DIRECT_CHAT = "direct_chat"        # 直接对话（闲聊/简单回答）
    RAG_SEARCH = "rag_search"          # RAG 知识检索 + LLM 生成
    TOOL_PRE_EXEC = "tool_pre_exec"    # 工具预执行 + LLM 润色
    TOOL_LLM_CALL = "tool_llm_call"    # LLM 自主决定工具调用
    DATA_REPORT = "data_report"        # 数据报表查询
    SYSTEM_ACTION = "system_action"    # 系统操作
    MULTI_STEP = "multi_step"          # 多步骤执行（多意图）
    LLM_FALLBACK = "llm_fallback"      # LLM 兜底判断


@dataclass
class ExecutionPlan:
    """执行计划。"""
    path: ExecutionPath
    intent_result: IntentResult
    steps: list[dict] = field(default_factory=list)
    tools_prompt: str = ""
    should_use_rag: bool = True
    should_inject_tools: bool = False
    pre_execute_tools: list[dict] = field(default_factory=list)
    prompt_additions: list[str] = field(default_factory=list)


class IntentResolver:
    """
    意图解析器。
    将 IntentClassifier 的输出转化为可执行的计划。
    """

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self.db = db
        self.redis = redis
        self.classifier = IntentClassifier()

    async def resolve(
        self,
        query: str,
        conversation_history: list[dict] | None = None,
    ) -> ExecutionPlan:
        """
        解析用户查询，生成执行计划。

        Returns:
            ExecutionPlan 包含执行路径和详细步骤
        """
        # 1. 意图分类
        intent = self.classifier.classify(query, conversation_history)

        # 2. 根据分类结果决定执行路径
        plan = self._build_plan(intent)

        # 3. 多意图处理
        if len(intent.sub_intents) > 1:
            plan = await self._handle_multi_intent(intent, plan)

        return plan

    def _build_plan(self, intent: IntentResult) -> ExecutionPlan:
        """根据意图构建执行计划。"""

        # === 闲聊 ===
        if intent.category == IntentCategory.CHAT:
            return ExecutionPlan(
                path=ExecutionPath.DIRECT_CHAT,
                intent_result=intent,
                should_use_rag=False,
                should_inject_tools=False,
                prompt_additions=["这是一个闲聊/寒暄，请简短友好地回应。"],
            )

        # === 工具调用 ===
        if intent.category == IntentCategory.TOOL_CALL:
            return self._build_tool_plan(intent)

        # === 数据查询 ===
        if intent.category == IntentCategory.DATA_QUERY:
            return ExecutionPlan(
                path=ExecutionPath.DATA_REPORT,
                intent_result=intent,
                should_use_rag=False,
                should_inject_tools=False,
                prompt_additions=[
                    "用户想要查看数据报表。请引导用户选择报表类型和时间范围，"
                    "或告知可以在'数据报表'页面查看。"
                ],
            )

        # === 系统指令 ===
        if intent.category == IntentCategory.SYSTEM_CMD:
            return ExecutionPlan(
                path=ExecutionPath.SYSTEM_ACTION,
                intent_result=intent,
                should_use_rag=False,
                should_inject_tools=False,
                prompt_additions=[
                    "用户想要执行系统管理操作。请告知对应的操作入口或所需权限。"
                ],
            )

        # === 知识问答（默认路径）===
        if intent.category == IntentCategory.KNOWLEDGE_QA:
            return ExecutionPlan(
                path=ExecutionPath.RAG_SEARCH,
                intent_result=intent,
                should_use_rag=True,
                should_inject_tools=False,
            )

        # === 意图不清 → LLM 兜底 ===
        return ExecutionPlan(
            path=ExecutionPath.LLM_FALLBACK,
            intent_result=intent,
            should_use_rag=True,
            should_inject_tools=True,  # 不确定时都注入
        )

    def _build_tool_plan(self, intent: IntentResult) -> ExecutionPlan:
        """构建工具调用执行计划。"""

        # 高置信度：预执行
        if intent.confidence_level == ConfidenceLevel.HIGH:
            pre_exec_tools = []
            for tool_name in intent.matched_tools[:2]:
                params = intent.extracted_params.get(tool_name, {})
                if params:  # 有参数才预执行
                    pre_exec_tools.append({
                        "tool": tool_name,
                        "params": params,
                    })

            if pre_exec_tools:
                return ExecutionPlan(
                    path=ExecutionPath.TOOL_PRE_EXEC,
                    intent_result=intent,
                    should_use_rag=False,
                    should_inject_tools=False,
                    pre_execute_tools=pre_exec_tools,
                )

        # 中置信度：让 LLM 自主调用（注入工具描述）
        if intent.confidence_level in (ConfidenceLevel.MEDIUM, ConfidenceLevel.HIGH):
            return ExecutionPlan(
                path=ExecutionPath.TOOL_LLM_CALL,
                intent_result=intent,
                should_use_rag=False,
                should_inject_tools=True,
            )

        # 低置信度：同时走 RAG + 工具
        return ExecutionPlan(
            path=ExecutionPath.LLM_FALLBACK,
            intent_result=intent,
            should_use_rag=True,
            should_inject_tools=True,
        )

    async def _handle_multi_intent(
        self, intent: IntentResult, base_plan: ExecutionPlan
    ) -> ExecutionPlan:
        """处理多意图：对每个子意图分别规划。"""
        steps = []
        for sub in intent.sub_intents:
            sub_intent = self.classifier.classify(sub["query"])
            steps.append({
                "query": sub["query"],
                "category": sub_intent.category.value,
                "tools": sub_intent.matched_tools,
                "params": sub_intent.extracted_params,
            })

        base_plan.path = ExecutionPath.MULTI_STEP
        base_plan.steps = steps
        base_plan.should_use_rag = True
        base_plan.should_inject_tools = True
        base_plan.prompt_additions.append(
            f"用户的问题包含 {len(steps)} 个子问题，请依次回答每个部分。"
        )
        return base_plan
