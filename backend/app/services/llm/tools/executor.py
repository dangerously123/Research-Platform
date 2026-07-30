"""工具执行器：解析 LLM 输出中的工具调用、执行工具、返回结果。"""

import ast
import json
import re
from typing import Any

from app.services.llm.tools.registry import tool_registry


class ToolExecutor:
    """
    工具执行器。
    - 解析 LLM 输出中的 [TOOL_CALL: ...] 格式
    - 执行对应工具
    - 将结果格式化后返回
    - 支持多轮工具调用（LLM 可在一次回答中调多个工具）
    """

    # 匹配工具调用的正则
    TOOL_CALL_PATTERN = re.compile(
        r"\[TOOL_CALL:\s*(\w+)\((.*?)\)\]", re.DOTALL
    )

    async def execute_from_text(self, text: str) -> tuple[str, list[dict]]:
        """
        从 LLM 输出文本中提取并执行所有工具调用。

        Returns:
            tuple: (替换工具结果后的文本, 工具执行记录列表)
        """
        calls = self.TOOL_CALL_PATTERN.findall(text)
        if not calls:
            return text, []

        results_log = []
        result_text = text

        for tool_name, params_str in calls:
            result = await self._execute_single(tool_name, params_str)
            results_log.append({
                "tool": tool_name,
                "params": params_str,
                "result": result,
            })

            original_call = f"[TOOL_CALL: {tool_name}({params_str})]"
            formatted_result = self._format_result(tool_name, result)
            result_text = result_text.replace(original_call, formatted_result)

        return result_text, results_log

    async def execute_tool(self, tool_name: str, **kwargs) -> dict[str, Any]:
        """直接执行指定工具。"""
        tool = tool_registry.get(tool_name)
        if not tool:
            return {"error": f"未知工具: {tool_name}"}

        try:
            result = await tool.handler(**kwargs)
            return result
        except Exception as e:
            return {"error": f"工具执行失败: {str(e)}"}

    def has_tool_calls(self, text: str) -> bool:
        """检查文本中是否包含工具调用。"""
        return bool(self.TOOL_CALL_PATTERN.search(text))

    async def _execute_single(
        self, tool_name: str, params_str: str
    ) -> dict[str, Any]:
        """执行单个工具调用。"""
        tool = tool_registry.get(tool_name)
        if not tool:
            return {"error": f"未知工具: {tool_name}"}

        try:
            params = self._parse_params(params_str)
            result = await tool.handler(**params)
            return result
        except Exception as e:
            return {"error": f"执行失败: {str(e)}"}

    def _parse_params(self, params_str: str) -> dict:
        """解析工具参数字符串为字典。"""
        params_str = params_str.strip()
        if not params_str:
            return {}

        try:
            result = self._kwargs_to_dict(params_str)
            if result:
                return result
        except Exception:
            pass

        try:
            return json.loads(f"{{{params_str}}}")
        except Exception:
            pass

        return self._manual_parse(params_str)

    def _kwargs_to_dict(self, params_str: str) -> dict:
        """将 kwargs 字符串解析为 dict。"""
        result = {}
        parts = self._split_params(params_str)
        for part in parts:
            if "=" in part:
                key, val = part.split("=", 1)
                key = key.strip()
                val = val.strip()
                try:
                    result[key] = ast.literal_eval(val)
                except (ValueError, SyntaxError):
                    result[key] = val.strip("'\"")
        return result

    def _split_params(self, s: str) -> list[str]:
        """智能分割参数，处理括号和引号内的逗号。"""
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

    def _manual_parse(self, params_str: str) -> dict:
        """手动解析简单 key=value 参数。"""
        result = {}
        parts = self._split_params(params_str)
        for part in parts:
            if "=" in part:
                key, val = part.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'\"")
                try:
                    val = int(val)
                except ValueError:
                    try:
                        val = float(val)
                    except ValueError:
                        pass
                result[key] = val
        return result

    def _format_result(self, tool_name: str, result: dict) -> str:
        """格式化工具执行结果供展示。"""
        if "error" in result and result["error"]:
            return f"[工具 {tool_name} 执行失败: {result['error']}]"

        display = {k: v for k, v in result.items() if k != "error"}
        parts = []
        for k, v in display.items():
            if isinstance(v, float):
                parts.append(f"{k}: {v:.4g}")
            elif isinstance(v, list) and len(v) > 5:
                parts.append(f"{k}: [{v[0]}, ..., {v[-1]}] (共{len(v)}项)")
            else:
                parts.append(f"{k}: {v}")

        return f"[工具结果: {', '.join(parts)}]"


