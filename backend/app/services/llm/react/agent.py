"""
ReAct Agent：Thought → Action → Observation 循环推理引擎。

核心机制：
1. LLM 输出 Thought（推理）和 Action（工具调用）
2. 系统执行 Action，将 Observation（结果）反馈给 LLM
3. LLM 基于 Observation 继续推理，决定下一步
4. 循环直到 LLM 输出 Final Answer 或达到最大轮数
5. 每轮有自检机制，判断回答是否满足用户需求

退出条件（任一满足即退出）：
- LLM 输出 [FINAL_ANSWER: ...]
- 达到最大循环轮数（默认5轮）
- 自检评分达到质量阈值（0.8）
- 连续2轮无新的 Action（LLM 已无需工具）
"""

import json
import re
import time
from dataclasses import dataclass, field
from typing import AsyncIterator

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm.adapters.base import LLMRequest, LLMResponse
from app.services.llm.gateway import LLMGateway
from app.services.llm.token_counter import TokenCounter
from app.services.llm.tools.executor import ToolExecutor
from app.services.llm.tools.registry import tool_registry


@dataclass
class ReActConfig:
    """ReAct 配置。"""
    max_iterations: int = 5            # 最大循环轮数
    quality_threshold: float = 0.8     # 自检质量阈值（达到即退出）
    enable_self_check: bool = True     # 是否启用自检
    max_tokens_per_step: int = 2048    # 每步 LLM 最大 Token
    timeout_seconds: int = 60          # 总超时时间
    allow_chain_tools: bool = True     # 是否允许链式工具调用
    model_context_window: int = 8192   # 模型上下文窗口大小
    provider: str = "openai"           # 模型供应商（用于 tokenizer 选择）


@dataclass
class ReActStep:
    """单步记录。"""
    iteration: int
    thought: str = ""
    action: str | None = None
    action_input: dict | None = None
    observation: str = ""
    is_final: bool = False


@dataclass
class ReActResult:
    """ReAct 执行结果。"""
    final_answer: str
    steps: list[ReActStep] = field(default_factory=list)
    total_iterations: int = 0
    exit_reason: str = ""              # max_iter / quality_met / final_answer / no_action / timeout
    quality_score: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    model_id: str = ""
    elapsed_ms: float = 0


# ReAct 系统 Prompt
REACT_SYSTEM_PROMPT = """你是一个能够使用工具解决问题的智能助手。请按照以下格式进行推理和行动：

思考步骤格式：
Thought: [你的推理过程，分析问题需要什么信息或计算]
Action: [TOOL_CALL: tool_name(param1=value1, param2=value2)]

当你收到工具执行结果后，继续推理：
Thought: [基于工具结果的进一步分析]
Action: [如果还需要其他工具调用]

当你认为已经收集到足够信息可以回答时：
Thought: [总结推理过程]
[FINAL_ANSWER: 你的最终回答]

重要规则：
- 每次只执行一个 Action
- 如果不需要工具，直接给出 [FINAL_ANSWER: ...]
- 回答必须准确、有依据
- 如果工具返回错误，尝试换一种方式或直接回答
"""


