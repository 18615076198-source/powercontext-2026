import httpx, json, time

base = "http://127.0.0.1:8000"
for _ in range(20):
    try:
        h = httpx.get(base + "/api/health", timeout=3).json()
        break
    except Exception:
        time.sleep(0.5)
print("HEALTH", h)
r = httpx.post(base + "/api/conflicts/rescan", timeout=30)
print("RESCAN", r.json())
c = httpx.get(base + "/api/conflicts?status=open", timeout=20).json()["conflicts"]
print("CONFLICTS", len(c))
for x in c:
    print("-", x["paper_id"], x["paper_title"][:55], "|", x["reason"][:100])
r = httpx.post(base + "/api/ask", json={"query": "我们为什么放弃 Self-RAG 的全量自反思？"}, timeout=30).json()
print("ANSWER", r["answer"][:700])
print("CITES", [(x["type"], x["title"][:40], x["section"], x["page"]) for x in r["citations"]])
