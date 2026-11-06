---
id: note-2026-09-15
date: 2026-09-15
kind: experiment
project: rag-lab
title: 实验：chunk size 512 vs 1024
tags: 实验, chunk, recall, 检索
---
# 实验：chunk size 512 vs 1024

在 8 篇 RAG 相关论文上做了小规模对比（演示数据）：

| chunk size | overlap | recall@5 | 备注 |
|---|---|---|---|
| 512 | 64 | 0.71 | 片段更聚焦，引用更精确 |
| 1024 | 128 | 0.65 | 上下文完整，但噪声变多 |

结论：首版用 512 + overlap 64。引用要精确到段落，512 更适合做「证据卡片」。后续可以试 hierarchical chunk，但不在本周范围。
