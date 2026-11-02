# StudyFlow 学习科研工作台

StudyFlow 面向需要长期推进课程、论文和项目的人，把每天的碎片记录整理成下一步可执行的计划。

## 作品亮点

- **今日工作台**：输入主题和当前进展，自动生成下一步行动清单。
- **上下文复用**：保存“偏好、薄弱点、研究结论”等长期记忆，下次打开自动召回相关内容。
- **复盘闭环**：提交一次学习记录，系统会生成可追踪的复盘卡片，展示记忆写入和召回结果。
- **真实 PowerContext 接入**：通过 PowerContext HTTP API 创建 Scope、捕获 Source、写入 atomic-memory 并检索。
- **零配置演示**：没有 PowerContext 服务时使用本地内存适配器，评审可直接运行核心流程。

## 快速运行

```bash
cd qoder/studyflow
python app.py
```

打开 <http://127.0.0.1:8787>。

## 接入 PowerContext

先启动 PowerContext Server（默认监听 `http://127.0.0.1:8001`），再设置环境变量：

```bash
# Windows PowerShell
$env:POWERCONTEXT_BASE_URL = "http://127.0.0.1:8001"
$env:POWERCONTEXT_TOKEN = ""
python app.py
```

可复制 `.env.example` 中的配置。应用会在启动后访问 `/health/live`；连接成功时，所有记忆写入和召回都走 PowerContext。连接失败时，页面会明确显示“本地演示模式”。

## 验证样例

1. 输入主题“论文方法论复习”，选择“考试复习”，填写当前进展。
2. 点击“生成下一步”，查看基于上下文生成的 3 条行动。
3. 点击“保存为长期记忆”，确认右侧出现 PowerContext 写入记录。
4. 在“检索记忆”输入“复习”，点击检索，查看召回的记忆卡片。
5. 再次输入同一主题并点击“生成下一步”，验证历史记忆会出现在主题上下文中。

## 提交说明

- 项目网站：将 `web/` 作为 Qoder Sites 的静态发布目录，公开访问。
- 代码仓库：本仓库的 `codex/studyflow` 分支（可合并到 `2026-competition`），项目源码位于 `qoder/studyflow`。
- Qoder 开发记录：保留需求拆解、编码、调试和验证的 Qoder 对话截图或录屏。


