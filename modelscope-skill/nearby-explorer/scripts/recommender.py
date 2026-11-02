"""候选召回 + 打分排序 + 多样性。

打分公式（权重集中在 SCORING_WEIGHTS，方便调参）
------------------------------------------------
final = 0.30 * 距离分 + 0.28 * 评分分 + 0.16 * 人气分 + 0.16 * 类目分 + 0.10 * 营业分
        + 约束加减分（安静 / 无障碍 / 停车 / 连锁 / 预算 / 停留时长）

* 距离衰减分：步行 exp(-d/500)，骑行 exp(-d/1200)，公交/驾车 exp(-d/3000)
  （任务书写的是 1-exp(-d/500)，该式随距离增大，直接当得分会把远处排前面；
   这里用它的补数 exp(-d/500) 表示衰减，详见 README「与任务书的差异」）
* 评分分：clamp((rating-3.0)/2.0)，缺失时按中性 3.8 计算（=0.40）
* 人气分：0.55*人均消费合理度 + 0.30*评论数（有则用） + 0.15*图片数
* 类目分：类型码命中 1.0 / 关键词命中 0.9 / 同大类 0.65 / 未知 0.5
* 营业分：营业中 1.0 / 未知 0.6 / 已打烊 0.0
* 一致性：同一输入、同一 fixtures 永远得到同一排序（tie-break 用 POI id）
"""
from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

if __package__:
    from . import amap_client, geo
    from .text_parser import CATEGORIES, CategorySpec, ParsedQuery, category_label
else:
    import amap_client  # type: ignore
    import geo  # type: ignore
    from text_parser import CATEGORIES, CategorySpec, ParsedQuery, category_label  # type: ignore

SCORING_WEIGHTS: Dict[str, float] = {
    "distance": 0.30,
    "rating": 0.28,
    "popularity": 0.16,
    "category": 0.16,
    "open": 0.10,
}

DISTANCE_DECAY_M = {"walking": 500.0, "bicycling": 1200.0, "transit": 3000.0, "driving": 3000.0}
NEUTRAL_RATING = 3.8
RATING_FLOOR = 3.0
MAX_PER_CATEGORY = 2
MIN_SEPARATION_M = 150.0
RELAXED_SEPARATION_M = 60.0
MAX_RADIUS_M = 3000
MAX_QUERIES = 4
MAX_PAGES = 2


@dataclass
class Candidate:
    poi: Dict[str, Any]
    category: str
    distance_m: float
    score: float
    parts: Dict[str, float]
    reason: str = ""
    walk_minutes: Optional[int] = None
    route_plans: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def name(self) -> str:
        return str(self.poi.get("name") or "")

    @property
    def poi_id(self) -> str:
        return str(self.poi.get("id") or self.name)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.poi_id,
            "name": self.name,
            "category": self.category,
            "category_label": category_label(self.category),
            "distance_m": round(self.distance_m, 1),
            "walk_minutes": self.walk_minutes,
            "rating": self.poi.get("rating"),
            "cost": self.poi.get("cost"),
            "open_time": self.poi.get("open_time") or "",
            "address": self.poi.get("address") or "",
            "tags": self.poi.get("tags") or [],
            "score": round(self.score, 4),
            "score_parts": {k: round(v, 4) for k, v in self.parts.items()},
            "reason": self.reason,
            "routes": self.route_plans,
            "location": "%s,%s" % (self.poi.get("lng"), self.poi.get("lat")),
            "city": self.poi.get("city") or "",
        }


# ---------------------------------------------------------------------------
# 单维打分
# ---------------------------------------------------------------------------
def typecode_prefix(code: str) -> str:
    stripped = str(code).rstrip("0")
    return stripped or str(code)


def distance_score(distance_m: float, transport: str = "walking") -> float:
    """距离衰减分：越近越高，1 -> 0。等价于任务书里的 1 - (1-exp(-d/500))。"""
    decay = DISTANCE_DECAY_M.get(transport, 500.0)
    return max(0.0, math.exp(-max(0.0, distance_m) / decay))


def rating_score(rating: Optional[float]) -> float:
    value = NEUTRAL_RATING if rating is None else float(rating)
    return min(1.0, max(0.0, (value - RATING_FLOOR) / 2.0))


