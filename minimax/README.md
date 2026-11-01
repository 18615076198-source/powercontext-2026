# 规有所依 —— 面向软件持续演进的 SDD 上下文管理系统

> 赛题：MiniMax × OceanBase《规有所依——面向软件持续演进的 SDD 上下文管理系统》
> 仓库：`oceanbase/powercontext` 分支 `2026-competition-ecosystem`，产物位于 `minimax/`

AI 改代码时最容易出问题的三件事：**不知道要遵守哪些规格、不知道要改哪里、改完不知道有没有破坏原有行为**。
`minimax/` 里的 `sddctx` 就是回答这三个问题的上下文模块：它把规格、代码、测试索引进 **seekdb**，
按任务组装出可溯源、可校验的**上下文包**，把上下文交给 **MiniMax** 完成真实代码修改，
跑功能与回归测试，再用 **PowerContext** 保存任务状态供下一次运行接着干。

## 一、题目要求与实现对照

| 题目要求 | 本仓库的实现 | 证据位置 |
| --- | --- | --- |
| 选择可运行、有测试的业务工程，完成一次局部修改 | `demo/billing-service`（结算报表服务，25 条回归测试）；任务：月度报表新增 `region` 过滤 | `demo/`、`runs/task-001-*/change.patch` |
| ①导入规格、代码、测试 | `sddctx import`：切分为 63 个资料块（规格条目 / 函数符号 / 测试用例）写入 seekdb | `runs/*/import.json` |
| ②按任务选择资料形成上下文 | `sddctx plan`：锚点精确取 + 检索补充，输出规格/代码/测试三分节，逐条校验来源真实存在 | `runs/*/context-pack.json` |
| ③上下文交给 MiniMax 完成修改 | `sddctx apply`：把上下文渲染成提示词，MiniMax 返回整文件重写，过护栏后落盘 | `runs/*/minimax-output.txt`、`change.patch` |
| ④运行功能与回归测试 | `sddctx verify`：验收用例 8 条 + 既有回归 25 条，并校验测试文件未被改动 | `runs/*/verify.json` |
| ⑤保存状态、重启后读取并使用 | `sddctx save` / `sddctx resume`：状态写入 PowerContext，新进程用 `context/prepare` 召回并并入上下文包 | `runs/*/state.json`、`context-pack.resume.json` |
| MiniMax 参与代码生成/修改 | `MINIMAX_MODEL=MiniMax-M3.1-Flash`，OpenAI 兼容接口流式调用 | `docs/03-技术使用记录.md` |
| seekdb / OceanBase 存储检索 | `pyseekdb` 嵌入式 seekdb：`where_document` 全文下推 + 可选向量近邻 | `src/sddctx/store/seekdb_store.py` |
| PowerContext 保存并复用状态 | HTTP API：`/v1/scopes`、`/v1/memory/remember`、`/v1/sources/content`、`/v1/context/prepare` | `src/sddctx/powercontext.py` |
| 输出能定位四类信息 | `plan` 打印并写出：适用规格条目、待改代码符号、验证测试、已完成/待办/验证结果 | `runs/*/context-pack.json` |
| 来源必须真实存在 | `verify_sources()`：文件存在性 + 整文件哈希 + 片段逐字包含 | `tests/test_context.py` |
| 更新规格重新导入后不能返回固定答案 | `spec-apply` → `import` → `plan`：缺口先报 `BR-REPORT-05..07 未导入`，导入后才出现 | 见下「六、规格演进」 |

## 二、三个指定技术怎么用

| 技术 | 版本 | 接入方式 | 承担的职责 |
| --- | --- | --- | --- |
| MiniMax | `MiniMax-M3.1-Flash`（`api.minimaxi.com/v1`，OpenAI 兼容 + SSE 流式） | 原生 HTTP | 读取上下文包，产出 `src/billing/report.py` 的完整新版本 |
| seekdb | `pyseekdb>=1.4`（嵌入式 `pylibseekdb`，集合 `sddctx_chunks`） | Python SDK | 持久化 63 个资料块，`where_document $contains` 承担检索召回 |
| PowerContext | `powercontext==1.2.0`（Server + SQLite 后端），HTTP API | HTTP | 保存任务状态快照与验证证据，跨进程召回 |

