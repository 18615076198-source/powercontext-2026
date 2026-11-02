"""nearby-explorer 编排入口：一句话 -> 地点 -> 候选 -> 怎么去 -> Markdown / JSON。

用法：
    python scripts/nearby_explorer.py "我在西湖附近想喝咖啡"
    python scripts/nearby_explorer.py --json --top 3 "..."
    python scripts/nearby_explorer.py --origin 120.148,30.246 "离我 1 公里内找个公园"
    AMAP_MOCK=1 python scripts/nearby_explorer.py "..."   # 离线模式

任何单点失败都会降级为可读的结果（status = ok / no_result / need_location / error），
不会直接抛异常退出。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

if __package__:
    from . import amap_client, geo, planner, recommender, render, text_parser
else:
    import amap_client  # type: ignore
    import geo  # type: ignore
    import planner  # type: ignore
    import recommender  # type: ignore
    import render  # type: ignore
    import text_parser  # type: ignore

MAX_TOP = 8
DEFAULT_TOP = 5


def _stdout_utf8() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _origin_from_geocodes(
    items: List[Dict[str, Any]],
    city_hint: Optional[str],
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    valid = [item for item in items if item.get("lng") is not None and item.get("lat") is not None]
    if not valid:
        return None, []
    level_rank = {"兴趣点": 0, "门牌号": 0, "热点商圈": 1, "商务住宅": 1, "道路": 2, "村庄": 3, "区县": 4, "市": 5, "省": 6}
    valid.sort(key=lambda item: (level_rank.get(item.get("level") or "", 2), 0))
    if city_hint:
        same_city = [item for item in valid if item.get("city") == city_hint]
        if same_city:
            valid = same_city
    best = valid[0]
    alternatives = [
        {"name": item.get("name"), "city": item.get("city"), "lng": item.get("lng"), "lat": item.get("lat")}
        for item in valid[1:4]
    ]
    origin = {
        "name": best.get("raw", {}).get("raw_name") or best.get("name") or "",
        "address": best.get("name") or "",
        "lng": float(best["lng"]),
        "lat": float(best["lat"]),
        "city": best.get("city") or city_hint or "",
        "district": best.get("district") or "",
        "level": best.get("level") or "",
        "source": "geocode",
        "alternatives": alternatives,
    }
    return origin, alternatives


def resolve_origin(
    client: amap_client.AmapClient,
    parsed: text_parser.ParsedQuery,
    deadline: Optional[amap_client.Deadline],
    origin_hint: Optional[Tuple[float, float]] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[amap_client.AmapError], List[str]]:
    """把输入变成 (lng, lat)。返回 (origin, api_error, notes)。"""
    notes: List[str] = []
    if origin_hint is not None:
        lng, lat = origin_hint
        origin = {
            "name": "当前坐标",
            "lng": lng,
            "lat": lat,
            "city": parsed.city_hint or "",
            "district": "",
            "level": "",
            "source": "manual",
            "alternatives": [],
        }
        return origin, None, notes

    if parsed.location_kind == "relative":
        return None, None, notes

    city_filter = parsed.city_hint if parsed.city_source == "explicit" else None
    api_error: Optional[amap_client.AmapError] = None

    def _try_geocode(address: str, city: Optional[str]) -> List[Dict[str, Any]]:
        nonlocal api_error
        try:
            return client.geocode(address, city=city, deadline=deadline)
        except amap_client.AmapError as exc:
            if exc.category != "no_result" and api_error is None:
                api_error = exc
            return []

    if parsed.location_text:
        candidates = _try_geocode(parsed.location_text, city_filter)
        origin, alternatives = _origin_from_geocodes(candidates, parsed.city_hint)
        if origin is not None:
            if len({alt.get("city") for alt in [origin] + alternatives}) > 1:
                cities = []
                for item in [origin] + alternatives:
                    if item.get("city") and item["city"] not in cities:
                        cities.append(item["city"])
                notes.append(
                    "「%s」在多个城市都存在（%s），默认选了%s；补充城市名可以精确指定"
                    % (parsed.location_text, "、".join(cities), origin.get("city") or "")
                )
            return origin, None, notes
        if city_filter:
            candidates = _try_geocode(parsed.location_text, None)
            origin, alternatives = _origin_from_geocodes(candidates, parsed.city_hint)
            if origin is not None:
                return origin, None, notes
        try:
            tips = client.inputtips(parsed.location_text, city=city_filter, deadline=deadline)
        except amap_client.AmapError as exc:
            tips = []
            if exc.category != "no_result" and api_error is None:
                api_error = exc
        tip_items = [
            {
                "name": tip.get("name"),
                "lng": tip.get("lng"),
                "lat": tip.get("lat"),
                "city": (tip.get("district") or "")[:0] or parsed.city_hint,
                "district": tip.get("district") or "",
                "level": "兴趣点",
            }
            for tip in tips
            if tip.get("lng") is not None
        ]
        origin, alternatives = _origin_from_geocodes(tip_items, parsed.city_hint)
        if origin is not None:
            origin["source"] = "inputtips"
            return origin, None, notes

    if parsed.city_hint:
        candidates = _try_geocode(parsed.city_hint, None)
        origin, alternatives = _origin_from_geocodes(candidates, parsed.city_hint)
        if origin is not None:
            origin["source"] = "city_center"
            origin["name"] = parsed.city_hint
            notes.append("没有识别到具体地点，改用城市中心：%s" % parsed.city_hint)
            return origin, None, notes

    if api_error is not None:
        return None, api_error, notes
    return None, None, notes


def _empty_result(parsed: text_parser.ParsedQuery) -> Dict[str, Any]:
    return {
        "status": "ok",
        "message": "",
        "query": parsed.to_dict(),
        "origin": None,
        "candidates": [],
        "diagnostics": {},
        "degraded": [],
        "suggestions": [],
        "source": {},
        "elapsed_ms": 0,
    }


def _error_result(base: Dict[str, Any], exc: amap_client.AmapError, elapsed_ms: int) -> Dict[str, Any]:
    suggestions = []
    if exc.suggestion:
        suggestions.append(exc.suggestion)
    if exc.category == "config":
        suggestions.append("或者直接使用离线模式验证流程：AMAP_MOCK=1")
    if exc.category == "quota":
        suggestions.append("也可以在离线模式下完整预览效果：AMAP_MOCK=1")
    base.update(
        {
            "status": "error",
            "message": "%s（%s）" % (exc.message, exc.code),
            "error": exc.to_dict(),
            "suggestions": suggestions,
            "elapsed_ms": elapsed_ms,
        }
    )
    return base


def explore(
    query: str,
    *,
    top: int = DEFAULT_TOP,
    client: Optional[amap_client.AmapClient] = None,
    now=None,
    default_city: Optional[str] = None,
    origin_hint: Optional[Tuple[float, float]] = None,
    mock: Optional[bool] = None,
) -> Dict[str, Any]:
    """完整流程：任何异常都转成 status=error 的结果，绝不让调用方崩掉。"""
    try:
        return _explore(
            query,
            top=top,
            client=client,
            now=now,
            default_city=default_city,
            origin_hint=origin_hint,
            mock=mock,
        )
    except Exception as exc:  # 最后一道保险
        parsed = text_parser.parse(query, default_city=default_city or os.environ.get("AMAP_DEFAULT_CITY"))
        result = _empty_result(parsed)
        result.update(
            {
                "status": "error",
                "message": "内部错误：%s" % exc,
                "error": {"infocode": "INTERNAL", "message": str(exc), "category": "internal", "suggestion": "请把这句话和日志一起反馈，或先用 AMAP_MOCK=1 复现"},
                "suggestions": ["换一种说法再试一次", "AMAP_MOCK=1 可以离线复现问题"],
                "elapsed_ms": 0,
            }
        )
        return result


def _explore(
    query: str,
    *,
    top: int = DEFAULT_TOP,
    client: Optional[amap_client.AmapClient] = None,
    now=None,
    default_city: Optional[str] = None,
    origin_hint: Optional[Tuple[float, float]] = None,
    mock: Optional[bool] = None,
) -> Dict[str, Any]:
    started = time.monotonic()
    top = max(1, min(MAX_TOP, int(top or DEFAULT_TOP)))
    parsed = text_parser.parse(query, default_city=default_city or os.environ.get("AMAP_DEFAULT_CITY"))
    base = _empty_result(parsed)

    def elapsed() -> int:
        return int((time.monotonic() - started) * 1000)

    if origin_hint is not None:
        # 宿主已经给了当前坐标，就不再追问位置
        parsed.need_clarification = False
        parsed.questions = []
        if parsed.location_kind == "none":
            parsed.location_kind = "relative"
        base["query"] = parsed.to_dict()

    if parsed.need_clarification:
        base.update(
            {
                "status": "need_location",
                "message": "还需要一个位置才能开始搜索。",
                "questions": parsed.questions,
                "suggestions": [
                    "可以说「我在西湖附近，想喝咖啡」这样带地名的句子",
                    "也可以直接给坐标：--origin 120.148,30.246",
                ],
                "elapsed_ms": elapsed(),
            }
        )
        return base

    owned_client = False
    if client is None:
        try:
            client = amap_client.AmapClient(mock=mock)
            owned_client = True
        except amap_client.AmapError as exc:
            return _error_result(base, exc, elapsed())

    try:
        base["source"] = {
            "offline": bool(client.mock),
            "key_masked": amap_client.mask_key(client.key),
        }
        deadline = client.new_deadline()
        origin, origin_error, origin_notes = resolve_origin(client, parsed, deadline, origin_hint)
        base["degraded"].extend(origin_notes)
        if origin_error is not None:
            return _error_result(base, origin_error, elapsed())
        if origin is None:
            base.update(
                {
                    "status": "no_result",
                    "message": "没找到「%s」这个地点。" % (parsed.location_text or parsed.city_hint or "目标位置"),
                    "suggestions": [
                        "换个更具体的地名，例如「西湖文化广场」「国贸商城」",
                        "在地名前面加上城市，例如「杭州 解放路」",
                        "如果是当前位置，可以用 --origin 经度,纬度 指定",
                    ],
                    "elapsed_ms": elapsed(),
                }
            )
            return base
        base["origin"] = origin
        origin_ll = (origin["lng"], origin["lat"])

        try:
            recommendation = recommender.recommend(
                client, parsed, origin_ll, top=top, now=now, deadline=deadline
            )
        except amap_client.AmapError as exc:
            return _error_result(base, exc, elapsed())

        base["degraded"].extend(recommendation.get("degraded") or [])
        diagnostics = dict(recommendation.get("diagnostics") or {})
        base["diagnostics"] = diagnostics

        if recommendation.get("status") != "ok" or not recommendation.get("candidates"):
            base.update(
                {
                    "status": "no_result",
                    "message": "在「%s」周边 %s 内没有找到符合条件的%s。"
                    % (
                        origin.get("name") or "目标位置",
                        geo.format_distance(parsed.radius_m),
                        "、".join(text_parser.category_label(c) for c in parsed.categories) or "地点",
                    ),
                    "suggestions": recommendation.get("suggestions") or [],
                    "elapsed_ms": elapsed(),
                }
            )
            return base

        candidates: List[recommender.Candidate] = recommendation["candidates"]
        city = origin.get("city") or parsed.city_hint or (candidates[0].poi.get("city") if candidates else "") or ""
        # 公交规划必须带城市；只有坐标时用逆地理编码补齐（结果缓存 24h）
        if not city:
            try:
                regeo = client.regeo(origin_ll[0], origin_ll[1], deadline=deadline)
                component = regeo.get("addressComponent") or {}
                city = component.get("city") or component.get("province") or ""
                if city:
                    origin["city"] = city
            except amap_client.AmapError:
                city = ""
        try:
            _, plan_diagnostics = planner.plan_routes(
                client, parsed, origin_ll, candidates, city=city, deadline=deadline
            )
        except Exception as exc:  # 规划整体异常也不能中断
            plan_diagnostics = [{"error": str(exc)}]
            base["degraded"].append("路径规划整体失败，已全部改为估算：%s" % exc)
        base["diagnostics"]["planning"] = plan_diagnostics

        payload_candidates = []
        for candidate in candidates:
            item = candidate.to_dict()
            routes = item.get("routes") or []
            primary_mode = routes[0]["mode"] if routes else parsed.transport
            primary_distance = routes[0].get("distance_m") if routes else None
            item["reason"] = recommender.build_reason(
                candidate,
                parsed,
                minutes=item.get("walk_minutes"),
                distance_m=primary_distance or candidate.distance_m,
            )
            item["links"] = planner.candidate_links(candidate, origin_ll, primary_mode)
            item["open_now"] = recommender.is_open_now(candidate.poi.get("open_time") or "", now)
            item["city"] = candidate.poi.get("city") or city
            payload_candidates.append(item)
            if candidate.poi.get("city") and city and candidate.poi.get("city") != city:
                base["degraded"].append(
                    "「%s」位于%s，与出发点城市不同，路线可能不准" % (candidate.name, candidate.poi.get("city"))
                )
        base["candidates"] = payload_candidates

        if len(payload_candidates) < 3:
            base["suggestions"].append("候选偏少，可以放宽半径、换个类目，或补充更具体的地名")

        stats = client.stats
        base["diagnostics"]["api_calls"] = dict(stats)
        base["diagnostics"]["cache"] = client.cache_stats()
        base["elapsed_ms"] = elapsed()
        base["status"] = "ok"
        return base
    finally:
        if owned_client and client is not None:
            client.close()


def main(argv: Optional[List[str]] = None) -> int:
    _stdout_utf8()
    parser = argparse.ArgumentParser(
        prog="nearby-explorer",
        description="一句话找出附近 3~5 个去处，并说明怎么去（高德 Web 服务）。",
    )
    parser.add_argument("query", nargs="*", help="自然语言请求，例如：我在西湖附近想找个安静的咖啡馆")
    parser.add_argument("--json", action="store_true", help="输出 JSON（便于脚本 / 测试断言）")
    parser.add_argument("--top", type=int, default=DEFAULT_TOP, help="候选数量 3~8，默认 5")
    parser.add_argument("--origin", help="当前位置坐标 lng,lat（相对位置表达时需要）")
    parser.add_argument("--default-city", help="缺省城市，例如 杭州市")
    parser.add_argument("--mock", dest="mock", action="store_true", default=None, help="强制离线模式（等同 AMAP_MOCK=1）")
    parser.add_argument("--no-mock", dest="mock", action="store_false", help="强制联网模式")
    parser.add_argument("--explain", action="store_true", help="附加打分与召回诊断")
    parser.add_argument("--verbose", "-v", action="store_true", help="打印脱敏调用日志")
    args = parser.parse_args(argv)

    query = " ".join(args.query).strip()
    if not query:
        parser.print_help()
        return 2

    if args.verbose:
        import logging

        amap_client.configure_logging(logging.INFO)

    origin_hint = None
    origin_text = args.origin or os.environ.get("AMAP_ORIGIN")
    if origin_text:
        origin_hint = geo.parse_lnglat(origin_text)
        if origin_hint is None:
            print("--origin 格式应为 经度,纬度，例如 120.148,30.246", file=sys.stderr)
            return 2

    result = explore(
        query,
        top=args.top,
        default_city=args.default_city,
        origin_hint=origin_hint,
        mock=args.mock,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        text = render.render_markdown(result)
        if args.explain:
            text += render.render_explain(result)
        print(text, end="")

    return {"ok": 0, "no_result": 2, "need_location": 3, "error": 4}.get(result.get("status"), 1)


if __name__ == "__main__":
    sys.exit(main())
