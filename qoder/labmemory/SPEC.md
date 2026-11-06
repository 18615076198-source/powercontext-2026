# LabMemory（研忆）— 产品与工程规格

> 一句话：把「读过什么、为什么这么定、导师说过什么」变成可检索、可追溯、会提醒的课题组记忆。
>
> 参赛方向：OceanBase 大赛 Qoder 赛题 · 学习科研 / 工作提效
> 核心技术：seekdb（混合检索）+ PowerContext（显式记忆与召回）
> 约束：2 天内交付可运行 MVP；不依赖外部 LLM/API；论文必须是真实存在的 arXiv 论文。

## 1. 用户与痛点

目标用户：3-8 人的研究生/本科生科研小组。

真实痛点：
- 组会前要翻几十篇 PDF、几周的聊天记录，才能找回「上次为什么放弃这个方法」。
- 决策、约束、实验结论散落在会议纪要和个人笔记里；新人重复踩坑。
- 普通论文问答只给一段话，不能定位到段落/页码，也不能记住组内已经做过的决定。

## 2. MVP 范围

必须做：
1. 导入 9 篇真实 arXiv 论文（PDF）+ 8 条组会/实验笔记（Markdown）。
2. seekdb 混合检索：BM25 全文 + 向量 + 标量过滤，RRF 融合，结果带出处（论文/笔记、章节、页码、片段）。
3. PowerContext 记忆：显式写入决策/约束/进度/待办；搜索时召回；UI 展示 artifact_id/revision。
4. 证据型回答：本地抽取式摘要，只引用检索到的原文；没有证据就明确说找不到。
5. 冲突提醒：新论文与既有决策相关时，提示「可能影响决策，建议复核」。
6. 3 个页面：工作台 Dashboard、提问 Ask、资料库 Library、记忆 Memory（可用 tab 切换）。
7. Qoder Sites 展示站（单独静态站，不要求公网运行后端）。

不做（MVP 之外）：
- 多用户登录/权限；真实 PDF 上传（用 seed 脚本导入即可）。
- 自动爬取 arXiv；PDF 表格/公式高精度解析。
- 外部 LLM 生成（保留可选接口，但默认关闭）。
- 移动端深度适配（响应式即可）。

## 3. 技术栈与运行环境

- OS：Windows 11 + WSL2 Ubuntu（开发/演示）；README 同时给出 Linux 步骤。
- seekdb：已在本机 WSL 运行，127.0.0.1:2881，root 无密码，数据库 `labmemory`。
- PowerContext 1.5.0：WSL 本地 Server，127.0.0.1:18080，SQLite 存储，Basic memory（无需模型 API）。
- Python 3.12，venv：`~/venvs/labmemory`。
- 后端：FastAPI + Uvicorn + PyMySQL + fastembed + PyMuPDF + httpx。
- 前端：原生 HTML/CSS/JS（无 Node 构建），由 FastAPI 静态托管。
- Embedding：`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`（384 维，多语言，fastembed/ONNX，CPU 可跑）。

## 4. 数据模型（seekdb）

数据库：`labmemory`，字符集 utf8mb4。