class SmartToolRouter:
    """
    智能工具路由器。

    预执行规则从 @tool 装饰器元数据自动加载，
    无需在此文件手动维护 if/elif 规则。

    两阶段工具调用策略：
    1. 预执行阶段：根据装饰器中的 pre_execute_pattern 自动匹配并执行
    2. 后执行阶段：对 LLM 回答中的工具调用进行解析和执行
    """

    def __init__(self):
        from app.services.llm.tools.intent_matcher import intent_matcher
        self.intent_matcher = intent_matcher
        self.executor = ToolExecutor()
        self._pre_execute_rules: list[dict] | None = None

    def _ensure_rules_loaded(self):
        """确保预执行规则已从装饰器元数据加载。"""
        if self._pre_execute_rules is not None:
            return
        try:
            from app.services.llm.tools.decorator import get_pre_execute_rules
            self._pre_execute_rules = get_pre_execute_rules()
        except ImportError:
            self._pre_execute_rules = []

    async def pre_execute(self, query: str) -> dict | None:
        """
        预执行阶段：遍历所有工具的 pre_execute 规则，
        匹配成功则直接执行工具。

        Returns:
            {"tool": str, "result": dict, "context_injection": str} 或 None
        """
        self._ensure_rules_loaded()

        for rule in self._pre_execute_rules:
            pattern = rule["pattern"]
            extractor = rule["extractor"]
            formatter = rule.get("formatter")
            tool_name = rule["tool_name"]

            try:
                match = re.search(pattern, query)
                if not match:
                    continue

                # 提取参数
                params = extractor(match)
                if not params:
                    continue

                # 验证是否为纯数学表达式（calculator 特殊处理）
                if tool_name == "calculator":
                    expr = params.get("expression", "")
                    if not re.match(r'^[\d\s\+\-\*\/\.\(\)\^%sqrtlogsincotan]+$', expr.replace(" ", "")):
                        continue

                # 执行工具
                result = await self.executor.execute_tool(tool_name, **params)
                if "error" in result and result["error"]:
                    continue

                # 格式化上下文注入
                context_injection = ""
                if formatter:
                    try:
                        context_injection = formatter(result)
                    except Exception:
                        context_injection = str(result)
                else:
                    context_injection = str(result)

                return {
                    "tool": tool_name,
                    "result": result,
                    "context_injection": context_injection,
                }
            except Exception:
                continue

        return None

    async def post_execute(self, llm_output: str) -> tuple[str, list[dict]]:
        """后执行阶段：处理 LLM 输出中的工具调用。"""
        return await self.executor.execute_from_text(llm_output)

    def build_enhanced_prompt(
        self,
        query: str,
        pre_result: dict | None = None,
    ) -> str:
        """
        构建增强版工具提示。
        如果有预执行结果，将其作为已知事实注入。
        """
        parts = []

        if pre_result:
            parts.append(
                f"[已知计算结果] 使用工具 {pre_result['tool']} 计算得到：\n"
                f"{pre_result['context_injection']}\n"
                f"请基于此结果用自然语言回答用户问题。"
            )
        else:
            tools_prompt = self.intent_matcher.get_relevant_tools_prompt(query)
            if tools_prompt:
                parts.append(tools_prompt)

        return "\n".join(parts)
