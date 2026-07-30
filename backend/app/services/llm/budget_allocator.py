"""
Prompt Token 预算统一分配器。

核心思想：
- 将 Prompt 的各组成部分视为"预算消费者"
- 先满足不可压缩的固定部分（System Prompt、用户 Query）
- 剩余预算按优先级分配给可压缩部分（历史、记忆、工具、RAG 文档）
- 超预算时按优先级从低到高裁剪/丢弃

使用方式：
    allocator = TokenBudgetAllocator(
        model_context_window=8192,
        max_output_tokens=2048,
        provider="openai",
    )
    result = allocator.allocate({
        "system_prompt": "你是...",
        "user_query": "帮我分析...",
        "recent_history": "用户: ...\n助手: ...",
        "memory_context": "- [3天前] ...",
        "tools_prompt": "可用工具: ...",
        "rag_docs": "相关文档: ...",
        "older_history": "[历史摘要]: ...",
    })
    # result.components 是裁剪后的各组件
    # result.final_prompt 是组装后的完整 Prompt
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import IntEnum

from app.services.llm.token_counter import TokenCounter, count_tokens, truncate_to_tokens

logger = logging.getLogger(__name__)


class ComponentPriority(IntEnum):
    """
    组件优先级（数值越小越优先保留）。
    P0 不可裁剪；P1-P5 可裁剪，预算不足时从 P5 开始丢弃。
    """
    SYSTEM_PROMPT = 0
    USER_QUERY = 0
    RECENT_HISTORY = 1
    TOOLS_PROMPT = 2
    MEMORY_CONTEXT = 3
    RAG_DOCS = 4
    OLDER_HISTORY = 5


@dataclass
class ComponentPolicy:
    """单个组件的预算策略。"""
    priority: int
    min_ratio: float       # 占总输入预算的最低比例（0 表示可完全丢弃）
    max_ratio: float       # 占总输入预算的最大比例
    compressible: bool     # 是否可裁剪/压缩
    truncate_from: str = "start"  # 裁剪方向："start"（保留尾部）或 "end"（保留头部）


# 默认分配策略
DEFAULT_POLICIES: dict[str, ComponentPolicy] = {
    "system_prompt": ComponentPolicy(
        priority=ComponentPriority.SYSTEM_PROMPT,
        min_ratio=0.0, max_ratio=1.0,
        compressible=False,
    ),
    "user_query": ComponentPolicy(
        priority=ComponentPriority.USER_QUERY,
        min_ratio=0.0, max_ratio=1.0,
        compressible=False,
    ),
    "file_context": ComponentPolicy(
        priority=1,
        min_ratio=0.05, max_ratio=0.40,
        compressible=True, truncate_from="end",
    ),
    "recent_history": ComponentPolicy(
        priority=ComponentPriority.RECENT_HISTORY,
        min_ratio=0.05, max_ratio=0.30,
        compressible=True, truncate_from="start",
    ),
    "tools_prompt": ComponentPolicy(
        priority=ComponentPriority.TOOLS_PROMPT,
        min_ratio=0.0, max_ratio=0.15,
        compressible=True, truncate_from="end",
    ),
    "memory_context": ComponentPolicy(
        priority=ComponentPriority.MEMORY_CONTEXT,
        min_ratio=0.0, max_ratio=0.15,
        compressible=True, truncate_from="end",
    ),
    "rag_docs": ComponentPolicy(
        priority=ComponentPriority.RAG_DOCS,
        min_ratio=0.0, max_ratio=0.25,
        compressible=True, truncate_from="end",
    ),
    "older_history": ComponentPolicy(
        priority=ComponentPriority.OLDER_HISTORY,
        min_ratio=0.0, max_ratio=0.15,
        compressible=True, truncate_from="start",
    ),
}


@dataclass
class AllocationResult:
    """预算分配结果。"""
    components: dict[str, str]         # 裁剪后的各组件文本
    token_usage: dict[str, int]        # 各组件实际占用的 Token 数
    total_input_tokens: int            # 总输入 Token 数
    total_input_budget: int            # 总输入预算
    output_reserve: int                # 输出预留 Token 数
    warnings: list[str] = field(default_factory=list)  # 裁剪警告

    @property
    def budget_utilization(self) -> float:
        """预算利用率。"""
        if self.total_input_budget == 0:
            return 0.0
        return self.total_input_tokens / self.total_input_budget

    @property
    def remaining_budget(self) -> int:
        """剩余可用输入 Token 数。"""
        return max(0, self.total_input_budget - self.total_input_tokens)

    def assemble_prompt(self, separator: str = "\n\n") -> str:
        """
        按标准顺序组装最终 Prompt。

        组装顺序：
        system_prompt → tools_prompt → memory_context → rag_docs
        → older_history → recent_history → user_query
        """
        order = [
            "system_prompt",
            "tools_prompt",
            "file_context",
            "memory_context",
            "rag_docs",
            "older_history",
            "recent_history",
            "user_query",
        ]
        parts = []
        for key in order:
            content = self.components.get(key, "")
            if content.strip():
                parts.append(content)
        return separator.join(parts)


class InputTooLongException(Exception):
    """用户输入超出模型上下文窗口。"""

    def __init__(self, message: str, input_tokens: int = 0, budget: int = 0):
        self.input_tokens = input_tokens
        self.budget = budget
        super().__init__(message)


class TokenBudgetAllocator:
    """
    Prompt Token 预算统一分配器。

    工作流程：
    1. 计算总输入预算 = model_context_window - output_reserve
    2. 固定组件（P0）先占位
    3. 如果 P0 已超预算 → 抛出异常
    4. 剩余预算按优先级从高到低分配给可压缩组件
    5. 每个组件的实际预算 = min(剩余空间, max_ratio × 总预算, 组件实际大小)
    6. 如果组件超出预算 → 裁剪
    7. 如果所有组件分配后仍超预算 → 从最低优先级开始丢弃
    """

    # 输出预留的最大占比（防止小窗口模型输出被过度压缩）
    OUTPUT_RESERVE_MAX_RATIO = 0.35
    # 安全边距（预留给格式化开销）
    SAFETY_MARGIN_TOKENS = 50

    def __init__(
        self,
        model_context_window: int,
        max_output_tokens: int,
        provider: str = "openai",
        model_name: str | None = None,
        policies: dict[str, ComponentPolicy] | None = None,
    ):
        """
        Args:
            model_context_window: 模型总上下文窗口大小（Token）
            max_output_tokens: 期望的最大输出 Token 数
            provider: 模型供应商（用于选择 tokenizer）
            model_name: 具体模型名称（可选）
            policies: 自定义分配策略（可选，默认使用 DEFAULT_POLICIES）
        """
        self.model_context_window = model_context_window
        self.max_output_tokens = max_output_tokens
        self.provider = provider

        # 计算输出预留
        self.output_reserve = min(
            max_output_tokens,
            int(model_context_window * self.OUTPUT_RESERVE_MAX_RATIO),
        )

        # 总输入预算（扣除输出预留和安全边距）
        self.total_input_budget = (
            model_context_window - self.output_reserve - self.SAFETY_MARGIN_TOKENS
        )

        # Token 计数器
        self.counter = TokenCounter.for_provider(provider, model_name)

        # 分配策略
        self.policies = policies or DEFAULT_POLICIES.copy()

    def allocate(self, components: dict[str, str]) -> AllocationResult:
        """
        执行预算分配。

        Args:
            components: 各组件的原始文本
                {
                    "system_prompt": "...",
                    "user_query": "...",
                    "recent_history": "...",
                    "tools_prompt": "...",
                    "memory_context": "...",
                    "rag_docs": "...",
                    "older_history": "...",
                }

        Returns:
            AllocationResult 包含裁剪后的组件和使用统计

        Raises:
            InputTooLongException: 不可压缩组件已超出预算
        """
        warnings: list[str] = []

        # Step 1: 计算各组件原始 Token 数
        raw_tokens: dict[str, int] = {}
        for key, text in components.items():
            raw_tokens[key] = self.counter.count(text) if text else 0

        # Step 2: 固定组件（不可压缩）占位
        fixed_keys = [
            k for k, policy in self.policies.items()
            if not policy.compressible and k in components
        ]
        fixed_cost = sum(raw_tokens.get(k, 0) for k in fixed_keys)

        if fixed_cost > self.total_input_budget:
            raise InputTooLongException(
                f"系统指令+用户输入({fixed_cost} tokens)已超出输入预算"
                f"({self.total_input_budget} tokens)，请缩短消息后重试",
                input_tokens=fixed_cost,
                budget=self.total_input_budget,
            )

        # Step 3: 剩余预算分配给可压缩组件
        remaining = self.total_input_budget - fixed_cost
        allocated_texts: dict[str, str] = {}
        allocated_tokens: dict[str, int] = {}

        # 固定组件原样保留
        for key in fixed_keys:
            allocated_texts[key] = components.get(key, "")
            allocated_tokens[key] = raw_tokens.get(key, 0)

        # 可压缩组件按优先级排序
        flexible_items = sorted(
            [
                (key, self.policies[key])
                for key in components
                if key in self.policies and self.policies[key].compressible
            ],
            key=lambda x: x[1].priority,
        )

        for comp_key, policy in flexible_items:
            text = components.get(comp_key, "")
            if not text:
                allocated_texts[comp_key] = ""
                allocated_tokens[comp_key] = 0
                continue

            comp_tokens = raw_tokens[comp_key]

            # 计算该组件可用的最大预算
            max_by_ratio = int(self.total_input_budget * policy.max_ratio)
            actual_budget = min(remaining, max_by_ratio)

            if actual_budget <= 0:
                # 没有剩余预算了
                allocated_texts[comp_key] = ""
                allocated_tokens[comp_key] = 0
                warnings.append(
                    f"[{comp_key}] 预算不足，已完全丢弃（原始 {comp_tokens} tokens）"
                )
                continue

            if comp_tokens <= actual_budget:
                # 不需要裁剪
                allocated_texts[comp_key] = text
                allocated_tokens[comp_key] = comp_tokens
            else:
                # 需要裁剪
                truncated = self._truncate_component(comp_key, text, actual_budget, policy)
                actual_count = self.counter.count(truncated)
                allocated_texts[comp_key] = truncated
                allocated_tokens[comp_key] = actual_count
                warnings.append(
                    f"[{comp_key}] 已裁剪: {comp_tokens} → {actual_count} tokens"
                )

            remaining -= allocated_tokens[comp_key]

        # Step 4: 最终验证 — 如果总量仍超预算，从最低优先级开始丢弃
        total_used = sum(allocated_tokens.values())
        if total_used > self.total_input_budget:
            allocated_texts, allocated_tokens, extra_warnings = self._emergency_trim(
                allocated_texts, allocated_tokens, flexible_items
            )
            warnings.extend(extra_warnings)
            total_used = sum(allocated_tokens.values())

        return AllocationResult(
            components=allocated_texts,
            token_usage=allocated_tokens,
            total_input_tokens=total_used,
            total_input_budget=self.total_input_budget,
            output_reserve=self.output_reserve,
            warnings=warnings,
        )

    def estimate_available_budget(
        self, fixed_components: dict[str, str]
    ) -> dict[str, int]:
        """
        预估各可压缩组件的可用预算（不执行实际裁剪）。
        适用于在构建组件前了解各部分可用空间。

        Args:
            fixed_components: 已确定的固定组件文本（至少包含 system_prompt 和 user_query）

        Returns:
            {"recent_history": N, "tools_prompt": N, ...} 各组件的可用 Token 预算
        """
        fixed_cost = sum(
            self.counter.count(text) for text in fixed_components.values() if text
        )
        remaining = self.total_input_budget - fixed_cost

        if remaining <= 0:
            return {k: 0 for k, p in self.policies.items() if p.compressible}

        budgets = {}
        flexible_items = sorted(
            [(k, p) for k, p in self.policies.items() if p.compressible],
            key=lambda x: x[1].priority,
        )

        for comp_key, policy in flexible_items:
            max_by_ratio = int(self.total_input_budget * policy.max_ratio)
            budgets[comp_key] = min(remaining, max_by_ratio)
            # 简化估算：按最大比例扣减（实际分配可能用得少）
            remaining -= int(self.total_input_budget * policy.min_ratio)
            remaining = max(0, remaining)

        return budgets

    def _truncate_component(
        self,
        comp_key: str,
        text: str,
        budget: int,
        policy: ComponentPolicy,
    ) -> str:
        """
        裁剪单个组件到预算内。
        根据组件类型选择不同策略。
        """
        if comp_key == "recent_history":
            return self._truncate_history(text, budget)
        elif comp_key == "older_history":
            return self._truncate_older_history(text, budget)
        elif comp_key in ("memory_context", "rag_docs"):
            return self._truncate_by_items(text, budget)
        elif comp_key == "tools_prompt":
            return self._truncate_tools(text, budget)
        else:
            # 通用裁剪
            if policy.truncate_from == "start":
                return self._truncate_keep_tail(text, budget)
            else:
                return self.counter.truncate(text, budget)

    def _truncate_history(self, text: str, budget: int) -> str:
        """
        裁剪对话历史：保留最近的消息，丢弃最早的。
        按行分割，从前面移除直到满足预算。
        """
        lines = text.split("\n")
        # 从后向前累积
        kept_lines: list[str] = []
        accumulated = 0
        for line in reversed(lines):
            line_tokens = self.counter.count(line) + 1  # +1 for newline
            if accumulated + line_tokens > budget:
                break
            kept_lines.insert(0, line)
            accumulated += line_tokens

        if not kept_lines:
            # 至少保留最后一行
            if lines:
                return self.counter.truncate(lines[-1], budget)
            return ""

        return "\n".join(kept_lines)

    def _truncate_older_history(self, text: str, budget: int) -> str:
        """
        裁剪早期历史：保留摘要的核心内容。
        """
        return self.counter.truncate(text, budget)

    def _truncate_by_items(self, text: str, budget: int) -> str:
        """
        按条目裁剪（适用于记忆和 RAG 文档）。
        每条记忆/文档以 "- " 开头，按顺序保留直到预算耗尽。
        """
        lines = text.split("\n")
        items: list[str] = []
        current_item: list[str] = []

        for line in lines:
            if line.startswith("- ") and current_item:
                items.append("\n".join(current_item))
                current_item = [line]
            else:
                current_item.append(line)
        if current_item:
            items.append("\n".join(current_item))

        # 按顺序保留（假设前面的更相关）
        kept: list[str] = []
        accumulated = 0
        for item in items:
            item_tokens = self.counter.count(item) + 1
            if accumulated + item_tokens > budget:
                break
            kept.append(item)
            accumulated += item_tokens

        if not kept and items:
            # 至少保留第一条（裁剪）
            return self.counter.truncate(items[0], budget)

        return "\n".join(kept)

    def _truncate_tools(self, text: str, budget: int) -> str:
        """
        裁剪工具描述：按工具块裁剪，保留前面（更相关）的工具。
        工具描述通常以空行分隔。
        """
        sections = text.split("\n\n")
        kept: list[str] = []
        accumulated = 0

        for section in sections:
            section_tokens = self.counter.count(section) + 2  # +2 for double newline
            if accumulated + section_tokens > budget:
                break
            kept.append(section)
            accumulated += section_tokens

        if not kept and sections:
            return self.counter.truncate(sections[0], budget)

        return "\n\n".join(kept)

    def _truncate_keep_tail(self, text: str, budget: int) -> str:
        """保留尾部（丢弃开头）的裁剪。"""
        tokens_count = self.counter.count(text)
        if tokens_count <= budget:
            return text

        # 从末尾反向截取
        # 粗略估算需要保留的字符比例
        ratio = budget / max(tokens_count, 1)
        start_char = int(len(text) * (1 - ratio))

        # 尝试在换行处截断
        newline_pos = text.find("\n", start_char)
        if newline_pos != -1 and newline_pos < start_char + 200:
            candidate = text[newline_pos + 1:]
        else:
            candidate = text[start_char:]

        # 验证并微调
        actual = self.counter.count(candidate)
        if actual > budget:
            candidate = self.counter.truncate(candidate, budget)

        return "[...已截断...]\n" + candidate if candidate != text else candidate

    def _emergency_trim(
        self,
        texts: dict[str, str],
        tokens: dict[str, int],
        flexible_items: list[tuple[str, ComponentPolicy]],
    ) -> tuple[dict[str, str], dict[str, int], list[str]]:
        """
        紧急裁剪：总量仍超预算时，从最低优先级开始清空。
        """
        warnings: list[str] = []
        total = sum(tokens.values())

        # 从最低优先级开始清空
        for comp_key, policy in reversed(flexible_items):
            if total <= self.total_input_budget:
                break
            if tokens.get(comp_key, 0) > 0:
                freed = tokens[comp_key]
                texts[comp_key] = ""
                tokens[comp_key] = 0
                total -= freed
                warnings.append(
                    f"[紧急裁剪] {comp_key} 已完全丢弃（释放 {freed} tokens）"
                )

        return texts, tokens, warnings
