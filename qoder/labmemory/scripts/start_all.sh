#!/usr/bin/env bash
# Start PowerContext (if needed) and the LabMemory FastAPI app.
# seekdb must already be running on 127.0.0.1:2881.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PC_HOME="${PC_HOME:-$HOME/powercontext-manual}"
APP_PORT="${APP_PORT:-8000}"
VENV="${VENV:-$HOME/venvs/labmemory}"

if ! (echo > /dev/tcp/127.0.0.1/2881) >/dev/null 2>&1; then
  echo "[!] seekdb is not listening on 127.0.0.1:2881."
  echo "    Docker: docker run -d --name labmemory-seekdb -p 2881:2881 oceanbase/seekdb"
  echo "    Binary: ~/sdb-src/build_release/src/observer/seekdb --base-dir ~/labmemory-seekdb --port 2881 --nodaemon"
  exit 1
fi

if ! curl -sf http://127.0.0.1:18080/health/live >/dev/null 2>&1; then
  if [ ! -f "$PC_HOME/manual.env" ]; then
    echo "[!] Missing $PC_HOME/manual.env; see README step 2."
    exit 1
  fi
  echo "[*] starting PowerContext from $PC_HOME ..."
  (cd "$PC_HOME" && nohup ~/.local/bin/powercontext server run --env-file manual.env > server.log 2>&1 &)
  for i in $(seq 1 20); do
    if curl -sf http://127.0.0.1:18080/health/live >/dev/null 2>&1; then break; fi
    sleep 0.5
  done
fi

echo "[*] PowerContext: http://127.0.0.1:18080/dashboard/home"
echo "[*] LabMemory:    http://127.0.0.1:$APP_PORT"
cd "$ROOT"
exec "$VENV/bin/uvicorn" backend.app.main:app --host 0.0.0.0 --port "$APP_PORT"
