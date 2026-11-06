from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app import conflicts, db, memory  # noqa: E402
from backend.app.config import settings  # noqa: E402
from backend.app.embeddings import embed_texts, vector_literal  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ingest")

MEMORY_SEEDS: list[tuple[str, str]] = [
    ("decision", "我们不做 retriever fine-tune，先用 BM25 + DPR zero-shot 混合，原因是单卡 3090、要保证可复现。"),
    ("decision", "chunk size 定为 512 + overlap 64；引用精确到段落优先，1024 的噪声更多。"),
    ("decision", "暂不采用 Self-RAG 的全量自反思，端到端延迟约 2.3x；只保留按需检索和证据相关性检查。"),
    ("decision", "主方案仍是 RAG，长上下文模型只做对照；原因是成本、可追溯性和中间内容丢失。"),
    ("decision", "保留 BM25，使用 RRF(k=60) 融合；纯向量的 recall@10 不够，混合检索更稳。"),
    ("constraint", "最终系统必须离线可跑，不依赖外部 API；embedding 模型小于 100MB，CPU 可推理。"),
    ("progress", "已完成 9 篇论文和 8 条组会/实验笔记入库；下一步补 CRAG fallback 与 Adaptive-RAG 对比。"),
    ("next_step", "找不到证据时明确说找不到，不要硬编答案；回答必须带出处。"),
]


