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

"""Capture the raw visible events of one selected Pi session branch."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal
from urllib.parse import quote

import rfc8785
from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter, model_validator

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.connectors import ConnectorRunCompletion, ConnectorRunSession, ConnectorRunStatus
from powercontext.sources.definitions import SourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

PI_EVENT_SOURCE_NAME = "pi-event"
PI_EVENT_SOURCE_VERSION = "1"
PI_SESSION_CONNECTOR_NAME = "pi-session-history"
PI_CONNECTOR_VERSION = "1"

_SESSION_TYPE = "session"
_SESSION_VERSION = 3
_CONTROL_EVENT_TYPES = frozenset({"compaction", "branch_summary", "custom_message", "message"})
_JSON_VALUE = TypeAdapter(JsonValue)
_UTF8_BOM = b"\xef\xbb\xbf"


class PiSessionInput(BaseModel):
    """One raw Pi session archive and the branch leaf to capture."""

    model_config = ConfigDict(frozen=True)

    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    """One visible event of the selected branch with its complete input record."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


class PiEventSource(Source):
    """A captured Pi event addressed by session and event identity."""

    materialization: Literal[SourceMaterialization.CAPTURED] = SourceMaterialization.CAPTURED
    source_id: str
    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]

    @model_validator(mode="after")
    def validate_identity(self) -> PiEventSource:
        if self.source_id != self.name:
            raise ValueError("source_id must equal the event identity carried by name")  # noqa: TRY003
        if self.source_id != pi_event_source_id(self.session_id, self.event_id):
            raise ValueError("source_id must encode the session and event identity")  # noqa: TRY003
        return self


