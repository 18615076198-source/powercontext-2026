import httpx
import pymysql

conn = pymysql.connect(host="127.0.0.1", port=2881, user="root", password="", database="labmemory", autocommit=True)
with conn.cursor() as cur:
    cur.execute("DELETE FROM queries")
conn.close()

BASE = "http://127.0.0.1:8000"
questions = [
    "我们为什么放弃 Self-RAG 的全量自反思？",
    "DPR 的 fine-tune 结果会不会影响我们不做 retriever 微调的决定？",
    "长上下文模型能不能替代 RAG？",
    "chunk size 最后定了多少，依据是什么？",
]
for q in questions:
    r = httpx.post(BASE + "/api/ask", json={"query": q}, timeout=60)
    print(r.status_code, q, r.json().get("latency_ms"))
