"""
精确 Token 计数器。

支持多种模型的 Tokenizer：
- OpenAI 系模型：使用 tiktoken
- 本地/其他模型：根据 provider 选择合适的编码策略

提供统一的 count / truncate 接口，供预算分配器和其他模块调用。
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class TokenCounter:
    """
    精确 Token 计数器。

    使用策略：
    - OpenAI / Qwen / 通用模型 → tiktoken cl100k_base 编码
    - 本地模型（ollama/vllm）→ 尝试 tiktoken，失败则回退到估算
    - 文心 → 中文粗略估算（百度未公开 tokenizer）

    用法：
        counter = TokenCounter.for_provider("openai")
        token_count = counter.count("你好世界")
        truncated = counter.truncate("很长的文本...", max_tokens=100)
    """

    def __init__(self, encoder=None, fallback_mode: str = "chinese"):
        """
        Args:
            encoder: tiktoken Encoding 实例，或 None（使用估算模式）
            fallback_mode: 估算模式 "chinese"（中文为主）或 "english"（英文为主）
        """
        self._encoder = encoder
        self._fallback_mode = fallback_mode

    @classmethod
    def for_provider(cls, provider: str, model_name: str | None = None) -> "TokenCounter":
        """
        根据 provider 创建对应的计数器。

        Args:
            provider: 模型供应商（openai, qwen, ollama, vllm, wenxin）
            model_name: 可选的具体模型名称
        """
        if provider in ("openai", "qwen", "ollama", "vllm"):
            encoder = _get_tiktoken_encoder(model_name)
            if encoder:
                return cls(encoder=encoder)
            # tiktoken 不可用时回退
            return cls(encoder=None, fallback_mode="chinese")
        elif provider == "wenxin":
            # 文心没有公开的 tokenizer，使用中文估算
            return cls(encoder=None, fallback_mode="chinese")
        else:
            return cls(encoder=None, fallback_mode="chinese")

    @classmethod
    def default(cls) -> "TokenCounter":
        """创建默认计数器（尝试 tiktoken，不可用则回退估算）。"""
        encoder = _get_tiktoken_encoder(None)
        if encoder:
            return cls(encoder=encoder)
        return cls(encoder=None, fallback_mode="chinese")

    def count(self, text: str) -> int:
        """
        计算文本的 Token 数量。

        Args:
            text: 输入文本

        Returns:
            Token 数量
        """
        if not text:
            return 0

        if self._encoder:
            try:
                return len(self._encoder.encode(text))
            except Exception:
                pass

        # 回退到估算
        return self._estimate_tokens(text)

    def count_messages(self, messages: list[dict]) -> int:
        """
        计算消息列表的总 Token 数。
        每条消息额外计算 role 标记开销（约4 token/消息）。

        Args:
            messages: [{"role": "...", "content": "..."}]

        Returns:
            总 Token 数
        """
        total = 0
        for msg in messages:
            # 每条消息的结构开销（role + 分隔符）
            total += 4
            total += self.count(msg.get("content", ""))
        # 最终的分隔 token
        total += 2
        return total

    def truncate(self, text: str, max_tokens: int) -> str:
        """
        将文本截断到指定 Token 数以内。

        Args:
            text: 输入文本
            max_tokens: 最大 Token 数

        Returns:
            截断后的文本
        """
        if not text or max_tokens <= 0:
            return ""

        current = self.count(text)
        if current <= max_tokens:
            return text

        if self._encoder:
            try:
                tokens = self._encoder.encode(text)
                truncated_tokens = tokens[:max_tokens]
                return self._encoder.decode(truncated_tokens)
            except Exception:
                pass

        # 回退到字符级截断
        return self._char_truncate(text, max_tokens)

    def truncate_messages(
        self, messages: list[dict], max_tokens: int, keep_last_n: int = 2
    ) -> list[dict]:
        """
        截断消息列表以满足 Token 预算。
        保留最后 keep_last_n 条消息不动，从前面开始移除。

        Args:
            messages: 消息列表
            max_tokens: 最大 Token 预算
            keep_last_n: 至少保留最后 N 条消息

        Returns:
            截断后的消息列表
        """
        if not messages:
            return []

        total = self.count_messages(messages)
        if total <= max_tokens:
            return messages

        # 保护最后 N 条
        protected = messages[-keep_last_n:] if keep_last_n > 0 else []
        removable = messages[:-keep_last_n] if keep_last_n > 0 else messages[:]

        # 从最早的消息开始移除
        while removable and self.count_messages(removable + protected) > max_tokens:
            removable.pop(0)

        return removable + protected

    def _estimate_tokens(self, text: str) -> int:
        """
        Token 估算（无精确 tokenizer 时使用）。

        策略：
        - 中文字符：约 1.5 字符 / token
        - 英文单词：约 1.3 word / token（即 ~4 字符 / token）
        - 数字/符号：约 2 字符 / token
        """
        if not text:
            return 0

        # 分离中文和非中文部分
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]", text))
        non_chinese = len(text) - chinese_chars

        # 中文：约 1.5 字/token；非中文：约 4 字符/token
        chinese_tokens = chinese_chars / 1.5
        non_chinese_tokens = non_chinese / 4.0

        return int(chinese_tokens + non_chinese_tokens) + 1

    def _char_truncate(self, text: str, max_tokens: int) -> str:
        """基于字符估算的截断。"""
        # 反向计算大约需要多少字符
        ratio = len(text) / max(self.count(text), 1)
        target_chars = int(max_tokens * ratio * 0.9)  # 留 10% 余量
        if target_chars >= len(text):
            return text
        return text[:target_chars]


@lru_cache(maxsize=4)
def _get_tiktoken_encoder(model_name: str | None):
    """
    获取 tiktoken 编码器（带缓存）。
    如果 tiktoken 未安装则返回 None。
    """
    try:
        import tiktoken
    except ImportError:
        return None

    if model_name:
        try:
            return tiktoken.encoding_for_model(model_name)
        except KeyError:
            pass

    # 默认使用 cl100k_base（覆盖 GPT-4, GPT-3.5, 大多数现代模型）
    try:
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


# ============================================================
# 模块级便捷函数
# ============================================================

_default_counter: TokenCounter | None = None


def get_token_counter() -> TokenCounter:
    """获取全局默认 Token 计数器（单例）。"""
    global _default_counter
    if _default_counter is None:
        _default_counter = TokenCounter.default()
    return _default_counter


def count_tokens(text: str) -> int:
    """快捷函数：计算文本 Token 数。"""
    return get_token_counter().count(text)


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """快捷函数：截断文本到指定 Token 数。"""
    return get_token_counter().truncate(text, max_tokens)