def popularity_score(poi: Dict[str, Any], category: str) -> float:
    spec = CATEGORIES.get(category)
    band = spec.cost_band if spec else (30.0, 150.0)
    low, high = band
    cost = poi.get("cost")
    if cost is None:
        cost_part = 0.5
    elif low <= cost <= high:
        mid = (low + high) / 2.0
        span = max(1.0, (high - low) / 2.0)
        cost_part = 1.0 - abs(cost - mid) / span * 0.6
    elif cost < low:
        cost_part = 0.55
    else:
        cost_part = max(0.15, 0.8 - (cost - high) / max(1.0, high))

    biz = poi.get("raw", {}).get("biz_ext") if isinstance(poi.get("raw"), dict) else {}
    biz = biz if isinstance(biz, dict) else {}
    reviews = None
    for key in ("comment_count", "review_count", "comments", "rating_count"):
        try:
            if biz.get(key) not in (None, "", "[]"):
                reviews = float(biz[key])
                break
        except (TypeError, ValueError):
            continue
    review_part = min(1.0, math.log1p(reviews) / math.log1p(2000)) if reviews else 0.5

    photos = poi.get("photos") or []
    photo_part = min(1.0, len(photos) / 5.0) if photos else 0.4

    return 0.55 * cost_part + 0.30 * review_part + 0.15 * photo_part


def category_score(poi: Dict[str, Any], category: str) -> float:
    spec = CATEGORIES.get(category)
    if spec is None:
        return 0.5
    typecode = str(poi.get("typecode") or "")
    if typecode and any(typecode.startswith(typecode_prefix(code)) for code in spec.typecodes):
        return 1.0
    text = " ".join(
        str(poi.get(key) or "") for key in ("name", "type", "tag")
    )
    if any(keyword in text for keyword in spec.match_keywords):
        return 0.9
    poi_type = str(poi.get("type") or "")
    if typecode and poi_type and any(code[:2] == typecode[:2] for code in spec.typecodes):
        return 0.65
    return 0.5


def parse_open_time(open_time: str) -> Optional[Tuple[Tuple[int, int], Tuple[int, int]]]:
    """解析 '09:00-22:00' / '17:00-02:00' / '24小时'，返回 (开始, 结束)。"""
    text = str(open_time or "").strip()
    if not text:
        return None
    if "24小时" in text or "全天" in text:
        return (0, 0), (24, 0)
    cleaned = text.replace("；", ";").replace("，", ",")
    for chunk in cleaned.replace(";", ",").split(","):
        chunk = chunk.strip()
        if "-" not in chunk:
            continue
        left, right = chunk.split("-", 1)
        try:
            start = tuple(int(x) for x in left.strip().split(":")[:2])
            end = tuple(int(x) for x in right.strip().split(":")[:2])
        except (TypeError, ValueError):
            continue
        if len(start) == 2 and len(end) == 2:
            return start, end  # type: ignore[return-value]
    return None


def is_open_now(open_time: str, now: Optional[datetime] = None) -> Optional[bool]:
    span = parse_open_time(open_time)
    if span is None:
        return None
    now = now or datetime.now()
    start, end = span
    minutes = now.hour * 60 + now.minute
    start_m = start[0] * 60 + start[1]
    end_m = end[0] * 60 + end[1]
    if end_m == 0 and start_m == 0:
        return True
    if end_m > start_m:
        return start_m <= minutes < end_m
    if end_m == start_m:
        return True
    return minutes >= start_m or minutes < end_m


def open_score(poi: Dict[str, Any], now: Optional[datetime]) -> float:
    opened = is_open_now(poi.get("open_time") or "", now)
    if opened is None:
        return 0.6
    return 1.0 if opened else 0.0


def is_chain(poi: Dict[str, Any]) -> bool:
    if poi.get("chain"):
        return True
    tags = poi.get("tags") or []
    if "连锁" in tags:
        return True
    name = str(poi.get("name") or "")
    chain_names = ("星巴克", "瑞幸", "Manner", "麦当劳", "肯德基", "外婆家", "盒马", "永辉", "海底捞")
    return any(brand in name for brand in chain_names)


