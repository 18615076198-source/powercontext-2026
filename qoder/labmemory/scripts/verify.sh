#!/usr/bin/env bash
# Quick acceptance check for the demo environment.
set -euo pipefail
BASE="${BASE:-http://127.0.0.1:8000}"

echo "== health =="
curl -s "$BASE/api/health" | python3 -m json.tool

echo
echo "== stats =="
curl -s "$BASE/api/stats" | python3 -m json.tool

echo
echo "== ask: Self-RAG memory =="
curl -s -X POST "$BASE/api/ask" \
  -H 'Content-Type: application/json' \
  -d '{"query":"我们为什么放弃 Self-RAG 的全量自反思？"}' \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["answer"][:700]); print("citations:", [(c["type"], c["title"][:40], c["section"]) for c in d["citations"]]); print("memory_refs:", [(m["artifact_id"], m["revision"]) for m in d["memories"]]); print("trace:", {k:d["trace"][k] for k in ("bm25_count","vector_count","rrf_k","latency_ms")})'

echo
echo "== conflicts =="
curl -s "$BASE/api/conflicts?status=open" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("open conflicts:", len(d["conflicts"])); [print("-", c["paper_id"], c["paper_title"][:60]) for c in d["conflicts"]]'
