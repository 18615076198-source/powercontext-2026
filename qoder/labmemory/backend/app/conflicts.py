from __future__ import annotations

import hashlib
import logging
from typing import Any

from . import db, memory

log = logging.getLogger(__name__)

# (label, terms, weight). Weak groups alone are not enough to raise a review card.
GROUPS: list[tuple[str, set[str], int]] = [
    ("retriever 微调", {"fine-tune", "finetune", "微调", "dpr", "dense-retrieval", "retriever"}, 3),
    ("Self-RAG / 自反思", {"self-rag", "自反思", "reflection", "反思 token", "反思token"}, 3),
    ("长上下文", {"long-context", "long context", "长上下文", "longbench", "lost in the middle"}, 2),
    ("纠错 / corrective", {"crag", "corrective", "纠错", "retrieval evaluator", "检索评估"}, 2),
    ("自适应检索", {"adaptive-rag", "adaptive", "自适应", "question complexity", "问题复杂度"}, 2),
    ("混合检索", {"bm25", "rrf", "hybrid", "混合检索"}, 1),
    ("延迟 / 成本", {"latency", "延迟", "cost", "成本", "efficient", "高效"}, 1),
]


def _paper_blob(paper: dict[str, Any]) -> str:
    parts = [
        str(paper.get("title") or ""),
        str(paper.get("tags") or ""),
        str(paper.get("keywords_zh") or ""),
        str(paper.get("abstract") or ""),
    ]
    return " ".join(parts).lower()


def _match_groups(paper_text: str, mem_text: str) -> list[tuple[str, list[str], list[str], int]]:
    matches: list[tuple[str, list[str], list[str], int]] = []
    for label, terms, weight in GROUPS:
        p_hits = sorted({t for t in terms if t in paper_text})
        m_hits = sorted({t for t in terms if t in mem_text})
        if p_hits and m_hits:
            matches.append((label, p_hits, m_hits, weight))
    return matches


def _conflict_id(paper_id: str, artifact_id: str) -> str:
    return "cf_" + hashlib.md5(f"{paper_id}:{artifact_id}".encode()).hexdigest()[:16]


def rescan(max_conflicts: int = 4) -> dict[str, Any]:
    papers = db.fetch_all("SELECT id, title, tags, keywords_zh, abstract FROM papers")
    try:
        entries = memory.client.list_entries(limit=100)
    except Exception as exc:  # noqa: BLE001
        log.warning("conflict scan skipped; PowerContext unavailable: %s", exc)
        return {"created": 0, "scanned": 0, "error": str(exc)[:300]}

    memories = [
        m
        for m in entries
        if m.get("state") == "active" and m.get("kind") in ("decision", "constraint")
    ]

    candidates: list[dict[str, Any]] = []
    for paper in papers:
        paper_text = _paper_blob(paper)
        for mem in memories:
            art = mem.get("artifact", {})
            aid = art.get("artifact_id", "")
            if not aid:
                continue
            matches = _match_groups(paper_text, _memory_blob(mem))
            score = sum(m[3] for m in matches)
            if score <= 0:
                continue
            candidates.append(
                {
                    "paper": paper,
                    "mem": mem,
                    "artifact_id": aid,
                    "revision": art.get("revision"),
                    "matches": matches,
                    "score": score,
                }
            )

    candidates.sort(key=lambda c: (-c["score"], len(c["matches"]), c["paper"]["id"]))
    db.execute("DELETE FROM conflicts WHERE status='open'")

    created = 0
    used_papers: set[str] = set()
    used_memories: set[str] = set()
    for cand in candidates:
        if created >= max_conflicts:
            break
        paper_id = cand["paper"]["id"]
        aid = cand["artifact_id"]
        if paper_id in used_papers or aid in used_memories:
            continue
        used_papers.add(paper_id)
        used_memories.add(aid)
        matches = cand["matches"]
        labels = [m[0] for m in matches]
        terms = sorted({t for m in matches for t in m[1] + m[2]})
        reason = (
            f"论文《{cand['paper'].get('title', cand['paper']['id'])}》涉及「{'、'.join(labels)}」"
            f"（关键词：{', '.join(terms[:6])}），可能影响既有决策："
            f"{cand['mem'].get('text', '')[:160]}"
        )
        db.execute(
            """INSERT IGNORE INTO conflicts
               (id, paper_id, memory_artifact_id, memory_revision, memory_text, reason, status)
               VALUES (%s, %s, %s, %s, %s, %s, 'open')""",
            (
                _conflict_id(cand["paper"]["id"], aid),
                cand["paper"]["id"],
                aid,
                cand["revision"],
                cand["mem"].get("text", ""),
                reason,
            ),
        )
        created += 1
    return {"created": created, "scanned": len(papers) * len(memories), "candidates": len(candidates)}


def _memory_blob(mem: dict[str, Any]) -> str:
    return str(mem.get("text") or "").lower()


def list_conflicts(status: str = "open") -> list[dict[str, Any]]:
    return db.fetch_all(
        """SELECT c.*, p.title AS paper_title, p.arxiv_id
           FROM conflicts c LEFT JOIN papers p ON p.id = c.paper_id
           WHERE c.status = %s ORDER BY c.created_at DESC""",
        (status,),
    )


def dismiss(conflict_id: str) -> bool:
    return db.execute("UPDATE conflicts SET status='dismissed' WHERE id=%s", (conflict_id,)) > 0


def create_review_task(conflict_id: str) -> dict[str, Any] | None:
    row = db.fetch_one(
        """SELECT c.*, p.title AS paper_title
           FROM conflicts c LEFT JOIN papers p ON p.id = c.paper_id
           WHERE c.id = %s""",
        (conflict_id,),
    )
    if not row:
        return None
    text = (
        f"复核任务：论文《{row.get('paper_title') or row['paper_id']}》可能影响决策——"
        f"{row.get('memory_text', '')[:240]}。请确认是否需要修改方案。"
    )
    record = memory.client.remember("review", text, description="由冲突提醒生成的复核任务")
    db.execute("UPDATE conflicts SET status='reviewed' WHERE id=%s", (conflict_id,))
    return record
