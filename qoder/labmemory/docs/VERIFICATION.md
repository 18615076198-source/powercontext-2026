# 验证样例（Verification）

> 目标：评审按本文步骤，能在本机复现「seekdb 混合检索 + PowerContext 记忆」并核对技术确实发挥作用。
>
> 环境：WSL2 Ubuntu 22.04/24.04、Python 3.12、seekdb 1.4、PowerContext 1.5.0。完整启动见 README。

## 0. 初始数据

| 数据 | 数量 | 位置 |
|---|---|---|
| 真实 arXiv 论文 | 9 篇 | <code>data/papers/*.pdf</code> |
| 组会/实验笔记 | 8 条 | <code>data/notes/*.md</code> |
| seekdb chunk | 874 | 表 <code>labmemory.chunks</code> |
| PowerContext 记忆 | 8 条 | scope <code>PC_SCOPE_ID</code> |
| 冲突提醒 | 3 条 | 表 <code>labmemory.conflicts</code> |

导入命令：

~~~bash
~/venvs/labmemory/bin/python -m backend.seed.ingest --reset
~~~

预期输出：

~~~json
{
  "papers": 9,
  "chunks": 874,
  "memories_created": 8,
  "conflicts": {"created": 3, "scanned": 54, "candidates": 10},
  "counts": {"papers": 9, "notes": 8, "chunks": 874, "queries": 0, "conflicts": 3}
}
~~~

> 数值会随 chunk 策略微调略有变化；核心是 papers=9、memories=8、conflicts=3。

## 样例 1：记忆 + 原文，回答「为什么放弃 Self-RAG」

**输入**

~~~bash
curl -s -X POST http://127.0.0.1:8000/api/ask \
  -H 'Content-Type: application/json' \
  -d '{"query":"我们为什么放弃 Self-RAG 的全量自反思？"}' | python3 -m json.tool
~~~

**预期结果**

- <code>answer</code> 以「根据课题组记忆（decision）：暂不采用 Self-RAG 的全量自反思，端到端延迟约 2.3x…」开头。
- <code>citations</code> 同时包含：
  - 一条 <code>type=memory</code>，<code>artifact_id</code> 形如 <code>art_...</code>，<code>revision=1</code>；
  - 一条 <code>type=note</code>，标题「决策：暂不采用 Self-RAG 全量自反思」；
  - 一条 <code>type=paper</code>，Self-RAG 的「中文摘要」；
  - 一条 <code>type=paper</code>，Self-RAG 正文 <code>p.3</code>。
- <code>trace.bm25_count &gt; 0</code>、<code>trace.vector_count &gt; 0</code>、<code>trace.rrf_k = 60</code>。
- 页面截图：<code>docs/screenshots/ask.png</code>。

**技术作用记录**

- seekdb：BM25 与向量两路都返回候选（见 <code>trace</code> 和 <code>queries.trace_json</code>）。
- PowerContext：<code>memories[0].artifact_id @ revision</code> 可在记忆页/entries/list 核对。

## 样例 2：冲突提醒，DPR 论文 vs 「不 fine-tune retriever」决策

**输入**

~~~bash
curl -s http://127.0.0.1:8000/api/conflicts?status=open | python3 -m json.tool
~~~

**预期结果**

- 至少 3 条 open 冲突，其中包含：
  - Self-RAG 论文 ↔ Self-RAG 自反思决策；
  - Lost in the Middle 论文 ↔ 长上下文只做对照决策；
  - DPR 论文 ↔ 不 fine-tune retriever 决策。
- 每条有 <code>reason</code>（匹配的关键词组 + 被影响的记忆文本）和 <code>memory_artifact_id</code>。
- 页面截图：<code>docs/screenshots/conflicts.png</code>。

**操作**

- 点「生成复核任务」：调用 <code>POST /api/conflicts/{id}/review</code>，写入一条 <code>kind=review</code> 的 PowerContext 记忆，并把冲突标记为 reviewed。
- 点「忽略」：<code>POST /api/conflicts/{id}/dismiss</code>，冲突从 open 列表消失。

## 样例 3：写入新记忆，下一次提问能召回

**输入**

~~~bash
curl -s -X POST http://127.0.0.1:8000/api/memories \
  -H 'Content-Type: application/json' \
  -d '{"kind":"decision","text":"我们决定采用 RRF(k=60) 融合 BM25 与向量检索，因为混合检索的 recall@10 更高。"}'
~~~

**预期结果**

- 返回 <code>artifact_id</code>、<code>revision=1</code>、<code>state=active</code>。
- 再问「我们的混合检索融合参数是多少？」，回答里出现这条记忆，<code>memories</code> 数组包含该 artifact_id。
- 页面截图：<code>docs/screenshots/memory.png</code>。

## 样例 4：直接核对 seekdb（绕过应用）

~~~bash
mysql -h127.0.0.1 -P2881 -uroot labmemory -e "
SELECT COUNT(*) AS papers FROM papers;
SELECT COUNT(*) AS chunks FROM chunks;
SELECT source_title, section, page,
       MATCH(search_text, keywords) AGAINST ('Self-RAG') AS bm25
FROM chunks
WHERE MATCH(search_text, keywords) AGAINST ('Self-RAG') > 0
ORDER BY bm25 DESC LIMIT 5;"
~~~

**预期结果**

- <code>papers=9</code>，<code>chunks=874</code>。
- 命中行包含 Self-RAG 的 <code>p.3</code> 或中文摘要，<code>bm25 &gt; 0</code>。

向量路径：

~~~bash
mysql -h127.0.0.1 -P2881 -uroot labmemory -e "
SELECT id, source_title, l2_distance(embedding, '[0.1,0.2,...]') AS dist
FROM chunks ORDER BY dist ASC LIMIT 3;"
~~~

> 实际查询由应用计算 384 维 query 向量；上面的向量仅示意语法。

## 样例 5：直接核对 PowerContext（绕过应用）

~~~bash
SCOPE=$(grep '^PC_SCOPE_ID=' .env | cut -d= -f2)
curl -s -X POST http://127.0.0.1:18080/v1/memory/entries/list \
  -H 'Content-Type: application/json' \
  -d "{\"scope_id\":\"$SCOPE\",\"limit\":20}" | python3 -m json.tool
~~~

**预期结果**

- 返回 8 条 active 记忆，kind 包含 decision / constraint / progress / next_step。
- 每条有 <code>artifact.family=atomic-memory</code>、<code>artifact_id</code>、<code>revision</code>、<code>state</code>。
- 页面截图：<code>docs/screenshots/memory.png</code>。

## 样例 6：最近提问历史（Qoder 实现）

~~~bash
curl -s 'http://127.0.0.1:8000/api/history?limit=5' | python3 -m json.tool
pytest -q tests/test_api.py::test_history
~~~

**预期结果**

- <code>items</code> 返回最新 5 条 question / latency_ms / created_at。
- Dashboard 的「最近提问」显示这些记录；点击任意一条回到提问页并自动提交。
- <code>test_history</code> 1 passed；截图：<code>docs/screenshots/history.png</code>。

## 验收自检

- [x] 9 篇论文 PDF 存在，标题/链接可在 site 的「数据来源」核对。
- [x] <code>/api/health</code> 返回 seekdb=ok、powercontext=ok。
- [x] 提问返回记忆 + 论文/笔记引用；无外部 LLM。
- [x] 检索 trace 同时有 bm25_count、vector_count、rrf_k。
- [x] PowerContext 记忆可在 Dashboard 和 API 核对 artifact_id @ revision。
- [x] 冲突列表 3 条，可生成复核任务/忽略。
- [x] <code>/api/history</code> 返回最近提问；Dashboard 可点击重问；test_history passed。
- [x] 前端 5 页无控制台错误；截图见 <code>docs/screenshots/</code>。
- [x] README 启动步骤可复现；未提交真实密钥。
