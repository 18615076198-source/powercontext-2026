"""PowerContext 接入：保存任务进展与验证结果，并在新进程里回读。

接入方式为 HTTP API（``POST /v1/memory/remember``、``POST /v1/sources/content``、
``POST /v1/context/prepare``），不依赖 PowerContext 的 Python SDK，
因此对 Server 版本不敏感，也能直接在 CI 里跑。

状态以两种形态落库：

* Memory（``kind=progress``）：一行带标记的紧凑 JSON，供下一次运行精确回读；
* Source（``metadata.kind=sdd-task-state``）：完整证据，供人工审阅与 Experience 孵化。
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from .models import RunState, now_iso

PREPARE_BLOCK = re.compile(
    r"BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1\s*(\{.*?\})\s*END_POWERCONTEXT_PREPARED_CONTEXT_V1",
    re.S,
)
STATE_MARKER = "SDDCTX-STATE"


class PowerContextError(RuntimeError):
    """PowerContext 不可用或调用失败。"""


@dataclass
class RecallResult:
    state: RunState | None
    source: str
    detail: str
    raw: dict | None = None


class PowerContextClient:
    def __init__(self, settings, trace=None) -> None:
        self.settings = settings
        self.trace = trace

    # ------------------------------------------------------------------ HTTP
    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        url = f"{self.settings.powercontext_url}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.settings.powercontext_token:
            headers["Authorization"] = f"Bearer {self.settings.powercontext_token}"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:600]
            raise PowerContextError(f"{method} {path} -> HTTP {error.code}: {detail}") from error
        except Exception as error:
            raise PowerContextError(f"{method} {path} 失败：{error}") from error
        return json.loads(body) if body else {}

    def _emit(self, event: str, **fields) -> None:
        if self.trace is not None:
            self.trace.emit(event, **fields)

    # ------------------------------------------------------------------ 能力
    def health(self) -> dict:
        try:
            return self._request("GET", "/health/ready")
        except PowerContextError as error:
            return {"status": "unavailable", "detail": str(error)}

    def capabilities(self) -> dict:
        try:
            return self._request("GET", "/v1/capabilities")
        except PowerContextError as error:
            return {"status": "unavailable", "detail": str(error)}

    # ------------------------------------------------------------------ 写入
    def ensure_scope(self, title: str, summary: str, key: str) -> str:
        """创建（或按幂等键复用）一个 Scope，返回 scope_id。"""

        payload = {"title": title, "summary": summary, "idempotency_key": key}
        response = self._request("POST", "/v1/scopes", payload)
        scope_id = response.get("scope_id") or ""
        if not scope_id:
            raise PowerContextError(f"创建 Scope 未返回 scope_id: {response}")
        self._emit("powercontext.scope", scope_id=scope_id, title=title, idempotency_key=key)
        return scope_id

    def remember(self, scope_id: str, kind: str, text: str, reason: str = "") -> dict:
        payload = {"scope_id": scope_id, "kind": kind, "text": text}
        if reason:
            payload["reason"] = reason
        response = self._request("POST", "/v1/memory/remember", payload)
        entry = (response.get("entry") or {}).get("citation", {}).get("entry_id", "")
        self._emit("powercontext.remember", scope_id=scope_id, kind=kind, entry_id=entry, chars=len(text))
        return response

    def capture_source(self, scope_id: str, source_id: str, content: str, metadata: dict) -> dict:
        payload = {
            "scope_id": scope_id,
            "source_id": source_id,
            "content": content,
            "metadata": metadata,
        }
        response = self._request("POST", "/v1/sources/content", payload)
        self._emit(
            "powercontext.source",
            scope_id=scope_id,
            source_id=source_id,
            status=response.get("status"),
            chars=len(content),
        )
        return response

    # ------------------------------------------------------------------ 业务动作
    def save_state(self, scope_id: str, state: RunState) -> dict:
        """把任务状态写入 PowerContext：Memory 承载可回读快照，Source 承载完整证据。"""

        compact = {
            "task_id": state.task_id,
            "status": state.status,
            "done": state.done,
            "todo": state.todo,
            "verification": state.verification,
            "change": state.change,
            "revision": state.revision,
            "updated_at": state.updated_at,
        }
        text = f"{STATE_MARKER} {state.task_id} " + json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
        memory_response = self.remember(
            scope_id,
            "progress",
            text,
            reason=f"{state.task_id} 状态快照 r{state.revision}",
        )
        evidence = json.dumps(state.to_dict(), ensure_ascii=False, indent=2)
        # Source 身份不可复用不同内容：把内容摘要拼进 source_id，天然幂等
        digest = hashlib.sha256(evidence.encode("utf-8")).hexdigest()[:8]
        source_id = f"sddctx-state-{state.task_id}-r{state.revision}-{digest}"
        try:
            source_response = self.capture_source(
                scope_id,
                source_id,
                evidence,
                {"kind": "sdd-task-state", "task_id": state.task_id, "revision": state.revision},
            )
        except PowerContextError as error:
            # 409 source_conflict：同一份状态已入库过，视为成功
            if "source_conflict" not in str(error):
                raise
            source_response = {"status": "already_captured", "source_id": source_id}
        return {"memory": memory_response, "source": source_response, "text": text}

    def recall_state(self, scope_id: str, task_id: str) -> RecallResult:
        """回读任务状态：先走上下文准备，再退回记忆检索。"""

        query = f"{STATE_MARKER} {task_id} 任务状态"
        try:
            prepared = self._request(
                "POST", "/v1/context/prepare", {"scope_id": scope_id, "query": query, "max_bytes": 8000}
            )
            found = self._state_from_prepared(prepared, task_id)
            if found is not None:
                self._emit("powercontext.recall", scope_id=scope_id, task_id=task_id, source="prepare", hit=True)
                return RecallResult(state=found, source="prepare", detail="context/prepare 召回", raw=prepared)
        except PowerContextError as error:
            prepared = {"error": str(error)}

        try:
            hits = self._request(
                "POST", "/v1/memory/search", {"scope_id": scope_id, "query": f"{STATE_MARKER} {task_id}", "limit": 10}
            )
        except PowerContextError as error:
            return RecallResult(state=None, source="none", detail=f"记忆检索失败：{error}")

        candidates: list[RunState] = []
        for hit in hits.get("hits") or []:
            state = self._state_from_text(hit.get("text", ""), task_id)
            if state is not None:
                candidates.append(state)
        latest = _latest(candidates)
        if latest is not None:
            self._emit(
                "powercontext.recall",
                scope_id=scope_id,
                task_id=task_id,
                source="memory_search",
                hit=True,
                revision=latest.revision,
            )
            return RecallResult(state=latest, source="memory_search", detail="memory/search 召回", raw=hits)
        self._emit("powercontext.recall", scope_id=scope_id, task_id=task_id, source="none", hit=False)
        return RecallResult(state=None, source="none", detail="未召回该任务的状态", raw=hits)

    # ------------------------------------------------------------------ 解析
    @staticmethod
    def _state_from_text(text: str, task_id: str) -> RunState | None:
        prefix = f"{STATE_MARKER} {task_id} "
        index = text.find(prefix)
        if index < 0:
            return None
        payload = text[index + len(prefix) :].strip()
        depth = 0
        end = -1
        for position, char in enumerate(payload):
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = position + 1
                    break
        if end < 0:
            return None
        try:
            return RunState.from_dict(json.loads(payload[:end]))
        except json.JSONDecodeError:
            return None

    def _state_from_prepared(self, prepared: dict, task_id: str) -> RunState | None:
        content = prepared.get("content") or ""
        match = PREPARE_BLOCK.search(content)
        if not match:
            return None
        try:
            block = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
        candidates = [
            state
            for item in (block.get("items") or [])
            if (state := self._state_from_text(item.get("content", ""), task_id)) is not None
        ]
        return _latest(candidates)


def _latest(states: list[RunState]) -> RunState | None:
    """同一任务可能留下多次状态快照，取 revision 最大（同 revision 取更新）的那份。"""

    if not states:
        return None
    return max(states, key=lambda state: (state.revision, state.updated_at))


def build_state(
    task_id: str,
    *,
    status: str,
    done: list[str],
    todo: list[str],
    verification: list[dict],
    change: dict,
    revision: int,
) -> RunState:
    return RunState(
        task_id=task_id,
        status=status,
        done=done,
        todo=todo,
        verification=verification,
        change=change,
        revision=revision,
        updated_at=now_iso(),
    )