def clean_text(text: str) -> str:
    text = text.replace("\u00ad", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    text = clean_text(text)
    parts = re.split(r"(?<=[.!?。！？])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def chunk_text(text: str, max_chars: int = 700, min_chars: int = 80) -> list[str]:
    text = clean_text(text)
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    units: list[str] = []
    for para in paragraphs:
        if len(para) <= max_chars:
            units.append(para)
        else:
            units.extend(split_sentences(para))
    chunks: list[str] = []
    buf = ""
    for unit in units:
        if not buf:
            buf = unit
        elif len(buf) + len(unit) + 1 <= max_chars:
            buf += " " + unit
        else:
            if len(buf) >= min_chars:
                chunks.append(buf.strip())
            buf = unit
    if len(buf) >= min_chars:
        chunks.append(buf.strip())
    return chunks


def paper_pages(pdf_path: Path) -> list[tuple[int, str]]:
    pages: list[tuple[int, str]] = []
    doc = pymupdf.open(pdf_path)
    try:
        for idx, page in enumerate(doc, start=1):
            text = clean_text(page.get_text("text"))
            if not text:
                continue
            head = text[:200].lower()
            if idx > 3 and ("references" in head or "bibliography" in head):
                break
            pages.append((idx, text))
    finally:
        doc.close()
    return pages


def load_papers() -> list[dict[str, Any]]:
    return json.loads((Path(__file__).with_name("papers.json")).read_text(encoding="utf-8"))


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    return meta, parts[2].lstrip()


def ingest_papers() -> tuple[list[dict[str, Any]], list[tuple]]:
    papers = load_papers()
    chunk_rows: list[tuple] = []
    for paper in papers:
        pdf_path = Path(settings.papers_dir) / f"{paper['id']}.pdf"
        if not pdf_path.exists():
            log.warning("missing PDF for %s: %s", paper["id"], pdf_path)
            continue
        db.execute(
            """REPLACE INTO papers
               (id, arxiv_id, title, authors, published, abstract, summary_zh, keywords_zh, tags, pdf_path)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                paper["id"],
                paper["arxiv_id"],
                paper["title"],
                ", ".join(paper.get("authors", [])),
                paper.get("published"),
                paper.get("abstract", ""),
                paper.get("summary_zh", ""),
                paper.get("keywords_zh", ""),
                ", ".join(paper.get("tags", [])),
                str(pdf_path),
            ),
        )
        year = int(str(paper.get("published", "2020"))[:4])
        tags = ", ".join(paper.get("tags", []))
        url = f"https://arxiv.org/abs/{paper['arxiv_id']}"
        summary_text = f"{paper.get('summary_zh', '')} {paper.get('keywords_zh', '')}".strip()
        if summary_text:
            chunk_rows.append(
                (
                    "paper",
                    paper["id"],
                    paper["title"],
                    url,
                    0,
                    "中文摘要",
                    1,
                    year,
                    tags,
                    paper.get("summary_zh", ""),
                    summary_text,
                    paper.get("keywords_zh", ""),
                )
            )
        pages = paper_pages(pdf_path)
        chunk_index = 1
        for page_no, page_text in pages:
            for chunk in chunk_text(page_text):
                chunk_rows.append(
                    (
                        "paper",
                        paper["id"],
                        paper["title"],
                        url,
                        chunk_index,
                        f"p.{page_no}",
                        page_no,
                        year,
                        tags,
                        chunk,
                        chunk,
                        paper.get("keywords_zh", ""),
                    )
                )
                chunk_index += 1
        log.info("paper %s: %d chunks", paper["id"], chunk_index)
    return papers, chunk_rows


def ingest_notes() -> list[tuple]:
    rows: list[tuple] = []
    for path in sorted(settings.notes_dir.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(raw)
        note_id = meta.get("id", path.stem)
        title = meta.get("title", path.stem)
        kind = meta.get("kind", "note")
        project = meta.get("project", "rag-lab")
        note_date = meta.get("date")
        tags = meta.get("tags", "")
        db.execute(
            """REPLACE INTO notes (id, title, kind, project, note_date, content, tags)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (note_id, title, kind, project, note_date, body, tags),
        )
        note_chunks = chunk_text(body, max_chars=650, min_chars=40)
        for idx, chunk in enumerate(note_chunks):
            rows.append(
                (
                    "note",
                    note_id,
                    title,
                    "",
                    idx,
                    kind,
                    1,
                    int((note_date or "2026")[:4]),
                    tags,
                    chunk,
                    f"{title}\n{chunk}\n{tags}",
                    tags,
                )
            )
        log.info("note %s: %d chunks", note_id, len(note_chunks))
    return rows


def insert_chunks(rows: list[tuple]) -> int:
    if not rows:
        return 0
    texts = [r[10] for r in rows]
    log.info("embedding %d chunks ...", len(texts))
    vectors: list[list[float]] = []
    batch = 32
    for start in range(0, len(texts), batch):
        vectors.extend(embed_texts(texts[start : start + batch]))
        log.info("embedded %d/%d", min(start + batch, len(texts)), len(texts))
    payload = [(*row, vector_literal(vec)) for row, vec in zip(rows, vectors)]
    db.executemany(
        """INSERT INTO chunks
           (source_type, source_id, source_title, source_url, chunk_index, section, page, year,
            tags, content, search_text, keywords, embedding)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        payload,
    )
    return len(payload)


def seed_memories() -> int:
    try:
        memory.client.ensure_scope()
        existing = memory.client.list_entries(limit=100)
    except Exception as exc:  # noqa: BLE001
        log.warning("PowerContext unavailable; skip memory seed: %s", exc)
        return 0
    existing_texts = {e.get("text", "").strip() for e in existing}
    created = 0
    for kind, text in MEMORY_SEEDS:
        if text.strip() in existing_texts:
            continue
        memory.client.remember(kind, text)
        created += 1
    log.info("PowerContext memories created: %d (existing: %d)", created, len(existing))
    return created


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="clear papers/notes/chunks/conflicts first")
    args = parser.parse_args()

    db.init_db()
    if args.reset:
        for table in ("chunks", "papers", "notes", "conflicts"):
            db.execute(f"DELETE FROM {table}")
        log.info("cleared tables")

    papers, paper_chunks = ingest_papers()
    note_chunks = ingest_notes()
    total = insert_chunks(paper_chunks + note_chunks)
    log.info("inserted %d chunks", total)

    memories = seed_memories()
    try:
        scan = conflicts.rescan()
    except Exception as exc:  # noqa: BLE001
        scan = {"error": str(exc)[:200]}
    print(json.dumps({
        "papers": len(papers),
        "chunks": total,
        "memories_created": memories,
        "conflicts": scan,
        "counts": db.counts(),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
