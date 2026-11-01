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
import re
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, model_validator
from pypdf import PdfReader

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import SourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

PDF_PAGE_SOURCE_NAME = "pdf-page"
PDF_PAGE_SOURCE_VERSION = "1"

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
    """Return distinct page citations for one natural-language question."""

    from powercontext.builtin.artifacts.memory.models import MemoryCitation
    from powercontext.builtin.runtime import GetMemoryEntryRequest, SearchMemoryRequest

    if limit <= 0:
        return ()
    candidates: dict[str, tuple[MemoryCitation, str]] = {}
    for query in _query_variants(question):
        page = await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=max(limit * 5, 50)))
        for hit in page.hits:
            citation = MemoryCitation(
                memory_ref=hit.memory_ref,
                entry_id=hit.entry_id,
                entry_version_id=hit.entry_version_id,
            )
            if citation.entry_id in candidates:
                continue
            entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
            candidates[citation.entry_id] = (citation, entry.text)

    terms = _terms(question)
    ranked = sorted(
        candidates.values(),
        key=lambda item: (-_score(terms, item[1]), item[0].entry_id),
    )
    return tuple(citation for citation, _text in ranked[:limit])


def _query_variants(question: str) -> tuple[str, ...]:
    terms = _terms(question)
    variants = [question]
    if terms:
        variants.append(" ".join(terms))
    for term in terms[:6]:
        variants.append(term)
    return tuple(dict.fromkeys(variants))


def _terms(text: str) -> tuple[str, ...]:
    tokens = _TOKEN.findall(text.lower())
    terms = [token for token in tokens if token not in _QUERY_STOPWORDS and len(token) > 1]
    return tuple(dict.fromkeys(terms))


def _score(terms: tuple[str, ...], text: str) -> int:
    lowered = text.lower()
    return sum(1 for term in terms if term in lowered)


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
