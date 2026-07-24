"""工具管理 API：列出可用工具、手动执行工具。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.services.auth.dependencies import get_current_user
from app.services.llm.tools.registry import tool_registry
from app.services.llm.tools.executor import ToolExecutor

router = APIRouter()


class ToolInfo(BaseModel):
    name: str
    description: str
    category: str
    parameters: dict
    examples: list[str] = []


class ExecuteToolRequest(BaseModel):
    tool_name: str
    params: dict = {}


@router.get("", response_model=list[ToolInfo])
async def list_tools(
    category: str | None = None,
    current_user: dict = Depends(get_current_user),
):
    """列出所有可用工具。"""
    if category:
        tools = tool_registry.list_by_category(category)
    else:
        tools = tool_registry.list_all()

    return [
        ToolInfo(
            name=t.name,
            description=t.description,
            category=t.category,
            parameters=t.parameters,
            examples=t.examples,
        )
        for t in tools
    ]


@router.get("/categories")
async def list_categories(
    current_user: dict = Depends(get_current_user),
):
    """列出工具分类。"""
    return {"categories": tool_registry.get_categories()}


@router.post("/execute")
async def execute_tool(
    request: ExecuteToolRequest,
    current_user: dict = Depends(get_current_user),
):
    """手动执行指定工具（用于调试和直接调用）。"""
    executor = ToolExecutor()
    result = await executor.execute_tool(request.tool_name, **request.params)
    return {"tool": request.tool_name, "result": result}
