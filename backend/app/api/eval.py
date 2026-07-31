"""评测系统 API：触发评测、查看结果。"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from app.services.auth.dependencies import get_current_user
from app.services.permission.middleware import require_admin

router = APIRouter()

# 评测超时时间（秒）
EVAL_TIMEOUT_SECONDS = 120


@router.get("/suites")
async def list_eval_suites(
    current_user: dict = Depends(get_current_user),
    _admin=Depends(require_admin),
):
    """列出所有可用的评测套件（管理员）。"""
    from app.services.eval.base import eval_runner
    import app.services.eval.tool_eval  # noqa: F401
    import app.services.eval.intent_eval  # noqa: F401

    return {"suites": eval_runner.list_suites()}


# 注意：/run-all 必须在 /run/{suite_name} 之前定义，
# 否则 FastAPI 会将 "all" 匹配为 suite_name 路径参数。
@router.post("/run-all")
async def run_all_evals(
    current_user: dict = Depends(get_current_user),
    _admin=Depends(require_admin),
):
    """运行所有评测套件（管理员，带超时保护）。"""
    from app.services.eval.base import eval_runner
    import app.services.eval.tool_eval  # noqa: F401
    import app.services.eval.intent_eval  # noqa: F401

    try:
        reports = await asyncio.wait_for(
            eval_runner.run_all(),
            timeout=EVAL_TIMEOUT_SECONDS * 2,
        )
        return {
            "total_suites": len(reports),
            "results": [r.to_dict() for r in reports],
        }
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"评测超时（>{EVAL_TIMEOUT_SECONDS * 2}秒），建议逐个套件运行",
        )


@router.post("/run/{suite_name}")
async def run_eval_suite(
    suite_name: str,
    current_user: dict = Depends(get_current_user),
    _admin=Depends(require_admin),
):
    """运行指定评测套件（管理员，带超时保护）。"""
    from app.services.eval.base import eval_runner
    import app.services.eval.tool_eval  # noqa: F401
    import app.services.eval.intent_eval  # noqa: F401

    try:
        report = await asyncio.wait_for(
            eval_runner.run_suite(suite_name),
            timeout=EVAL_TIMEOUT_SECONDS,
        )
        return report.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"评测超时（>{EVAL_TIMEOUT_SECONDS}秒），请减少用例数或拆分执行",
        )
