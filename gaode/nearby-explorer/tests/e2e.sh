#!/usr/bin/env bash
# 一键验收：单元测试 + 10 条端到端 + 安全检查（全部离线，无需 Key / 网络）
set +u   # PYTHON 变量可能未设置，用空值判断更稳妥
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

PY="$PYTHON"
if [ -z "$PY" ]; then PY=python; fi

export PYTHONIOENCODING=utf-8
export AMAP_MOCK=1

FAIL=0

echo "=============================================================="
echo " 1/3  单元测试（离线 fixtures 回放）"
echo "=============================================================="
if ! "$PY" -m unittest discover -s tests -p "test_*.py" -v; then
  FAIL=1
fi

echo ""
echo "=============================================================="
echo " 2/3  端到端：10 条中文语句（命令行 + JSON 断言）"
echo "=============================================================="
if ! "$PY" tests/e2e_check.py; then
  FAIL=1
fi

echo ""
echo "=============================================================="
echo " 3/3  安全检查：仓库内不得出现明文 Key"
echo "=============================================================="
if ! "$PY" tests/check_no_secrets.py; then
  FAIL=1
fi

echo ""
if [ "$FAIL" -eq 0 ]; then
  echo "全部通过 ✅（离线模式，数据来自 fixtures/，不是实时高德结果）"
else
  echo "存在失败项 ❌"
fi
exit "$FAIL"
