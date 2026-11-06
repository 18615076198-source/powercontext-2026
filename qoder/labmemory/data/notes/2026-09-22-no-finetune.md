---
id: note-2026-09-22
date: 2026-09-22
kind: decision
project: rag-lab
title: 决策：不 fine-tune retriever
tags: 决策, DPR, fine-tune, 算力
---
# 决策：不 fine-tune retriever

决定：首版不 fine-tune DPR / retriever，先用 BM25 + DPR zero-shot 混合。

原因：
1. 单卡 3090，fine-tune 的显存和时间成本高；
2. 要保证评审能复现，zero-shot 依赖更少；
3. 先验证「混合检索 + 引用 + 记忆」是否真的解决找证据的问题。

风险：DPR 论文（arXiv:2004.04906）显示 fine-tune 后 Top-20 准确率约 78%，比 BM25 高不少；如果我们的 zero-shot 召回不够，需要重新评估这条决策。