```sql
CREATE TABLE IF NOT EXISTS papers (
  id VARCHAR(32) PRIMARY KEY,
  arxiv_id VARCHAR(32) NOT NULL,
  title TEXT NOT NULL,
  authors TEXT,
  published DATE,
  abstract TEXT,
  summary_zh TEXT,
  keywords_zh VARCHAR(512),
  tags VARCHAR(255),
  pdf_path VARCHAR(512),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notes (
  id VARCHAR(64) PRIMARY KEY,
  title TEXT NOT NULL,
  kind VARCHAR(32),
  project VARCHAR(64),
  note_date DATE,
  content TEXT NOT NULL,
  tags VARCHAR(255),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chunks (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  source_type VARCHAR(16) NOT NULL,      -- paper | note
  source_id VARCHAR(64) NOT NULL,
  chunk_index INT NOT NULL,
  section VARCHAR(255),
  page INT,
  content TEXT NOT NULL,                 -- 原文，用于展示/引用
  search_text TEXT NOT NULL,             -- 用于全文索引：原文 + 中文摘要/关键词
  keywords VARCHAR(512),
  embedding VECTOR(384),
  FULLTEXT INDEX ft_chunks(search_text, keywords),
  VECTOR INDEX vidx_chunks(embedding) WITH (distance=L2, type=hnsw),
  INDEX idx_chunk_source(source_type, source_id)
);

CREATE TABLE IF NOT EXISTS queries (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  question TEXT NOT NULL,
  filters_json TEXT,
  trace_json TEXT,
  latency_ms INT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conflicts (
  id VARCHAR(64) PRIMARY KEY,
  paper_id VARCHAR(32) NOT NULL,
  memory_artifact_id VARCHAR(128) NOT NULL,
  memory_revision INT,
  memory_text TEXT,
  reason TEXT,
  status VARCHAR(16) DEFAULT 'open',     -- open | dismissed | reviewed
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

说明：
- 向量使用 L2 距离；embedding 先归一化，L2 等价于 cosine。
- 中文 query 的 BM25 可能为 0（seekdb 默认分词对中文不友好），检索必须能降级为向量召回；中文摘要 chunk 用于提升中文命中。
- 每篇论文额外生成 1 个 `section='中文摘要'` 的 chunk，content/summary 为 `summary_zh`，search_text 含中文摘要 + 关键词，便于中文 query 命中并给出来源。

## 5. 数据与导入

- `backend/seed/papers.json`：9 篇论文的真实 arXiv 元数据（title/authors/published/abstract）+ 人工中文摘要/关键词/tags。
- `data/papers/*.pdf`：9 个真实 PDF。
- `data/notes/*.md`：8 条演示场景笔记（YAML frontmatter + 正文）。**笔记是演示场景数据，论文和引用是真实的；实验数值需在 README/网站上标注「演示数据」。**
- 导入脚本 `backend/seed/ingest.py`：
  1. 建库建表（幂等）。
  2. 用 PyMuPDF 抽取每页文本；按章节标题/段落切 chunk（约 500-700 字符，overlap 80）。
  3. 每篇论文生成 1 个中文摘要 chunk。
  4. 笔记按段落切 chunk；search_text 加入标题/tags。
  5. fastembed 批量编码（batch 32），插入 seekdb。
  6. 调用 PowerContext 写入 8 条记忆（幂等，按 key 去重）；生成 conflicts。
  7. 输出统计：papers/chunks/memories/conflicts。
- 支持 `--reset` 清空 chunks/papers/notes/conflicts（不删库）。
- 编码缓存：`data/cache/embeddings.npz`（text hash -> vector），重复导入不重复编码。

## 6. 混合检索

输入：`query`、可选 filters（source_type、year_gte、tags、paper_id）。

步骤：
1. 编码 query（fastembed，normalize）。
2. BM25 路：
```sql
SELECT id, source_type, source_id, section, page, content,
       MATCH(search_text, keywords) AGAINST (%s) AS bm25
FROM chunks
WHERE MATCH(search_text, keywords) AGAINST (%s) > 0
  [AND source_type = %s] [AND ...]
ORDER BY bm25 DESC
LIMIT 30;
```
3. 向量路：
```sql
SELECT id, source_type, source_id, section, page, content,
       l2_distance(embedding, %s) AS dist
FROM chunks
[WHERE ...]
ORDER BY dist ASC
LIMIT 30;
```
4. RRF：`score = 1/(60+bm25_rank) + 1/(60+vec_rank)`；合并、按 score 降序。
5. 回表取 paper/note 元数据；返回 top_k（默认 6）+ trace：
   - bm25_rank / vec_rank / rrf_score
   - 耗时、候选数、SQL 摘要
6. 异常处理：BM25 失败（中文分词/语法）时记录 `bm25_error`，仅用向量路，不返回 500。

## 7. PowerContext 记忆

Server：`http://127.0.0.1:18080`，scope 由 `.env` 的 `PC_SCOPE_ID` 指定；启动时若为空，调用 `POST /v1/scopes` 创建并写回。

用到的接口：
- `POST /v1/scopes` {title, summary, idempotency_key} -> {scope_id}
- `POST /v1/memory/remember` {scope_id, kind, text} -> {records:[{artifact:{family,artifact_id,revision},...}]}
- `POST /v1/memory/search` {scope_id, query, limit, mode:"auto"} -> {mode, hits:[{memory,score,matched_by}]}
- `POST /v1/memory/entries/list` {scope_id, limit} -> {entries:[...]}
- 可选：`POST /v1/atomic-memory/lifecycle` 做 forget（MVP 可只展示，不实现删除）

记忆 seed（8 条）：
1. decision：不 fine-tune retriever，BM25 + DPR zero-shot；原因单卡 3090/可复现。关联 DPR 论文。
2. decision：chunk 512 + overlap 64，引用精确优先。
3. decision：暂不采用 Self-RAG 全量自反思，延迟 2.3x；保留按需检索。
4. decision：主方案仍是 RAG，长上下文只做对照；成本/可追溯/中间内容丢失。
5. decision：保留 BM25，RRF(k=60) 融合；纯向量 recall 不够。
6. constraint：离线可跑，embedding < 100MB，CPU 推理。
7. progress：已完成 9 篇论文入库 + 8 条笔记；下一步补 CRAG/Adaptive-RAG 对比。
8. next_step：找不到证据时明确说找不到，不硬编答案。

每条记忆在 UI 展示：kind、text、artifact_id（截断）、revision、state。搜索命中时显示 matched_by/score。

## 8. 证据型回答（无外部 LLM）

`answer.py`：
1. 调 `memory.search_memory(query)` 召回 top 3 记忆。
2. 调混合检索 top 4 chunks。
3. 组织回答：
   - 若命中记忆：`根据组会记忆（{kind}，{date?}）：{text}`
   - 若命中论文中文摘要：`《{title}》指出：{summary_zh}`
   - 若只有英文原文：`《{title}》{section}（p.{page}）提到：{snippet}`
   - 末尾：`以上为本地抽取式回答，只引用检索到的原文；未使用外部模型。`
4. 没有证据：`没有在当前资料库中找到足够证据；建议换关键词或补充论文/笔记。`
5. 返回 `citations`（source_type/source_id/title/section/page/snippet/url）和 `memories`、`trace`、`latency_ms`。

## 9. 冲突提醒

规则版（透明、可解释，不依赖 LLM）：
- 对每篇论文，取 tags + keywords_zh + 标题中的方法名；对每条 active 记忆，取文本中的关键词。
- 维护同义词组，例如：
  - `fine-tune` / `微调` / `DPR` / `dense-retrieval`
  - `Self-RAG` / `自反思` / `reflection` / `latency`
  - `long-context` / `长上下文` / `LongBench`
- 命中 >= 2 个关键词，且记忆 kind 为 decision/constraint，生成 conflict：
  `论文《{title}》涉及 {matched}，可能影响决策「{memory_text}」，建议复核。`
- 同一 (paper_id, artifact_id) 幂等。
- UI：Dashboard 顶部 conflict banner + 冲突列表；可 dismiss；可「生成复核任务」（写一条 kind=review 的 PowerContext 记忆）。

## 10. 后端 API（FastAPI）

统一前缀 `/api`，JSON；错误返回 `{detail}`。

- `GET /api/health` -> {seekdb:"ok", powercontext:"ok", scope_id, chunk_count}
- `GET /api/stats` -> {papers, notes, chunks, memories, conflicts_open, queries}
- `GET /api/papers` -> [{id,title,authors,published,tags,summary_zh,chunk_count}]
- `GET /api/papers/{id}` -> paper + chunks（分页可选）
- `GET /api/notes` -> [{id,title,kind,date,tags,content}]
- `POST /api/search` {query, filters?, top_k?} -> {results:[...], trace, latency_ms}
- `POST /api/ask` {query, filters?} -> {answer, citations, memories, trace, latency_ms}
- `GET /api/memories` -> {scope_id, entries:[{artifact_id,revision,kind,text,state}]}
- `POST /api/memories` {kind, text} -> same record
- `GET /api/conflicts` -> {conflicts:[...]}
- `POST /api/conflicts/{id}/dismiss` -> {ok:true}
- `POST /api/conflicts/rescan` -> {created:N}
- `GET /` 及静态资源 -> frontend/index.html

## 11. 前端页面

设计语言：暖纸色背景（#f6f1e7）、墨色文字（#1f1c17）、橙色强调（#c65d2e）、衬线标题；左侧窄导航，右侧内容区；卡片式布局；无外部 CDN。

页面：
1. **工作台**：项目名 + 一句话；4 个统计卡（论文/笔记/chunk/记忆）；冲突 banner；最近记忆；快速提问入口；技术徽章（seekdb / PowerContext）。
2. **提问**：大搜索框 + filters（全部/论文/笔记/年份）；回答卡（结论 + 引用 chips）；证据列表（标题、章节、页码、片段、BM25/向量/RRF 分数）；可折叠「检索轨迹」显示 SQL 摘要/耗时/候选数；右侧「用到的记忆」。
3. **资料库**：论文卡片（标题/作者/年份/标签/中文摘要）；点击展开 chunk 列表；笔记列表（日期/kind/title）。
4. **记忆**：按 kind 分组（决策/约束/进度/待办）；记忆卡显示 artifact_id/revision；新增记忆表单（kind + text）；说明「由 PowerContext 存储与召回」。
5. **冲突**：列表 + reason + dismiss + 复核任务按钮。

交互细节：
- Enter 提交；loading skeleton；错误 toast；空状态。
- 答案中的引用 chip 点击滚动到对应证据。
- 所有数字/ID 来自真实 API，不写死。
- 页面底部显示 "seekdb 1.4.0 · PowerContext 1.5.0 · 本地离线"。

## 12. 文件布局

```
qoder/labmemory/
  README.md
  SPEC.md
  .env.example
  backend/
    app/__init__.py
    app/config.py
    app/db.py
    app/embeddings.py
    app/memory.py
    app/search.py
    app/answer.py
    app/conflicts.py
    app/main.py
    seed/papers.json
    seed/ingest.py
  frontend/index.html
  frontend/styles.css
  frontend/app.js
  data/papers/*.pdf
  data/notes/*.md
  data/cache/
  scripts/pc_smoke.py
  scripts/start_all.sh
  tests/test_api.py
  docs/qoder-log.md
  docs/demo-script.md
  docs/architecture.md
```

## 13. 验收标准

- `python -m backend.seed.ingest --reset` 在 WSL 一次跑通，输出 >= 9 papers / >= 120 chunks / 8 memories。
- `curl /api/health` 返回 seekdb/powercontext 都 ok。
- 5 个 demo 问题都能返回带出处的回答，P95 < 2s（本地）。
- 检索 trace 中能看到 BM25 与 vector 两路排名；seekdb 查询日志可截图。
- 记忆页显示的 artifact_id/revision 与 PowerContext API 返回一致；重启 PowerContext 后仍能召回。
- 冲突列表至少 2 条，reason 可读；dismiss 后不再出现。
- 前端在 1280px/768px 下不横向滚动；无控制台报错。
- README 从零启动步骤可复现；不包含真实密钥。

## 14. Qoder 开发任务拆分（按顺序）

1. **Session 1**：读 SPEC，生成 `config.py`、`db.py`、`schema.sql`，跑通建库/健康检查。
2. **Session 2**：生成 `embeddings.py` + `ingest.py`，导入 9 篇 PDF + 8 条笔记，输出统计。
3. **Session 3**：生成 `memory.py`（PowerContext client）+ seed 8 条记忆，验证 remember/search/list。
4. **Session 4**：生成 `search.py`（BM25 + 向量 + RRF）+ `answer.py`，用 5 个问题验证引用。
5. **Session 5**：生成 `conflicts.py` + API 路由 `main.py`，curl 验收。
6. **Session 6**：生成前端三页 + 交互，截图。
7. **Session 7**：生成 `tests/test_api.py`，Qoder review + 修复，提交。
8. **Session 8**：生成展示站文案/截图，Qoder Sites 发布。

每个 session 记录：prompt、Qoder 摘要、改动文件、运行命令/结果、截图路径。写入 `docs/qoder-log.md`。
