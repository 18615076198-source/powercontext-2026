# 架构说明（Architecture）

## 1. 目标与非目标

**目标**：让科研小组在提问时同时拿到「原文证据」和「当时的决定」，并能在新论文出现时提示复核。

**非目标**：多用户权限、自动爬取 arXiv、表格/公式高精度解析、外部 LLM 生成、生产级高可用。

## 2. 组件

~~~mermaid
flowchart TB
  subgraph UI[前端 · HTML/CSS/JS]
    D[工作台]
    A[提问]
    L[资料库]
    M[记忆]
    C[冲突]
  end
  subgraph API[FastAPI]
    ASK[/api/ask/]
    SEARCH[/api/search/]
    MEM[/api/memories/]
    CONF[/api/conflicts/]
  end
  subgraph DATA[数据层]
    S[(seekdb 1.4<br/>labmemory)]
    P[(PowerContext 1.5<br/>SQLite + scope)]
  end
  D --> ASK
  A --> ASK
  A --> SEARCH
  L --> S
  M --> MEM
  C --> CONF
  ASK --> S
  ASK --> P
  SEARCH --> S
  MEM --> P
  CONF --> P
  CONF --> S
~~~

| 组件 | 职责 |
|---|---|
| 前端 | 5 个页面；调用 <code>/api/*</code>；不直连数据库 |
| FastAPI | 参数校验、检索编排、记忆召回、冲突扫描、静态文件 |
| seekdb | papers/notes/chunks/queries/conflicts；FULLTEXT + VECTOR + 标量索引 |
| PowerContext | scope 级显式记忆（decision/constraint/progress/next_step/review） |
| fastembed | 多语言 384 维 embedding，CPU/ONNX，无外部 API |

## 3. 数据模型（seekdb）

~~~sql
papers(id, arxiv_id, title, authors, published, abstract, summary_zh, keywords_zh, tags, pdf_path)
notes(id, title, kind, project, note_date, content, tags)
chunks(id, source_type, source_id, source_title, source_url, chunk_index,
       section, page, year, tags, content, search_text, keywords,
       embedding VECTOR(384),
       FULLTEXT INDEX ft_chunks(search_text, keywords),
       VECTOR INDEX vidx_chunks(embedding) WITH (distance=L2, type=hnsw))
queries(id, question, filters_json, trace_json, latency_ms, created_at)
conflicts(id, paper_id, memory_artifact_id, memory_revision, memory_text, reason, status)
~~~

设计要点：

- 每篇论文额外生成 1 个「中文摘要」chunk，解决中文 query 对英文 PDF 的召回问题。
- 每个 chunk 保留 <code>source_title/section/page</code>，回答可精确引用。
- embedding 归一化后用 L2；L2 与 cosine 排序等价。
- 中文 BM25 可能为 0；检索失败时降级为纯向量，不返回 500。

## 4. 导入链路

~~~text
PDF ──PyMuPDF──> 页文本 ──按段落/句子切分──> chunk (500-700 chars)
  └─ 元数据 + 中文摘要 ──> summary chunk
笔记 Markdown ──frontmatter + 正文──> chunk
所有 text ──fastembed──> 384 维向量 ──批量 INSERT──> seekdb
论文/笔记 ──> PowerContext 8 条显式记忆 ──> 冲突扫描
~~~

- <code>--reset</code> 清空 chunks/papers/notes/conflicts，不删除 PowerContext 记忆（按文本幂等去重）。
- 首次运行下载 220MB 模型；之后离线可跑。

## 5. 混合检索

输入：query、可选 filters（source_type / paper_id / year_gte / tag）。

1. query -> 384 维向量（归一化）。
2. BM25 路：
   ~~~sql
   SELECT ..., MATCH(search_text, keywords) AGAINST (%s) AS bm25
   FROM chunks
   WHERE MATCH(search_text, keywords) AGAINST (%s) > 0
   ORDER BY bm25 DESC LIMIT 30;
   ~~~
3. 向量路：
   ~~~sql
   SELECT ..., l2_distance(embedding, %s) AS dist
   FROM chunks
   WHERE ... ORDER BY dist ASC LIMIT 30;
   ~~~
4. RRF：<code>score = 1/(60+bm25_rank) + 1/(60+vec_rank)</code>；合并去重，取 top_k。
5. 返回 trace：两路候选数、每路排名、RRF、耗时、错误（若有）。

为什么用 RRF：BM25 擅长方法名/术语，向量擅长中文语义；两路分数不可直接比较，RRF 只依赖排名，稳定且无需调参。

## 6. PowerContext 记忆

- 每个课题一个 scope；本 demo 用 <code>labmemory-demo-v1</code> 幂等创建。
- 8 条 seed 记忆，kind 为 decision/constraint/progress/next_step。
- 提问时 <code>POST /v1/memory/search</code>（mode=auto，失败回退 fts），取 top 5；回答只引用 top 1，侧栏展示全部命中。
- 回答/记忆页显示 <code>artifact_id @ revision</code>，可直接在 Dashboard 或 <code>/v1/memory/entries/list</code> 核对。
- 记忆写入 API 不调用生成模型（Basic memory）；不需要外部 Key。

## 7. 冲突提醒

- 对每篇论文与每条 active decision/constraint，按 7 组关键词匹配（retriever 微调、Self-RAG、长上下文、纠错、自适应、混合检索、延迟/成本）。
- 组有 weight；只保留有强/中权重命中的候选；按 score 排序。
- 同时限制「每篇论文最多 1 条、每条记忆最多 1 条」，最多 4 条，避免噪声。
- reason 写明命中的组、关键词和被影响的记忆文本；用户可 dismiss 或生成 review 记忆。
- 规则透明、可解释，不依赖 LLM。

## 8. 失败与降级

| 故障 | 行为 |
|---|---|
| seekdb 未启动 | <code>/api/health</code> 返回 seekdb=down；页面提示 |
| BM25 中文分词失败 | 记录 <code>bm25_error</code>，仅走向量路 |
| PowerContext 不可用 | 回答仍返回检索证据；<code>memory_error</code> 写入 trace；记忆页 503 |
| embedding 模型缺失 | 首次运行自动下载；失败则启动报错，README 给出镜像配置 |
| 前端 fetch 失败 | toast + 空状态，不白屏 |

## 9. 安全与隐私

- 不提交真实 API Key/密码；<code>.env</code> 在 <code>.gitignore</code>。
- PowerContext 默认只监听 127.0.0.1，access mode disabled，仅本机演示。
- 论文为公开 arXiv；笔记为演示场景数据，不含真实个人信息。
- 前端对 API 数据做 HTML 转义，避免 XSS。

## 10. 目录

~~~text
backend/app/
  config.py     环境变量
  db.py         seekdb 连接/建表/统计
  schema.sql    表结构
  embeddings.py fastembed 封装
  search.py     BM25 + 向量 + RRF + trace
  answer.py     记忆召回 + 抽取式回答 + 引用
  memory.py     PowerContext HTTP 客户端
  conflicts.py  规则版冲突扫描
  main.py       FastAPI 路由 + 静态托管
backend/seed/
  papers.json   9 篇论文元数据 + 中文摘要
  ingest.py     PDF/笔记导入 + 记忆 seed
frontend/
  index.html / styles.css / app.js
site/           Qoder Sites 展示站
docs/           验证、架构、Qoder 记录、截图
~~~
