# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Parse a report PDF into one captured Source per physical page."""

from __future__ import annotations

import hashlib
import io
import math
import re
from typing import Any, Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, model_validator
from pypdf import PdfReader

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import SourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

PDF_PAGE_SOURCE_NAME = "pdf-page"
PDF_PAGE_SOURCE_VERSION = "1"
_MIN_SEARCH_CANDIDATES = 300
_TITLE_MATCH_BONUS = 2.0
# Questions that name a statement, table or note reward pages whose heading says so; prose
# questions ("what do the segment geographies look like") would only be hurt by that prior.
_STRUCTURE_CUES = frozenset({
    "statement",
    "statements",
    "balance",
    "sheet",
    "cash",
    "flow",
    "flows",
    "income",
    "tables",
    "table",
    "note",
    "notes",
    "schedule",
})

_IDENTITY_PREFIX = "pdf"
_TOKEN = re.compile(r"[a-z0-9]+")
_QUERY_STOPWORDS = frozenset([
    "a",
    "an",
    "the",
    "and",
    "or",
    "of",
    "to",
    "in",
    "on",
    "at",
    "by",
    "for",
    "from",
    "with",
    "as",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "what",
    "which",
    "who",
    "how",
    "why",
    "when",
    "where",
    "do",
    "does",
    "did",
    "can",
    "could",
    "should",
    "would",
    "will",
    "may",
    "might",
    "i",
    "we",
    "you",
    "it",
    "its",
    "our",
    "your",
    "this",
    "that",
    "these",
    "those",
    "there",
    "their",
    "they",
    "them",
    "he",
    "she",
    "his",
    "her",
    "has",
    "have",
    "had",
    "not",
    "no",
    "if",
    "then",
    "than",
    "so",
    "such",
    "about",
    "into",
    "over",
    "under",
    "between",
    "during",
    "s",
    "t",
    "d",
    "ll",
    "re",
    "ve",
    "m",
])


class PDFDocumentInput(BaseModel):
    """One complete PDF document and the identity callers address it by."""

    model_config = ConfigDict(frozen=True)

    document_id: str
    content: bytes


class PDFPageInput(BaseModel):
    """One physical page of a PDF document in source order."""

    model_config = ConfigDict(frozen=True)

    document_id: str
    document_sha256: str
    page_number: int
    text: str


class PDFPageSource(Source):
    """A captured PDF page addressed by document revision and physical page."""

    materialization: Literal[SourceMaterialization.CAPTURED] = SourceMaterialization.CAPTURED
    source_id: str
    document_id: str
    document_sha256: str
    page_number: int
    text: str

    @model_validator(mode="after")
    def validate_identity(self) -> PDFPageSource:
        if self.source_id != self.name:
            raise ValueError("source_id must equal the page identity carried by name")  # noqa: TRY003
        expected = pdf_page_source_id(self.document_id, self.document_sha256, self.page_number)
        if self.source_id != expected:
            raise ValueError("source_id must encode document, revision and page number")  # noqa: TRY003
        return self


