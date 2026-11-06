from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx
from dotenv import set_key

from .config import settings

log = logging.getLogger(__name__)


class PowerContextError(RuntimeError):
    pass


class PowerContextClient:
    """Small HTTP client for the local PowerContext 1.5 server (Basic memory)."""

    def __init__(self, base_url: str | None = None, scope_id: str | None = None) -> None:
        self.base_url = (base_url or settings.pc_base_url).rstrip("/")
        self.scope_id = scope_id if scope_id is not None else settings.pc_scope_id
        self._client = httpx.Client(base_url=self.base_url, timeout=15.0)

    def close(self) -> None:
        self._client.close()

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = self._client.post(path, json=payload)
        except httpx.HTTPError as exc:
            raise PowerContextError(f"PowerContext request failed: {exc}") from exc
        if resp.status_code >= 400:
            detail = resp.text[:500]
            raise PowerContextError(f"PowerContext {path} -> {resp.status_code}: {detail}")
        return resp.json()

    def _get(self, path: str) -> dict[str, Any]:
        try:
            resp = self._client.get(path)
        except httpx.HTTPError as exc:
            raise PowerContextError(f"PowerContext request failed: {exc}") from exc
        if resp.status_code == 404:
            raise FileNotFoundError(path)
        if resp.status_code >= 400:
            raise PowerContextError(f"PowerContext {path} -> {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    def health(self) -> bool:
        try:
            resp = self._client.get("/health/ready")
            return resp.status_code < 500
        except httpx.HTTPError:
            return False

    def ensure_scope(self) -> str:
        if self.scope_id:
            try:
                self._get(f"/v1/scopes/{self.scope_id}")
                return self.scope_id
            except FileNotFoundError:
                log.warning("configured PowerContext scope %s not found; creating a new one", self.scope_id)
            except PowerContextError as exc:
                log.warning("PowerContext scope check failed: %s", exc)

        payload = {
            "title": settings.pc_scope_title,
            "summary": "LabMemory: 低成本、可追溯的 RAG 课题组记忆与文献检索",
            "idempotency_key": "labmemory-demo-v1",
        }
        try:
            scope = self._post("/v1/scopes", payload)
        except PowerContextError:
            # Idempotency key may already exist. Find it by title.
            page = self._get("/v1/scopes?limit=100")
            items = page.get("items", [])
            match = next((s for s in items if s.get("title") == settings.pc_scope_title), None)
            if not match:
                raise
            scope = match
        self.scope_id = scope["scope_id"]
        env_path = Path(settings.base_dir) / ".env"
        set_key(str(env_path), "PC_SCOPE_ID", self.scope_id)
        log.info("PowerContext scope ready: %s", self.scope_id)
        return self.scope_id

    def remember(self, kind: str, text: str, description: str | None = None) -> dict[str, Any]:
        if not self.scope_id:
            self.ensure_scope()
        payload: dict[str, Any] = {"scope_id": self.scope_id, "kind": kind, "text": text}
        if description:
            payload["description"] = description
        data = self._post("/v1/memory/remember", payload)
        records = data.get("records", [])
        if not records:
            raise PowerContextError("PowerContext returned no memory record")
        return records[0]

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        if not self.scope_id:
            self.ensure_scope()
        payload = {"scope_id": self.scope_id, "query": query, "limit": limit, "mode": "auto"}
        try:
            data = self._post("/v1/memory/search", payload)
        except PowerContextError:
            payload["mode"] = "fts"
            data = self._post("/v1/memory/search", payload)
        return data.get("hits", [])

    def list_entries(self, limit: int = 100, include_inactive: bool = False) -> list[dict[str, Any]]:
        if not self.scope_id:
            self.ensure_scope()
        data = self._post(
            "/v1/memory/entries/list",
            {"scope_id": self.scope_id, "limit": limit, "include_inactive": include_inactive},
        )
        return data.get("entries", [])

    def forget(self, artifact_id: str, revision: int, state_version: int) -> bool:
        """Best-effort forget via the lifecycle endpoint.

        The exact contract is version-specific; the UI treats this as best effort.
        """
        if not self.scope_id:
            self.ensure_scope()
        try:
            self._post(
                "/v1/atomic-memory/lifecycle",
                {
                    "scope_id": self.scope_id,
                    "artifact_id": artifact_id,
                    "revision": revision,
                    "state_version": state_version,
                    "action": "forget",
                },
            )
            return True
        except PowerContextError as exc:
            log.info("forget is not available in this build: %s", exc)
            return False


client = PowerContextClient()


def artifact_id(record: dict[str, Any]) -> str:
    return record.get("artifact", {}).get("artifact_id", "")


def revision(record: dict[str, Any]) -> int:
    return int(record.get("artifact", {}).get("revision", 0))
