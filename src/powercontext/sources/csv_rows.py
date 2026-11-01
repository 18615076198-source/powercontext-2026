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

"""Row-level CSV Sources that keep every field value byte-for-byte."""

from __future__ import annotations

import csv
import io
import json
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, JsonValue, model_validator

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import SourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

CSV_ROW_SOURCE_NAME = "csv-row"
CSV_ROW_SOURCE_VERSION = "1"

_IDENTITY_PREFIX = "csv"
_UTF8_BOM = b"\xef\xbb\xbf"


class CSVDocumentInput(BaseModel):
    """One offline CSV document to parse into row-level records."""

    model_config = ConfigDict(frozen=True)

    document_id: str
    primary_key: str
    content: bytes


class CSVRowInput(BaseModel):
    """One parsed CSV record in its original column order."""

    model_config = ConfigDict(frozen=True)

    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


class CSVRowSource(Source):
    """A captured CSV record addressed by document and primary key value."""

    materialization: Literal[SourceMaterialization.CAPTURED] = SourceMaterialization.CAPTURED
    source_id: str
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]

    @model_validator(mode="after")
    def validate_identity(self) -> CSVRowSource:
        if self.source_id != self.name:
            raise ValueError("source_id must equal the row identity carried by name")  # noqa: TRY003
        expected = csv_row_source_id(self.document_id, self.primary_key_value)
        if self.source_id != expected:
            raise ValueError("source_id must be the encoded document and primary key identity")  # noqa: TRY003
        if len(self.columns) != len(self.values):
            raise ValueError("columns and values must have the same width")  # noqa: TRY003
        return self


class _CSVRowTextEvidence:
    """Project one row into the standard textual evidence shape."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = CSVRowSource
    output_class = TextEvidence

    def project(self, source: CSVRowSource) -> TextEvidence:
        row = _row_mapping(source.columns, source.values)
        return TextEvidence(
            source_type=CSV_ROW_SOURCE_NAME,
            source_id=source.source_id,
            content=json.dumps(row, ensure_ascii=False, separators=(",", ":")),
            metadata={
                "document_id": source.document_id,
                "primary_key": source.primary_key,
                "primary_key_value": source.primary_key_value,
                "columns": list(source.columns),
                "row": row,
            },
        )


class _CSVRowSourceDefinition:
    """Bind the CSV row adapter to its durable version and projection."""

    name = CSV_ROW_SOURCE_NAME
    version = CSV_ROW_SOURCE_VERSION
    input_class = CSVRowInput
    source_class = CSVRowSource
    projections = (_CSVRowTextEvidence(),)

    async def resolve(self, value: CSVRowInput, /) -> CSVRowSource:
        identity = csv_row_source_id(value.document_id, value.primary_key_value)
        return CSVRowSource(
            name=identity,
            definition_version=self.version,
            source_id=identity,
            document_id=value.document_id,
            primary_key=value.primary_key,
            primary_key_value=value.primary_key_value,
            columns=value.columns,
            values=value.values,
        )

    async def read(self, source: CSVRowSource, /) -> CSVRowInput:
        return CSVRowInput(
            document_id=source.document_id,
            primary_key=source.primary_key,
            primary_key_value=source.primary_key_value,
            columns=source.columns,
            values=source.values,
        )


CSV_ROW_SOURCE_DEFINITION: SourceDefinition[CSVRowInput, CSVRowSource, CSVRowInput] = _CSVRowSourceDefinition()


def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    """Encode one row identity without delimiter collisions."""

    _require_trimmed(document_id, "document_id")
    if not isinstance(primary_key_value, str) or not primary_key_value.strip():
        raise ValueError("primary_key_value must be a non-empty string")  # noqa: TRY003
    identity = ":".join(
        (_IDENTITY_PREFIX, quote(document_id, safe=""), quote(primary_key_value, safe="")),
    )
    if len(identity) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"source_id must not exceed {MAX_SOURCE_ID_LENGTH} characters")  # noqa: TRY003
    return identity


def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    """Parse and validate a whole CSV document before returning any row."""

    document_id = _require_trimmed(value.document_id, "document_id")
    primary_key = value.primary_key
    if not isinstance(primary_key, str) or not primary_key.strip():
        raise ValueError("primary_key must be a non-empty string")  # noqa: TRY003

    records = _read_records(value.content)
    if not records:
        raise ValueError("CSV document must contain a header record")  # noqa: TRY003
    columns = tuple(_validate_header(records[0]))
    try:
        primary_key_index = columns.index(primary_key)
    except ValueError:
        raise ValueError(f"primary_key {primary_key!r} does not match any header column") from None  # noqa: TRY003

    rows: list[CSVRowInput] = []
    seen: set[str] = set()
    for record in records[1:]:
        if not record:
            continue
        if len(record) != len(columns):
            raise ValueError(  # noqa: TRY003
                f"record width {len(record)} does not match header width {len(columns)}",
            )
        primary_key_value = record[primary_key_index]
        if not primary_key_value.strip():
            raise ValueError("primary_key_value must be a non-empty string")  # noqa: TRY003
        if primary_key_value in seen:
            raise ValueError(f"duplicate primary_key_value {primary_key_value!r} in one document")  # noqa: TRY003
        seen.add(primary_key_value)
        rows.append(
            CSVRowInput(
                document_id=document_id,
                primary_key=primary_key,
                primary_key_value=primary_key_value,
                columns=columns,
                values=tuple(record),
            ),
        )
    for row in rows:
        csv_row_source_id(row.document_id, row.primary_key_value)
    return tuple(rows)


def _read_records(content: bytes) -> list[list[str]]:
    raw = bytes(content)
    if raw.startswith(_UTF8_BOM):
        raw = raw[len(_UTF8_BOM) :]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("CSV content must be valid UTF-8") from error  # noqa: TRY003
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        return list(reader)
    except csv.Error as error:
        raise ValueError(f"malformed CSV content: {error}") from error  # noqa: TRY003


def _validate_header(header: list[str]) -> tuple[str, ...]:
    if not header:
        raise ValueError("CSV document must contain a non-empty header record")  # noqa: TRY003
    seen: set[str] = set()
    for column in header:
        if not column or not column.strip():
            raise ValueError("header columns must be non-empty and not blank")  # noqa: TRY003
        if column in seen:
            raise ValueError(f"duplicate header column {column!r}")  # noqa: TRY003
        seen.add(column)
    return tuple(header)


def _row_mapping(columns: tuple[str, ...], values: tuple[str, ...]) -> dict[str, JsonValue]:
    return dict(zip(columns, values, strict=True))


def _require_trimmed(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")  # noqa: TRY003
    if value != value.strip():
        raise ValueError(f"{field} must not contain leading or trailing whitespace")  # noqa: TRY003
    return value


__all__ = [
    "CSV_ROW_SOURCE_DEFINITION",
    "CSV_ROW_SOURCE_NAME",
    "CSV_ROW_SOURCE_VERSION",
    "CSVDocumentInput",
    "CSVRowInput",
    "CSVRowSource",
    "csv_row_source_id",
    "parse_csv_document",
]
