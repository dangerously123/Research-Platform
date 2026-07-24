"""地理位置工具集：坐标计算、距离、地理编码等。"""

import math
from typing import Any

from app.services.llm.tools.registry import ToolDefinition, tool_registry


async def haversine_distance(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> dict[str, Any]:
    """计算两个经纬度坐标之间的距离（Haversine公式）。"""
    R = 6371  # 地球平均半径（公里）

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance_km = R * c

    return {
        "from": {"lat": lat1, "lon": lon1},
        "to": {"lat": lat2, "lon": lon2},
        "distance_km": round(distance_km, 2),
        "distance_miles": round(distance_km * 0.621371, 2),
    }


async def coordinate_to_dms(lat: float, lon: float) -> dict[str, Any]:
    """将十进制经纬度转换为度分秒(DMS)格式。"""
    def decimal_to_dms(decimal: float, is_lat: bool) -> str:
        direction = ("N" if decimal >= 0 else "S") if is_lat else ("E" if decimal >= 0 else "W")
        decimal = abs(decimal)
        degrees = int(decimal)
        minutes = int((decimal - degrees) * 60)
        seconds = ((decimal - degrees) * 60 - minutes) * 60
        return f"{degrees}°{minutes}'{seconds:.2f}\"{direction}"

    return {
        "decimal": {"lat": lat, "lon": lon},
        "dms": {
            "lat": decimal_to_dms(lat, True),
            "lon": decimal_to_dms(lon, False),
        },
    }


async def midpoint(lat1: float, lon1: float, lat2: float, lon2: float) -> dict[str, Any]:
    """计算两点之间的地理中点。"""
    lat1_r, lon1_r = math.radians(lat1), math.radians(lon1)
    lat2_r, lon2_r = math.radians(lat2), math.radians(lon2)

    bx = math.cos(lat2_r) * math.cos(lon2_r - lon1_r)
    by = math.cos(lat2_r) * math.sin(lon2_r - lon1_r)

    mid_lat = math.atan2(
        math.sin(lat1_r) + math.sin(lat2_r),
        math.sqrt((math.cos(lat1_r) + bx) ** 2 + by ** 2)
    )
    mid_lon = lon1_r + math.atan2(by, math.cos(lat1_r) + bx)

    return {
        "midpoint": {
            "lat": round(math.degrees(mid_lat), 6),
            "lon": round(math.degrees(mid_lon), 6),
        },
        "from": {"lat": lat1, "lon": lon1},
        "to": {"lat": lat2, "lon": lon2},
    }


async def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> dict[str, Any]:
    """计算从点A到点B的方位角（度）。"""
    lat1_r, lon1_r = math.radians(lat1), math.radians(lon1)
    lat2_r, lon2_r = math.radians(lat2), math.radians(lon2)
    dlon = lon2_r - lon1_r

    x = math.sin(dlon) * math.cos(lat2_r)
    y = (math.cos(lat1_r) * math.sin(lat2_r) -
         math.sin(lat1_r) * math.cos(lat2_r) * math.cos(dlon))

    initial_bearing = math.atan2(x, y)
    bearing_deg = (math.degrees(initial_bearing) + 360) % 360

    # 方向描述
    directions = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]
    idx = round(bearing_deg / 45) % 8

    return {
        "bearing_degrees": round(bearing_deg, 2),
        "direction": directions[idx],
        "from": {"lat": lat1, "lon": lon1},
        "to": {"lat": lat2, "lon": lon2},
    }


# 常用城市坐标库
CITY_COORDINATES = {
    "北京": (39.9042, 116.4074),
    "上海": (31.2304, 121.4737),
    "广州": (23.1291, 113.2644),
    "深圳": (22.5431, 114.0579),
    "杭州": (30.2741, 120.1551),
    "成都": (30.5728, 104.0668),
    "武汉": (30.5928, 114.3055),
    "南京": (32.0603, 118.7969),
    "西安": (34.3416, 108.9398),
    "重庆": (29.5630, 106.5516),
    "天津": (39.3434, 117.3616),
    "苏州": (31.2990, 120.5853),
    "长沙": (28.2282, 112.9388),
    "郑州": (34.7466, 113.6254),
    "东京": (35.6762, 139.6503),
    "首尔": (37.5665, 126.9780),
    "纽约": (40.7128, -74.0060),
    "伦敦": (51.5074, -0.1278),
    "巴黎": (48.8566, 2.3522),
    "悉尼": (-33.8688, 151.2093),
}


