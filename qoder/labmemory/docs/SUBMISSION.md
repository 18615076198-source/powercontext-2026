# 提交清单（Submission Checklist）

> 赛题：OceanBase 大赛 · Qoder 赛题（总分 20）
> 当前状态：**Qoder Sites 已发布并公开**；Qoder 编码/测试、站点更新、访问统计读取已完成；技术链路、代码、测试、文档已完成。剩余：提交平台。

## 1. 基础验收

| 要求 | 状态 | 证据 |
|---|---|---|
| 网站通过 Qoder Sites 发布，任何人可访问 | **完成** | https://labmemory-lasfpz26o0f.qoder.website；匿名 200；截图 <code>docs/screenshots/qoder-site.png</code> |
| 项目按运行说明可跑通 | 完成 | <code>README.md</code>、<code>scripts/start_all.sh</code>、<code>scripts/verify.sh</code> |
| 至少一组验证样例 | 完成 | <code>docs/VERIFICATION.md</code> + <code>docs/screenshots/</code> |
| Qoder 开发可核对 | **完成** | <code>docs/qoder-log.md</code>：Sites session + 编码 session（history feature）+ pytest 7/7 |
| seekdb/PowerContext 真实发挥作用 | 完成 | 874 chunks、BM25+向量+RRF、8 条记忆、artifact revision、<code>docs/VERIFICATION.md</code> |

## 2. 提交物

| 材料 | 状态 | 位置 / 备注 |
|---|---|---|
| 项目网站网址 | 完成 | https://labmemory-lasfpz26o0f.qoder.website |
| 代码仓库 | 完成 | https://github.com/18615076198-source/powercontext-2026/tree/2026-competition-ecosystem/qoder/labmemory |
| 运行说明 | 完成 | <code>README.md</code>（环境、依赖、seekdb/PowerContext、启动步骤） |
| 验证样例 | 完成 | <code>docs/VERIFICATION.md</code> |
| Qoder 开发记录 | 完成 | <code>docs/qoder-log.md</code>（4 个 session：Sites 发布/公开、history 编码+测试、两次站点更新；含 transcript/日志路径） |
| Qoder 账号 UID | 完成 | 01a1b466-1089-70fc-8d82-c343b049e38a |
| 使用效果材料 | 部分完成 | Qoder Sites 24h **26 PV / 6 estimated UV**（partial，下限）；<code>docs/qoder-analytics.log</code> |
| 一页项目介绍 | 完成 | <code>docs/one-pager.md</code> |
| 架构说明 | 完成 | <code>docs/ARCHITECTURE.md</code> |
| 数据来源 | 完成 | 9 篇真实 arXiv 论文 + 演示笔记说明（README / site） |
| 无真实密钥 | 完成 | <code>.env</code> 已 gitignore；<code>.env.example</code> 为占位值 |

## 3. 仓库与提交

- 仓库：<code>18615076198-source/powercontext-2026</code>（public）
- 分支：<code>2026-competition-ecosystem</code>
- 提交：<code>ac8cf79</code>（本轮使用数据/视频更新待提交；最终 hash 见 git log）
- 项目目录：<code>qoder/labmemory</code>
- 本地 worktree：<code>D:\deepseek\qoder-2026</code>（不影响其他赛道分支）

## 4. 网站内容检查

- [x] 项目简介 / 解决的问题
- [x] 核心功能
- [x] 演示视频（15 秒，<code>site/assets/demo.mp4</code>，含最近提问/点击重问）
- [x] 截图（工作台/提问/资料库/记忆/冲突）
- [x] Qoder 实现的「最近提问」截图（<code>history.png</code>）
- [x] Qoder 完成说明（Sites 发布/公开 + history + 7 passed）
- [x] 代码仓库链接
- [x] 技术分工（seekdb / PowerContext / Qoder）
- [x] 数据来源与演示数据说明
- [x] 使用数据区块（Qoder Sites 24h 26 PV / 6 estimated UV，partial）
- [x] Qoder Sites 公网 URL
- [x] 无痕窗口验证截图（<code>docs/screenshots/qoder-site.png</code>）

## 5. 剩余关键路径

1. **提交平台**：填网站 URL、仓库地址、Qoder UID，上传其余材料。
2. **使用效果**（鼓励，已有初步数据）：Qoder Sites 24h 26 PV / 6 estimated UV（partial）；可继续找 3-5 位同学试用并附反馈截图。
3. **提交后复核**：无痕窗口再开一次站点；评审结束前不要暂停/删除站点。

## 6. 风险

- 展示站已重新发布并保持 public；匿名访问 200；评审结束前不要暂停/删除站点。
- 代码仓库为 public，评审可直接访问；若平台要求私有 repo，请改为向评审开放权限。
- Qoder device flow 曾两次 5 分钟超时；当前使用 PAT 登录。若登录失效，重新设置 <code>QODER_PERSONAL_ACCESS_TOKEN</code> 即可。
