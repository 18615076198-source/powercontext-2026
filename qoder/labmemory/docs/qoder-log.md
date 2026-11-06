# Qoder 开发记录

> 说明：本文件只记录**真实发生**的开发过程。Qoder 账号尚未登录成功（两次 device flow 均在 5 分钟内超时），因此准备阶段由人工/AI 辅助完成，先跑通技术链路；Qoder 会话将在登录后补入，不伪造。

- Qoder 产品：Qoder CLI 1.1.84（赛题允许 CLI）
- Qoder 账号 UID：<待登录后填写>
- 项目路径：<code>powercontext-2026/qoder/labmemory</code>
- 分支：<code>2026-competition-ecosystem</code>
- 当前提交：<code>5caeebc</code>（已 push 到公开仓库）

## 准备阶段（非 Qoder，如实记录）

时间：2026-11-07 02:30 - 03:40（Asia/Shanghai）

- 创建独立 git worktree，停在 <code>2026-competition-ecosystem</code>，不影响其他赛道分支。
- 下载 9 篇真实 arXiv 论文 PDF，抓取真实元数据；编写 8 条演示场景笔记。
- 跑通 seekdb 1.4.0：建库/表、VECTOR(384) + FULLTEXT + 标量索引；验证 BM25 与向量查询。
- 跑通 PowerContext 1.5.0：本地 Server、scope、8 条显式记忆、search/list。
- 完成 FastAPI + 原生前端的初版；5 个页面；874 chunks；3 条冲突；API 测试 6/6 通过。
- 完成展示站初版、21 秒录屏、README/验证/架构/一页介绍。
- 这部分**不计入 Qoder 产出**；登录后 Qoder 会做代码审查、补测试、前端迭代、站点发布，并逐条记录。

## Qoder 会话（待执行，登录后补入）

| # | 计划 prompt | 预期 Qoder 产出 | 验证 | 截图 |
|---|---|---|---|---|
| 1 | 读 SPEC/README，审查后端与前端，列出 3 个最高风险问题，不改文件 | 审查报告 | 人工确认 | 待补 |
| 2 | 为 FastAPI 补 pytest：health/ask/conflicts/memories/search，运行并修复失败 | 测试文件 + 修复 | <code>pytest -q</code> | 待补 |
| 3 | 审查 search.py 的 SQL 参数化/RRF/降级逻辑，修一个真实问题并加回归测试 | diff + 测试 | 测试通过 | 待补 |
| 4 | 迭代前端提问页：过滤器、URL 保留 query、键盘提交；保证 0 console error | diff | Playwright 截图 | 待补 |
| 5 | 用 Qoder Sites skill 发布 <code>site/</code>，设为「任何人可访问」，返回 URL | 公网站点 | 无痕访问 | 待补 |
| 6 | review 全部改动并生成 commit message，提交 | commit | <code>git log</code> | 待补 |

## 证明清单

- Qoder CLI 版本：<code>qodercli --version</code> -> 1.1.84
- Qoder 登录状态：待
- Qoder Sites URL：待
- 无痕窗口验证截图：待
- 真实 Qoder 会话截图：待
- 对应 commit：待
