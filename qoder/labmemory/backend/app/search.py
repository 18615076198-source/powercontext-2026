from __future__ import annotations

import json
import logging
import time
from typing import Any

import pymysql

from . import db
from .embeddings import embed_query, vector_literal

log = logging.getLogger(__name__)

BM25_LIMIT = 30
VECTOR_LIMIT = 30
RRF_K = 60


def _filter_sql(filters: dict[str, Any] | None) -> tuple[str, list[Any]]:
    filters = filters or {}
    clauses: list[str] = []
    params: list[Any] = []

    source_type = filters.get("source_type")
    if source_type in ("paper", "note"):
        clauses.append("source_type = %s")
        params.append(source_type)

    paper_id = filters.get("paper_id")
    if paper_id:
        clauses.append("source_type = 'paper' AND source_id = %s")
        params.append(paper_id)

    year_gte = filters.get("year_gte")
    if year_gte:
        clauses.append("year >= %s")
        params.append(int(year_gte))

    tag = filters.get("tag")
    if tag:
        clauses.append("tags LIKE %s")
        params.append(f"%{tag}%")

    where = (" AND " + " AND ".join(clauses)) if clauses else ""
    return where, params


def _decorate(row: dict[str, Any], route: str, rank: int, score: float | None) -> dict[str, Any]:
    content = (row.get("content") or "").strip()
    snippet = " ".join(content.split())
    if len(snippet) > 280:
        snippet = snippet[:280].rstrip() + "…"
    item = {
        "chunk_id": row["id"],
        "source_type": row["source_type"],
        "source_id": row["source_id"],
        "title": row.get("source_title") or row["source_id"],
        "section": row.get("section") or "",
        "page": row.get("page"),
        "year": row.get("year"),
        "tags": row.get("tags") or "",
        "snippet": snippet,
        "content": content,
        "url": row.get("source_url") or "",
        "routes": [route],
        "ranks": {route: rank},
        "scores": {route: score},
    }
    return item


def hybrid_search(
    query: str,
    filters: dict[str, Any] | None = None,
    top_k: int = 6,
) -> dict[str, Any]:
    started = time.perf_counter()
    top_k = max(1, min(int(top_k or 6), 12))
    query = (query or "").strip()
    if not query:
        return {"results": [], "trace": {"error": "empty query"}, "latency_ms": 0}

    where, filter_params = _filter_sql(filters)
    query_vec = vector_literal(embed_query(query))

    bm25_rows: list[dict[str, Any]] = []
    bm25_error = None
    bm25_sql = f"""
        SELECT id, source_type, source_id, source_title, source_url, section, page, year, tags,
               content, MATCH(search_text, keywords) AGAINST (%s) AS bm25
        FROM chunks
        WHERE MATCH(search_text, keywords) AGAINST (%s) > 0 {where}
        ORDER BY bm25 DESC
        LIMIT {BM25_LIMIT}
    """
    try:
        bm25_rows = db.fetch_all(bm25_sql, [query, query, *filter_params])
    except pymysql.MySQLError as exc:
        bm25_error = str(exc)[:300]
        log.warning("BM25 route failed (falling back to vector): %s", bm25_error)

    vector_rows: list[dict[str, Any]] = []
    vector_error = None
    vector_sql = f"""
        SELECT id, source_type, source_id, source_title, source_url, section, page, year, tags,
               content, l2_distance(embedding, %s) AS dist
        FROM chunks
        WHERE 1=1 {where}
        ORDER BY dist ASC
        LIMIT {VECTOR_LIMIT}
    """
    try:
        vector_rows = db.fetch_all(vector_sql, [query_vec, *filter_params])
    except pymysql.MySQLError as exc:
        vector_error = str(exc)[:300]
        log.warning("vector route failed: %s", vector_error)

    merged: dict[int, dict[str, Any]] = {}
    for rank, row in enumerate(bm25_rows, start=1):
        merged[row["id"]] = _decorate(row, "bm25", rank, float(row.get("bm25") or 0))
    for rank, row in enumerate(vector_rows, start=1):
        item = merged.get(row["id"])
        if item is None:
            item = _decorate(row, "vector", rank, float(row.get("dist") or 0))
            merged[row["id"]] = item
        else:
            item["routes"].append("vector")
            item["ranks"]["vector"] = rank
            item["scores"]["vector"] = float(row.get("dist") or 0)

    for item in merged.values():
        score = 0.0
        for route, rank in item["ranks"].items():
            score += 1.0 / (RRF_K + rank)
        item["rrf"] = round(score, 6)

    results = sorted(merged.values(), key=lambda x: x["rrf"], reverse=True)[:top_k]
    latency_ms = int((time.perf_counter() - started) * 1000)
    trace = {
        "query": query,
        "filters": filters or {},
        "bm25_count": len(bm25_rows),
        "vector_count": len(vector_rows),
        "merged_count": len(merged),
        "bm25_error": bm25_error,
        "vector_error": vector_error,
        "rrf_k": RRF_K,
        "latency_ms": latency_ms,
        "sql": {
            "bm25": "MATCH(search_text, keywords) AGAINST (?) ORDER BY bm25 DESC",
            "vector": "ORDER BY l2_distance(embedding, ?) ASC",
        },
    }
    return {"results": results, "trace": trace, "latency_ms": latency_ms}


def log_query(question: str, filters: dict[str, Any] | None, trace: dict[str, Any], latency_ms: int) -> None:
    try:
        db.execute(
            "INSERT INTO queries (question, filters_json, trace_json, latency_ms) VALUES (%s, %s, %s, %s)",
            (
                question[:2000],
                json.dumps(filters or {}, ensure_ascii=False),
                json.dumps(trace, ensure_ascii=False)[:60000],
                latency_ms,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        log.info("query log skipped: %s", exc)
