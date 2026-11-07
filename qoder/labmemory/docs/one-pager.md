# LabMemory · 研忆 — 一页项目介绍

## 一句话

把科研组会的决策、约束和论文证据放进一个可检索、可追溯的记忆：问一句「上次为什么放弃这个方法」，同时拿到原文出处和当时的决定。

## 问题

- 组会前翻几十篇 PDF 和几周聊天记录，只为找回一个决策理由。
- 决策散落在会议纪要和个人笔记里，新人重复踩坑。
- 新论文与旧决策相关，却没人提醒复核。

## 方案

1. **导入**：9 篇真实 arXiv 论文 PDF + 8 条组会/实验笔记；按页切 chunk，生成中文摘要。
2. **提问**：seekdb 同时跑 BM25 全文与 384 维向量检索，RRF 融合；结果带论文/笔记、章节、页码、分数。
3. **记忆**：PowerContext 保存决策/约束/进度/待办；回答里显示 artifact_id @ revision；新论文与旧决策冲突时提示复核。

## 技术分工

| 技术 | 作用 |
|---|---|
| seekdb 1.4 | 874 个 chunk 的存储与混合检索；FULLTEXT + VECTOR + 标量过滤；RRF |
| PowerContext 1.5 | 8 条显式记忆；scope 隔离；跨会话召回；artifact revision 可核对 |
| Qoder | 需求拆解、编码/调试、测试、Qoder Sites 发布；记录见 docs/qoder-log.md |
| fastembed | 多语言 384 维 embedding，CPU/ONNX，无外部 LLM |

## 演示

- 工作台：9 papers / 874 chunks / 8 memories / 3 conflicts。
- 问「我们为什么放弃 Self-RAG 的全量自反思？」→ 记忆 + 笔记 + Self-RAG 中文摘要 + p.3 原文，约 178ms。
- 冲突页：Self-RAG / Lost in the Middle / DPR 三条「可能影响决策」，可生成复核任务。
- 记忆页：新增一条决策后，下一次提问能召回。

## 证据

- 截图：<code>docs/screenshots/dashboard.png</code>、<code>ask.png</code>、<code>memory.png</code>、<code>conflicts.png</code>
- 验证步骤：<code>docs/VERIFICATION.md</code>
- 架构：<code>docs/ARCHITECTURE.md</code>
- 运行：README 的 5 步；Docker seekdb + PowerContext 1.5 + FastAPI
- 数据：论文真实存在（arXiv 链接可核对）；笔记与实验数值为演示场景数据，已标注

## 价值

- 组会前找依据：30 分钟 → 1 分钟（目标值；以实际使用记录为准）。
- 决策可追溯：每条回答能点回论文页码或 PowerContext 记忆 revision。
- 离线可跑：不依赖外部 LLM/API；适合实验室隐私与成本约束。

## 链接

- 项目网站：https://labmemory-lasfpz26o0f.qoder.website
- 代码仓库：https://github.com/18615076198-source/powercontext-2026/tree/2026-competition-ecosystem/qoder/labmemory
- Qoder 账号 UID：01a1b466-1089-70fc-8d82-c343b049e38a
