"""
工具调用准确率评测。

评测维度：
1. 工具选择准确率：给定问题，是否选择了正确的工具
2. 参数提取准确率：工具参数是否正确提取
3. 结果正确性：工具返回结果是否与期望一致
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.services.eval.base import EvalCase, EvalResult, EvalSuite, eval_runner, load_yaml_dataset
from app.services.llm.tools.registry import tool_registry

logger = logging.getLogger(__name__)

DATASET_DIR = Path(__file__).parent / "datasets"


class ToolCallEvalSuite(EvalSuite):
    """工具调用评测套件。"""

    name = "tool_call"
    description = "评测工具选择准确率、参数提取和结果正确性"

    async def load_cases(self) -> list[EvalCase]:
        """从 YAML 加载工具调用评测数据集。"""
        raw = load_yaml_dataset(DATASET_DIR / "tool_cases.yaml")
        cases = []
        for item in raw:
            cases.append(EvalCase(
                id=item["id"],
                query=item["query"],
                expected={
                    "tool": item["expected_tool"],
                    "params": item.get("expected_params", {}),
                    "result_contains": item.get("result_contains"),
                    "result_value": item.get("result_value"),
                },
                category=item.get("category", ""),
                tags=item.get("tags", []),
            ))
        return cases

    async def evaluate_case(self, case: EvalCase) -> EvalResult:
        """
        评测单条工具调用用例。

        评分规则：
        - 工具选择正确: +0.4
        - 参数提取正确: +0.3
        - 结果正确: +0.3
        """
        score = 0.0
        actual: dict = {}
        details: dict = {}

        expected_tool = case.expected["tool"]
        expected_params = case.expected.get("params", {})

        # 1. 工具选择评测（使用 IntentMatcher）
        from app.services.llm.tools.intent_matcher import intent_matcher
        matched = intent_matcher.match_tools(case.query, max_tools=3)
        matched_names = [t.name for t in matched]
        actual["matched_tools"] = matched_names

        tool_correct = expected_tool in matched_names
        if tool_correct:
            score += 0.4
            # 如果是第一个匹配的，额外加分
            if matched_names and matched_names[0] == expected_tool:
                score += 0.1
        details["tool_selection"] = {
            "correct": tool_correct,
            "expected": expected_tool,
            "actual_top3": matched_names,
        }

        # 2. 工具执行评测
        tool_def = tool_registry.get(expected_tool)
        if not tool_def:
            return EvalResult(
                case_id=case.id, passed=False, score=score,
                actual=actual, expected=case.expected,
                error=f"工具 {expected_tool} 未注册",
            )

        # 使用期望参数执行工具
        try:
            result = await tool_def.handler(**expected_params)
            actual["tool_result"] = result
        except Exception as e:
            return EvalResult(
                case_id=case.id, passed=False, score=score,
                actual=actual, expected=case.expected,
                error=f"工具执行失败: {e}",
            )

        # 3. 参数评测（SmartToolRouter 预执行提取）
        if expected_params:
            from app.services.llm.tools.executor import SmartToolRouter
            router = SmartToolRouter()
            pre_result = await router.pre_execute(case.query)

            if pre_result and pre_result["tool"] == expected_tool:
                score += 0.3
                details["param_extraction"] = {"correct": True, "method": "pre_execute"}
            else:
                details["param_extraction"] = {
                    "correct": False,
                    "pre_execute_result": pre_result["tool"] if pre_result else None,
                }

        # 4. 结果正确性检查
        result_correct = False
        if case.expected.get("result_value") is not None:
            expected_val = case.expected["result_value"]
            # 检查 result dict 中是否有匹配值
            for v in result.values():
                if isinstance(v, (int, float)) and isinstance(expected_val, (int, float)):
                    if abs(v - expected_val) < 0.01:
                        result_correct = True
                        break
                elif v == expected_val:
                    result_correct = True
                    break
        elif case.expected.get("result_contains"):
            keyword = case.expected["result_contains"]
            result_str = str(result)
            result_correct = keyword in result_str

        if result_correct:
            score += 0.3
        details["result_check"] = {"correct": result_correct}

        passed = score >= 0.7  # 70% 以上算通过
        return EvalResult(
            case_id=case.id,
            passed=passed,
            score=score,
            actual=actual,
            expected=case.expected,
            details=details,
        )


# 注册到全局运行器
eval_runner.register_suite(ToolCallEvalSuite())