async def get_city_location(city_name: str) -> dict[str, Any]:
    """获取城市的经纬度坐标。"""
    coords = CITY_COORDINATES.get(city_name)
    if coords:
        return {
            "city": city_name,
            "lat": coords[0],
            "lon": coords[1],
            "found": True,
        }
    # 模糊匹配
    for name, coord in CITY_COORDINATES.items():
        if city_name in name or name in city_name:
            return {"city": name, "lat": coord[0], "lon": coord[1], "found": True}
    return {"city": city_name, "found": False, "error": "未找到该城市坐标"}


async def city_distance(city1: str, city2: str) -> dict[str, Any]:
    """计算两个城市之间的直线距离。"""
    loc1 = await get_city_location(city1)
    loc2 = await get_city_location(city2)

    if not loc1.get("found") or not loc2.get("found"):
        return {"error": f"无法获取城市坐标: {city1 if not loc1.get('found') else city2}"}

    dist = await haversine_distance(loc1["lat"], loc1["lon"], loc2["lat"], loc2["lon"])
    return {
        "city1": city1,
        "city2": city2,
        "distance_km": dist["distance_km"],
        "distance_miles": dist["distance_miles"],
    }


def register_geo_tools():
    """注册所有地理工具。"""
    tools = [
        ToolDefinition(
            name="haversine_distance",
            description="计算两个经纬度坐标之间的距离（公里和英里）",
            category="geo",
            parameters={
                "type": "object",
                "properties": {
                    "lat1": {"type": "number", "description": "起点纬度"},
                    "lon1": {"type": "number", "description": "起点经度"},
                    "lat2": {"type": "number", "description": "终点纬度"},
                    "lon2": {"type": "number", "description": "终点经度"},
                },
                "required": ["lat1", "lon1", "lat2", "lon2"],
            },
            handler=haversine_distance,
            examples=["[TOOL_CALL: haversine_distance(lat1=39.9, lon1=116.4, lat2=31.2, lon2=121.5)]"],
        ),
        ToolDefinition(
            name="get_city_location",
            description="获取城市的经纬度坐标（支持国内主要城市和部分国际城市）",
            category="geo",
            parameters={
                "type": "object",
                "properties": {
                    "city_name": {"type": "string", "description": "城市名称，如'北京'、'上海'"},
                },
                "required": ["city_name"],
            },
            handler=get_city_location,
            examples=["[TOOL_CALL: get_city_location(city_name='深圳')]"],
        ),
        ToolDefinition(
            name="city_distance",
            description="计算两个城市之间的直线距离",
            category="geo",
            parameters={
                "type": "object",
                "properties": {
                    "city1": {"type": "string", "description": "城市1名称"},
                    "city2": {"type": "string", "description": "城市2名称"},
                },
                "required": ["city1", "city2"],
            },
            handler=city_distance,
            examples=["[TOOL_CALL: city_distance(city1='北京', city2='上海')]"],
        ),
        ToolDefinition(
            name="coordinate_to_dms",
            description="将十进制经纬度转换为度分秒(DMS)格式",
            category="geo",
            parameters={
                "type": "object",
                "properties": {
                    "lat": {"type": "number", "description": "纬度（十进制）"},
                    "lon": {"type": "number", "description": "经度（十进制）"},
                },
                "required": ["lat", "lon"],
            },
            handler=coordinate_to_dms,
            examples=["[TOOL_CALL: coordinate_to_dms(lat=39.9042, lon=116.4074)]"],
        ),
        ToolDefinition(
            name="bearing",
            description="计算从A点到B点的方位角和方向",
            category="geo",
            parameters={
                "type": "object",
                "properties": {
                    "lat1": {"type": "number", "description": "起点纬度"},
                    "lon1": {"type": "number", "description": "起点经度"},
                    "lat2": {"type": "number", "description": "终点纬度"},
                    "lon2": {"type": "number", "description": "终点经度"},
                },
                "required": ["lat1", "lon1", "lat2", "lon2"],
            },
            handler=bearing,
            examples=["[TOOL_CALL: bearing(lat1=39.9, lon1=116.4, lat2=31.2, lon2=121.5)]"],
        ),
    ]
    for t in tools:
        tool_registry.register(t)