## 三、快速开始

### 3.1 Linux / 评测环境（含 seekdb 真实路径）

```bash
cd minimax
python -m pip install -r requirements.txt   # pyseekdb + powercontext + pytest
cp .env.example .env                        # 填入 MINIMAX_API_KEY

# 另开一个终端启动 PowerContext（SQLite 后端，无需额外数据库）
powercontext server run --no-env-file --host 127.0.0.1 --port 8077

# 本终端
export PYTHONPATH=src SDDCTX_STORE=seekdb POWERCONTEXT_URL=http://127.0.0.1:8077
python -m sddctx doctor
./demo.sh                                   # 跑完整故事（见 3.3）
```

### 3.2 Windows / 无 seekdb 内核时

`pylibseekdb` 只提供 Linux 与 macOS(arm64) 轮子，Windows 上无法加载嵌入式内核。
此时把存储换成等价的 SQLite 实现，其余流程完全一致：

```powershell
$env:SDDCTX_STORE="sqlite"; $env:PYTHONPATH="src"; $env:POWERCONTEXT_URL="http://127.0.0.1:8077"
python -m sddctx doctor
```

> 评测请使用 `SDDCTX_STORE=seekdb`。CI（`.github/workflows/minimax-ci.yml`）在 ubuntu-latest 上用 seekdb 跑通了全流程。

### 3.3 一条命令复现

`demo.sh` 依次执行 8 步并打印每一步的产出：

```
import → plan（报 3 条规格缺口）→ spec-apply（规格演进）→ import → plan（缺口消失）
       → apply（MiniMax 改代码）→ verify（8 功能 + 25 回归）→ save / resume（跨进程回读）
```

## 四、命令与输入输出

| 命令 | 输入 | 输出 |
| --- | --- | --- |
| `sddctx doctor` | 环境变量 | 存储/MiniMax/PowerContext 可用性 |
| `sddctx import --task T` | 任务 JSON（取其中的 `project`） | `runs/<task>/import.json` |
| `sddctx plan --task T` | 任务 JSON + 存储 | `context-pack.json`（规格/代码/测试/状态/缺口） |
| `sddctx spec-apply --task T` | 任务里的 `spec_update` | 演进后的规格文件 |
| `sddctx apply --task T` | 上下文包 | `change.patch`、`minimax-output.txt`、`apply.json` |
| `sddctx verify --task T` | 验收用例 + 回归套件 | `verify.json`（逐条用例结果） |
| `sddctx save --task T` | apply/verify 结果 | PowerContext 中的 Memory + Source |
| `sddctx resume --task T` | PowerContext | 状态回读 + `context-pack.resume.json` |
| `sddctx run --task T` | 以上全部 | 顺序执行 import→plan→apply→verify→save |

上下文包（`context-pack.json`）的字段就是题面要求的四类定位信息：

```jsonc
{
  "specs": [{"spec_id": "BR-REPORT-05", "path": "specs/02-report.md", "line_start": 38, "why": "任务锚点 BR-REPORT-05", "content_hash": "..."}],
  "code":  [{"symbol": "billing.report:build_monthly_report", "path": "src/billing/report.py", "line_start": 50, "why": "任务锚点 ..."}],
  "tests": [{"test_id": "tests/test_report.py::test_currency_filter", "why": "命中：currency、none、report"}],
  "state": {"status": "verified", "done": ["..."], "todo": ["..."], "verification": [{"name": "functional", "status": "passed"}]},
  "gaps": ["锚点规格 BR-REPORT-05 尚未导入（规格缺口）"],
  "source_problems": []
}
```

## 五、验证样例：要改什么 / 必须保持什么

任务文件 `samples/task-001-report-region-filter/task.json`：

