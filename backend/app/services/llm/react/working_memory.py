"""
ReAct 工作记忆管理器。

解决的问题：
1. 循环中 Prompt 越来越长（Token 爆炸）→ 中间结果周期性压缩
2. 关键事实容易被截断 → 维护独立的"事实板"
3. 工具结果散落在对话历史中 → 结构化存储供快速引用

设计：
- Scratchpad（草稿板）：存储当前推理链的关键中间结果
- Facts（事实板）：提取并维护已确认的事实
- Compression（压缩器）：每 N 轮对历史进行摘要压缩
"""

import re
from dataclasses import dataclass, field


@dataclass
class Fact:
    """已确认的事实。"""
    content: str             # 事实内容
    source: str              # 来源（工具名或推理）
    iteration: int           # 产生于第几轮
    confidence: float = 1.0  # 置信度


@dataclass
class ScratchpadEntry:
    """草稿板条目。"""
    iteration: int
    thought_summary: str     # 推理摘要
    action: str | None       # 执行的工具
    result_summary: str      # 结果摘要
    is_compressed: bool = False


class WorkingMemory:
    """
    ReAct 工作记忆。

    在推理循环中维护结构化的中间状态，
    解决纯 Prompt 堆叠导致的 Token 膨胀和信息丢失问题。
    """

    COMPRESS_EVERY_N = 3     # 每3轮压缩一次
    MAX_FACTS = 10           # 事实板最大容量
    MAX_SCRATCHPAD = 10      # 草稿板最大容量

    def __init__(self):
        self.facts: list[Fact] = []
        self.scratchpad: list[ScratchpadEntry] = []
        self.compressed_history: str = ""  # 压缩后的早期历史
        self._raw_observations: list[str] = []

    def record_step(
        self,
        iteration: int,
        thought: str,
        action: str | None,
        observation: str,
    ) -> None:
        """记录一步推理结果。"""
        # 加入草稿板
        entry = ScratchpadEntry(
            iteration=iteration,
            thought_summary=self._summarize_thought(thought),
            action=action,
            result_summary=self._summarize_observation(observation),
        )
        self.scratchpad.append(entry)
        self._raw_observations.append(observation)

        # 从 Observation 中提取事实
        new_facts = self._extract_facts(observation, action, iteration)
        self.facts.extend(new_facts)

        # 事实板容量控制
        if len(self.facts) > self.MAX_FACTS:
            # 保留置信度最高的
            self.facts.sort(key=lambda f: f.confidence, reverse=True)
            self.facts = self.facts[:self.MAX_FACTS]

        # 周期性压缩
        if len(self.scratchpad) >= self.COMPRESS_EVERY_N and len(self.scratchpad) % self.COMPRESS_EVERY_N == 0:
            self._compress()

    def get_context_injection(self) -> str:
        """
        生成注入 Prompt 的工作记忆上下文。
        比原始对话历史更紧凑且结构化。
        """
        parts = []

        # 压缩历史
        if self.compressed_history:
            parts.append(f"[早期推理摘要]\n{self.compressed_history}")

        # 事实板
        if self.facts:
            facts_text = "\n".join(
                f"  • {f.content} (来源:{f.source}, 第{f.iteration}轮)"
                for f in self.facts
            )
            parts.append(f"[已确认事实]\n{facts_text}")

        # 最近的草稿板（未压缩部分）
        recent = [s for s in self.scratchpad if not s.is_compressed]
        if recent:
            recent_text = "\n".join(
                f"  第{s.iteration}轮: {s.thought_summary}"
                + (f" → {s.action}() → {s.result_summary}" if s.action else "")
                for s in recent[-3:]  # 只展示最近3条
            )
            parts.append(f"[最近推理过程]\n{recent_text}")

        return "\n\n".join(parts)

    def get_facts_summary(self) -> str:
        """获取当前事实板的纯文本摘要。"""
        if not self.facts:
            return ""
        return "; ".join(f.content for f in self.facts)

    def has_fact_about(self, keyword: str) -> bool:
        """检查事实板中是否已包含某关键词相关的事实。"""
        return any(keyword in f.content for f in self.facts)

    def get_all_observations(self) -> list[str]:
        """获取所有原始 Observation。"""
        return self._raw_observations.copy()

    def _extract_facts(self, observation: str, action: str | None, iteration: int) -> list[Fact]:
        """从工具 Observation 中提取结构化事实。"""
        facts = []

        if not observation or "失败" in observation:
            return facts

        # 提取数值型结果
        # 格式: "key = value" 或 "key: value"
        kv_patterns = re.findall(r'(\w+)\s*[=:]\s*([\d.]+)', observation)
        for key, value in kv_patterns:
            # 过滤无意义的 key（如 id、count 等）
            if key.lower() in ("id", "count", "index"):
                continue
            fact = Fact(
                content=f"{key} = {value}",
                source=action or "推理",
                iteration=iteration,
                confidence=0.9,
            )
            facts.append(fact)

        # 提取描述性结果
        # 如 "北京到上海的直线距离约为 1068 公里"
        desc_patterns = [
            r'(.+(?:距离|时间|结果|平均|总和|中位数).+[\d.]+.+)',
            r'(.+(?:增长|下降|变化).+[\d.]+%?)',
        ]
        for pattern in desc_patterns:
            matches = re.findall(pattern, observation)
            for match in matches:
                if len(match) > 10 and len(match) < 100:
                    fact = Fact(
                        content=match.strip(),
                        source=action or "推理",
                        iteration=iteration,
                        confidence=0.85,
                    )
                    facts.append(fact)

        return facts[:3]  # 每步最多提取3个事实

    def _summarize_thought(self, thought: str) -> str:
        """压缩 Thought 为一句话摘要。"""
        if len(thought) <= 50:
            return thought
        # 取第一句话
        first_sentence = re.split(r'[。！？\n]', thought)[0]
        if len(first_sentence) > 80:
            return first_sentence[:77] + "..."
        return first_sentence

    def _summarize_observation(self, observation: str) -> str:
        """压缩 Observation 为关键结果。"""
        if len(observation) <= 40:
            return observation
        # 提取数值结果
        numbers = re.findall(r'[\w]+\s*=\s*[\d.]+', observation)
        if numbers:
            return "; ".join(numbers[:3])
        return observation[:37] + "..."

    def _compress(self) -> None:
        """压缩早期草稿板内容为摘要。"""
        # 将前 N-2 条标记为已压缩并生成摘要
        uncompressed = [s for s in self.scratchpad if not s.is_compressed]
        if len(uncompressed) <= 2:
            return

        to_compress = uncompressed[:-2]  # 保留最近2条不压缩
        summary_parts = []
        for entry in to_compress:
            entry.is_compressed = True
            line = f"第{entry.iteration}轮"
            if entry.action:
                line += f": {entry.action}() → {entry.result_summary}"
            else:
                line += f": {entry.thought_summary}"
            summary_parts.append(line)

        new_summary = "; ".join(summary_parts)
        if self.compressed_history:
            self.compressed_history += "; " + new_summary
        else:
            self.compressed_history = new_summary

        # 控制压缩历史长度
        if len(self.compressed_history) > 500:
            self.compressed_history = self.compressed_history[-500:]