class ReActAgent:
    """
    ReAct 循环推理引擎。

    执行流程：
    ┌─────────────────────────────────────────┐
    │ 初始化：构建 System Prompt + 用户问题    │
    └───────────────────┬─────────────────────┘
                        │
    ┌───────────────────▼─────────────────────┐
    │ 第N轮循环（N ≤ max_iterations）          │
    │                                         │
    │ ① LLM 生成 Thought + Action             │
    │ ② 解析输出：                             │
    │    - 有 FINAL_ANSWER → 退出循环          │
    │    - 有 Action → 执行工具                │
    │    - 无 Action → 连续空Action计数+1      │
    │ ③ 执行工具，获得 Observation             │
    │ ④ 自检：评估当前信息是否足够回答         │
    │    - 质量 ≥ 阈值 → 让LLM生成最终回答    │
    │ ⑤ 将 Observation 追加到对话历史          │
    │ ⑥ 检查退出条件                          │
    └───────────────────┬─────────────────────┘
                        │
    ┌───────────────────▼─────────────────────┐
    │ 输出：最终回答 + 推理过程记录            │
    └─────────────────────────────────────────┘
    """

    # 解析模式
    THOUGHT_PATTERN = re.compile(r"Thought:\s*(.+?)(?=Action:|$|\[FINAL_ANSWER:)", re.DOTALL)
    ACTION_PATTERN = re.compile(r"\[TOOL_CALL:\s*(\w+)\((.*?)\)\]", re.DOTALL)
    FINAL_ANSWER_PATTERN = re.compile(r"\[FINAL_ANSWER:\s*(.*?)\]", re.DOTALL)

    def __init__(
        self,
        db: AsyncSession,
        redis: aioredis.Redis,
        config: ReActConfig | None = None,
    ):
        self.db = db
        self.redis = redis
        self.config = config or ReActConfig()
        self.gateway = LLMGateway(db=db, redis=redis)
        self.executor = ToolExecutor()
        # Token 计数器：用于每轮预算控制
        self.token_counter = TokenCounter.for_provider(
            self.config.provider, None
        )
        # 输入预算 = 上下文窗口 - 输出预留 - 安全边距
        self._input_budget = (
            self.config.model_context_window
            - self.config.max_tokens_per_step
            - 50  # 安全边距
        )
        # 工具规划器：每轮动态推荐工具
        from app.services.llm.react.tool_planner import ToolPlanner
        self.tool_planner = ToolPlanner()
        # 推理过程记忆：复用历史成功链路
        from app.services.llm.react.trace_memory import TraceMemory
        self.trace_memory = TraceMemory(redis=redis)

    async def run(
        self,
        query: str,
        context: str = "",
        tools_prompt: str = "",
    ) -> ReActResult:
        """
        执行 ReAct 循环。

        Args:
            query: 用户问题
            context: 额外上下文（RAG文档、记忆等）
            tools_prompt: 可用工具描述

        Returns:
            ReActResult 包含最终回答和推理过程
        """
        start_time = time.perf_counter()
        steps: list[ReActStep] = []
        total_input_tokens = 0
        total_output_tokens = 0
        model_id = ""
        no_action_count = 0

        # === 初始化工作记忆 ===
        from app.services.llm.react.working_memory import WorkingMemory
        working_mem = WorkingMemory()

        # === 检索推理链路记忆（复用历史成功路径）===
        trace_guidance = ""
        try:
            trace_result = await self.trace_memory.recall_trace(query)
            if trace_result:
                trace_guidance = trace_result["guidance"]
        except Exception:
            pass

        # 构建初始对话历史
        messages = self._build_initial_messages(query, context, tools_prompt)

        # 如果有历史链路参考，注入到对话中
        if trace_guidance:
            messages.append({"role": "system", "content": trace_guidance})

        for iteration in range(1, self.config.max_iterations + 1):
            step = ReActStep(iteration=iteration)

            # 超时检查
            elapsed = (time.perf_counter() - start_time) * 1000
            if elapsed > self.config.timeout_seconds * 1000:
                return self._build_result(
                    steps, "timeout", total_input_tokens, total_output_tokens,
                    model_id, elapsed, self._extract_best_answer(steps)
                )

            # ===== 动态工具推荐（每轮智能选择）=====
            completed_tools = [
                {"tool": s.action, "result": s.observation}
                for s in steps if s.action
            ]
            failed_tools = [
                s.action for s in steps
                if s.action and ("失败" in s.observation or "错误" in s.observation)
            ]
            last_obs = steps[-1].observation if steps else ""

            # 获取当前轮次的工具建议
            tool_suggestions = self.tool_planner.suggest_next_tool(
                query=query,
                completed_tools=completed_tools,
                last_observation=last_obs,
                failed_tools=failed_tools,
            )

            # 生成当前轮次的工具引导（注入 Prompt）
            tool_guidance = self.tool_planner.format_tool_guidance(
                suggestions=tool_suggestions,
                iteration=iteration,
                completed_tools=completed_tools,
            )
            if tool_guidance and iteration > 1:
                # 在后续轮次中追加动态工具建议
                messages.append({"role": "system", "content": tool_guidance})

            # ① 调用 LLM（预算控制：确保 messages 不超出上下文窗口）
            messages = self._trim_messages_to_budget(messages)
            prompt = self._messages_to_prompt(messages)
            try:
                response = await self.gateway.generate(
                    LLMRequest(
                        prompt=prompt,
                        max_tokens=self.config.max_tokens_per_step,
                        stream=False,
                    )
                )
            except Exception as e:
                step.thought = f"LLM 调用失败: {str(e)}"
                steps.append(step)
                break

            total_input_tokens += response.input_tokens
            total_output_tokens += response.output_tokens
            model_id = response.model_id
            llm_output = response.content

            # ② 解析输出
            thought, action_name, action_params, final_answer = self._parse_output(llm_output)
            step.thought = thought

            # 如果 LLM 没有输出 Action 但有预提取参数的建议，辅助纠正
            if not action_name and not final_answer and tool_suggestions:
                top_sug = tool_suggestions[0]
                if top_sug.pre_extracted_params and top_sug.confidence >= 0.8:
                    # 高置信度建议 + LLM 未自行调用 → 自动采纳建议
                    action_name = top_sug.tool_name
                    action_params = top_sug.pre_extracted_params
                    step.thought += f"\n[系统辅助] 自动采纳工具建议: {action_name}"

            # 检查是否有最终回答
            if final_answer:
                step.is_final = True
                steps.append(step)
                elapsed = (time.perf_counter() - start_time) * 1000

                # 保存成功的推理链路
                try:
                    await self.trace_memory.save_successful_trace(
                        query=query, steps=steps,
                        exit_reason="final_answer",
                        quality_score=self._assess_quality(query, steps),
                    )
                except Exception:
                    pass

                return self._build_result(
                    steps, "final_answer", total_input_tokens, total_output_tokens,
                    model_id, elapsed, final_answer
                )

            # 检查是否有 Action
            if not action_name:
                no_action_count += 1
                step.observation = "[无工具调用]"
                steps.append(step)

                # 连续2轮无Action → 将最后输出作为回答
                if no_action_count >= 2:
                    elapsed = (time.perf_counter() - start_time) * 1000
                    answer = thought or llm_output
                    return self._build_result(
                        steps, "no_action", total_input_tokens, total_output_tokens,
                        model_id, elapsed, answer
                    )

                # 追加到对话历史继续
                messages.append({"role": "assistant", "content": llm_output})
                messages.append({"role": "user", "content": "请继续推理，或给出 [FINAL_ANSWER: 你的回答]"})
                continue

            no_action_count = 0  # 有Action，重置计数

            # ③ 执行工具 + 结果验证
            step.action = action_name
            step.action_input = action_params
            observation = await self._execute_action(action_name, action_params)

            # 验证工具结果
            raw_result = await self.executor.execute_tool(action_name, **(action_params or {}))
            is_valid, validation_msg = self.tool_planner.validate_tool_result(
                action_name, action_params or {}, raw_result
            )

            if not is_valid:
                # 结果不合理，标记为异常并追加提示
                observation += f"\n⚠️ 结果验证: {validation_msg}"
                # 推荐替代工具
                alt_suggestions = self.tool_planner._get_alternatives({action_name}, query)
                if alt_suggestions:
                    alt_hint = f"建议尝试: {alt_suggestions[0].tool_name} ({alt_suggestions[0].reason})"
                    observation += f"\n{alt_hint}"

            step.observation = observation
            steps.append(step)

            # ④ 记录到工作记忆
            working_mem.record_step(
                iteration=iteration,
                thought=thought,
                action=action_name,
                observation=observation,
            )

            # ⑤ 自检（可选）
            if self.config.enable_self_check and iteration >= 2:
                quality = self._assess_quality(query, steps)
                if quality >= self.config.quality_threshold:
                    # 质量达标，要求 LLM 给出最终回答
                    # 使用工作记忆的结构化上下文（比原始对话历史更紧凑）
                    mem_context = working_mem.get_context_injection()
                    messages.append({"role": "assistant", "content": llm_output})
                    messages.append({
                        "role": "user",
                        "content": f"Observation: {observation}\n\n"
                                   f"{mem_context}\n\n"
                                   f"已收集到足够信息（质量评分:{quality:.2f}），请给出 [FINAL_ANSWER: 你的完整回答]"
                    })

                    # 再调一次 LLM 获取最终回答
                    messages = self._trim_messages_to_budget(messages)
                    final_prompt = self._messages_to_prompt(messages)
                    try:
                        final_response = await self.gateway.generate(
                            LLMRequest(prompt=final_prompt, max_tokens=self.config.max_tokens_per_step, stream=False)
                        )
                        total_input_tokens += final_response.input_tokens
                        total_output_tokens += final_response.output_tokens
                        _, _, _, final_ans = self._parse_output(final_response.content)
                        elapsed = (time.perf_counter() - start_time) * 1000
                        return self._build_result(
                            steps, "quality_met", total_input_tokens, total_output_tokens,
                            model_id, elapsed, final_ans or final_response.content, quality
                        )
                    except Exception:
                        pass

            # ⑥ 将 Observation 追加到对话历史（注入工作记忆上下文）
            mem_injection = working_mem.get_context_injection() if iteration >= 3 else ""
            messages.append({"role": "assistant", "content": llm_output})
            obs_msg = f"Observation: {observation}"
            if mem_injection:
                obs_msg += f"\n\n{mem_injection}"
            obs_msg += "\n\n请基于以上结果继续推理。"
            messages.append({"role": "user", "content": obs_msg})

        # 达到最大轮数 → 保存推理链路后返回
        elapsed = (time.perf_counter() - start_time) * 1000
        answer = self._extract_best_answer(steps)

        # 保存成功的推理链路到记忆
        try:
            has_tools = any(s.action for s in steps)
            if has_tools:
                await self.trace_memory.save_successful_trace(
                    query=query,
                    steps=steps,
                    exit_reason="max_iter",
                    quality_score=self._assess_quality(query, steps),
                )
        except Exception:
            pass

        return self._build_result(
            steps, "max_iter", total_input_tokens, total_output_tokens,
            model_id, elapsed, answer
        )

    async def run_stream(
        self,
        query: str,
        context: str = "",
        tools_prompt: str = "",
    ) -> AsyncIterator[dict]:
        """
        流式执行 ReAct 循环。
        每一步产生事件，前端可实时展示推理过程。

        Yields:
            {"type": "thought", "content": "...", "iteration": N}
            {"type": "action", "tool": "...", "params": {...}, "iteration": N}
            {"type": "observation", "content": "...", "iteration": N}
            {"type": "final_answer", "content": "...", "iterations": N, "exit_reason": "..."}
        """
        result = await self.run(query, context, tools_prompt)

        # 逐步输出推理过程
        for step in result.steps:
            if step.thought:
                yield {"type": "thought", "content": step.thought, "iteration": step.iteration}
            if step.action:
                yield {"type": "action", "tool": step.action, "params": step.action_input, "iteration": step.iteration}
            if step.observation:
                yield {"type": "observation", "content": step.observation, "iteration": step.iteration}

        # 最终回答
        yield {
            "type": "final_answer",
            "content": result.final_answer,
            "iterations": result.total_iterations,
            "exit_reason": result.exit_reason,
            "quality_score": result.quality_score,
        }

    # ==================== 内部方法 ====================

    def _build_initial_messages(
        self, query: str, context: str, tools_prompt: str
    ) -> list[dict]:
        """构建初始对话消息。"""
        system = REACT_SYSTEM_PROMPT

        if tools_prompt:
            system += f"\n\n可用工具：\n{tools_prompt}"

        messages = [{"role": "system", "content": system}]

        user_content = ""
        if context:
            user_content += f"参考资料：\n{context}\n\n"
        user_content += f"用户问题：{query}"

        messages.append({"role": "user", "content": user_content})
        return messages

    def _messages_to_prompt(self, messages: list[dict]) -> str:
        """将消息列表拼接为单一 Prompt 字符串。"""
        parts = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if role == "system":
                parts.append(f"[System]\n{content}")
            elif role == "user":
                parts.append(f"[User]\n{content}")
            elif role == "assistant":
                parts.append(f"[Assistant]\n{content}")
        return "\n\n".join(parts)

    def _trim_messages_to_budget(self, messages: list[dict]) -> list[dict]:
        """
        确保消息列表不超出输入预算。

        策略：
        1. 保留第一条 system 消息（不可裁剪）
        2. 保留最后 2 条消息（最近的上下文）
        3. 从中间部分（第2条起到倒数第3条）按时间从早到晚移除
        4. 如果仍超预算，对中间消息的 content 进行截断
        """
        total_tokens = self.token_counter.count_messages(messages)
        if total_tokens <= self._input_budget:
            return messages

        # 不能裁剪的部分
        if len(messages) <= 3:
            # 太少了无法裁剪，直接返回
            return messages

        # 分离：系统消息 + 中间可裁剪部分 + 最后2条保护
        system_msgs = [messages[0]] if messages[0]["role"] == "system" else []
        protected_tail = messages[-2:]
        middle = messages[len(system_msgs):-2]

        # 从最早的中间消息开始移除
        while middle:
            current_messages = system_msgs + middle + protected_tail
            current_tokens = self.token_counter.count_messages(current_messages)
            if current_tokens <= self._input_budget:
                return current_messages
            # 移除最早的中间消息
            middle.pop(0)

        # 中间全部移除后仍超预算 → 截断系统消息和保护尾部
        remaining = system_msgs + protected_tail
        total_tokens = self.token_counter.count_messages(remaining)
        if total_tokens <= self._input_budget:
            return remaining

        # 最后手段：截断保护尾部的 content
        for msg in protected_tail:
            if total_tokens <= self._input_budget:
                break
            original_tokens = self.token_counter.count(msg["content"])
            allowed = max(100, original_tokens - (total_tokens - self._input_budget))
            msg["content"] = self.token_counter.truncate(msg["content"], allowed)
            total_tokens = self.token_counter.count_messages(system_msgs + protected_tail)

        return system_msgs + protected_tail

    def _parse_output(self, text: str) -> tuple[str, str | None, dict | None, str | None]:
        """
        解析 LLM 输出。

        Returns:
            (thought, action_name, action_params, final_answer)
        """
        # 提取 Final Answer
        final_match = self.FINAL_ANSWER_PATTERN.search(text)
        if final_match:
            final_answer = final_match.group(1).strip()
            thought_match = self.THOUGHT_PATTERN.search(text)
            thought = thought_match.group(1).strip() if thought_match else ""
            return thought, None, None, final_answer

        # 提取 Thought
        thought_match = self.THOUGHT_PATTERN.search(text)
        thought = thought_match.group(1).strip() if thought_match else text.strip()

        # 提取 Action
        action_match = self.ACTION_PATTERN.search(text)
        if action_match:
            action_name = action_match.group(1)
            params_str = action_match.group(2)
            action_params = self._parse_action_params(params_str)
            return thought, action_name, action_params, None

        return thought, None, None, None

    def _parse_action_params(self, params_str: str) -> dict:
        """解析工具参数。"""
        import ast
        params = {}
        if not params_str.strip():
            return params

        # 逐个参数解析
        parts = self._split_params(params_str)
        for part in parts:
            if "=" in part:
                key, val = part.split("=", 1)
                key = key.strip()
                val = val.strip()
                try:
                    params[key] = ast.literal_eval(val)
                except (ValueError, SyntaxError):
                    params[key] = val.strip("'\"")
        return params

    def _split_params(self, s: str) -> list[str]:
        """智能分割参数字符串。"""
        parts = []
        depth = 0
        in_str = False
        str_char = ""
        current = ""
        for ch in s:
            if ch in ("'", '"') and not in_str:
                in_str = True
                str_char = ch
                current += ch
            elif ch == str_char and in_str:
                in_str = False
                current += ch
            elif ch in ("(", "[", "{") and not in_str:
                depth += 1
                current += ch
            elif ch in (")", "]", "}") and not in_str:
                depth -= 1
                current += ch
            elif ch == "," and depth == 0 and not in_str:
                parts.append(current.strip())
                current = ""
            else:
                current += ch
        if current.strip():
            parts.append(current.strip())
        return parts

    async def _execute_action(self, tool_name: str, params: dict | None) -> str:
        """执行工具并返回 Observation 文本。"""
        if not params:
            params = {}

        result = await self.executor.execute_tool(tool_name, **params)

        if "error" in result and result["error"]:
            return f"工具 {tool_name} 执行失败: {result['error']}"

        # 格式化为可读文本
        display = {k: v for k, v in result.items() if k != "error"}
        parts = []
        for k, v in display.items():
            if isinstance(v, float):
                parts.append(f"{k} = {v:.4g}")
            else:
                parts.append(f"{k} = {v}")
        return f"工具 {tool_name} 返回: {'; '.join(parts)}"

    def _assess_quality(self, query: str, steps: list[ReActStep]) -> float:
        """
        自检：评估当前收集的信息是否足够回答用户问题。

        评估维度：
        1. 工具调用是否成功返回了有效结果
        2. 结果是否与问题相关（关键词覆盖）
        3. 是否有足够的数据点
        """
        if not steps:
            return 0.0

        score = 0.0

        # 维度1：成功的工具调用数量
        successful_actions = [
            s for s in steps
            if s.action and "失败" not in s.observation and "错误" not in s.observation
        ]
        if successful_actions:
            score += min(0.4, len(successful_actions) * 0.2)

        # 维度2：observation 中是否包含数值结果
        has_numeric_result = any(
            re.search(r'\d+\.?\d*', s.observation) for s in steps if s.observation
        )
        if has_numeric_result:
            score += 0.3

        # 维度3：observation 是否包含查询中的关键词
        query_keywords = set(re.findall(r'[\u4e00-\u9fff]{2,}', query))
        all_observations = " ".join(s.observation for s in steps if s.observation)
        keyword_hits = sum(1 for kw in query_keywords if kw in all_observations)
        if query_keywords:
            score += min(0.3, (keyword_hits / len(query_keywords)) * 0.3)

        return min(1.0, score)

    def _extract_best_answer(self, steps: list[ReActStep]) -> str:
        """从推理步骤中提取最佳回答（达到最大轮数时使用）。"""
        # 优先取最后一步的 thought
        if steps:
            last = steps[-1]
            if last.thought and len(last.thought) > 20:
                return last.thought

        # 拼接所有 observation 作为回答
        observations = [s.observation for s in steps if s.observation and "失败" not in s.observation]
        if observations:
            return "根据查询结果：\n" + "\n".join(f"- {obs}" for obs in observations)

        return "抱歉，未能完成推理。请尝试重新描述您的问题。"

    def _build_result(
        self,
        steps: list[ReActStep],
        exit_reason: str,
        input_tokens: int,
        output_tokens: int,
        model_id: str,
        elapsed_ms: float,
        answer: str,
        quality: float = 0.0,
    ) -> ReActResult:
        """构建最终结果。"""
        return ReActResult(
            final_answer=answer,
            steps=steps,
            total_iterations=len(steps),
            exit_reason=exit_reason,
            quality_score=quality,
            total_input_tokens=input_tokens,
            total_output_tokens=output_tokens,
            model_id=model_id,
            elapsed_ms=elapsed_ms,
        )
