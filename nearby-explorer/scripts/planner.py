"""路径规划与「怎么去」文案，以及高德 URI 跳转链接。

四种方式：
    步行 /v3/direction/walking
    骑行 /v4/direction/bicycling
    公交 /v3/direction/transit/integrated
    驾车 /v3/direction/driving

兜底策略（任何单点失败都不抛给用户）：
    路径规划失败 -> /v3/distance?type=1 取距离 -> 仍失败则用球面距离 * 路网系数
    兜底结果统一加「约」，并在文案里注明是估算。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote

if __package__:
    from . import amap_client, geo
    from .recommender import Candidate
    from .text_parser import ParsedQuery, category_label
else:
    import amap_client  # type: ignore
    import geo  # type: ignore
    from recommender import Candidate  # type: ignore
    from text_parser import ParsedQuery, category_label  # type: ignore

MAX_MODES_PER_CANDIDATE = 2
MAX_PLANNED_CANDIDATES = 5
URI_SRC = "nearby-explorer"
MODE_TO_URI = {"walking": "walk", "bicycling": "ride", "transit": "bus", "driving": "car"}


@dataclass
class RoutePlan:
    mode: str
    summary: str
    distance_m: Optional[float] = None
    duration_s: Optional[float] = None
    estimated: bool = False
    error: Optional[str] = None
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "mode": self.mode,
            "mode_label": geo.MODE_LABEL.get(self.mode, self.mode),
            "summary": self.summary,
            "distance_m": round(self.distance_m) if self.distance_m is not None else None,
            "duration_minutes": int(round(self.duration_s / 60.0)) if self.duration_s else None,
            "estimated": self.estimated,
        }
        if self.error:
            data["error"] = self.error
        if self.detail:
            data["detail"] = self.detail
        return data


# ---------------------------------------------------------------------------
# 解析各接口返回
# ---------------------------------------------------------------------------
def _int(value: Any) -> Optional[int]:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def parse_walking(payload: Dict[str, Any]) -> RoutePlan:
    paths = ((payload.get("route") or {}).get("paths") or [])
    if not paths:
        raise ValueError("walking response has no paths")
    path = paths[0]
    distance = _int(path.get("distance")) or 0
    duration = _int(path.get("duration")) or 0
    steps = path.get("steps") or []
    summary = "步行 %s（%s）" % (geo.format_minutes(duration), geo.format_distance(distance))
    return RoutePlan(
        mode="walking",
        summary=summary,
        distance_m=float(distance),
        duration_s=float(duration),
        detail={"steps": len(steps), "first_step": (steps[0].get("instruction") if steps else "")},
    )


def parse_bicycling(payload: Dict[str, Any]) -> RoutePlan:
    paths = ((payload.get("data") or {}).get("paths") or [])
    if not paths:
        raise ValueError("bicycling response has no paths")
    path = paths[0]
    distance = _int(path.get("distance")) or 0
    duration = _int(path.get("duration")) or 0
    return RoutePlan(
        mode="bicycling",
        summary="骑行 %s（%s）" % (geo.format_minutes(duration), geo.format_distance(distance)),
        distance_m=float(distance),
        duration_s=float(duration),
        detail={"steps": len(path.get("steps") or [])},
    )


def parse_driving(payload: Dict[str, Any]) -> RoutePlan:
    paths = ((payload.get("route") or {}).get("paths") or [])
    if not paths:
        raise ValueError("driving response has no paths")
    path = paths[0]
    distance = _int(path.get("distance")) or 0
    duration = _int(path.get("duration")) or 0
    roads: List[str] = []
    for step in path.get("steps") or []:
        road = str(step.get("road") or "").strip()
        if road and road not in roads:
            roads.append(road)
    road_text = "、".join(roads[:2])
    summary = "驾车 %s（%s%s）" % (
        geo.format_minutes(duration),
        geo.format_distance(distance),
        "，途经 " + road_text if road_text else "",
    )
    return RoutePlan(
        mode="driving",
        summary=summary,
        distance_m=float(distance),
        duration_s=float(duration),
        detail={"roads": roads[:4], "traffic_lights": path.get("traffic_lights")},
    )


def parse_transit(payload: Dict[str, Any]) -> RoutePlan:
    route = payload.get("route") or {}
    transits = route.get("transits") or []
    if not transits:
        raise ValueError("transit response has no transits")
    best = min(transits, key=lambda item: _int(item.get("duration")) or 10 ** 9)
    duration = _int(best.get("duration")) or 0
    distance = _int(best.get("distance")) or 0
    walking_distance = _int(best.get("walking_distance")) or 0
    lines: List[str] = []
    for segment in best.get("segments") or []:
        bus = segment.get("bus") or {}
        for busline in bus.get("buslines") or []:
            name = str(busline.get("name") or "").split("(")[0].strip()
            if name and name not in lines:
                lines.append(name)
        railway = segment.get("railway") or {}
        if isinstance(railway, dict) and railway.get("name"):
            name = str(railway["name"]).split("(")[0].strip()
            if name and name not in lines:
                lines.append(name)
    transfers = max(0, len(lines) - 1)
    line_text = " → ".join(lines[:3]) if lines else "公交/地铁"
    summary = "%s，换乘 %d 次，%s（含步行 %s）" % (
        line_text,
        transfers,
        geo.format_minutes(duration),
        geo.format_distance(walking_distance) if walking_distance else "少量",
    )
    return RoutePlan(
        mode="transit",
        summary=summary,
        distance_m=float(distance),
        duration_s=float(duration),
        detail={
            "lines": lines,
            "transfers": transfers,
            "walking_distance_m": walking_distance,
            "cost": best.get("cost"),
        },
    )


PARSERS = {
    "walking": parse_walking,
    "bicycling": parse_bicycling,
    "driving": parse_driving,
    "transit": parse_transit,
}


# ---------------------------------------------------------------------------
# 兜底
# ---------------------------------------------------------------------------
def estimate_plan(mode: str, straight_m: float, note: str = "") -> RoutePlan:
    distance, duration = geo.estimate_route(straight_m, mode)
    suffix = "（%s）" % note if note else "（按直线距离估算）"
    summary = "%s 约 %s（%s）%s" % (
        geo.MODE_LABEL.get(mode, mode),
        geo.format_minutes(duration),
        geo.format_distance(distance),
        suffix,
    )
    return RoutePlan(
        mode=mode,
        summary=summary,
        distance_m=distance,
        duration_s=duration,
        estimated=True,
        detail={"fallback": True, "straight_m": round(straight_m, 1)},
    )


def _fallback_plan(
    client: amap_client.AmapClient,
    mode: str,
    origin: str,
    destination: str,
    straight_m: float,
    deadline: Optional[amap_client.Deadline],
    error: str = "",
) -> RoutePlan:
    """路径规划失败：先试 /v3/distance?type=1，再退回球面距离估算。"""
    distance: Optional[float] = None
    try:
        payload = client.distance(origin, destination, dtype=1, deadline=deadline)
        results = payload.get("results") or []
        if results:
            distance = _int(results[0].get("distance"))
    except amap_client.AmapError:
        distance = None
    if distance:
        speed = geo.MODE_SPEED_MPS.get(mode, 1.25)
        duration = distance / speed
        if mode == "transit":
            duration += 300
        elif mode == "driving":
            duration += 120
        summary = "%s 约 %s（%s）" % (
            geo.MODE_LABEL.get(mode, mode),
            geo.format_minutes(duration),
            geo.format_distance(distance),
        )
        return RoutePlan(
            mode=mode,
            summary=summary,
            distance_m=float(distance),
            duration_s=duration,
            estimated=True,
            error=error or None,
            detail={"fallback": "distance_api", "straight_m": round(straight_m, 1)},
        )
    plan = estimate_plan(mode, straight_m, "路线规划失败，按直线距离估算")
    plan.error = error or None
    return plan


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def desired_modes(parsed: ParsedQuery, candidate: Candidate) -> List[str]:
    """每条候选给 1~2 种交通方案：主方式 + 一个合理的备选。"""
    primary = parsed.transport
    modes = [primary]
    distance = candidate.distance_m
    if primary == "walking":
        if distance > 1500:
            modes.append("transit")
        elif distance > 800:
            modes.append("bicycling")
    elif primary == "bicycling":
        if distance > 4000:
            modes.append("transit")
        elif distance > 600:
            modes.append("walking")
    elif primary == "transit":
        if distance < 2500:
            modes.append("walking")
        else:
            modes.append("driving")
    elif primary == "driving":
        if distance <= 1500:
            modes.append("walking")
    deduped: List[str] = []
    for mode in modes:
        if mode not in deduped:
            deduped.append(mode)
    return deduped[:MAX_MODES_PER_CANDIDATE]


def _plan_one(
    client: amap_client.AmapClient,
    mode: str,
    origin_lnglat: Tuple[float, float],
    candidate: Candidate,
    city: Optional[str],
    deadline: Optional[amap_client.Deadline],
) -> RoutePlan:
    destination = "%s,%s" % (candidate.poi.get("lng"), candidate.poi.get("lat"))
    origin = geo.format_lnglat(origin_lnglat[0], origin_lnglat[1])
    if candidate.poi.get("lng") is None or candidate.poi.get("lat") is None:
        return estimate_plan(mode, candidate.distance_m, "缺少坐标，按直线距离估算")
    straight = geo.haversine_m(origin_lnglat, (float(candidate.poi["lng"]), float(candidate.poi["lat"])))
    try:
        if mode == "walking":
            payload = client.walking(origin, destination, deadline=deadline)
        elif mode == "bicycling":
            payload = client.bicycling(origin, destination, deadline=deadline)
        elif mode == "driving":
            payload = client.driving(origin, destination, deadline=deadline)
        elif mode == "transit":
            payload = client.transit(origin, destination, city=city, cityd=city, deadline=deadline)
        else:
            return estimate_plan(mode, straight, "未知交通方式")
        plan = PARSERS[mode](payload)
        if plan.distance_m is None or plan.duration_s is None:
            raise ValueError("route fields missing")
        return plan
    except amap_client.AmapError as exc:
        if exc.code == "BUDGET":
            return estimate_plan(mode, straight, "查询时间预算用尽，按直线距离估算")
        return _fallback_plan(client, mode, origin, destination, straight, deadline, error="%s %s" % (exc.code, exc.message))
    except Exception as exc:  # 解析失败也要降级
        return _fallback_plan(client, mode, origin, destination, straight, deadline, error=str(exc))


def plan_routes(
    client: amap_client.AmapClient,
    parsed: ParsedQuery,
    origin: Tuple[float, float],
    candidates: Sequence[Candidate],
    *,
    city: Optional[str] = None,
    deadline: Optional[amap_client.Deadline] = None,
    max_workers: int = 4,
) -> Tuple[Dict[str, List[Dict[str, Any]]], List[Dict[str, Any]]]:
    """为候选批量规划路线，返回 ({poi_id: [route dict]}, diagnostics)。"""
    plans: Dict[str, List[RoutePlan]] = {c.poi_id: [] for c in candidates}
    diagnostics: List[Dict[str, Any]] = []

    targets = list(candidates)[:MAX_PLANNED_CANDIDATES]
    tasks = []
    for candidate in targets:
        for mode in desired_modes(parsed, candidate):
            tasks.append((candidate, mode))
    if not tasks:
        return {}, diagnostics

    workers = max(1, min(max_workers, len(tasks)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="amap-route") as pool:
        futures = {
            pool.submit(_plan_one, client, mode, origin, candidate, city, deadline): (candidate, mode)
            for candidate, mode in tasks
        }
        for future in as_completed(futures):
            candidate, mode = futures[future]
            try:
                plan = future.result()
            except Exception as exc:  # 理论上 _plan_one 不会抛，但保持兜底
                plan = estimate_plan(mode, candidate.distance_m, "规划异常，按直线距离估算")
                plan.error = str(exc)
            plans[candidate.poi_id].append(plan)
            if plan.estimated:
                diagnostics.append(
                    {
                        "poi": candidate.name,
                        "mode": mode,
                        "estimated": True,
                        "error": plan.error,
                    }
                )

    result: Dict[str, List[Dict[str, Any]]] = {}
    for candidate in candidates:
        ordered = []
        seen = set()
        for plan in plans.get(candidate.poi_id, []):
            if plan.mode in seen:
                continue
            seen.add(plan.mode)
            ordered.append(plan.to_dict())
        ordered.sort(key=lambda item: 0 if item["mode"] == parsed.transport else 1)
        result[candidate.poi_id] = ordered
        candidate.route_plans = ordered
        if ordered:
            primary = ordered[0]
            if primary.get("mode") == "walking" and primary.get("duration_minutes"):
                candidate.walk_minutes = int(primary["duration_minutes"])
    return result, diagnostics


# ---------------------------------------------------------------------------
# 高德 URI 链接
# ---------------------------------------------------------------------------
def marker_uri(lng: float, lat: float, name: str) -> str:
    return (
        "https://uri.amap.com/marker?position=%s&name=%s&src=%s&coordinate=gaode&callnative=0"
        % (geo.format_lnglat(lng, lat), quote(str(name), safe=""), URI_SRC)
    )


def navigation_uri(
    origin: Tuple[float, float],
    destination: Tuple[float, float],
    name: str,
    mode: str,
    origin_name: str = "我的位置",
) -> str:
    return (
        "https://uri.amap.com/navigation?from=%s&to=%s&mode=%s&policy=1&src=%s&coordinate=gaode&callnative=0"
        % (
            "%s,%s" % (geo.format_lnglat(origin[0], origin[1]), quote(str(origin_name), safe="")),
            "%s,%s" % (geo.format_lnglat(destination[0], destination[1]), quote(str(name), safe="")),
            MODE_TO_URI.get(mode, "walk"),
            URI_SRC,
        )
    )


def amap_app_uri(origin: Tuple[float, float], destination: Tuple[float, float], name: str, mode: str) -> str:
    """手机端唤起高德 App 的 scheme（t=0 驾车 / 1 公交 / 2 步行 / 3 骑行）。"""
    t = {"driving": 0, "transit": 1, "walking": 2, "bicycling": 3}.get(mode, 0)
    return (
        "amapuri://route/plan/?slon=%s&slat=%s&sname=%s&dlon=%s&dlat=%s&dname=%s&dev=0&t=%d"
        % (
            origin[0],
            origin[1],
            quote("我的位置", safe=""),
            destination[0],
            destination[1],
            quote(str(name), safe=""),
            t,
        )
    )


def candidate_links(
    candidate: Candidate,
    origin: Tuple[float, float],
    mode: str,
) -> Dict[str, str]:
    lng = candidate.poi.get("lng")
    lat = candidate.poi.get("lat")
    links = {
        "marker": "",
        "navigation": "",
        "app_scheme": "",
    }
    if lng is None or lat is None:
        return links
    links["marker"] = marker_uri(float(lng), float(lat), candidate.name)
    links["navigation"] = navigation_uri(origin, (float(lng), float(lat)), candidate.name, mode)
    links["app_scheme"] = amap_app_uri(origin, (float(lng), float(lat)), candidate.name, mode)
    return links
