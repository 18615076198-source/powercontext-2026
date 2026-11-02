#!/usr/bin/env bash
# 本地启动 seekdb（server 模式，MySQL 协议，默认 2881）。
# 已安装 seekdb 的前提下运行；数据目录可用 SEEKDB_BASE_DIR 覆盖。
set -e

BASE_DIR="$SEEKDB_BASE_DIR"
if [ -z "$BASE_DIR" ]; then BASE_DIR="$HOME/seekdb-kb"; fi
PORT="$SEEKDB_PORT"
if [ -z "$PORT" ]; then PORT=2881; fi

mkdir -p "$BASE_DIR"

if ! command -v seekdb >/dev/null 2>&1; then
  echo "未找到 seekdb 可执行文件。" >&2
  echo "安装方式见 https://docs.seekdb.ai/ ，或使用已有的 seekdb/OceanBase 实例，" >&2
  echo "并通过 SEEKDB_HOST / SEEKDB_PORT 配置连接。" >&2
  exit 1
fi

echo "启动 seekdb：base-dir=$BASE_DIR port=$PORT"
exec seekdb --nodaemon --base-dir "$BASE_DIR" --port "$PORT"
