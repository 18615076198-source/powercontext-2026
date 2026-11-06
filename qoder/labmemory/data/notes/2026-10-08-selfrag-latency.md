---
id: note-2026-10-08
date: 2026-10-08
kind: decision
project: rag-lab
title: 决策：暂不采用 Self-RAG 全量自反思
tags: 决策, Self-RAG, 延迟, 自反思
---
# 决策：暂不采用 Self-RAG 全量自反思

读了 Self-RAG（arXiv:2310.11511），它的反思 token 设计能提升事实性，但我们实测（演示数据）端到端延迟从 1.0x 增加到 2.3x。

决定：不采用全量自反思；只保留「按需检索」和「证据相关性检查」两个轻量环节。等有更高效的实现（例如自适应检索）再评估。

这条决策要记住，下次有人提 Self-RAG 时先看延迟预算。
