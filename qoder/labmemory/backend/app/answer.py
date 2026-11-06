from __future__ import annotations

import logging
import re
import time
from typing import Any

from . import memory
from .search import hybrid_search, log_query

log = logging.getLogger(__name__)


def _clean(text: str, limit: int = 320) -> str:
    text = " ".join((text or "").split())
    text = re.sub(r"^#+\s*", "", text)
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


def _memory_citation(hit: dict[str, Any]) -> dict[str, Any]:
    mem = hit.get("memory", {})
    art = mem.get("artifact", {})
    return {
        "type": "memory",
        "title": f"PowerContext 记忆 · {mem.get('kind', 'memory')}",
        "section": "记忆",
        "page": None,
        "snippet": _clean(mem.get("text", ""), 360),
        "url": "",
        "artifact_id": art.get("artifact_id", ""),
        "revision": art.get("revision"),
        "matched_by": hit.get("matched_by", []),
        "score": hit.get("score"),
    }


def _result_citation(item: dict[str, Any]) -> dict[str, Any]:
    kind = "论文" if item["source_type"] == "paper" else "笔记"
    section = item.get("section") or kind
    return {
        "type": item["source_type"],
        "title": item["title"],
        "section": section,
        "page": item.get("page"),
        "snippet": _clean(item.get("snippet", "")),
        "url": item.get("url", ""),
        "chunk_id": item.get("chunk_id"),
        "rrf": item.get("rrf"),
        "routes": item.get("routes", []),
        "ranks": item.get("ranks", {}),
        "scores": item.get("scores", {}),
    }


def _evidence_line(item: dict[str, Any]) -> str:
    title = item["title"]
    section = item.get("section") or ""
    page = item.get("page")
    snippet = _clean(item.get("snippet", ""), 260)
    if item["source_type"] == "note":
        return f"笔记《{title}》提到：{snippet}"
    if section == "中文摘要":
        return f"《{title}》的中文摘要：{snippet}"
    loc = section or ""
    if page and not loc.startswith("p."):
        loc = (loc + " ") if loc else ""
        loc += f"（p.{page}）"
    return f"《{title}》{loc}：{snippet}"


def answer_question(query: str, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    query = (query or "").strip()
    if not query:
        return {
            "answer": "请输入一个问题。",
            "citations": [],
            "memories": [],
            "trace": {"error": "empty query"},
            "latency_ms": 0,
        }

    memories: list[dict[str, Any]] = []
    memory_error = None
    try:
        memories = memory.client.search(query, limit=5)
    except Exception as exc:  # noqa: BLE001
        memory_error = str(exc)[:300]
        log.warning("PowerContext recall failed: %s", memory_error)

    search = hybrid_search(query, filters=filters, top_k=6)
    results = search["results"]
    trace = search["trace"]
    trace["memory_count"] = len(memories)
    trace["memory_error"] = memory_error

    citations: list[dict[str, Any]] = []
    lines: list[str] = []

    for hit in memories[:1]:
        citations.append(_memory_citation(hit))
        text = _clean(hit.get("memory", {}).get("text", ""), 300)
        if text:
            lines.append(f"根据课题组记忆（{hit.get('memory', {}).get('kind', 'memory')}）：{text}")

    evidence = [r for r in results if r.get("source_type") in ("paper", "note")][:3]
    if evidence:
        if lines:
            lines.append("相关证据：")
        else:
            lines.append("根据当前资料库，找到以下证据：")
        for item in evidence:
            citations.append(_result_citation(item))
            lines.append("- " + _evidence_line(item))

    if not lines:
        answer = "没有在当前资料库中找到足够证据。建议换一个关键词，或先补充相关论文/组会笔记。"
    else:
        answer = "\n".join(lines)
        answer += "\n\n以上为本地抽取式回答，只引用检索到的原文；未使用外部 LLM。"

    latency_ms = int((time.perf_counter() - started) * 1000)
    trace["latency_ms"] = latency_ms
    log_query(query, filters, trace, latency_ms)
    return {
        "answer": answer,
        "citations": citations,
        "memories": [
            {
                "kind": h.get("memory", {}).get("kind"),
                "text": h.get("memory", {}).get("text"),
                "artifact_id": h.get("memory", {}).get("artifact", {}).get("artifact_id"),
                "revision": h.get("memory", {}).get("artifact", {}).get("revision"),
                "score": h.get("score"),
                "matched_by": h.get("matched_by", []),
            }
            for h in memories
        ],
        "trace": trace,
        "latency_ms": latency_ms,
    }