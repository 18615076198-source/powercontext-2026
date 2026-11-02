"""StudyFlow demo app for the Qoder x OceanBase competition.

The app uses the real PowerContext HTTP contract when a server is reachable and
falls back to an in-process store so the judging flow remains runnable offline.
"""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent
WEB = ROOT / "web"
PORT = int(os.getenv("STUDYFLOW_PORT", "8787"))


class PowerContextAdapter:
    """Small adapter for scopes, sources, memories and search."""

    def __init__(self) -> None:
        self.base = os.getenv("POWERCONTEXT_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
        self.token = os.getenv("POWERCONTEXT_TOKEN", "")
        self.scope_id: str | None = None
        self.online = False
        self.local: list[dict[str, Any]] = [
            {
                "id": "demo-memory-1",
                "kind": "preference",
                "text": "偏好：先看结论，再看证据；每次复习控制在 25 分钟。",
                "source": "演示数据",
                "created_at": "2026-11-01T09:00:00+08:00",
            },
            {
                "id": "demo-memory-2",
                "kind": "progress",
                "text": "进展：已经掌握混合检索的基本概念，下一步练习一个真实查询。",
                "source": "演示数据",
                "created_at": "2026-11-01T18:20:00+08:00",
            },
        ]
        self._probe()

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(f"{self.base}{path}", data=body, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=2.5) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}

    def _probe(self) -> None:
        try:
            self._request("GET", "/health/live")
            self.online = True
        except (OSError, urllib.error.URLError, TimeoutError, ValueError):
            self.online = False

    def ensure_scope(self) -> str:
        if self.scope_id:
            return self.scope_id
        if self.online:
            try:
                self._request(
                    "POST",
                    "/v1/sources/content",
                    {
                        "scope_id": scope,
                        "source_id": f"studyflow-{uuid.uuid4().hex[:10]}",
                        "content": text,
                        "metadata": {"app": "studyflow", "kind": kind},
                    },
                )
                result = self._request(
                    "POST",
                    "/v1/scopes",
                    {
                        "title": "StudyFlow 学习科研工作台",
                        "summary": "记录学习偏好、研究进展和复盘行动",
                        "idempotency_key": "studyflow-demo-scope",
                    },
                )
                self.scope_id = result.get("scope_id") or result.get("id")
            except (OSError, urllib.error.URLError, TimeoutError, ValueError):
                self.online = False
        self.scope_id = self.scope_id or "local-studyflow"
        return self.scope_id

    def save(self, text: str, kind: str = "progress") -> dict[str, Any]:
        scope = self.ensure_scope()
        item = {
            "id": f"memory-{uuid.uuid4().hex[:8]}",
            "kind": kind,
            "text": text,
            "source": "PowerContext" if self.online else "本地演示",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if self.online:
            try:
                result = self._request(
                    "POST",
                    f"/v1/scopes/{scope}/artifacts",
                    {
                        "family": "atomic-memory",
                        "content": {
                            "schema": "powercontext.atomic-memory.v1",
                            "kind": kind,
                            "text": text,
                        },
                    },
                )
                item["id"] = result.get("artifact_id", item["id"])
            except (OSError, urllib.error.URLError, TimeoutError, ValueError):
                self.online = False
        self.local.insert(0, item)
        return item

    def search(self, query: str) -> list[dict[str, Any]]:
        scope = self.ensure_scope()
        if self.online:
            try:
                result = self._request(
                    "POST",
                    "/v1/atomic-memory/search",
                    {"scope_id": scope, "query": query, "mode": "text", "limit": 20},
                )
                items = result.get("items", [])
                return [
                    {
                        "id": i.get("artifact_id", i.get("id", "memory")),
                        "kind": i.get("content", {}).get("kind", i.get("kind", "memory")),
                        "text": i.get("content", {}).get("text", i.get("text", "")),
                        "source": "PowerContext",
                        "created_at": i.get("created_at", ""),
                    }
                    for i in items
                ]
            except (OSError, urllib.error.URLError, TimeoutError, ValueError):
                self.online = False
        tokens = [token for token in re.split(r"\s+", query.strip().lower()) if token]
        return [
            item
            for item in self.local
            if not tokens or any(token in item["text"].lower() for token in tokens)
        ][:20]

    def status(self) -> dict[str, Any]:
        return {
            "online": self.online,
            "mode": "PowerContext 实时模式" if self.online else "本地演示模式",
            "base_url": self.base,
            "scope_id": self.scope_id or "尚未创建",
            "memory_count": len(self.local),
        }


STORE = PowerContextAdapter()
LOCK = threading.Lock()


def json_response(handler: BaseHTTPRequestHandler, payload: Any, status: int = 200) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(data)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

    def do_GET(self) -> None:
        if self.path == "/api/health":
            json_response(self, {"ok": True, "service": "StudyFlow", **STORE.status()})
            return
        if self.path.startswith("/api/context"):
            query = self.path.split("?q=", 1)[1] if "?q=" in self.path else ""
            json_response(self, {"items": STORE.search(query), **STORE.status()})
            return
        path = self.path.split("?", 1)[0]
        target = WEB / ("index.html" if path == "/" else path.lstrip("/"))
        if target.is_file() and WEB in target.parents:
            content = target.read_bytes()
            mime = "text/html; charset=utf-8" if target.suffix == ".html" else "text/css; charset=utf-8"
            if target.suffix == ".js":
                mime = "text/javascript; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        json_response(self, {"error": "Not found"}, 404)

    def do_POST(self) -> None:
        try:
            body = self._body()
            if self.path == "/api/plan":
                topic = (body.get("topic") or "未命名主题").strip()
                progress = (body.get("progress") or "还没有记录进展").strip()
                context = STORE.search(topic)
                actions = [
                    f"用 25 分钟补齐“{topic}”的一个关键概念，并写下 3 句自己的解释。",
                    f"把当前进展“{progress[:42]}”拆成一个可验证的小问题，完成后保存证据。",
                    "在今天结束前做一次 5 分钟复盘，记录卡点和下一次开始的位置。",
                ]
                json_response(self, {"topic": topic, "actions": actions, "context": context, **STORE.status()})
                return
            if self.path == "/api/remember":
                text = (body.get("text") or "").strip()
                if not text:
                    json_response(self, {"error": "记忆内容不能为空"}, 400)
                    return
                with LOCK:
                    item = STORE.save(text, body.get("kind", "progress"))
                json_response(self, {"item": item, **STORE.status()}, 201)
                return
            if self.path == "/api/review":
                topic = (body.get("topic") or "学习主题").strip()
                note = (body.get("note") or "").strip()
                item = STORE.save(f"复盘｜{topic}：{note}", "review")
                json_response(self, {"item": item, "message": "复盘已保存，下一次可以从这里继续。", **STORE.status()}, 201)
                return
            json_response(self, {"error": "Not found"}, 404)
        except (ValueError, KeyError, UnicodeDecodeError) as exc:
            json_response(self, {"error": str(exc)}, 400)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"StudyFlow running at http://127.0.0.1:{PORT}")
    print(f"PowerContext: {STORE.status()['mode']} ({STORE.base})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