# ---------------------------------------------------------------------------
# 召回
# ---------------------------------------------------------------------------
def _query_plan(parsed: ParsedQuery) -> List[Dict[str, Any]]:
    plan: List[Dict[str, Any]] = []
    focus = parsed.focus_keywords[0] if parsed.focus_keywords else None
    for category in parsed.categories[:MAX_QUERIES]:
        spec = CATEGORIES.get(category)
        if spec is None:
            continue
        plan.append(
            {
                "category": category,
                "types": spec.query_types,
                "keywords": None if spec.query_types else spec.search_keyword,
                "fallback_keywords": spec.search_keyword,
                # 具体口味词只对餐饮类目做精确召回，避免把"火锅"套到景点上
                "focus": focus if category in ("restaurant", "night_snack", "tea") else None,
                "page": 1,
            }
        )
    if not plan:
        spec = CATEGORIES["attraction"]
        plan.append(
            {
                "category": "attraction",
                "types": spec.query_types,
                "keywords": None,
                "fallback_keywords": spec.search_keyword,
                "page": 1,
            }
        )
    return plan


def _run_query(
    client: amap_client.AmapClient,
    query: Dict[str, Any],
    origin: Tuple[float, float],
    radius: int,
    deadline: Optional[amap_client.Deadline],
) -> Tuple[int, List[Dict[str, Any]]]:
    """单类目召回。

    先做「精确召回」：类型码 + 具体口味词（例如 火锅）；
    精确结果不足 3 条时再放宽为纯类型码召回并合并，保证候选数量。
    第一页满 25 条时继续翻第二页。
    """
    lng, lat = origin
    focus = query.get("focus")
    count, pois = 0, []
    if focus:
        count, pois = client.place_around(
            lng,
            lat,
            radius=radius,
            types=query.get("types"),
            keywords=focus,
            page=1,
            offset=25,
            extensions="all",
            sortrule="weight",
            deadline=deadline,
        )
        if len(pois) < 3:
            query["focus_relaxed"] = True
            broad_count, broad = client.place_around(
                lng,
                lat,
                radius=radius,
                types=query.get("types"),
                page=1,
                offset=25,
                extensions="all",
                sortrule="weight",
                deadline=deadline,
            )
            seen = {str(item.get("id")) for item in pois}
            pois = list(pois) + [item for item in broad if str(item.get("id")) not in seen]
            count = max(count, broad_count)
    if not pois and not focus:
        count, pois = client.place_around(
            lng,
            lat,
            radius=radius,
            types=query.get("types"),
            keywords=query.get("keywords"),
            page=1,
            offset=25,
            extensions="all",
            sortrule="weight",
            deadline=deadline,
        )
    if not pois and query.get("fallback_keywords"):
        count, pois = client.place_around(
            lng,
            lat,
            radius=radius,
            keywords=query["fallback_keywords"],
            page=1,
            offset=25,
            extensions="all",
            sortrule="weight",
            deadline=deadline,
        )
        query["used_fallback"] = True
    if len(pois) >= 25 and MAX_PAGES > 1:
        try:
            _, extra = client.place_around(
                lng,
                lat,
                radius=radius,
                types=query.get("types"),
                keywords=query.get("keywords"),
                page=2,
                offset=25,
                extensions="all",
                sortrule="weight",
                deadline=deadline,
            )
            pois = list(pois) + list(extra)
        except amap_client.AmapError:
            pass
    return count, pois


