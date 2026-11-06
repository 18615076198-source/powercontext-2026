from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

import pymysql
from pymysql.cursors import DictCursor

from .config import settings

log = logging.getLogger(__name__)


def _connect(database: str | None = None) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=settings.seekdb_host,
        port=settings.seekdb_port,
        user=settings.seekdb_user,
        password=settings.seekdb_password,
        database=database,
        charset="utf8mb4",
        autocommit=True,
        cursorclass=DictCursor,
        connect_timeout=5,
        read_timeout=20,
        write_timeout=20,
    )


@contextmanager
def get_conn(database: str | None = None):
    conn = _connect(database)
    try:
        yield conn
    finally:
        conn.close()


def _schema_statements() -> list[str]:
    sql = (Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8")
    lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    return [stmt.strip() for stmt in "\n".join(lines).split(";") if stmt.strip()]


def init_db() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{settings.seekdb_db}` "
                "CHARACTER SET utf8mb4"
            )
    with get_conn(settings.seekdb_db) as conn:
        with conn.cursor() as cur:
            for stmt in _schema_statements():
                cur.execute(stmt)
    log.info("seekdb schema ready in %s", settings.seekdb_db)


def fetch_all(sql: str, params: Iterable[Any] | None = None) -> list[dict[str, Any]]:
    with get_conn(settings.seekdb_db) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params or ()))
            return list(cur.fetchall())


def fetch_one(sql: str, params: Iterable[Any] | None = None) -> dict[str, Any] | None:
    rows = fetch_all(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: Iterable[Any] | None = None) -> int:
    with get_conn(settings.seekdb_db) as conn:
        with conn.cursor() as cur:
            return cur.execute(sql, tuple(params or ()))


def executemany(sql: str, rows: list[tuple[Any, ...]]) -> int:
    with get_conn(settings.seekdb_db) as conn:
        with conn.cursor() as cur:
            return cur.executemany(sql, rows)


def counts() -> dict[str, int]:
    out: dict[str, int] = {}
    for table in ("papers", "notes", "chunks", "queries", "conflicts"):
        row = fetch_one(f"SELECT COUNT(*) AS n FROM {table}")
        out[table] = int(row["n"]) if row else 0
    return out


def ping() -> bool:
    try:
        row = fetch_one("SELECT 1 AS ok")
        return bool(row and row["ok"] == 1)
    except Exception as exc:  # noqa: BLE001
        log.warning("seekdb ping failed: %s", exc)
        return False