- **要改什么**：`request` + 规格新增条目 `BR-REPORT-05/06/07`（`spec-update/02-report.md`）
  —— 月度报表 `build_monthly_report` 增加 `region` 过滤（去空白、大小写不敏感、空白入参抛 `ValueError`、未知区域返回空报表），
  并与既有 `currency` 过滤取交集；`MonthlyReport` 增加 `totals_by_region` 且只统计过滤后订单。
- **必须保持什么**：`must_preserve` 锁定 `BR-REPORT-01/02/03/04`（统计范围、币种过滤语义、按币种分组汇总、明细排序），
  外加 `tests/` 全量回归，以及「既有测试文件不得被改动」的哈希校验。
- **怎么判定**：`acceptance/test_acceptance_report_region.py` 8 条功能用例（改动前全部失败）+ 25 条回归用例（改动前后都必须通过）。

## 六、规格演进：证明不是固定答案

```
$ python -m sddctx plan --task ...          # 规格 v1：只有 BR-REPORT-01..04
  - 锚点规格 BR-REPORT-05 尚未导入（规格缺口）
  - 锚点规格 BR-REPORT-06 尚未导入（规格缺口）
  - 锚点规格 BR-REPORT-07 尚未导入（规格缺口）

$ python -m sddctx spec-apply --task ...     # 规格演进：写入 BR-REPORT-05..08
$ python -m sddctx import --task ...         # 重新导入（63 → 67 个资料块）
$ python -m sddctx plan --task ...           # 缺口消失，新增条目出现在「适用规格」里
  - [spec:BR-REPORT-05] 区域过滤  @ specs/02-report.md:38-49
```

`tests/test_context.py::test_pack_follows_updated_spec_after_reimport` 把这条链路固化成测试：
新增一条 `BR-REPORT-77` 并重新导入后，检索结果里必须出现它，且来源校验仍然通过。

## 七、目录结构

```
minimax/
├── README.md                    本文件
├── demo.sh / Makefile           一键复现与常用任务
├── requirements.txt             评测环境依赖（Linux）
├── src/sddctx/                  上下文模块
│   ├── cli.py                   命令行入口（输入/输出见第四节）
│   ├── chunker.py               规格条目 / 函数符号 / 测试用例切分
│   ├── store/                   存储抽象：seekdb（主）+ SQLite（兜底）
│   ├── context.py               上下文包组装、来源校验、状态合并
│   ├── minimax.py               MiniMax 调用、输出协议、护栏
│   ├── verify.py                功能 + 回归测试执行与结果解析
│   ├── powercontext.py          任务状态写入与跨进程召回
│   └── trace.py                 技术使用记录（JSONL）
├── demo/billing-service/        被修改的业务工程（规格 + 源码 + 回归测试）
├── samples/task-001-.../        验证样例：任务、规格更新、验收用例
├── runs/task-001-.../           运行证据：上下文包、diff、测试结果、状态
├── tests/                       模块自身测试（28 条，不需要网络）
└── docs/                        设计说明、验证样例、技术使用记录、提测说明
```

## 八、已知边界

1. **Windows 无法跑嵌入式 seekdb**：`pylibseekdb` 只有 Linux/macOS 轮子。模块内置 SQLite 兜底后端（`SDDCTX_STORE=sqlite`），
   两条后端共用同一套接口与同一批测试；评测与 CI 使用 seekdb。
2. **MiniMax 输出是「整文件重写」而不是 diff**：小文件场景下整文件替换的落地成功率远高于 diff 逆向，
   但代价是单次输出更长（本次约 6.8 KB）。护栏会拒绝路径越权、删除公共符号、语法错误的输出。
3. **向量检索默认关闭**：`SDDCTX_SEEKDB_EMBEDDING=off` 时只用全文下推，避免首次运行下载 embedding 模型；
   设为 `default` 可叠加向量近邻（`collection.query`）。
4. **状态以 Memory + Source 承载**，未使用 Handoff/Work Contract 全流程——后者需要额外的接收方身份与回执建模，
   与本题「保存进展、重启后复用」的目标相比收益不大。