class _PDFPageTextEvidence:
    """Project one page into the standard textual evidence shape."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class = TextEvidence

    def project(self, source: PDFPageSource) -> TextEvidence:
        return TextEvidence(
            source_type=PDF_PAGE_SOURCE_NAME,
            source_id=source.source_id,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


class _PDFPageSourceDefinition:
    """Bind the PDF page adapter to its durable version and projection."""

    name = PDF_PAGE_SOURCE_NAME
    version = PDF_PAGE_SOURCE_VERSION
    input_class = PDFPageInput
    source_class = PDFPageSource
    projections = (_PDFPageTextEvidence(),)

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        identity = pdf_page_source_id(value.document_id, value.document_sha256, value.page_number)
        return PDFPageSource(
            name=identity,
            definition_version=self.version,
            source_id=identity,
            document_id=value.document_id,
            document_sha256=value.document_sha256,
            page_number=value.page_number,
            text=value.text,
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput(
            document_id=source.document_id,
            document_sha256=source.document_sha256,
            page_number=source.page_number,
            text=source.text,
        )


PDF_PAGE_SOURCE_DEFINITION: SourceDefinition[PDFPageInput, PDFPageSource, PDFPageInput] = _PDFPageSourceDefinition()


def pdf_page_source_id(document_id: str, document_sha256: str, page_number: int) -> str:
    """Encode one page identity so a new revision never collides with the old one."""

    if not isinstance(page_number, int) or page_number < 1:
        raise ValueError("page_number must be a positive integer")  # noqa: TRY003
    identity = ":".join(
        (_IDENTITY_PREFIX, quote(document_id, safe=""), document_sha256, str(page_number)),
    )
    if len(identity) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"source_id must not exceed {MAX_SOURCE_ID_LENGTH} characters")  # noqa: TRY003
    return identity


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Extract every physical page of a complete PDF document."""

    document_id = value.document_id
    if not isinstance(document_id, str) or not document_id.strip():
        raise ValueError("document_id must be a non-empty string")  # noqa: TRY003
    content = bytes(value.content)
    if not content:
        raise ValueError("PDF content must not be empty")  # noqa: TRY003
    digest = hashlib.sha256(content).hexdigest()
    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as error:
        raise ValueError(f"PDF could not be parsed: {error}") from error  # noqa: TRY003
    if reader.is_encrypted and not reader.decrypt(""):
        raise ValueError("PDF requires a user password")  # noqa: TRY003
    try:
        pages = tuple(reader.pages)
    except Exception as error:
        raise ValueError(f"PDF could not be parsed: {error}") from error  # noqa: TRY003
    if not pages:
        raise ValueError("PDF must contain at least one page")  # noqa: TRY003

    parsed: list[PDFPageInput] = []
    for index, page in enumerate(pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as error:
            raise ValueError(f"PDF page {index} could not be extracted: {error}") from error  # noqa: TRY003
        parsed.append(
            PDFPageInput(document_id=document_id, document_sha256=digest, page_number=index, text=text),
        )
    for page in parsed:
        pdf_page_source_id(page.document_id, page.document_sha256, page.page_number)
    return tuple(parsed)


async def search_pdf_pages(memory, question: str, limit: int = 10):
    """Return distinct page citations for one natural-language question.

    Candidates are gathered with several lexical probes so a page that matches only part of
    the question is still considered, then ranked with BM25 over the candidate set instead of
    counting question substrings. Questions that name a statement or table also reward pages
    whose heading carries the same terms, because a statement's heading is the strongest
    lexical evidence of which page holds it.
    """

    from powercontext.builtin.artifacts.memory.models import MemoryCitation
    from powercontext.builtin.runtime import SearchMemoryRequest

    if not isinstance(question, str) or limit <= 0:
        return ()
    terms = _terms(question)
    hits: dict[str, Any] = {}
    for probe in _search_probes(question, terms):
        page = await memory.search(
            SearchMemoryRequest(query=probe, mode="fts", limit=max(limit * 10, _MIN_SEARCH_CANDIDATES)),
        )
        for hit in page.hits:
            hits.setdefault(hit.entry_id, hit)
    if not hits:
        return ()
    if terms:
        documents = {entry_id: _page_tokens(hit.text) for entry_id, hit in hits.items()}
        scores = _bm25_scores(documents, terms)
        query = set(terms)
        bonus = _TITLE_MATCH_BONUS if query & _STRUCTURE_CUES else 0.0
        if bonus:
            for entry_id, hit in hits.items():
                scores[entry_id] += bonus * len(query & set(_title_terms(hit.text)))
    else:
        scores = {entry_id: float(hit.score) for entry_id, hit in hits.items()}
    ranked = sorted(hits, key=lambda entry_id: (-scores.get(entry_id, 0.0), entry_id))
    selected = ranked[:limit]
    return tuple(
        MemoryCitation(
            memory_ref=hits[entry_id].memory_ref,
            entry_id=hits[entry_id].entry_id,
            entry_version_id=hits[entry_id].entry_version_id,
        )
        for entry_id in selected
    )


def _page_tokens(text: str) -> tuple[str, ...]:
    return tuple(
        token for token in _TOKEN.findall(text.lower()) if token not in _QUERY_STOPWORDS and len(token) > 1
    )


def _terms(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_page_tokens(text)))


def _search_probes(question: str, terms: tuple[str, ...]) -> tuple[str, ...]:
    probes = [question]
    if terms:
        probes.append(" ".join(terms))
    probes.extend(terms[:8])
    return tuple(dict.fromkeys(probe for probe in probes if probe.strip()))


def _bm25_scores(documents: dict[str, tuple[str, ...]], terms: tuple[str, ...]) -> dict[str, float]:
    total = len(documents)
    if total == 0:
        return {}
    lengths = {entry_id: len(tokens) for entry_id, tokens in documents.items()}
    average = sum(lengths.values()) / total or 1.0
    frequency: dict[str, int] = {}
    for tokens in documents.values():
        for token in set(tokens):
            frequency[token] = frequency.get(token, 0) + 1
    scores: dict[str, float] = {}
    for entry_id, tokens in documents.items():
        occurrences: dict[str, int] = {}
        for token in tokens:
            occurrences[token] = occurrences.get(token, 0) + 1
        score = 0.0
        for term in terms:
            count = occurrences.get(term, 0)
            if count == 0:
                continue
            common = frequency.get(term, 0)
            inverse = math.log(1.0 + (total - common + 0.5) / (common + 0.5))
            score += inverse * count * 2.2 / (count + 1.2 * (0.25 + 0.75 * lengths[entry_id] / average))
        scores[entry_id] = score
    return scores


def _title_terms(text: str) -> tuple[str, ...]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    # The text projection prefixes the document id; the heading starts on the next line.
    headings = [line for line in lines[1:] if line != "Table of Contents"]
    return _terms(" ".join(headings[:2]))


__all__ = [
    "PDF_PAGE_SOURCE_DEFINITION",
    "PDF_PAGE_SOURCE_NAME",
    "PDF_PAGE_SOURCE_VERSION",
    "PDFDocumentInput",
    "PDFPageInput",
    "PDFPageSource",
    "parse_pdf_document",
    "pdf_page_source_id",
    "search_pdf_pages",
]
