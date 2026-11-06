from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import conflicts, db, memory
from .answer import answer_question
from .config import settings
from .search import hybrid_search, log_query

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("labmemory")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        db.init_db()
    except Exception as exc:  # noqa: BLE001
        log.error("seekdb init failed: %s", exc)
    try:
        memory.client.ensure_scope()
    except Exception as exc:  # noqa: BLE001
        log.warning("PowerContext not ready at startup: %s", exc)
    yield
    memory.client.close()


app = FastAPI(title="LabMemory API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    filters: dict[str, Any] | None = None
    top_k: int = Field(default=6, ge=1, le=12)


class AskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    filters: dict[str, Any] | None = None


class MemoryCreate(BaseModel):
    kind: str = Field(default="decision", max_length=64)
    text: str = Field(min_length=1, max_length=8000)
    description: str | None = Field(default=None, max_length=200)


@app.get("/api/health")
def health() -> dict[str, Any]:
    counts = db.counts()
    pc_ok = memory.client.health()
    scope = memory.client.scope_id
    return {
        "seekdb": "ok" if db.ping() else "down",
        "powercontext": "ok" if pc_ok else "down",
        "scope_id": scope,
        "counts": counts,
    }


@app.get("/api/stats")
def stats() -> dict[str, Any]:
    counts = db.counts()
    mem_count = 0
    mem_error = None
    try:
        mem_count = len(memory.client.list_entries(limit=100))
    except Exception as exc:  # noqa: BLE001
        mem_error = str(exc)[:200]
    return {
        "papers": counts["papers"],
        "notes": counts["notes"],
        "chunks": counts["chunks"],
        "queries": counts["queries"],
        "conflicts_open": counts["conflicts"],
        "memories": mem_count,
        "memory_error": mem_error,
        "scope_id": memory.client.scope_id,
    }


@app.get("/api/papers")
def papers() -> list[dict[str, Any]]:
    return db.fetch_all(
        """SELECT p.*, (SELECT COUNT(*) FROM chunks c
                        WHERE c.source_type='paper' AND c.source_id=p.id) AS chunk_count
           FROM papers p ORDER BY p.published DESC"""
    )


@app.get("/api/papers/{paper_id}")
def paper_detail(paper_id: str) -> dict[str, Any]:
    paper = db.fetch_one("SELECT * FROM papers WHERE id=%s", (paper_id,))
    if not paper:
        raise HTTPException(404, "paper not found")
    chunks = db.fetch_all(
        """SELECT id, chunk_index, section, page, content, MATCH(search_text, keywords)
                  AGAINST (%s) AS bm25
           FROM chunks WHERE source_type='paper' AND source_id=%s
           ORDER BY chunk_index LIMIT 100""",
        (paper.get("title", ""), paper_id),
    )
    return {"paper": paper, "chunks": chunks}


@app.get("/api/notes")
def notes() -> list[dict[str, Any]]:
    return db.fetch_all("SELECT * FROM notes ORDER BY note_date DESC")


@app.post("/api/search")
def search(req: SearchRequest) -> dict[str, Any]:
    result = hybrid_search(req.query, req.filters, req.top_k)
    log_query(req.query, req.filters, result["trace"], result["latency_ms"])
    return result


@app.post("/api/ask")
def ask(req: AskRequest) -> dict[str, Any]:
    return answer_question(req.query, req.filters)


@app.get("/api/memories")
def memories() -> dict[str, Any]:
    try:
        entries = memory.client.list_entries(limit=100)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"PowerContext unavailable: {exc}") from exc
    out = []
    for e in entries:
        art = e.get("artifact", {})
        out.append(
            {
                "artifact_id": art.get("artifact_id"),
                "revision": art.get("revision"),
                "kind": e.get("kind"),
                "text": e.get("text"),
                "state": e.get("state"),
                "state_version": e.get("state_version"),
            }
        )
    return {"scope_id": memory.client.scope_id, "entries": out}


@app.post("/api/memories")
def create_memory(req: MemoryCreate) -> dict[str, Any]:
    try:
        record = memory.client.remember(req.kind, req.text, req.description)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"PowerContext unavailable: {exc}") from exc
    art = record.get("artifact", {})
    return {
        "artifact_id": art.get("artifact_id"),
        "revision": art.get("revision"),
        "kind": record.get("kind"),
        "text": record.get("text"),
        "state": record.get("state"),
    }


@app.get("/api/conflicts")
def conflict_list(status: str = "open") -> dict[str, Any]:
    return {"conflicts": conflicts.list_conflicts(status)}


@app.post("/api/conflicts/{conflict_id}/dismiss")
def conflict_dismiss(conflict_id: str) -> dict[str, Any]:
    ok = conflicts.dismiss(conflict_id)
    if not ok:
        raise HTTPException(404, "conflict not found")
    return {"ok": True}


@app.post("/api/conflicts/{conflict_id}/review")
def conflict_review(conflict_id: str) -> dict[str, Any]:
    record = conflicts.create_review_task(conflict_id)
    if not record:
        raise HTTPException(404, "conflict not found")
    art = record.get("artifact", {})
    return {"ok": True, "artifact_id": art.get("artifact_id"), "revision": art.get("revision")}


@app.post("/api/conflicts/rescan")
def conflict_rescan() -> dict[str, Any]:
    return conflicts.rescan()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(settings.frontend_dir / "index.html")


app.mount("/static", StaticFiles(directory=str(settings.frontend_dir)), name="static")
