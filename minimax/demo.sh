#!/usr/bin/env bash
# 一键复现：从 v1 规格出发，走完「找规格 → 改规格 → 找代码 → 改代码 → 验证 → 存状态 → 接着干」。
set -euo pipefail
cd "$(dirname "$0")"

export PYTHONPATH="${PYTHONPATH:-}:src"
PY="${PYTHON:-python}"
TASK="samples/task-001-report-region-filter/task.json"

step() { printf '\n\033[1m========== %s ==========\033[0m\n' "$1"; }

step "0 · 环境自检"
"$PY" -m sddctx doctor

step "1 · 导入规格/代码/测试（当前为 v1 规格）"
"$PY" -m sddctx import --task "$TASK" --reset

step "2 · 组装上下文包（规格尚未演进，应报 3 条缺口）"
"$PY" -m sddctx plan --task "$TASK"

step "3 · 规格演进：写入 BR-REPORT-05..08"
"$PY" -m sddctx spec-apply --task "$TASK"

step "4 · 重新导入演进后的资料"
"$PY" -m sddctx import --task "$TASK"

step "5 · 再次组装（缺口消失，新规格进入上下文）"
"$PY" -m sddctx plan --task "$TASK"

step "6 · MiniMax 依据上下文修改代码"
"$PY" -m sddctx apply --task "$TASK"

step "7 · 功能测试 + 回归测试"
"$PY" -m sddctx verify --task "$TASK"

step "8 · 任务状态写入 PowerContext"
"$PY" -m sddctx save --task "$TASK"

step "9 · 新进程回读状态并继续"
"$PY" -m sddctx resume --task "$TASK"

printf '\n\033[1m全部步骤完成。产物见 runs/task-001-report-region-filter/\033[0m\n'
