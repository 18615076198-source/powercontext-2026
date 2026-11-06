# 提交清单（Submission Checklist）

> 赛题：OceanBase 大赛 · Qoder 赛题（总分 20）
> 当前状态：技术链路、代码、展示站、测试、文档已完成；**Qoder 账号登录 / Qoder Sites 发布 / 使用效果材料** 待完成。

## 1. 基础验收

| 要求 | 状态 | 证据 |
|---|---|---|
| 网站通过 Qoder Sites 发布，任何人可访问 | **待办** | 发布后填 URL；无痕访问截图 |
| 项目按运行说明可跑通 | 完成 | <code>README.md</code>、<code>scripts/start_all.sh</code>、<code>scripts/verify.sh</code> |
| 至少一组验证样例 | 完成 | <code>docs/VERIFICATION.md</code> + <code>docs/screenshots/</code> |
| Qoder 开发可核对 | **部分** | <code>docs/qoder-log.md</code> 已如实记录准备阶段；Qoder 会话待补 |
| seekdb/PowerContext 真实发挥作用 | 完成 | 874 chunks、BM25+向量+RRF、8 条记忆、artifact revision、<code>docs/VERIFICATION.md</code> |

## 2. 提交物

| 材料 | 状态 | 位置 / 备注 |
|---|---|---|
| 项目网站网址 | 待办 | Qoder Sites 发布后填写 |
| 代码仓库 | 完成 | https://github.com/18615076198-source/powercontext-2026/tree/2026-competition-ecosystem/qoder/labmemory |
| 运行说明 | 完成 | <code>README.md</code>（环境、依赖、seekdb/PowerContext、启动步骤） |
| 验证样例 | 完成 | <code>docs/VERIFICATION.md</code>（初始数据、输入、步骤、预期结果、技术作用记录） |
| Qoder 开发记录 | 部分 | <code>docs/qoder-log.md</code>（准备阶段 + 待执行 Qoder sessions） |
| Qoder 账号 UID | 待办 | 登录后填 |
| 使用效果材料 | 可选/待办 | 访问统计、使用日志、问卷/反馈（匿名） |
| 一页项目介绍 | 完成 | <code>docs/one-pager.md</code> |
| 架构说明 | 完成 | <code>docs/ARCHITECTURE.md</code> |
| 数据来源 | 完成 | 9 篇真实 arXiv 论文 + 演示笔记说明（README / site） |
| 无真实密钥 | 完成 | <code>.env</code> 已 gitignore；<code>.env.example</code> 为占位值 |

## 3. 仓库与提交

- 仓库：<code>18615076198-source/powercontext-2026</code>（public）
- 分支：<code>2026-competition-ecosystem</code>
- 提交：<code>5caeebc</code>（后续 Qoder 会话会追加 commit）
- 项目目录：<code>qoder/labmemory</code>
- 本地 worktree：<code>D:\deepseek\qoder-2026</code>（不影响其他赛道分支）

## 4. 网站内容检查

- [x] 项目简介 / 解决的问题
- [x] 核心功能
- [x] 演示视频（21 秒，<code>site/assets/demo.mp4</code>）
- [x] 截图（工作台/提问/资料库/记忆/冲突）
- [x] 代码仓库链接
- [x] 技术分工（seekdb / PowerContext / Qoder）
- [x] 数据来源与演示数据说明
- [ ] Qoder Sites 公网 URL（发布后填）
- [ ] 无痕窗口验证截图

## 5. 剩余关键路径

1. **Qoder 登录**（device flow 5 分钟有效，或 PAT）。
2. **Qoder 会话**：审查、补测试、修真实问题、前端迭代、Qoder Sites 发布；逐条写 <code>docs/qoder-log.md</code>，对应 commit。
3. **Qoder Sites 发布**：<code>site/</code> -> 公网 URL -> 无痕验证。
4. **Qoder UID**：登录后从账号设置/CLI 获取，填入提交材料。
5. **使用效果**（鼓励）：找 3-5 位同学试用，记录提问数/反馈/提效对比；附访问统计或日志。
6. **提交平台**：填网站 URL、仓库地址、Qoder UID，上传其余材料。

## 6. 风险

- Qoder 账号注册/登录是硬阻塞；两次 device flow 已超时，需要本人在 5 分钟内完成，或使用 PAT。
- 若 Qoder 无法登录，赛题「Qoder 开发」基础验收无法满足；技术链路本身已完成，但不能替代该要求。
- 代码仓库为 public，评审可直接访问；若平台要求私有 repo，请改为向评审开放权限。
