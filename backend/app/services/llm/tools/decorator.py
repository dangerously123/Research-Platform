"""
工具装饰器框架：通过 @tool 装饰器实现零模板注册。

核心功能：
1. 从函数签名自动推断参数 JSON Schema（类型注解 + docstring）
2. 自动注册到 tool_registry
3. 内聚触发规则（triggers / trigger_patterns）
4. 内聚预执行规则（pre_execute_pattern）
5. 按目录自动发现所有 @tool 装饰函数

使用方式：
    from app.services.llm.tools.decorator import tool

    @tool(
        category="math",
        description="数学表达式计算器",
        triggers=["计算", "算一下"],
        trigger_patterns=[r"\\d+\\s*[\\+\\-\\*\\/]\\s*\\d+"],
        trigger_priority=10,
        requires_numbers=True,
        examples=["[TOOL_CALL: calculator(expression='2+3')]"],
        pre_execute_pattern=r"(?:计算|算)\\s*[:：]?\\s*(.+)",
        pre_execute_extractor=lambda m: {"expression": m.group(1).strip()},
        pre_execute_formatter=lambda r: f"{r.get('expression')} = {r.get('result')}",
    )
    async def calculator(expression: str) -> dict[str, Any]:
        '''
        安全的数学表达式计算器。

        Args:
            expression: 数学表达式，如 '2**10 + sqrt(144)'
        '''
        ...
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, get_type_hints

from app.services.llm.tools.registry import ToolDefinition, tool_registry

logger = logging.getLogger(__name__)


# ============================================================
# 全局注册表：收集所有 @tool 装饰的函数元数据
# ============================================================

@dataclass
class ToolMetadata:
    """@tool 装饰器收集的元数据。"""
    name: str
    description: str
    category: str
    handler: Callable[..., Awaitable[Any]]
    parameters: dict
    examples: list[str] = field(default_factory=list)

    # 触发规则（用于 IntentMatcher）
    triggers: list[str] = field(default_factory=list)
    trigger_patterns: list[str] = field(default_factory=list)
    trigger_priority: int = 5
    requires_numbers: bool = False

    # 预执行规则（用于 SmartToolRouter）
    pre_execute_pattern: str | None = None
    pre_execute_extractor: Callable | None = None
    pre_execute_formatter: Callable | None = None


# 全局元数据列表
_registered_tools: list[ToolMetadata] = []


def get_all_tool_metadata() -> list[ToolMetadata]:
    """获取所有已注册的工具元数据。"""
    return _registered_tools.copy()


# ============================================================
# @tool 装饰器
# ============================================================

def tool(
    category: str,
    description: str,
    triggers: list[str] | None = None,
    trigger_patterns: list[str] | None = None,
    trigger_priority: int = 5,
    requires_numbers: bool = False,
    examples: list[str] | None = None,
    pre_execute_pattern: str | None = None,
    pre_execute_extractor: Callable | None = None,
    pre_execute_formatter: Callable | None = None,
    name: str | None = None,
):
    """
    工具注册装饰器。

    Args:
        category: 工具分类（math / geo / datetime / text / data / custom）
        description: 功能描述（给 LLM 看，决定是否调用）
        triggers: 触发关键词列表（用户问题含任一关键词即推荐该工具）
        trigger_patterns: 触发正则模式列表（比关键词权重更高）
        trigger_priority: 优先级 0-10（越高越优先推荐）
        requires_numbers: 是否要求问题中必须含数字
        examples: 调用示例列表（给 LLM 学习格式）
        pre_execute_pattern: 预执行正则（匹配成功则直接执行，不等 LLM 决策）
        pre_execute_extractor: 从正则 match 中提取参数的函数 match → dict
        pre_execute_formatter: 格式化预执行结果为上下文注入文本 result → str
        name: 工具名称（默认使用函数名）
    """
    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        tool_name = name or func.__name__

        # 自动推断参数 Schema
        parameters = _infer_parameters_schema(func)

        # 自动生成示例（如果未提供）
        tool_examples = examples or [_generate_example(tool_name, parameters)]

        # 构建元数据
        metadata = ToolMetadata(
            name=tool_name,
            description=description,
            category=category,
            handler=func,
            parameters=parameters,
            examples=tool_examples,
            triggers=triggers or [],
            trigger_patterns=trigger_patterns or [],
            trigger_priority=trigger_priority,
            requires_numbers=requires_numbers,
            pre_execute_pattern=pre_execute_pattern,
            pre_execute_extractor=pre_execute_extractor,
            pre_execute_formatter=pre_execute_formatter,
        )

        # 注册到全局列表
        _registered_tools.append(metadata)

        # 立即注册到 tool_registry（保持向后兼容）
        tool_registry.register(ToolDefinition(
            name=tool_name,
            description=description,
            category=category,
            parameters=parameters,
            handler=func,
            examples=tool_examples,
        ))

        # 在函数上附加元数据标记
        func._tool_metadata = metadata
        return func

    return decorator


# ============================================================
# Schema 自动推断
# ============================================================

# Python 类型 → JSON Schema 类型映射
_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _infer_parameters_schema(func: Callable) -> dict:
    """
    从函数签名和 docstring 自动推断参数 JSON Schema。

    支持：
    - 类型注解 → JSON Schema type
    - 默认值 → 非 required
    - Google-style docstring Args 段 → description
    - list[float] → {"type": "array", "items": {"type": "number"}}
    """
    sig = inspect.signature(func)
    try:
        hints = get_type_hints(func)
    except Exception:
        hints = {}

    # 从 docstring 提取参数描述
    param_docs = _parse_docstring_args(func.__doc__ or "")

    properties: dict[str, dict] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        # 跳过 self, return
        if param_name in ("self", "cls"):
            continue

        # 获取类型
        type_hint = hints.get(param_name, param.annotation)
        json_type = _python_type_to_json_schema(type_hint)

        # 构建属性定义
        prop: dict[str, Any] = {}
        prop.update(json_type)

        # 添加描述
        if param_name in param_docs:
            prop["description"] = param_docs[param_name]

        properties[param_name] = prop

        # 判断是否必填（无默认值 = 必填）
        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required

    return schema


def _python_type_to_json_schema(type_hint) -> dict[str, Any]:
    """将 Python 类型注解转为 JSON Schema 类型描述。"""
    # 基础类型
    if type_hint in _TYPE_MAP:
        return {"type": _TYPE_MAP[type_hint]}

    # 处理 list[X] 类型
    origin = getattr(type_hint, "__origin__", None)
    if origin is list:
        args = getattr(type_hint, "__args__", ())
        if args:
            item_type = _python_type_to_json_schema(args[0])
            return {"type": "array", "items": item_type}
        return {"type": "array"}

    # 处理 dict 类型
    if origin is dict:
        return {"type": "object"}

    # 处理 Optional[X] (Union[X, None])
    if origin is type(int | None):
        args = getattr(type_hint, "__args__", ())
        non_none = [a for a in args if a is not type(None)]
        if non_none:
            return _python_type_to_json_schema(non_none[0])

    # inspect.Parameter.empty 或未知类型
    if type_hint is inspect.Parameter.empty:
        return {"type": "string"}

    return {"type": "string"}


def _parse_docstring_args(docstring: str) -> dict[str, str]:
    """
    从 Google-style docstring 中提取 Args 段的参数描述。

    示例输入:
        Args:
            expression: 数学表达式，如 '2+3'
            precision: 精度（可选，默认2位）

    返回: {"expression": "数学表达式，如 '2+3'", "precision": "精度（可选，默认2位）"}
    """
    result: dict[str, str] = {}
    if not docstring:
        return result

    # 查找 Args: 段
    args_match = re.search(r"Args:\s*\n(.*?)(?:\n\s*\n|\nReturns:|\nRaises:|\Z)", docstring, re.DOTALL)
    if not args_match:
        return result

    args_text = args_match.group(1)
    # 解析每个参数行
    for match in re.finditer(r"^\s+(\w+)\s*[:：]\s*(.+?)(?=\n\s+\w+\s*[:：]|\Z)", args_text, re.MULTILINE | re.DOTALL):
        param_name = match.group(1)
        param_desc = match.group(2).strip().replace("\n", " ").strip()
        # 清理多余空格
        param_desc = re.sub(r"\s+", " ", param_desc)
        result[param_name] = param_desc

    return result


def _generate_example(tool_name: str, parameters: dict) -> str:
    """自动生成调用示例。"""
    props = parameters.get("properties", {})
    required = parameters.get("required", [])

    params_parts = []
    for param_name, prop in props.items():
        ptype = prop.get("type", "string")
        if ptype == "string":
            params_parts.append(f"{param_name}='示例'")
        elif ptype == "integer":
            params_parts.append(f"{param_name}=1")
        elif ptype == "number":
            params_parts.append(f"{param_name}=1.0")
        elif ptype == "array":
            params_parts.append(f"{param_name}=[1, 2, 3]")
        elif ptype == "boolean":
            params_parts.append(f"{param_name}=True")
        else:
            params_parts.append(f"{param_name}=...")

        # 只展示必填参数
        if param_name not in required and len(params_parts) > 2:
            break

    return f"[TOOL_CALL: {tool_name}({', '.join(params_parts)})]"


# ============================================================
# 自动发现机制
# ============================================================

def auto_discover_tools(package_path: str = "app.services.llm.tools"):
    """
    自动扫描指定包下所有 *_tools.py 模块，导入它们以触发 @tool 装饰器注册。

    Args:
        package_path: 包的点分路径
    """
    try:
        package = importlib.import_module(package_path)
    except ImportError as e:
        logger.error(f"[Tools] 无法导入工具包 {package_path}: {e}")
        return

    package_dir = getattr(package, "__path__", None)
    if not package_dir:
        return

    count_before = len(_registered_tools)

    for importer, module_name, is_pkg in pkgutil.iter_modules(package_dir):
        if module_name.endswith("_tools") and not is_pkg:
            full_module = f"{package_path}.{module_name}"
            try:
                importlib.import_module(full_module)
            except Exception as e:
                logger.warning(f"[Tools] 加载模块 {full_module} 失败: {e}")

    count_after = len(_registered_tools)
    categories = set(m.category for m in _registered_tools)
    logger.info(
        f"[Tools] 自动发现完成: {count_after - count_before} 个新工具, "
        f"总计 {count_after} 个, 分类: {sorted(categories)}"
    )


def get_trigger_rules() -> list[dict]:
    """
    从所有已注册工具的元数据中生成触发规则列表。
    供 IntentMatcher 使用。

    Returns:
        [{"tool_name": str, "keywords": [...], "patterns": [...],
          "priority": int, "requires_numbers": bool}, ...]
    """
    rules = []
    for meta in _registered_tools:
        if meta.triggers or meta.trigger_patterns:
            rules.append({
                "tool_name": meta.name,
                "keywords": meta.triggers,
                "patterns": meta.trigger_patterns,
                "priority": meta.trigger_priority,
                "requires_numbers": meta.requires_numbers,
            })
    return rules


def get_pre_execute_rules() -> list[dict]:
    """
    从所有已注册工具的元数据中生成预执行规则列表。
    供 SmartToolRouter 使用。

    Returns:
        [{"tool_name": str, "pattern": str,
          "extractor": Callable, "formatter": Callable}, ...]
    """
    rules = []
    for meta in _registered_tools:
        if meta.pre_execute_pattern and meta.pre_execute_extractor:
            rules.append({
                "tool_name": meta.name,
                "pattern": meta.pre_execute_pattern,
                "extractor": meta.pre_execute_extractor,
                "formatter": meta.pre_execute_formatter,
            })
    return rules
