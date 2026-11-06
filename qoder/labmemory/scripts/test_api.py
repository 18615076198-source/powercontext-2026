import httpx

base = "http://127.0.0.1:8000"
r = httpx.post(base + "/api/ask", json={"query": "我们为什么放弃 Self-RAG 的全量自反思？"}, timeout=30)
print("status", r.status_code, "encoding", r.encoding)
data = r.json()
print("QUERY:", data["trace"]["query"])
print("ANSWER:", data["answer"][:900])
print("MEMORIES:", len(data["memories"]), "CITATIONS:", len(data["citations"]))
for c in data["citations"][:5]:
    print("-", c["type"], c["title"][:60], c.get("section"), c.get("page"))
