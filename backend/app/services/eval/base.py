"""
评测框架基类和运行器。

设计：
- EvalCase: 单条评测用例（输入 + 期望输出 + 判定逻辑）
- EvalResult: 单条评测结果
- EvalSuite: 评测套件（一组用例 + 聚合指标）
- EvalRunner: 运行器（加载数据集 → 执行 → 生成报告）
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EvalCase:
    """单条评测用例。"""
    id: str                               # 用例唯一标识
    query: str                            # 用户输入
    expected: dict[str, Any]              # 期望结果
    category: str = ""                    # 分类标签
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalResult:
    """单条评测结果。"""
    case_id: str
    passed: bool
    score: float = 0.0                    # 0-1 分数
    actual: dict[str, Any] = field(default_factory=dict)
    expected: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    duration_ms: float = 0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalSuiteReport:
    """评测套件运行报告。"""
    suite_name: str
    total_cases: int
    passed: int
    failed: int
    accuracy: float                       # passed / total
    avg_score: float
    avg_duration_ms: float
    results: list[EvalResult]
    failed_cases: list[EvalResult]
    run_at: str = ""
    duration_total_ms: float = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_name": self.suite_name,
            "total_cases": self.total_cases,
            "passed": self.passed,
            "failed": self.failed,
            "accuracy": round(self.accuracy, 4),
            "avg_score": round(self.avg_score, 4),
            "avg_duration_ms": round(self.avg_duration_ms, 1),
            "duration_total_ms": round(self.duration_total_ms, 1),
            "run_at": self.run_at,
            "failed_cases": [
                {"case_id": r.case_id, "error": r.error, "expected": r.expected, "actual": r.actual}
                for r in self.failed_cases
            ],
        }


class EvalSuite(ABC):
    """
    评测套件抽象基类。
    子类实现具体的评测逻辑。
    """

    name: str = "unnamed"
    description: str = ""

    @abstractmethod
    async def load_cases(self) -> list[EvalCase]:
        """加载评测用例。"""
        ...

    @abstractmethod
    async def evaluate_case(self, case: EvalCase) -> EvalResult:
        """执行单条评测。"""
        ...


class EvalRunner:
    """
    评测运行器。
    加载评测套件 → 逐条执行 → 生成报告。
    """

    def __init__(self):
        self._suites: dict[str, EvalSuite] = {}

    def register_suite(self, suite: EvalSuite) -> None:
        """注册评测套件。"""
        self._suites[suite.name] = suite

    def list_suites(self) -> list[dict[str, str]]:
        """列出已注册的评测套件。"""
        return [
            {"name": s.name, "description": s.description}
            for s in self._suites.values()
        ]

    async def run_suite(self, suite_name: str) -> EvalSuiteReport:
        """运行指定评测套件。"""
        suite = self._suites.get(suite_name)
        if not suite:
            raise ValueError(f"评测套件不存在: {suite_name}")

        logger.info(f"[Eval] 开始运行评测套件: {suite_name}")
        start = time.perf_counter()

        cases = await suite.load_cases()
        results: list[EvalResult] = []

        for case in cases:
            try:
                case_start = time.perf_counter()
                result = await suite.evaluate_case(case)
                result.duration_ms = (time.perf_counter() - case_start) * 1000
                results.append(result)
            except Exception as e:
                results.append(EvalResult(
                    case_id=case.id,
                    passed=False,
                    error=f"执行异常: {str(e)}",
                    expected=case.expected,
                ))

        total_ms = (time.perf_counter() - start) * 1000

        # 聚合指标
        passed = [r for r in results if r.passed]
        failed = [r for r in results if not r.passed]
        total = len(results)

        report = EvalSuiteReport(
            suite_name=suite_name,
            total_cases=total,
            passed=len(passed),
            failed=len(failed),
            accuracy=len(passed) / max(total, 1),
            avg_score=sum(r.score for r in results) / max(total, 1),
            avg_duration_ms=sum(r.duration_ms for r in results) / max(total, 1),
            results=results,
            failed_cases=failed,
            run_at=datetime.now(timezone.utc).isoformat(),
            duration_total_ms=total_ms,
        )

        logger.info(
            f"[Eval] 套件 {suite_name} 完成: "
            f"{report.passed}/{report.total_cases} 通过, "
            f"准确率 {report.accuracy:.1%}, "
            f"耗时 {total_ms:.0f}ms"
        )

        return report

    async def run_all(self) -> list[EvalSuiteReport]:
        """运行所有已注册的评测套件。"""
        reports = []
        for name in self._suites:
            report = await self.run_suite(name)
            reports.append(report)
        return reports


# 全局运行器实例
eval_runner = EvalRunner()


def load_yaml_dataset(file_path: str | Path) -> list[dict]:
    """从 YAML 文件加载评测数据集。"""
    import yaml
    path = Path(file_path)
    if not path.exists():
        logger.warning(f"[Eval] 数据集文件不存在: {path}")
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, list) else []
