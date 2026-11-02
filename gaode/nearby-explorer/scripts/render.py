"""Markdown 渲染：每条候选固定字段，方便直接贴到对话 / 文档里。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

if __package__:
    from . import geo
else:
    import geo  # type: ignore

MODE_LABEL = {"walking": "步行", "bicycling": "骑行", "transit": "公交", "driving": "驾车"}


def _fmt_money(value: Optional[float]) -> str:
    if value is None:
        return "暂无"
    if float(value) <= 0:
        return "免费"
    return "¥%d" % int(round(float(value)))


def _fmt_rating(value: Optional[float]) -> str:
    return "%.1f" % float(value) if value is not None else "暂无"


def _open_label(open_time: str, open_now: Optional[bool]) -> str:
    if not open_time:
        return "未知"
    if open_now is True:
        return "%s（营业中）" % open_time
    if open_now is False:
        return "%s（已打烊）" % open_time
    return open_time


def _header(result: Dict[str, Any]) -> List[str]:
    parsed = result.get("query") or {}
    origin = result.get("origin") or {}
    lines: List[str] = []
    title_bits = []
    if origin.get("name"):
        title_bits.append("「%s」" % origin["name"])
    title_bits.append("周边 %s" % geo.format_distance(parsed.get("radius_m") or 1000))
    labels = parsed.get("category_labels") or []
    if labels:
        title_bits.append("· " + " / ".join(labels))
    lines.append("### 附近推荐：%s" % " ".join(title_bits))
    lines.append("")

    summary = []
    if origin.get("name"):
        where = origin.get("name")
        if origin.get("district"):
            where += "（%s%s）" % (origin.get("city") or "", origin.get("district"))
        summary.append("位置「%s」" % where)
    elif origin.get("source") == "manual":
        summary.append("位置「指定坐标」")
    if labels:
        summary.append("类目 " + " / ".join(labels))
    summary.append("半径 %d 米" % int(parsed.get("radius_m") or 1000))
    summary.append("交通 " + MODE_LABEL.get(parsed.get("transport") or "walking", "步行"))
    if parsed.get("budget_per_person"):
        summary.append("预算 %d 元/人" % int(parsed["budget_per_person"]))
    if parsed.get("min_rating"):
        summary.append("评分 ≥ %.1f" % float(parsed["min_rating"]))
    if parsed.get("duration_minutes"):
        summary.append("停留 %d 分钟" % int(parsed["duration_minutes"]))
    if parsed.get("require_open"):
        summary.append("要求营业中")
    lines.append("> **解析**：" + "｜".join(summary))

    source = result.get("source") or {}
    if source.get("offline"):
        lines.append("> **模式**：离线模式（AMAP_MOCK=1，数据来自 fixtures/ 合成样例，不是实时结果）")
    else:
        lines.append("> **模式**：实时高德 Web 服务（Key %s）" % source.get("key_masked", "****"))
    stats = result.get("diagnostics") or {}
    lines.append(
        "> **统计**：召回 %s 个 POI，过滤后 %s 个，最终 %d 个候选，耗时 %.2fs"
        % (
            stats.get("recalled", 0),
            stats.get("filtered", 0),
            len(result.get("candidates") or []),
            float(result.get("elapsed_ms") or 0) / 1000.0,
        )
    )
    lines.append("")
    return lines


def _candidate_block(index: int, candidate: Dict[str, Any], parsed: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    rating = _fmt_rating(candidate.get("rating"))
    open_time = candidate.get("open_time") or ""
    open_now = candidate.get("open_now")
    walk_minutes = candidate.get("walk_minutes")
    distance = candidate.get("distance_m")
    routes = candidate.get("routes") or []
    route_distance = routes[0].get("distance_m") if routes else None
    shown_distance = route_distance or distance
    lines.append(
        "#### %d. %s　·　%s　·　⭐ %s"
        % (index, candidate.get("name"), candidate.get("category_label"), rating)
    )
    lines.append("")
    lines.append("- **类目**：%s" % candidate.get("category_label"))
    lines.append(
        "- **距离**：步行约 %s 分钟（%s%s）"
        % (
            walk_minutes if walk_minutes else "—",
            geo.format_distance(shown_distance),
            "，直线 %s" % geo.format_distance(distance) if route_distance and abs(route_distance - distance) >= 50 else "",
        )
    )
    cost = candidate.get("cost")
    budget = parsed.get("budget_per_person")
    cost_text = _fmt_money(cost)
    if cost is not None and budget:
        if float(cost) <= float(budget):
            cost_text += "（在 %d 元预算内）" % int(budget)
        else:
            cost_text += "（超预算 %d 元）" % int(float(cost) - float(budget))
    lines.append("- **评分**：%s ｜ **人均**：%s" % (rating, cost_text))
    lines.append("- **营业时间**：%s" % _open_label(open_time, open_now))
    lines.append("- **地址**：%s" % (candidate.get("address") or "地址暂缺"))
    lines.append("- **推荐理由**：%s" % (candidate.get("reason") or ""))
    if routes:
        lines.append("- **交通方案**（最多 2 种）：")
        for route_index, route in enumerate(routes[:2], 1):
            suffix = "（估算）" if route.get("estimated") else ""
            lines.append("  %d. %s%s" % (route_index, route.get("summary") or "", suffix))
    else:
        lines.append("- **交通方案**：暂不可用（已按直线距离估算）")
    links = candidate.get("links") or {}
    link_bits = []
    if links.get("marker"):
        link_bits.append("[查看地点](%s)" % links["marker"])
    if links.get("navigation"):
        link_bits.append("[导航过去](%s)" % links["navigation"])
    if link_bits:
        lines.append("- **高德链接**：" + " · ".join(link_bits))
    lines.append("")
    return lines


def _degraded_block(result: Dict[str, Any]) -> List[str]:
    notes = result.get("degraded") or []
    if not notes:
        return []
    lines = ["", "> **降级说明**："]
    for note in notes:
        lines.append("> - %s" % note)
    return lines


def _suggestions_block(result: Dict[str, Any]) -> List[str]:
    suggestions = result.get("suggestions") or []
    if not suggestions:
        return []
    lines = ["", "**下一步建议**："]
    for item in suggestions:
        lines.append("- %s" % item)
    return lines


def render_markdown(result: Dict[str, Any]) -> str:
    status = result.get("status")
    lines: List[str] = []
    if status == "ok":
        lines.extend(_header(result))
        candidates = result.get("candidates") or []
        if not candidates:
            lines.append("（没有找到合适的候选地点）")
        for index, candidate in enumerate(candidates, 1):
            lines.extend(_candidate_block(index, candidate, result.get("query") or {}))
        lines.extend(_degraded_block(result))
        lines.extend(_suggestions_block(result))
        return "\n".join(lines).rstrip() + "\n"

    if status == "need_location":
        lines.append("### 还需要一个位置")
        lines.append("")
        lines.append(result.get("message") or "请告诉我你想在哪个位置附近找。")
        lines.append("")
        for question in result.get("questions") or []:
            lines.append("- %s" % question)
        lines.extend(_suggestions_block(result))
        return "\n".join(lines).rstrip() + "\n"

    if status == "no_result":
        lines.append("### 没有找到合适的地点")
        lines.append("")
        lines.append(result.get("message") or "周边没有符合条件的候选地点。")
        lines.extend(_degraded_block(result))
        lines.extend(_suggestions_block(result))
        return "\n".join(lines).rstrip() + "\n"

    lines.append("### 查询失败")
    lines.append("")
    lines.append(result.get("message") or "调用高德服务时出错。")
    error = result.get("error") or {}
    if error:
        lines.append("")
        lines.append("- 错误码：%s" % (error.get("infocode") or "UNKNOWN"))
        lines.append("- 分类：%s" % (error.get("category") or "unknown"))
        if error.get("suggestion"):
            lines.append("- 建议：%s" % error["suggestion"])
    lines.extend(_suggestions_block(result))
    return "\n".join(lines).rstrip() + "\n"


def render_explain(result: Dict[str, Any]) -> str:
    lines = ["", "### 打分与召回诊断", ""]
    for candidate in result.get("candidates") or []:
        parts = candidate.get("score_parts") or {}
        lines.append(
            "- %s：总分 %.4f（距离 %.4f / 评分 %.4f / 人气 %.4f / 类目 %.4f / 营业 %.4f，调整 %+.3f）"
            % (
                candidate.get("name"),
                float(candidate.get("score") or 0),
                float(parts.get("distance") or 0),
                float(parts.get("rating") or 0),
                float(parts.get("popularity") or 0),
                float(parts.get("category") or 0),
                float(parts.get("open") or 0),
                float(parts.get("adjustment") or 0),
            )
        )
    diagnostics = result.get("diagnostics") or {}
    queries = diagnostics.get("queries") or []
    if queries:
        lines.append("")
        lines.append("召回明细：")
        for query in queries:
            status = ""
            if not query.get("ok", True):
                status = "（失败：%s）" % ((query.get("error") or {}).get("infocode") or "UNKNOWN")
            lines.append(
                "  - %s：types=%s keywords=%s 命中 %s 条%s"
                % (
                    query.get("category"),
                    query.get("types") or "-",
                    query.get("keywords") or "-",
                    query.get("returned"),
                    status,
                )
            )
    return "\n".join(lines)
