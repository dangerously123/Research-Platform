"""文本处理工具集：字数统计、编码转换、文本分析等。"""

import hashlib
import json
import re
from typing import Any
from urllib.parse import quote, unquote

from app.services.llm.tools.registry import ToolDefinition, tool_registry


async def word_count(text: str) -> dict[str, Any]:
    """统计文本的字数、字符数、行数等。"""
    lines = text.split("\n")
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    english_words = len(re.findall(r"[a-zA-Z]+", text))
    return {
        "total_chars": len(text),
        "chinese_chars": chinese_chars,
        "english_words": english_words,
        "lines": len(lines),
        "non_empty_lines": len([l for l in lines if l.strip()]),
    }


async def json_format(text: str) -> dict[str, Any]:
    """格式化 JSON 字符串（美化输出）。"""
    try:
        data = json.loads(text)
        formatted = json.dumps(data, indent=2, ensure_ascii=False)
        return {"formatted": formatted, "valid": True}
    except json.JSONDecodeError as e:
        return {"error": str(e), "valid": False}


async def url_encode(text: str) -> dict[str, Any]:
    """URL 编码。"""
    return {"original": text, "encoded": quote(text)}


async def url_decode(text: str) -> dict[str, Any]:
    """URL 解码。"""
    return {"original": text, "decoded": unquote(text)}


async def hash_text(text: str, algorithm: str = "md5") -> dict[str, Any]:
    """计算文本哈希值。"""
    algos = {"md5": hashlib.md5, "sha1": hashlib.sha1, "sha256": hashlib.sha256}
    if algorithm not in algos:
        return {"error": f"不支持的算法: {algorithm}，可选: md5/sha1/sha256"}
    h = algos[algorithm](text.encode()).hexdigest()
    return {"text": text[:50], "algorithm": algorithm, "hash": h}


async def unit_convert(value: float, from_unit: str, to_unit: str) -> dict[str, Any]:
    """常用单位转换。"""
    conversions = {
        ("km", "mile"): 0.621371, ("mile", "km"): 1.60934,
        ("kg", "lb"): 2.20462, ("lb", "kg"): 0.453592,
        ("m", "ft"): 3.28084, ("ft", "m"): 0.3048,
        ("celsius", "fahrenheit"): lambda v: v * 9/5 + 32,
        ("fahrenheit", "celsius"): lambda v: (v - 32) * 5/9,
        ("cm", "inch"): 0.393701, ("inch", "cm"): 2.54,
        ("l", "gallon"): 0.264172, ("gallon", "l"): 3.78541,
        ("mb", "gb"): 1/1024, ("gb", "mb"): 1024,
        ("gb", "tb"): 1/1024, ("tb", "gb"): 1024,
        ("rmb", "wan"): 1/10000, ("wan", "rmb"): 10000,
    }
    key = (from_unit.lower(), to_unit.lower())
    if key not in conversions:
        available = ", ".join(f"{a}→{b}" for a, b in conversions.keys())
        return {"error": f"不支持 {from_unit}→{to_unit}，可用: {available}"}

    factor = conversions[key]
    if callable(factor):
        result = factor(value)
    else:
        result = value * factor

    return {
        "value": value, "from": from_unit, "to": to_unit,
        "result": round(result, 4),
    }


def register_text_tools():
    """注册文本处理工具。"""
    tools = [
        ToolDefinition(
            name="word_count",
            description="统计文本字数（中文字符数、英文单词数、行数等）",
            category="text",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string", "description": "要统计的文本"}},
                "required": ["text"],
            },
            handler=word_count,
            examples=["[TOOL_CALL: word_count(text='Hello 你好世界')]"],
        ),
        ToolDefinition(
            name="json_format",
            description="格式化JSON字符串（美化输出），并验证是否为有效JSON",
            category="text",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string", "description": "JSON字符串"}},
                "required": ["text"],
            },
            handler=json_format,
            examples=["[TOOL_CALL: json_format(text='{\"name\":\"test\"}')]"],
        ),
        ToolDefinition(
            name="hash_text",
            description="计算文本的哈希值（MD5/SHA1/SHA256）",
            category="text",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要计算哈希的文本"},
                    "algorithm": {"type": "string", "description": "算法: md5/sha1/sha256"},
                },
                "required": ["text"],
            },
            handler=hash_text,
            examples=["[TOOL_CALL: hash_text(text='hello', algorithm='sha256')]"],
        ),
        ToolDefinition(
            name="unit_convert",
            description="常用单位转换（长度/重量/温度/存储/货币单位等）",
            category="text",
            parameters={
                "type": "object",
                "properties": {
                    "value": {"type": "number", "description": "数值"},
                    "from_unit": {"type": "string", "description": "原单位"},
                    "to_unit": {"type": "string", "description": "目标单位"},
                },
                "required": ["value", "from_unit", "to_unit"],
            },
            handler=unit_convert,
            examples=["[TOOL_CALL: unit_convert(value=100, from_unit='km', to_unit='mile')]"],
        ),
    ]
    for t in tools:
        tool_registry.register(t)
