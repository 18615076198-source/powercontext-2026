"""存储抽象：同一套接口，两种后端（seekdb / SQLite 兜底）。"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Iterable

from ..models import Chunk, Hit

_CJK = re.compile(r"[\u4e00-\u9fff]+")
_WORD = re.compile(r"[A-Za-z0-9_]+")
_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "not",
    "的", "了", "和", "与", "在", "是", "为", "要", "把", "并", "需", "个",
}


def tokenize(text: str) -> list[str]:
    """中英混合分词：英文按词、中文按二元组，足够用于小语料检索。"""

    lowered = text.lower()
    tokens = [word for word in _WORD.findall(lowered) if len(word) > 1]
    for block in _CJK.findall(lowered):
        if len(block) == 1:
            tokens.append(block)
        else:
            tokens.extend(block[i : i + 2] for i in range(len(block) - 1))
    return [token for token in tokens if token not in _STOP]


def query_terms(query: str, limit: int = 16) -> list[str]:
    seen: list[str] = []
    for token in tokenize(query):
        if token not in seen:
            seen.append(token)
    return seen[:limit]


def lexical_score(terms: Iterable[str], chunk: Chunk) -> tuple[float, list[str]]:
    """按命中词数打分；标题/规格编号命中额外加权。"""

    body = chunk.content.lower()
    title = f"{chunk.title} {chunk.symbol}".lower()
    matched: list[str] = []
    score = 0.0
    for term in terms:
        in_body = body.count(term)
        in_title = title.count(term)
        if not in_body and not in_title:
            continue
        matched.append(term)
        score += min(in_body, 5) * 1.0 + in_title * 3.0
    if terms:
        score = score / (len(list(terms)) or 1) + 0.1 * len(matched)
    return score, matched


class Store(ABC):
    """工程资料存储与检索接口。"""

    name = "abstract"

    @abstractmethod
    def reset(self) -> None: ...

    @abstractmethod
    def upsert(self, chunks: list[Chunk]) -> int: ...

    @abstractmethod
    def count(self) -> dict[str, int]: ...

    @abstractmethod
    def get(self, chunk_id: str) -> Chunk | None: ...

    @abstractmethod
    def find(self, *, kind: str | None = None, symbol: str | None = None) -> list[Chunk]: ...

    @abstractmethod
    def search(self, query: str, kinds: list[str] | None, limit: int) -> list[Hit]: ...

    @abstractmethod
    def backend_info(self) -> dict: ...

    # 供两种后端复用：对候选集做统一排序
    def _rank(self, query: str, candidates: list[Chunk], kinds: list[str] | None, limit: int) -> list[Hit]:
        terms = query_terms(query)
        hits: list[Hit] = []
        for chunk in candidates:
            if kinds and chunk.kind not in kinds:
                continue
            score, matched = lexical_score(terms, chunk)
            if score <= 0:
                continue
            reason = "命中：" + "、".join(matched[:6])
            hits.append(Hit(chunk=chunk, score=score, reason=reason))
        hits.sort(key=lambda hit: (-hit.score, hit.chunk.chunk_id))
        return hits[:limit]


def open_store(settings) -> Store:
    """按配置打开存储后端，seekdb 不可用时给出明确提示。"""

    if settings.store_backend == "seekdb":
        from .seekdb_store import SeekdbStore

        return SeekdbStore(settings)
    from .sqlite_store import SqliteStore

    return SqliteStore(settings)
