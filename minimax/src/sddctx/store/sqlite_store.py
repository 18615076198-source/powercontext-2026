"""SQLite 兜底后端。

用途：本机（Windows）或离线环境没有 seekdb 内核时，仍能跑通完整流程。
它不是评测要求的存储方案——评测请使用 ``SDDCTX_STORE=seekdb``。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..models import Chunk, Hit
from .base import Store, query_terms


class SqliteStore(Store):
    name = "sqlite"

    def __init__(self, settings) -> None:
        self.path = Path(settings.sqlite_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._create_schema()

    def _create_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                path TEXT NOT NULL,
                symbol TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                line_start INTEGER NOT NULL,
                line_end INTEGER NOT NULL,
                metadata TEXT NOT NULL,
                content_hash TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_kind ON chunks(kind);
            CREATE INDEX IF NOT EXISTS idx_chunks_symbol ON chunks(symbol);
            """
        )
        self._conn.commit()

    def reset(self) -> None:
        self._conn.execute("DELETE FROM chunks")
        self._conn.commit()

    def upsert(self, chunks: list[Chunk]) -> int:
        rows = [
            (
                chunk.chunk_id,
                chunk.kind,
                chunk.path,
                chunk.symbol,
                chunk.title,
                chunk.content,
                chunk.line_start,
                chunk.line_end,
                json.dumps(chunk.metadata, ensure_ascii=False),
                chunk.content_hash,
            )
            for chunk in chunks
        ]
        self._conn.executemany(
            """
            INSERT INTO chunks (chunk_id, kind, path, symbol, title, content, line_start, line_end, metadata, content_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chunk_id) DO UPDATE SET
                kind=excluded.kind, path=excluded.path, symbol=excluded.symbol, title=excluded.title,
                content=excluded.content, line_start=excluded.line_start, line_end=excluded.line_end,
                metadata=excluded.metadata, content_hash=excluded.content_hash
            """,
            rows,
        )
        self._conn.commit()
        return len(rows)

    def count(self) -> dict[str, int]:
        rows = self._conn.execute("SELECT kind, COUNT(*) AS n FROM chunks GROUP BY kind").fetchall()
        return {row["kind"]: row["n"] for row in rows}

    def get(self, chunk_id: str) -> Chunk | None:
        row = self._conn.execute("SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
        return self._to_chunk(row) if row else None

    def find(self, *, kind: str | None = None, symbol: str | None = None) -> list[Chunk]:
        sql = "SELECT * FROM chunks WHERE 1=1"
        args: list[str] = []
        if kind:
            sql += " AND kind = ?"
            args.append(kind)
        if symbol:
            sql += " AND (symbol = ? OR chunk_id LIKE ?)"
            args.extend([symbol, f"%:{symbol}"])
        rows = self._conn.execute(sql, args).fetchall()
        return [self._to_chunk(row) for row in rows]

    def search(self, query: str, kinds: list[str] | None, limit: int) -> list[Hit]:
        terms = query_terms(query)
        if not terms:
            return []
        where = " OR ".join(["LOWER(content) LIKE ?" for _ in terms])
        args = [f"%{term}%" for term in terms]
        sql = f"SELECT * FROM chunks WHERE ({where})"
        if kinds:
            sql += f" AND kind IN ({','.join('?' for _ in kinds)})"
            args.extend(kinds)
        rows = self._conn.execute(sql, args).fetchall()
        candidates = [self._to_chunk(row) for row in rows]
        return self._rank(query, candidates, kinds, limit)

    def backend_info(self) -> dict:
        return {"backend": self.name, "path": str(self.path), "chunks": self.count()}

    @staticmethod
    def _to_chunk(row: sqlite3.Row) -> Chunk:
        return Chunk(
            chunk_id=row["chunk_id"],
            kind=row["kind"],
            path=row["path"],
            symbol=row["symbol"],
            title=row["title"],
            content=row["content"],
            line_start=row["line_start"],
            line_end=row["line_end"],
            metadata=json.loads(row["metadata"]),
            content_hash=row["content_hash"],
        )
