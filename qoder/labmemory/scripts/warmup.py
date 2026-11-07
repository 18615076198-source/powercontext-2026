import time
import httpx

start = time.time()
r = httpx.post(
    "http://127.0.0.1:8000/api/ask",
    json={"query": "我们为什么放弃 Self-RAG 的全量自反思？"},
    timeout=120,
)
print("status", r.status_code, "elapsed", round(time.time() - start, 2))
print(r.json().get("answer", "")[:120])