def recall(
    client: amap_client.AmapClient,
    parsed: ParsedQuery,
    origin: Tuple[float, float],
    *,
    radius: Optional[int] = None,
    max_workers: int = 4,
    deadline: Optional[amap_client.Deadline] = None,
) -> Dict[str, Any]:
    """并行召回并去重，返回 {'pois': [...], 'diagnostics': {...}}。"""
    radius = int(radius or parsed.radius_m)
    plan = _query_plan(parsed)
    diagnostics: Dict[str, Any] = {"queries": [], "errors": [], "degraded": [], "radius": radius}
    collected: Dict[str, Tuple[Dict[str, Any], str]] = {}

    workers = max(1, min(4, max_workers, len(plan)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="amap-recall") as pool:
        futures = {
            pool.submit(_run_query, client, query, origin, radius, deadline): query for query in plan
        }
        for future in as_completed(futures):
            query = futures[future]
            record = {
                "category": query["category"],
                "types": query.get("types"),
                "keywords": query.get("keywords"),
                "focus": query.get("focus"),
            }
            try:
                count, pois = future.result()
                record.update({"count": count, "returned": len(pois), "ok": True})
                if query.get("used_fallback"):
                    record["fallback"] = True
                if query.get("focus_relaxed"):
                    record["focus_relaxed"] = True
                for poi in pois:
                    poi_id = str(poi.get("id") or poi.get("name") or "")
                    if not poi_id:
                        continue
                    old = collected.get(poi_id)
                    if old is None or category_score(poi, query["category"]) > category_score(old[0], old[1]):
                        collected[poi_id] = (poi, query["category"])
            except amap_client.AmapError as exc:
                record.update({"count": 0, "returned": 0, "ok": False, "error": exc.to_dict()})
                diagnostics["errors"].append({"category": query["category"], **exc.to_dict()})
            except Exception as exc:  # 单类目失败不能拖垮整个查询
                record.update({"count": 0, "returned": 0, "ok": False, "error": str(exc)})
                diagnostics["errors"].append({"category": query["category"], "infocode": "UNKNOWN", "message": str(exc)})
            diagnostics["queries"].append(record)

    diagnostics["queries"].sort(key=lambda item: str(item.get("category")))
    diagnostics["recalled"] = len(collected)

    unique: List[Dict[str, Any]] = []
    seen_names: List[Tuple[str, float, float]] = []
    for poi, category in collected.values():
        name = str(poi.get("name") or "")
        lng, lat = float(poi.get("lng") or 0.0), float(poi.get("lat") or 0.0)
        duplicate = False
        for other_name, other_lng, other_lat in seen_names:
            if other_name == name and geo.haversine_m((lng, lat), (other_lng, other_lat)) < 30:
                duplicate = True
                break
        if duplicate:
            continue
        poi["_recall_category"] = category
        seen_names.append((name, lng, lat))
        unique.append(poi)
    diagnostics["deduped"] = len(unique)
    return {"pois": unique, "diagnostics": diagnostics}


# ---------------------------------------------------------------------------
# 过滤 / 打分 / 多样性
# ---------------------------------------------------------------------------
def _resolve_distance(poi: Dict[str, Any], origin: Tuple[float, float]) -> float:
    distance = poi.get("distance_m")
    if distance is not None:
        return float(distance)
    lng, lat = poi.get("lng"), poi.get("lat")
    if lng is None or lat is None:
        return float("inf")
    return geo.haversine_m(origin, (float(lng), float(lat)))


def filter_pois(
    pois: Sequence[Dict[str, Any]],
    parsed: ParsedQuery,
    origin: Tuple[float, float],
    *,
    radius: Optional[int] = None,
    now: Optional[datetime] = None,
    enforce_rating: bool = True,
    enforce_chain: bool = True,
) -> Tuple[List[Tuple[Dict[str, Any], str, float]], List[Dict[str, Any]], List[str]]:
    """过滤阶段。

    硬过滤（直接剔除）：超出半径 / 显式距离、类目明显不符、要求营业但已打烊。
    软过滤（候选不足 3 个时回补并记录原因）：评分低于门槛、连锁店。
    """
    radius = int(radius or parsed.radius_m)
    now = now or datetime.now()
    kept: List[Tuple[Dict[str, Any], str, float]] = []
    dropped: List[Dict[str, Any]] = []
    soft: List[Tuple[str, Dict[str, Any], str, float]] = []
    notes: List[str] = []

    for poi in pois:
        distance = _resolve_distance(poi, origin)
        category = str(poi.get("_recall_category") or "attraction")
        reason = None
        if parsed.max_distance_m and distance > parsed.max_distance_m:
            reason = "超过最大距离约束"
        elif distance > radius:
            reason = "超出搜索半径"
        elif category_score(poi, category) < 0.45:
            reason = "类目明显不符"
        elif parsed.require_open and is_open_now(poi.get("open_time") or "", now) is False:
            reason = "当前未营业"
        if reason:
            dropped.append({"id": poi.get("id"), "name": poi.get("name"), "reason": reason, "distance_m": round(distance, 1)})
            continue

        rating = poi.get("rating")
        effective_rating = NEUTRAL_RATING if rating is None else float(rating)
        if enforce_rating and parsed.min_rating and effective_rating < float(parsed.min_rating) - 0.05:
            soft.append(("rating", poi, category, distance))
            continue
        if enforce_chain and parsed.avoid_chain and is_chain(poi):
            soft.append(("chain", poi, category, distance))
            continue
        kept.append((poi, category, distance))

    if len(kept) < 3 and soft:
        for kind, message in (("rating", "满足评分门槛的候选不足，已补充部分低分选项"), ("chain", "避开连锁后候选不足，已补充连锁门店")):
            for item in list(soft):
                if item[0] != kind or len(kept) >= 3:
                    continue
                kept.append((item[1], item[2], item[3]))
                soft.remove(item)
                if message not in notes:
                    notes.append(message)
    return kept, dropped, notes


def score_poi(
    poi: Dict[str, Any],
    category: str,
    distance: float,
    parsed: ParsedQuery,
    now: Optional[datetime] = None,
) -> Tuple[float, Dict[str, float]]:
    parts = {
        "distance": distance_score(distance, parsed.transport),
        "rating": rating_score(poi.get("rating")),
        "popularity": popularity_score(poi, category),
        "category": category_score(poi, category),
        "open": open_score(poi, now),
    }
    base = sum(SCORING_WEIGHTS[key] * parts[key] for key in SCORING_WEIGHTS)
    adjustment = 0.0
    tags = poi.get("tags") or []
    tag_text = " ".join(str(t) for t in tags)
    if parsed.quiet and ("安静" in tag_text or "清净" in tag_text or "可自习" in tag_text):
        adjustment += 0.04
    if parsed.accessible and ("无障碍" in tag_text or "有电梯" in tag_text):
        adjustment += 0.03
    if parsed.parking and ("停车" in tag_text or (poi.get("raw") or {}).get("biz_ext", {}).get("parking_type")):
        adjustment += 0.03
    if parsed.avoid_chain and is_chain(poi):
        adjustment -= 0.10
    focus = [str(item) for item in (parsed.focus_keywords or [])]
    if focus and category in ("restaurant", "night_snack", "tea"):
        focus_text = str(poi.get("name") or "") + " " + " ".join(str(t) for t in tags)
        if any(word in focus_text for word in focus):
            adjustment += 0.12
        else:
            adjustment -= 0.04
    cost = poi.get("cost")
    if parsed.budget_per_person and cost is not None:
        over = float(cost) - float(parsed.budget_per_person)
        if over > 0:
            adjustment -= min(0.12, 0.02 + over / max(1.0, float(parsed.budget_per_person)) * 0.10)
    final = min(1.0, max(0.0, base + adjustment))
    parts["base"] = base
    parts["adjustment"] = adjustment
    parts["final"] = final
    return final, parts


def _pick_reason_tag(poi: Dict[str, Any], parsed: ParsedQuery) -> Optional[str]:
    tags = [str(t) for t in (poi.get("tags") or [])]
    preferred = []
    if parsed.quiet:
        preferred.extend(["安静", "可久坐", "可自习", "清净"])
    if parsed.parking:
        preferred.extend(["有停车位", "停车"])
    if parsed.accessible:
        preferred.extend(["有电梯", "无障碍"])
    if parsed.budget_per_person:
        preferred.extend(["免费"])
    preferred.extend(["可久坐", "安静", "免费", "夜景", "适合散步", "本地口味"])
    for tag in preferred:
        for actual in tags:
            if tag in actual:
                return actual
    return tags[0] if tags else None


def build_reason(
    candidate: Candidate,
    parsed: ParsedQuery,
    *,
    minutes: Optional[int] = None,
    distance_m: Optional[float] = None,
) -> str:
    """一句话推荐理由，必须同时引用类目、距离、评分。"""
    poi = candidate.poi
    label = category_label(candidate.category)
    tag = _pick_reason_tag(poi, parsed)
    transport_label = geo.MODE_LABEL.get(parsed.transport, "步行")
    shown_distance = float(distance_m if distance_m is not None else candidate.distance_m)
    shown_minutes = minutes if minutes is not None else (candidate.walk_minutes or geo.walk_minutes(shown_distance))
    first = label + ("「%s」" % tag if tag else "")
    second = "%s约 %d 分钟（%s）" % (
        transport_label,
        shown_minutes if shown_minutes else 1,
        geo.format_distance(shown_distance),
    )
    bits = [first, second]
    rating = poi.get("rating")
    if rating is None:
        bits.append("评分暂无（按 3.8 中性计）")
    else:
        bits.append("评分 %.1f" % float(rating))
    cost = poi.get("cost")
    if cost is not None and parsed.budget_per_person:
        delta = float(parsed.budget_per_person) - float(cost)
        if delta >= 0:
            bits.append("人均 %.0f 元，在 %d 元预算内" % (float(cost), int(parsed.budget_per_person)))
        else:
            bits.append("人均 %.0f 元，超出预算约 %.0f 元" % (float(cost), -delta))
    elif cost is not None:
        bits.append("人均 %.0f 元" % float(cost))
    if parsed.quiet and ("安静" in " ".join(poi.get("tags") or [])):
        bits.append("符合「安静」要求")
    focus = [str(item) for item in (parsed.focus_keywords or [])]
    focus_text = str(poi.get("name") or "") + " " + " ".join(str(t) for t in (poi.get("tags") or []))
    if focus and any(word in focus_text for word in focus):
        bits.append("对口「%s」" % next(word for word in focus if word in focus_text))
    return "，".join(bits) + "。"


def diversify(
    candidates: Sequence[Candidate],
    limit: int = 5,
    max_per_category: int = MAX_PER_CATEGORY,
    min_separation_m: float = MIN_SEPARATION_M,
) -> Tuple[List[Candidate], List[str]]:
    """贪心多样性选择：同类目最多 2 个、候选间直线距离 > 150m。"""
    notes: List[str] = []
    ordered = sorted(candidates, key=lambda c: (-c.score, c.poi_id))

    def pick(max_cat: int, min_sep: float) -> List[Candidate]:
        chosen: List[Candidate] = []
        counts: Dict[str, int] = {}
        for candidate in ordered:
            if len(chosen) >= limit:
                break
            if counts.get(candidate.category, 0) >= max_cat:
                continue
            lng, lat = candidate.poi.get("lng"), candidate.poi.get("lat")
            too_close = False
            if lng is not None and lat is not None:
                for picked in chosen:
                    lng2, lat2 = picked.poi.get("lng"), picked.poi.get("lat")
                    if lng2 is None or lat2 is None:
                        continue
                    if geo.haversine_m((lng, lat), (lng2, lat2)) < min_sep:
                        too_close = True
                        break
            if too_close:
                continue
            chosen.append(candidate)
            counts[candidate.category] = counts.get(candidate.category, 0) + 1
        return chosen

    chosen = pick(max_per_category, min_separation_m)
    if len(chosen) < min(3, len(ordered)):
        relaxed = pick(max_per_category, RELAXED_SEPARATION_M)
        if len(relaxed) > len(chosen):
            chosen = relaxed
            notes.append("候选距离较近，已放宽 150 米间距要求")
    if len(chosen) < min(3, len(ordered)):
        relaxed = pick(3, RELAXED_SEPARATION_M)
        if len(relaxed) > len(chosen):
            chosen = relaxed
            notes.append("同类目候选不足，已放宽「同类目最多 2 个」限制")
    if len(chosen) < limit:
        picked_ids = {c.poi_id for c in chosen}
        relaxed_again = False
        for candidate in ordered:
            if len(chosen) >= limit:
                break
            if candidate.poi_id in picked_ids:
                continue
            lng, lat = candidate.poi.get("lng"), candidate.poi.get("lat")
            if lng is not None and lat is not None:
                for picked in chosen:
                    lng2, lat2 = picked.poi.get("lng"), picked.poi.get("lat")
                    if lng2 is None or lat2 is None:
                        continue
                    if geo.haversine_m((lng, lat), (lng2, lat2)) < RELAXED_SEPARATION_M:
                        relaxed_again = True
                        break
            chosen.append(candidate)
            picked_ids.add(candidate.poi_id)
        if relaxed_again and "候选间距偏近，已放宽 150 米间距要求" not in notes:
            notes.append("候选间距偏近，已放宽 150 米间距要求")
    return chosen, notes


def recommend(
    client: amap_client.AmapClient,
    parsed: ParsedQuery,
    origin: Tuple[float, float],
    *,
    top: int = 5,
    now: Optional[datetime] = None,
    deadline: Optional[amap_client.Deadline] = None,
    max_workers: int = 4,
) -> Dict[str, Any]:
    """完整推荐流程：召回 -> 去重 -> 过滤 -> 打分 -> 多样性 -> top N。"""
    now = now or datetime.now()
    recall_result = recall(client, parsed, origin, max_workers=max_workers, deadline=deadline)
    pois = recall_result["pois"]
    diagnostics: Dict[str, Any] = dict(recall_result["diagnostics"])
    degraded: List[str] = list(diagnostics.get("degraded") or [])
    radius_used = parsed.radius_m

    kept, dropped, filter_notes = filter_pois(pois, parsed, origin, radius=radius_used, now=now)
    degraded.extend(filter_notes)
    diagnostics["dropped"] = dropped[:20]
    diagnostics["filtered"] = len(kept)
    diagnostics["radius_used"] = radius_used

    # 无结果时自动扩大半径（最多一次，且不超过用户约束 / 3000 米）
    if not kept and not parsed.max_distance_m:
        expanded = min(MAX_RADIUS_M, max(parsed.radius_m * 2, 2000))
        if expanded > parsed.radius_m:
            diagnostics.setdefault("expansion", []).append({"from": parsed.radius_m, "to": expanded})
            degraded.append("周边 1000 米内没有结果，已自动扩大到 %d 米" % expanded)
            recall_result = recall(client, parsed, origin, radius=expanded, max_workers=max_workers, deadline=deadline)
            pois = recall_result["pois"]
            for key in ("queries", "errors", "recalled", "deduped"):
                diagnostics[key + "_expanded"] = recall_result["diagnostics"].get(key)
            radius_used = expanded
            kept, dropped, filter_notes = filter_pois(pois, parsed, origin, radius=radius_used, now=now)
            degraded.extend(filter_notes)
            diagnostics["filtered"] = len(kept)
            diagnostics["radius_used"] = radius_used

    candidates: List[Candidate] = []
    for poi, category, distance in kept:
        score, parts = score_poi(poi, category, distance, parsed, now)
        candidate = Candidate(
            poi=poi,
            category=category,
            distance_m=distance,
            score=score,
            parts=parts,
            walk_minutes=geo.walk_minutes(distance),
        )
        candidate.reason = build_reason(candidate, parsed)
        candidates.append(candidate)

    if not candidates:
        suggestions = [
            "换个更常见的类目，例如咖啡 / 餐厅 / 公园",
            "把范围放宽到 2000~3000 米，或补充更明确的地名",
            "换个交通方式（例如从步行改为骑行 / 公交）",
        ]
        return {
            "status": "no_result",
            "candidates": [],
            "diagnostics": diagnostics,
            "degraded": degraded,
            "suggestions": suggestions,
        }

    # 单类目查询时用户就是要这一类，不再限制"同类目最多 2 个"（否则凑不满 3 个候选）
    per_category = top if len(parsed.categories) <= 1 else MAX_PER_CATEGORY
    chosen, diversity_notes = diversify(candidates, limit=top, max_per_category=per_category)
    degraded.extend(diversity_notes)
    diagnostics["candidates_total"] = len(candidates)
    diagnostics["selected"] = len(chosen)
    diagnostics["degraded"] = degraded
    diagnostics["scoring"] = dict(SCORING_WEIGHTS)
    return {
        "status": "ok" if chosen else "no_result",
        "candidates": chosen,
        "diagnostics": diagnostics,
        "degraded": degraded,
        "suggestions": [],
    }
