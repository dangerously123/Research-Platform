"""
意图识别评测。

评测维度：
1. 是否正确判断需要工具
2. 工具推荐是否准确
3. 直接回答 vs 工具调用的路由决策
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.services.eval.base import EvalCase, EvalResult, EvalSuite, eval_runner, load_yaml_dataset

logger = logging.getLogger(__name__)

DATASET_DIR = Path(__file__).parent / "datasets"


class IntentEvalSuite(EvalSuite):
    """意图识别评测套件。"""

    name = "intent"
    description = "评测意图分类准确率和工具路由决策"

    async def load_cases(self) -> list[EvalCase]:
        """从 YAML 加载意图评测数据集。"""
        raw = load_yaml_dataset(DATASET_DIR / "intent_cases.yaml")
        cases = []
        for item in raw:
            cases.append(EvalCase(
                id=item["id"],
                query=item["query"],
                expected={
                    "needs_tool": item["needs_tool"],
                    "expected_tools": item.get("expected_tools", []),
                    "category": item.get("category", ""),
                },
                category=item.get("category", ""),
                tags=item.get("tags", []),
            ))
        return cases

    async def evaluate_case(self, case: EvalCase) -> EvalResult:
        """
        评测单条意图用例。

        评分规则：
        - 是否需要工具判断正确: +0.5
        - 推荐的工具包含期望工具: +0.5
        """
        score = 0.0
        actual: dict = {}
        details: dict = {}

        needs_tool_expected = case.expected["needs_tool"]
        expected_tools = case.expected.get("expected_tools", [])

        # 使用 IntentMatcher 判断
        from app.services.llm.tools.intent_matcher import intent_matcher

        should_use = intent_matcher.should_use_tools(case.query)
        actual["should_use_tools"] = should_use

        # 1. 是否需要工具判断
        tool_decision_correct = should_use == needs_tool_expected
        if tool_decision_correct:
            score += 0.5
        details["tool_decision"] = {
            "correct": tool_decision_correct,
            "expected": needs_tool_expected,
            "actual": should_use,
        }

        # 2. 工具推荐准确率
        if needs_tool_expected and expected_tools:
            matched = intent_matcher.match_tools(case.query, max_tools=5)
            matched_names = [t.name for t in matched]
            actual["matched_tools"] = matched_names

            # 检查期望工具是否在推荐列表中
            hits = [t for t in expected_tools if t in matched_names]
            if hits:
                tool_score = len(hits) / len(expected_tools)
                score += 0.5 * tool_score
            details["tool_matching"] = {
                "expected": expected_tools,
                "actual": matched_names,
                "hits": hits,
            }
        elif not needs_tool_expected:
            # 不需要工具且判断正确，直接满分
            if tool_decision_correct:
                score += 0.5

        passed = score >= 0.7
        return EvalResult(
            case_id=case.id,
            passed=passed,
            score=score,
            actual=actual,
            expected=case.expected,
            details=details,
        )


# 注册到全局运行器
eval_runner.register_suite(IntentEvalSuite())
