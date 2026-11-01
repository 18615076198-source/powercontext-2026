"""seekdb 后端（评测要求的存储方案）。

两种接入形态：

* 嵌入式：``pyseekdb.Client(path=...)``，内核为 pylibseekdb（Linux / macOS）。
* 服务端：``pyseekdb.Client(host=..., port=...)``，连接 seekdb / OceanBase 实例。

集合里存的是「资料块」：规格条目、代码符号、测试用例。
检索走两条路：``where_document`` 全文下推 + 可选的向量近邻，再统一重排。
"""

from __future__ import annotations

from pathlib import Path

from ..models import Chunk, Hit
from .base import Store, query_terms

COLLECTION_NAME = "sddctx_chunks"
_FLAT_META = {"kind", "path", "symbol", "title", "line_start", "line_end", "content_hash"}


class SeekdbStore(Store):
    name = "seekdb"

    def __init__(self, settings) -> None:
        try:
            import pyseekdb
        except ImportError as exc:  # pragma: no cover - 平台相关
            raise RuntimeError(
                "seekdb 后端需要 pyseekdb。嵌入式内核 pylibseekdb 只提供 Linux/macOS 轮子；"
                "Windows 本机请改用 SDDCTX_STORE=sqlite，或在 Linux/CI 上运行。"
            ) from exc

        self.settings = settings
        self._client = self._make_client(pyseekdb)
        self._embedding = self._make_embedding(pyseekdb)
        self._collection = self._open_collection()

    # ---------------------------------------------------------------- 连接
    def _make_client(self, pyseekdb):
        settings = self.settings
        host = settings.extra.get("seekdb_host")
        if host:
            conn = {
                "host": host,
                "port": int(settings.extra.get("seekdb_port", 2881)),
                "user": settings.extra.get("seekdb_user", "root"),
                "password": settings.extra.get("seekdb_password", ""),
            }
        else:
            path = Path(settings.seekdb_path)
            path.mkdir(parents=True, exist_ok=True)
            conn = {"path": str(path)}
        self._ensure_database(pyseekdb, conn, settings.seekdb_database)
        return pyseekdb.Client(database=settings.seekdb_database, **conn)

    @staticmethod
    def _ensure_database(pyseekdb, conn: dict, database: str) -> None:
        """首次连接时库还不存在，先用 AdminClient 建库。

        seekdb 的 ``Client`` 只暴露集合操作，建库属于管理接口；``create_database``
        内部是 ``CREATE DATABASE IF NOT EXISTS``，重复调用安全。失败时不阻断流程，
        让后续真实错误带着原始堆栈暴露出来。
        """

        try:
            pyseekdb.AdminClient(**conn).create_database(database)
        except Exception as exc:  # pragma: no cover - 依赖真实 seekdb
            print(f"[seekdb] 建库 {database} 未成功（继续尝试直接使用）：{exc}")

    def _make_embedding(self, pyseekdb):
        if self.settings.seekdb_embedding in {"default", "on", "true", "1"}:
            from pyseekdb import DefaultEmbeddingFunction

            return DefaultEmbeddingFunction()
        return None

    def _open_collection(self):
        if self._client.has_collection(COLLECTION_NAME):
            return self._client.get_collection(COLLECTION_NAME, embedding_function=self._embedding)
        return self._client.get_or_create_collection(
            name=COLLECTION_NAME, embedding_function=self._embedding
        )

    # ---------------------------------------------------------------- 写入
    @staticmethod
    def _metadata(chunk: Chunk) -> dict:
        meta = {
            "kind": chunk.kind,
            "path": chunk.path,
            "symbol": chunk.symbol,
            "title": chunk.title,
            "line_start": int(chunk.line_start),
            "line_end": int(chunk.line_end),
            "content_hash": chunk.content_hash,
        }
        for key, value in chunk.metadata.items():
            if key in _FLAT_META or value is None:
                continue
            if isinstance(value, (str, int, float, bool)):
                meta[f"meta_{key}"] = value
            elif isinstance(value, list):
                meta[f"meta_{key}"] = ",".join(str(item) for item in value)[:500]
        return meta

    @staticmethod
    def _from_row(chunk_id: str, document: str | None, metadata: dict | None) -> Chunk:
        meta = metadata or {}
        extra = {
            key[5:]: value for key, value in meta.items() if key.startswith("meta_")
        }
        return Chunk(
            chunk_id=chunk_id,
            kind=str(meta.get("kind", "code")),
            path=str(meta.get("path", "")),
            symbol=str(meta.get("symbol", "")),
            title=str(meta.get("title", "")),
            content=document or "",
            line_start=int(meta.get("line_start", 0) or 0),
            line_end=int(meta.get("line_end", 0) or 0),
            metadata=extra,
            content_hash=str(meta.get("content_hash", "")),
        )

    def _vector_dim(self) -> int:
        dim = getattr(self._collection, "dimension", None)
        try:
            dim = int(dim) if dim is not None else 384
        except (TypeError, ValueError):
            dim = 384
        return dim or 384

    def upsert(self, chunks: list[Chunk]) -> int:
        if not chunks:
            return 0
        ids = [chunk.chunk_id for chunk in chunks]
        documents = [chunk.content for chunk in chunks]
        metadatas = [self._metadata(chunk) for chunk in chunks]
        # seekdb 的集合总带一个稠密向量列：开了 embedding 就让集合自己算，
        # 关掉 embedding 时写零向量——检索走全文通道（$contains），不依赖向量。
        embeddings = None
        if self._embedding is None:
            embeddings = [[0.0] * self._vector_dim() for _ in chunks]
        payload = {
            "ids": ids,
            "documents": documents,
            "metadatas": metadatas,
        }
        if embeddings is not None:
            payload["embeddings"] = embeddings
        if hasattr(self._collection, "upsert"):
            self._collection.upsert(**payload)
        else:  # pragma: no cover - 老版本兼容
            try:
                self._collection.delete(ids=ids)
            except Exception:
                pass
            self._collection.add(**payload)
        # 全文索引是异步构建的，刷一次再返回，保证紧接着的检索能命中
        refresh = getattr(self._collection, "refresh_index", None)
        if callable(refresh):
            try:
                refresh()
            except Exception:  # pragma: no cover - 1.2.0 及更早为空操作
                pass
        return len(ids)

    def reset(self) -> None:
        try:
            self._client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass
        self._collection = self._open_collection()

    # ---------------------------------------------------------------- 读取
    def count(self) -> dict[str, int]:
        result = self._collection.get(include=["metadatas"], limit=10000)
        metadatas = result.get("metadatas") or []
        counts: dict[str, int] = {}
        for meta in metadatas:
            kind = str((meta or {}).get("kind", "code"))
            counts[kind] = counts.get(kind, 0) + 1
        return counts

    def get(self, chunk_id: str) -> Chunk | None:
        result = self._collection.get(ids=[chunk_id], include=["documents", "metadatas"])
        ids = result.get("ids") or []
        if not ids:
            return None
        return self._from_row(ids[0], (result.get("documents") or [None])[0], (result.get("metadatas") or [None])[0])

    def find(self, *, kind: str | None = None, symbol: str | None = None) -> list[Chunk]:
        where: dict = {}
        if kind:
            where["kind"] = {"$eq": kind}
        if symbol:
            where["symbol"] = {"$eq": symbol}
        result = self._collection.get(
            where=where or None, include=["documents", "metadatas"], limit=1000
        )
        chunks: list[Chunk] = []
        for chunk_id, document, meta in zip(
            result.get("ids") or [], result.get("documents") or [], result.get("metadatas") or []
        ):
            chunks.append(self._from_row(chunk_id, document, meta))
        return chunks

    # ---------------------------------------------------------------- 检索
    def _collect(self, result: dict, bucket: dict[str, Chunk]) -> None:
        for chunk_id, document, meta in zip(
            result.get("ids") or [], result.get("documents") or [], result.get("metadatas") or []
        ):
            if chunk_id not in bucket:
                bucket[chunk_id] = self._from_row(chunk_id, document, meta)

    def search(self, query: str, kinds: list[str] | None, limit: int) -> list[Hit]:
        terms = query_terms(query, limit=10)
        candidates: dict[str, Chunk] = {}

        # 1) 全文下推：让 seekdb 按 $contains 过滤，只回传命中文档
        for term in terms[:8]:
            try:
                result = self._collection.get(
                    where_document={"$contains": term},
                    include=["documents", "metadatas"],
                    limit=200,
                )
            except Exception:
                continue
            self._collect(result, candidates)

        # 2) 启用 embedding 时追加向量近邻
        if self._embedding is not None:
            try:
                result = self._collection.query(
                    query_texts=[query],
                    n_results=max(limit * 3, 10),
                    include=["documents", "metadatas"],
                )
                self._collect(result, candidates)
            except Exception:
                pass

        # 3) 极端兜底：小语料直接取该 kind 的全部块
        if not candidates:
            where = {"kind": {"$in": kinds}} if kinds else None
            result = self._collection.get(where=where, include=["documents", "metadatas"], limit=1000)
            self._collect(result, candidates)

        return self._rank(query, list(candidates.values()), kinds, limit)

    # ---------------------------------------------------------------- 诊断
    def sql_ping(self) -> list:
        """用一条 SQL 证明连接可用（doctor 命令使用）。"""

        return self._client.execute("SELECT 1")

    def backend_info(self) -> dict:
        info = {
            "backend": self.name,
            "database": self.settings.seekdb_database,
            "path": str(self.settings.seekdb_path),
            "embedding": "default" if self._embedding is not None else "off",
            "chunks": self.count(),
        }
        try:
            info["sql_ping"] = str(self.sql_ping())
        except Exception as exc:  # pragma: no cover
            info["sql_ping"] = f"failed: {exc}"
        return info
