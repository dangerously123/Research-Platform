"""Token 计数器单元测试。"""

import pytest

from app.services.llm.token_counter import TokenCounter, count_tokens


class TestTokenCounter:
    """测试 TokenCounter 核心功能。"""

    def test_default_counter_creation(self):
        counter = TokenCounter.default()
        assert counter is not None

    def test_count_empty_string(self):
        counter = TokenCounter.default()
        assert counter.count("") == 0

    def test_count_english_text(self):
        counter = TokenCounter.default()
        tokens = counter.count("Hello, world!")
        assert tokens > 0
        assert tokens < 10

    def test_count_chinese_text(self):
        counter = TokenCounter.default()
        tokens = counter.count("你好世界")
        assert tokens > 0

    def test_truncate_within_limit(self):
        counter = TokenCounter.default()
        text = "short text"
        result = counter.truncate(text, max_tokens=100)
        assert result == text

    def test_truncate_long_text(self):
        counter = TokenCounter.default()
        text = "Hello world! " * 100
        result = counter.truncate(text, max_tokens=10)
        assert counter.count(result) <= 10

    def test_count_messages(self):
        counter = TokenCounter.default()
        messages = [
            {"role": "system", "content": "You are a helper."},
            {"role": "user", "content": "Hi"},
        ]
        tokens = counter.count_messages(messages)
        assert tokens > 0

    def test_module_level_count_tokens(self):
        """测试模块级便捷函数。"""
        result = count_tokens("hello")
        assert result > 0


class TestTokenCounterProviders:
    """测试不同 provider 的计数器。"""

    def test_openai_provider(self):
        counter = TokenCounter.for_provider("openai")
        tokens = counter.count("Hello")
        assert tokens > 0

    def test_wenxin_provider_fallback(self):
        counter = TokenCounter.for_provider("wenxin")
        tokens = counter.count("你好世界测试文本")
        assert tokens > 0

    def test_unknown_provider(self):
        counter = TokenCounter.for_provider("unknown_provider")
        tokens = counter.count("test")
        assert tokens > 0
