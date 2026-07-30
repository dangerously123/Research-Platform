"""文本处理工具集：字数统计、编码转换、文本分析、单位换算等。"""

import hashlib
import json
import re
from typing import Any
from urllib.parse import quote, unquote

from app.services.llm.tools.decorator import tool


# ============================================================
# 文本分析
# ============================================================

@tool(
    category="text",
    description="统计文本字数（中文字符数、英文单词数、行数等）",
    triggers=["字数", "多少字", "字符数", "几个字"],
    trigger_priority=6,
    examples=["[TOOL_CALL: word_count(text='Hello 你好世界')]"],
)
async def word_count(text: str) -> dict[str, Any]:
    """
    统计文本的字数、字符数、行数等。

    Args:
        text: 要统计的文本
    """
    lines = text.split("\n")
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    english_words = len(re.findall(r"[a-zA-Z]+", text))
    return {
        "total_chars": len(text),
        "chinese_chars": chinese_chars,
        "english_words": english_words,
        "lines": len(lines),
        "non_empty_lines": len([line for line in lines if line.strip()]),
    }


@tool(
    category="text",
    description="格式化JSON字符串（美化输出），并验证是否为有效JSON",
    triggers=["格式化JSON", "JSON格式化", "美化JSON"],
    trigger_patterns=[r'\{.*".*".*:.*\}'],
    trigger_priority=6,
    examples=["[TOOL_CALL: json_format(text='{\"name\":\"test\"}')]"],
)
async def json_format(text: str) -> dict[str, Any]:
    """
    格式化 JSON 字符串（美化输出）。

    Args:
        text: JSON字符串
    """
    try:
        data = json.loads(text)
        formatted = json.dumps(data, indent=2, ensure_ascii=False)
        return {"formatted": formatted, "valid": True}
    except json.JSONDecodeError as e:
        return {"error": str(e), "valid": False}


# ============================================================
# 编码与哈希
# ============================================================

@tool(
    category="text",
    description="对文本进行URL编码",
    triggers=["URL编码", "url编码", "编码"],
    trigger_priority=5,
    examples=["[TOOL_CALL: url_encode(text='你好世界')]"],
)
async def url_encode(text: str) -> dict[str, Any]:
    """
    URL 编码。

    Args:
        text: 要编码的文本
    """
    return {"original": text, "encoded": quote(text)}


@tool(
    category="text",
    description="对URL编码的文本进行解码",
    triggers=["URL解码", "url解码", "解码"],
    trigger_priority=5,
    examples=["[TOOL_CALL: url_decode(text='%E4%BD%A0%E5%A5%BD')]"],
)
async def url_decode(text: str) -> dict[str, Any]:
    """
    URL 解码。

    Args:
        text: URL编码的文本
    """
    return {"original": text, "decoded": unquote(text)}


@tool(
    category="text",
    description="计算文本的哈希值（MD5/SHA1/SHA256）",
    triggers=["MD5", "SHA", "哈希", "hash", "md5", "sha256"],
    trigger_priority=7,
    examples=["[TOOL_CALL: hash_text(text='hello', algorithm='sha256')]"],
)
async def hash_text(text: str, algorithm: str = "md5") -> dict[str, Any]:
    """
    计算文本哈希值。

    Args:
        text: 要计算哈希的文本
        algorithm: 算法: md5/sha1/sha256，默认md5
    """
    algos = {"md5": hashlib.md5, "sha1": hashlib.sha1, "sha256": hashlib.sha256}
    if algorithm not in algos:
        return {"error": f"不支持的算法: {algorithm}，可选: md5/sha1/sha256"}
    h = algos[algorithm](text.encode()).hexdigest()
    return {"text": text[:50], "algorithm": algorithm, "hash": h}


# ============================================================
# 单位换算
# ============================================================

@tool(
    category="text",
    description="常用单位转换（长度/重量/温度/存储/货币单位等）",
    triggers=["转换", "换算", "等于多少", "是多少"],
    trigger_patterns=[
        r"\d+\s*(公里|千米|英里|km|mile)",
        r"\d+\s*(公斤|千克|磅|kg|lb)",
        r"\d+\s*(摄氏度|华氏度|℃|°F)",
        r"\d+\s*(GB|MB|TB|gb|mb|tb)",
        r"\d+\s*万",
    ],
    trigger_priority=8,
    requires_numbers=True,
    examples=["[TOOL_CALL: unit_convert(value=100, from_unit='km', to_unit='mile')]"],
    pre_execute_pattern=r"(\d+\.?\d*)\s*(公里|千米|英里|公斤|千克|磅|摄氏度|华氏度|GB|MB|TB|万)\s*(?:等于|是|换算|转换).*?(公里|千米|英里|公斤|千克|磅|摄氏度|华氏度|GB|MB|TB|万|元)",
    pre_execute_extractor=lambda m: {
        "value": float(m.group(1)),
        "from_unit": _normalize_unit(m.group(2)),
        "to_unit": _normalize_unit(m.group(3)),
    },
    pre_execute_formatter=lambda r: f"{r.get('value')} {r.get('from')} = {r.get('result')} {r.get('to')}",
)
async def unit_convert(value: float, from_unit: str, to_unit: str) -> dict[str, Any]:
    """
    常用单位转换。

    Args:
        value: 数值
        from_unit: 原单位
        to_unit: 目标单位
    """
    conversions = {
        ("km", "mile"): 0.621371, ("mile", "km"): 1.60934,
        ("kg", "lb"): 2.20462, ("lb", "kg"): 0.453592,
        ("m", "ft"): 3.28084, ("ft", "m"): 0.3048,
        ("celsius", "fahrenheit"): lambda v: v * 9 / 5 + 32,
        ("fahrenheit", "celsius"): lambda v: (v - 32) * 5 / 9,
        ("cm", "inch"): 0.393701, ("inch", "cm"): 2.54,
        ("l", "gallon"): 0.264172, ("gallon", "l"): 3.78541,
        ("mb", "gb"): 1 / 1024, ("gb", "mb"): 1024,
        ("gb", "tb"): 1 / 1024, ("tb", "gb"): 1024,
        ("rmb", "wan"): 1 / 10000, ("wan", "rmb"): 10000,
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


# ============================================================
# 模块级辅助函数（供预执行规则使用）
# ============================================================

def _normalize_unit(unit_str: str) -> str:
    """标准化单位名称。"""
    mapping = {
        "公里": "km", "千米": "km", "英里": "mile",
        "公斤": "kg", "千克": "kg", "磅": "lb",
        "摄氏度": "celsius", "华氏度": "fahrenheit",
        "GB": "gb", "MB": "mb", "TB": "tb",
        "万": "wan", "元": "rmb",
    }
    return mapping.get(unit_str, unit_str.lower())
