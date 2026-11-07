import os

import httpx

BASE = os.environ.get("LABMEMORY_BASE", "http://127.0.0.1:8000")


def test_health():
    data = httpx.get(BASE + "/api/health", timeout=10).json()
    assert data["seekdb"] == "ok"
    assert data["powercontext"] == "ok"
    assert data["counts"]["papers"] == 9
    assert data["counts"]["chunks"] > 100


def test_stats():
    data = httpx.get(BASE + "/api/stats", timeout=10).json()
    assert data["papers"] == 9
    assert data["notes"] == 8
    assert data["memories"] >= 8
    assert data["conflicts_open"] >= 3


def test_ask_selfrag_memory_and_citation():
    data = httpx.post(
        BASE + "/api/ask",
        json={"query": "我们为什么放弃 Self-RAG 的全量自反思？"},
        timeout=30,
    ).json()
    assert "暂不采用 Self-RAG" in data["answer"]
    types = {c["type"] for c in data["citations"]}
    assert "memory" in types
    assert "paper" in types
    assert data["trace"]["bm25_count"] > 0
    assert data["trace"]["vector_count"] > 0
    assert data["trace"]["rrf_k"] == 60
    assert data["memories"][0]["artifact_id"].startswith("art_")
    assert data["memories"][0]["revision"] == 1


def test_conflicts_are_diverse():
    data = httpx.get(BASE + "/api/conflicts?status=open", timeout=10).json()
    assert len(data["conflicts"]) == 3
    papers = {c["paper_id"] for c in data["conflicts"]}
    assert "2310.11511" in papers
    assert "2004.04906" in papers
    assert "2307.03172" in papers


def test_memories_list():
    data = httpx.get(BASE + "/api/memories", timeout=10).json()
    assert len(data["entries"]) >= 8
    kinds = {e["kind"] for e in data["entries"]}
    assert "decision" in kinds
    assert "constraint" in kinds


def test_search_filter_paper_only():
    data = httpx.post(
        BASE + "/api/search",
        json={"query": "Self-RAG reflection", "filters": {"source_type": "paper"}, "top_k": 3},
        timeout=30,
    ).json()
    assert data["results"]
    assert all(r["source_type"] == "paper" for r in data["results"])


def test_history():
    question = "history probe: chunk size 定在多少，依据是什么？"
    httpx.post(BASE + "/api/ask", json={"query": question}, timeout=30).raise_for_status()
    data = httpx.get(BASE + "/api/history?limit=20", timeout=10).json()
    items = data["items"]
    assert items
    assert len(items) <= 20
    assert any(item["question"] == question for item in items)
    hit = next(item for item in items if item["question"] == question)
    assert isinstance(hit["created_at"], str) and hit["created_at"]
    assert hit["latency_ms"] is not None
