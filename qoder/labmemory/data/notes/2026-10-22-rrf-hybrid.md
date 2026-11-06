---
id: note-2026-10-22
date: 2026-10-22
kind: experiment
project: rag-lab
title: 实验：RRF 混合检索优于纯向量
tags: 实验, RRF, 混合检索, BM25, 向量
---
# 实验：RRF 混合检索优于纯向量

对比三种检索（演示数据，9 篇论文、约 200 个 chunk）：

- 纯向量：recall@10 = 0.62
- 纯 BM25：recall@10 = 0.55
- BM25 + 向量 RRF(k=60)：recall@10 = 0.70

结论：保留 BM25，RRF 融合。中文 query 主要靠向量召回，英文方法名/术语靠 BM25 补足；两路都保留，检索日志要展示每路的排名和融合分。
