import httpx
for item in httpx.get("http://127.0.0.1:8000/api/history?limit=5", timeout=10).json()["items"]:
    print(item["id"], "|", item["question"][:70], "|", item["latency_ms"], "ms |", item["created_at"])
