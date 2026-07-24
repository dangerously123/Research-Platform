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
            # 执行工具
            result = await self._execute_single(tool_name, params_str)
            results_log.append({
                "tool": tool_name,
                "params": params_str,
                "result": result,
            })

            # 替换原文中的工具调用为结果
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

        # 尝试解析为 Python kwargs 格式: key1=val1, key2=val2
        try:
            # 构造一个 dict 字面量来安全解析
            # "expression='2+3', numbers=[1,2,3]" → {"expression": "2+3", "numbers": [1,2,3]}
            fake_call = f"dict({params_str})"
            result = ast.literal_eval(
                fake_call.replace("dict(", "{").rstrip(")")  + "}"
                if "=" not in params_str
                else self._kwargs_to_dict_str(params_str)
            )
            return result
        except Exception:
            pass

        # 备用方案：尝试 JSON 格式
        try:
            return json.loads(f"{{{params_str}}}")
        except Exception:
            pass

        # 最终备用：简单的 key=value 逐个解析
        return self._manual_parse(params_str)

    def _kwargs_to_dict_str(self, params_str: str) -> str:
        """将 kwargs 字符串转为可 eval 的 dict 字符串。"""
        # 这里用安全方式解析
        result = {}
        # 分割参数（处理嵌套逗号）
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
        return json.dumps(result)

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
                # 尝试转数字
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

        # 移除 error 键
        display = {k: v for k, v in result.items() if k != "error"}
        # 简洁格式化
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

    实现两阶段工具调用策略：
    1. 预执行阶段：对高置信度的简单计算类问题，直接执行工具，
       将结果注入 Prompt 作为"已知事实"，让 LLM 基于结果生成自然语言回答。
    2. 后执行阶段：对 LLM 回答中的工具调用进行解析和执行。

    优势：
    - 预执行避免了 LLM 自行调用格式错误的问题
    - 结果作为事实注入，LLM 能更好地组织自然语言回答
    """

    def __init__(self):
        from app.services.llm.tools.intent_matcher import intent_matcher
        self.intent_matcher = intent_matcher
        self.executor = ToolExecutor()

    async def pre_execute(self, query: str) -> dict | None:
        """
        预执行阶段：尝试直接从问题中提取参数并执行工具。

        Returns:
            {"tool": str, "result": dict, "context_injection": str} 或 None
        """
        # 尝试高置信度的直接执行
        result = await self._try_direct_execution(query)
        if result:
            return result
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

        # 如果有预执行结果，注入为已知事实
        if pre_result:
            parts.append(
                f"[已知计算结果] 使用工具 {pre_result['tool']} 计算得到：\n"
                f"{pre_result['context_injection']}\n"
                f"请基于此结果用自然语言回答用户问题。"
            )
        else:
            # 注入相关工具描述
            tools_prompt = self.intent_matcher.get_relevant_tools_prompt(query)
            if tools_prompt:
                parts.append(tools_prompt)

        return "\n".join(parts)

    async def _try_direct_execution(self, query: str) -> dict | None:
        """
        尝试直接从问题中提取参数执行工具。
        只对高置信度、参数可明确提取的场景执行。
        """
        # 规则 1：简单数学表达式 "计算 3.14 * 25"
        math_match = re.search(
            r"(?:计算|算|求)\s*[:：]?\s*(.+)",
            query,
        )
        if math_match:
            expr = math_match.group(1).strip()
            # 检查是否为纯数学表达式
            if re.match(r'^[\d\s\+\-\*\/\.\(\)\^%sqrtlogsincotan]+$', expr.replace(" ", "")):
                result = await self.executor.execute_tool("calculator", expression=expr)
                if "error" not in result or not result["error"]:
                    return {
                        "tool": "calculator",
                        "result": result,
                        "context_injection": f"{expr} = {result.get('result')}",
                    }

        # 规则 2：城市距离 "北京到上海多远"
        city_dist_match = re.search(
            r"([\u4e00-\u9fff]{2,4})\s*(?:到|离|距|至)\s*([\u4e00-\u9fff]{2,4})\s*(?:多远|距离|几公里|多少公里)",
            query,
        )
        if city_dist_match:
            city1, city2 = city_dist_match.group(1), city_dist_match.group(2)
            result = await self.executor.execute_tool("city_distance", city1=city1, city2=city2)
            if "error" not in result:
                return {
                    "tool": "city_distance",
                    "result": result,
                    "context_injection": f"{city1}到{city2}的直线距离约为 {result.get('distance_km')} 公里 ({result.get('distance_miles')} 英里)",
                }

        # 规则 3：当前时间 "现在几点"
        if re.search(r"(现在|当前|今天).*(几点|时间|日期|星期)", query):
            result = await self.executor.execute_tool("current_time", timezone_offset=8)
            return {
                "tool": "current_time",
                "result": result,
                "context_injection": f"当前时间: {result.get('datetime')} ({result.get('weekday')})",
            }

        # 规则 4：日期差 含两个日期的问题
        date_match = re.findall(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})", query)
        if len(date_match) >= 2 and ("相隔" in query or "间隔" in query or "多少天" in query or "几天" in query):
            d1 = date_match[0].replace("/", "-")
            d2 = date_match[1].replace("/", "-")
            result = await self.executor.execute_tool("date_difference", date1=d1, date2=d2)
            if "error" not in result:
                return {
                    "tool": "date_difference",
                    "result": result,
                    "context_injection": f"{d1} 到 {d2} 相隔 {result.get('days')} 天（约 {result.get('weeks')} 周）",
                }

        # 规则 5：百分比变化 "从1000到1500增长了多少"
        change_match = re.search(
            r"从\s*(\d+\.?\d*)\s*(?:到|变为?|增[长加]到|降?[低到])\s*(\d+\.?\d*)",
            query,
        )
        if change_match and ("增" in query or "变" in query or "涨" in query or "降" in query or "跌" in query):
            old_val = float(change_match.group(1))
            new_val = float(change_match.group(2))
            result = await self.executor.execute_tool(
                "percentage_change", old_value=old_val, new_value=new_val
            )
            if "error" not in result or not result.get("error"):
                return {
                    "tool": "percentage_change",
                    "result": result,
                    "context_injection": f"从 {old_val} 到 {new_val}，{result.get('direction')} {abs(result.get('change_percent', 0))}%",
                }

        # 规则 6：平均值/求和 含数字列表
        numbers_in_query = re.findall(r"\d+\.?\d*", query)
        if len(numbers_in_query) >= 3:
            nums = [float(n) for n in numbers_in_query]
            if "平均" in query or "均值" in query:
                result = await self.executor.execute_tool("mean", numbers=nums)
                if "error" not in result or not result.get("error"):
                    return {
                        "tool": "mean",
                        "result": result,
                        "context_injection": f"{nums} 的平均值为 {result.get('mean')}",
                    }
            elif "求和" in query or "总和" in query or "加起来" in query:
                result = await self.executor.execute_tool("sum", numbers=nums)
                return {
                    "tool": "sum",
                    "result": result,
                    "context_injection": f"{nums} 的总和为 {result.get('sum')}",
                }

        # 规则 7：单位转换 "100公里等于多少英里"
        unit_match = re.search(
            r"(\d+\.?\d*)\s*(公里|千米|英里|公斤|千克|磅|摄氏度|华氏度|GB|MB|TB|万)\s*(?:等于|是|换算|转换).*?(公里|千米|英里|公斤|千克|磅|摄氏度|华氏度|GB|MB|TB|万|元)",
            query,
        )
        if unit_match:
            value = float(unit_match.group(1))
            from_u = self._normalize_unit(unit_match.group(2))
            to_u = self._normalize_unit(unit_match.group(3))
            if from_u and to_u:
                result = await self.executor.execute_tool(
                    "unit_convert", value=value, from_unit=from_u, to_unit=to_u
                )
                if "error" not in result:
                    return {
                        "tool": "unit_convert",
                        "result": result,
                        "context_injection": f"{value} {from_u} = {result.get('result')} {to_u}",
                    }

        return None

    def _normalize_unit(self, unit_str: str) -> str:
        """标准化单位名称。"""
        mapping = {
            "公里": "km", "千米": "km", "英里": "mile",
            "公斤": "kg", "千克": "kg", "磅": "lb",
            "摄氏度": "celsius", "华氏度": "fahrenheit",
            "GB": "gb", "MB": "mb", "TB": "tb",
            "万": "wan", "元": "rmb",
        }
        return mapping.get(unit_str, unit_str.lower())
