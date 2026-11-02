"""地理计算小工具：距离、方位、格式化、坐标系约定。

说明：高德 Web 服务返回的经纬度是 GCJ-02（火星坐标系），本 Skill 全程直接
使用 GCJ-02，不做 WGS-84 转换，避免二次偏移；只在展示时说明坐标系。
"""
from __future__ import annotations

import math
import re
from typing import Iterable, Optional, Sequence, Tuple

EARTH_RADIUS_M = 6371008.8

# 市区路网绕行系数：直线距离 -> 实际路网距离的经验倍数
ROUTE_FACTOR = {"walking": 1.25, "bicycling": 1.20, "driving": 1.35, "transit": 1.30}
# 各交通方式的平均速度（米/秒），用于估算耗时
MODE_SPEED_MPS = {"walking": 1.25, "bicycling": 3.6, "driving": 8.5, "transit": 6.5}
MODE_LABEL = {"walking": "步行", "bicycling": "骑行", "driving": "驾车", "transit": "公交"}

_LNGLAT_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)\s*$")


def parse_lnglat(value) -> Optional[Tuple[float, float]]:
    """解析 "lng,lat" / (lng, lat) / [lng, lat]，失败返回 None。"""
    if value is None:
        return None
    if isinstance(value, (tuple, list)) and len(value) >= 2:
        try:
            return float(value[0]), float(value[1])
        except (TypeError, ValueError):
            return None
    text = str(value).strip()
    m = _LNGLAT_RE.match(text)
    if not m:
        return None
    lng, lat = float(m.group(1)), float(m.group(2))
    if not (-180.0 <= lng <= 180.0 and -90.0 <= lat <= 90.0):
        return None
    return lng, lat


def format_lnglat(lng: float, lat: float, precision: int = 6) -> str:
    """高德接口要求的 "lng,lat" 字符串（经度在前）。"""
    return f"{lng:.{precision}f},{lat:.{precision}f}"


def haversine_m(a: Sequence[float], b: Sequence[float]) -> float:
    """两点球面距离（米）。参数为 (lng, lat)。"""
    lng1, lat1 = float(a[0]), float(a[1])
    lng2, lat2 = float(b[0]), float(b[1])
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lng2 - lng1)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def bearing_deg(a: Sequence[float], b: Sequence[float]) -> float:
    """a -> b 的方位角（0=正北，顺时针，度）。"""
    lng1, lat1 = math.radians(float(a[0])), math.radians(float(a[1]))
    lng2, lat2 = math.radians(float(b[0])), math.radians(float(b[1]))
    dlng = lng2 - lng1
    y = math.sin(dlng) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlng)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def offset_lnglat(lng: float, lat: float, distance_m: float, bearing: float) -> Tuple[float, float]:
    """从 (lng, lat) 出发，沿 bearing 方位移动 distance_m 米后的坐标（小范围近似）。"""
    dlat = distance_m * math.cos(math.radians(bearing)) / 111320.0
    dlng = distance_m * math.sin(math.radians(bearing)) / (111320.0 * max(0.2, math.cos(math.radians(lat))))
    return lng + dlng, lat + dlat


def estimate_route(straight_m: float, mode: str) -> Tuple[float, float]:
    """无路径规划时的兜底估算，返回 (距离米, 耗时秒)。"""
    factor = ROUTE_FACTOR.get(mode, 1.3)
    speed = MODE_SPEED_MPS.get(mode, 1.25)
    distance = max(1.0, straight_m * factor)
    duration = distance / speed
    if mode == "transit":
        duration += 300.0  # 候车 + 步行换乘
    elif mode == "driving":
        duration += 120.0  # 起步与红绿灯
    return distance, duration


def format_distance(meters: Optional[float], approx: bool = False) -> str:
    prefix = "约 " if approx else ""
    if meters is None:
        return "距离未知"
    if meters < 1000:
        return f"{prefix}{int(round(meters / 10.0) * 10)} 米"
    return f"{prefix}{meters / 1000.0:.1f} 公里"


def format_minutes(seconds: Optional[float], approx: bool = False) -> str:
    prefix = "约 " if approx else ""
    if seconds is None:
        return "耗时未知"
    minutes = int(round(seconds / 60.0))
    if minutes < 1:
        minutes = 1
    if minutes < 60:
        return f"{prefix}{minutes} 分钟"
    hours, rest = divmod(minutes, 60)
    if rest == 0:
        return f"{prefix}{hours} 小时"
    return f"{prefix}{hours} 小时 {rest} 分钟"


def walk_minutes(meters: Optional[float]) -> Optional[int]:
    """按 1.25 m/s 估算步行分钟数（展示用，与路径规划结果无关）。"""
    if meters is None:
        return None
    return max(1, int(round(meters / 1.25 / 60.0)))


def normalize_city_name(name: Optional[str]) -> Optional[str]:
    """把「杭州」「杭州市」「浙江省杭州市」统一成高德常用的城市名。"""
    if not name:
        return None
    text = str(name).strip()
    for suffix in ("特别行政区", "自治州", "地区", "盟"):
        if text.endswith(suffix) and len(text) > len(suffix):
            return text
    if text.endswith("市") or text.endswith("县"):
        return text
    if len(text) <= 4 and text.endswith(("州", "京", "海", "渝", "津", "安", "阳", "都", "庆", "沙")):
        return text + "市"
    return text
