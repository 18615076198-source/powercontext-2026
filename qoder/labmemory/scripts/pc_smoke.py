import json, urllib.request

BASE = "http://127.0.0.1:18080"

def post(path, payload):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())

scope = post("/v1/scopes", {
    "title": "LabMemory RAG 课题组",
    "summary": "RAG 低成本可追溯问答项目",
    "idempotency_key": "labmemory-scope-v1",
})
print("SCOPE", json.dumps(scope, ensure_ascii=False, indent=2))
sid = scope["scope_id"]

mem = post("/v1/memory/remember", {
    "scope_id": sid,
    "kind": "decision",
    "text": "我们不做 retriever fine-tune，先用 BM25 + DPR zero-shot 混合，原因是单卡 3090、要保证可复现。",
})
print("REMEMBER", json.dumps(mem, ensure_ascii=False, indent=2))

search = post("/v1/memory/search", {
    "scope_id": sid,
    "query": "为什么不做 retriever 微调",
    "limit": 5,
})
print("SEARCH", json.dumps(search, ensure_ascii=False, indent=2))

lst = post("/v1/memory/entries/list", {"scope_id": sid, "limit": 10})
print("LIST", json.dumps(lst, ensure_ascii=False, indent=2))