class _PiEventTextEvidence:
    """Project one event into the standard textual evidence shape."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PiEventSource
    output_class = TextEvidence

    def project(self, source: PiEventSource) -> TextEvidence:
        return TextEvidence(
            source_type=PI_EVENT_SOURCE_NAME,
            source_id=source.source_id,
            content=source.content,
            metadata={
                "session_id": source.session_id,
                "event_id": source.event_id,
                "parent_id": source.parent_id,
                "event_type": source.event_type,
                "role": source.role,
            },
        )


class _PiEventSourceDefinition:
    """Bind the Pi event adapter to its durable version and projection."""

    name = PI_EVENT_SOURCE_NAME
    version = PI_EVENT_SOURCE_VERSION
    input_class = PiEventInput
    source_class = PiEventSource
    projections = (_PiEventTextEvidence(),)

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        identity = pi_event_source_id(value.session_id, value.event_id)
        return PiEventSource(
            name=identity,
            definition_version=self.version,
            source_id=identity,
            session_id=value.session_id,
            event_id=value.event_id,
            parent_id=value.parent_id,
            event_type=value.event_type,
            role=value.role,
            content=value.content,
            record=value.record,
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput(
            session_id=source.session_id,
            event_id=source.event_id,
            parent_id=source.parent_id,
            event_type=source.event_type,
            role=source.role,
            content=source.content,
            record=source.record,
        )


PI_EVENT_SOURCE_DEFINITION: SourceDefinition[PiEventInput, PiEventSource, PiEventInput] = _PiEventSourceDefinition()


def pi_event_source_id(session_id: str, event_id: str) -> str:
    """Encode one event identity without delimiter collisions."""

    identity = ":".join(("pi", quote(session_id, safe=""), quote(event_id, safe="")))
    if len(identity) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"source_id must not exceed {MAX_SOURCE_ID_LENGTH} characters")  # noqa: TRY003
    return identity


def parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]:
    """Return the visible events of the selected branch, ordered root to leaf."""

    records = _read_records(value.content)
    session_id = _validate_header(records[0])
    nodes = _index_records(records[1:])
    leaf_id = _resolve_leaf(nodes, value.leaf_id)

    chain: list[dict[str, JsonValue]] = []
    cursor: str | None = leaf_id
    while cursor is not None:
        record = nodes[cursor]
        chain.append(record)
        parent = record.get("parentId")
        cursor = parent if isinstance(parent, str) else None
    chain.reverse()

    events: list[PiEventInput] = []
    for record in chain:
        visible = _visible_event(record)
        if visible is None:
            continue
        role, body = visible
        event_id = str(record["id"])
        parent_id = record.get("parentId")
        events.append(
            PiEventInput(
                session_id=session_id,
                event_id=event_id,
                parent_id=parent_id if isinstance(parent_id, str) else None,
                event_type=record["type"],
                role=role,
                content=f"{role}: {body}",
                record=record,
            ),
        )
    for event in events:
        pi_event_source_id(event.session_id, event.event_id)
    return tuple(events)


class PiSessionConnector:
    """Import newly visible branch events and keep durable progress."""

    name = PI_SESSION_CONNECTOR_NAME
    version = PI_CONNECTOR_VERSION
    source_definitions = frozenset({PI_EVENT_SOURCE_NAME})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self._path = Path(path)
        self._leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        events = parse_pi_session(PiSessionInput(content=self._path.read_bytes(), leaf_id=self._leaf_id))
        imported, imported_session = _load_checkpoint(session.checkpoint)
        if imported_session is not None and imported_session != _session_of(events):
            imported = {}

        digests = {event.event_id: _record_digest(event.record) for event in events}
        for event in events:
            recorded = imported.get(event.event_id)
            if recorded is not None and recorded != digests[event.event_id]:
                raise ValueError(f"imported Pi event {event.event_id!r} was rewritten")  # noqa: TRY003

        state = dict(imported)
        for event in events:
            if event.event_id in imported:
                continue
            outcome = await session.submit(event.event_id, PI_EVENT_SOURCE_NAME, event)
            if outcome.source_ref is not None:
                state[event.event_id] = digests[event.event_id]

        checkpoint = {
            "version": 1,
            "session_id": _session_of(events),
            "events": [{"event_id": key, "digest": value} for key, value in state.items()],
        }
        return ConnectorRunCompletion(status=ConnectorRunStatus.COMPLETE, checkpoint=checkpoint)


def _session_of(events: tuple[PiEventInput, ...]) -> str | None:
    return events[0].session_id if events else None


def _load_checkpoint(checkpoint: JsonValue | None) -> tuple[dict[str, str], str | None]:
    if checkpoint is None:
        return {}, None
    if not isinstance(checkpoint, dict):
        raise ValueError("Pi checkpoint must be a JSON object")  # noqa: TRY003, TRY004
    entries = checkpoint.get("events")
    if entries is None:
        return {}, None
    if not isinstance(entries, list):
        raise ValueError("Pi checkpoint events must be a JSON array")  # noqa: TRY003, TRY004
    recorded: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Pi checkpoint event must be a JSON object")  # noqa: TRY003, TRY004
        event_id, digest = entry.get("event_id"), entry.get("digest")
        if not isinstance(event_id, str) or not isinstance(digest, str):
            raise ValueError("Pi checkpoint event must carry event_id and digest")  # noqa: TRY003, TRY004
        recorded[event_id] = digest
    session_id = checkpoint.get("session_id")
    return recorded, session_id if isinstance(session_id, str) else None


def _record_digest(record: dict[str, JsonValue]) -> str:
    encoded = rfc8785.dumps(_JSON_VALUE.validate_python(record))
    return hashlib.sha256(encoded).hexdigest()


def _read_records(content: bytes) -> list[dict[str, JsonValue]]:
    raw = bytes(content)
    if raw.startswith(_UTF8_BOM):
        raw = raw[len(_UTF8_BOM) :]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("Pi session content must be valid UTF-8") from error  # noqa: TRY003
    records: list[dict[str, JsonValue]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"Pi session line is not valid JSON: {error}") from error  # noqa: TRY003
        if not isinstance(value, dict):
            raise ValueError("Pi session records must be JSON objects")  # noqa: TRY003, TRY004
        records.append(value)
    if not records:
        raise ValueError("Pi session content must contain a session header")  # noqa: TRY003
    return records


def _validate_header(header: dict[str, JsonValue]) -> str:
    if header.get("type") != _SESSION_TYPE:
        raise ValueError("Pi session must start with a session header")  # noqa: TRY003
    if header.get("version") != _SESSION_VERSION:
        raise ValueError("Pi session header must declare version 3")  # noqa: TRY003
    session_id = header.get("id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("Pi session header must declare a non-empty id")  # noqa: TRY003
    return session_id


def _index_records(records: list[dict[str, JsonValue]]) -> dict[str, dict[str, JsonValue]]:
    nodes: dict[str, dict[str, JsonValue]] = {}
    for record in records:
        event_id = record.get("id")
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("every Pi session record must declare a non-empty id")  # noqa: TRY003
        if event_id in nodes:
            raise ValueError(f"duplicate Pi session record id {event_id!r}")  # noqa: TRY003
        parent_id = record.get("parentId")
        if parent_id is not None:
            if not isinstance(parent_id, str):
                raise ValueError("Pi session parentId must be a string or null")  # noqa: TRY003
            if parent_id not in nodes:
                raise ValueError(f"Pi session parent {parent_id!r} does not precede its child")  # noqa: TRY003
        nodes[event_id] = record
    return nodes


def _resolve_leaf(nodes: dict[str, dict[str, JsonValue]], leaf_id: str | None) -> str:
    if leaf_id is None:
        if not nodes:
            raise ValueError("Pi session must contain at least one record")  # noqa: TRY003
        return next(reversed(nodes))
    if leaf_id not in nodes:
        raise ValueError(f"Pi session leaf {leaf_id!r} does not exist")  # noqa: TRY003
    return leaf_id


def _visible_event(record: dict[str, JsonValue]) -> tuple[str, str] | None:
    record_type = record.get("type")
    if record_type not in _CONTROL_EVENT_TYPES:
        return None
    if record_type == "message":
        message = record.get("message")
        if not isinstance(message, dict):
            return None
        role = message.get("role")
        if not isinstance(role, str) or not role.strip():
            return None
        if role == "toolResult":
            body = _tool_result_body(message)
        elif role == "bashExecution":
            body = _bash_execution_body(message)
        else:
            body = _block_text(message.get("content"))
        return (role, body) if body else None
    if record_type == "custom_message":
        body = _block_text(record.get("content"))
        return ("custom", body) if body else None
    summary = record.get("summary")
    body = summary if isinstance(summary, str) else ""
    return (str(record_type), body) if body else None


def _block_text(content: JsonValue) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            block_type = block.get("type")
            if block_type == "text":
                text = block.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
            elif block_type == "toolCall":
                parts.append(_tool_call_text(block))
    return "\n".join(parts)


def _tool_call_text(block: dict[str, JsonValue]) -> str:
    name = block.get("name")
    call_id = block.get("id")
    arguments = block.get("arguments")
    rendered = (
        json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if arguments is not None
        else "{}"
    )
    return (
        f"[tool_call {name if isinstance(name, str) else ''} {call_id if isinstance(call_id, str) else ''}] {rendered}"
    )


def _tool_result_body(message: dict[str, JsonValue]) -> str:
    name = message.get("toolName")
    call_id = message.get("toolCallId")
    text = _block_text(message.get("content"))
    header = f"[tool_result {name if isinstance(name, str) else ''} {call_id if isinstance(call_id, str) else ''}]"
    return f"{header} {text}" if text else header


def _bash_execution_body(message: dict[str, JsonValue]) -> str:
    command = message.get("command")
    output = message.get("output")
    head = f"$ {command if isinstance(command, str) else ''}"
    return f"{head}\n{output}" if isinstance(output, str) and output else head


__all__ = [
    "PI_CONNECTOR_VERSION",
    "PI_EVENT_SOURCE_DEFINITION",
    "PI_EVENT_SOURCE_NAME",
    "PI_EVENT_SOURCE_VERSION",
    "PI_SESSION_CONNECTOR_NAME",
    "PiEventInput",
    "PiEventSource",
    "PiSessionConnector",
    "PiSessionInput",
    "parse_pi_session",
    "pi_event_source_id",
]
