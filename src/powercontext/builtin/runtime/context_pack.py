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

"""Incremental transfer of prepared context through packs and deltas.

A ContextPack is the canonical wire form of one prepared context: an ordered tuple of
bounded, valid UTF-8 byte chunks plus a SHA-256 digest over the chunk list. A
ContextPackDelta names the digest of the pack it extends, the number of leading chunks
reused from that pack, and only the chunks that the target adds after them.

The encoding is a fixed interoperability contract, not an internal choice: JSON with
sorted keys and compact separators, UTF-8, SHA-256 digests rendered as ``sha256:<hex>``,
and standard Base64 chunk strings. The receiving side reconstructs the target from
serialized bytes alone; no process cache or shared object is involved.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from powercontext.errors import PowerContextError

PACK_SCHEMA = "powercontext.context-pack.v1"
DELTA_SCHEMA = "powercontext.context-pack-delta.v1"
DEFAULT_CHUNK_BYTES = 512

_DIGEST_PREFIX = "sha256:"
_DIGEST_HEX_LENGTH = 64
_PACK_FIELDS = frozenset({"schema", "items", "digest", "byte_count"})
_DELTA_FIELDS = frozenset({"schema", "base_digest", "target_digest", "prefix_items", "appended"})


class ContextPackError(PowerContextError, ValueError):
    """Raised when a Context Pack or a Context Pack delta violates the wire contract.

    The failure is reported by a stable code instead of a formatted message so callers can
    branch on the protocol rule that rejected the payload.
    """

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ContextPack:
    """One complete prepared context as ordered, bounded UTF-8 chunk bytes."""

    items: tuple[bytes, ...]
    digest: str

    @classmethod
    def build(cls, items: Iterable[bytes]) -> ContextPack:
        """Build a complete pack from already chunked bytes."""

        chunks = tuple(_coerce_chunk(item) for item in items)
        return cls(items=chunks, digest=_pack_digest(chunks))

    @classmethod
    def from_content(cls, content: str, *, chunk_bytes: int = DEFAULT_CHUNK_BYTES) -> ContextPack:
        """Chunk content deterministically into valid UTF-8 chunks of at most chunk_bytes."""

        if not isinstance(content, str):
            raise TypeError("context pack content must be a string")  # noqa: TRY003
        if type(chunk_bytes) is not int or chunk_bytes <= 0:
            raise ContextPackError("chunk-bytes")
        chunks: list[bytes] = []
        current = bytearray()
        for character in content:
            encoded = character.encode("utf-8")
            if len(encoded) > chunk_bytes:
                raise ContextPackError("chunk-character")
            if len(current) + len(encoded) > chunk_bytes:
                chunks.append(bytes(current))
                current.clear()
            current.extend(encoded)
        if current:
            chunks.append(bytes(current))
        return cls.build(chunks)

    @classmethod
    def from_bytes(cls, raw: bytes | bytearray | str) -> ContextPack:
        """Decode and validate one complete pack from its wire bytes."""

        encoded = _wire_bytes(raw)
        payload = _load_object(encoded, _PACK_FIELDS, "pack")
        if payload["schema"] != PACK_SCHEMA:
            raise ContextPackError("pack-schema")
        items = _decode_chunks(payload["items"])
        digest = payload["digest"]
        if not _is_digest(digest):
            raise ContextPackError("pack-digest")
        if digest != _pack_digest(items):
            raise ContextPackError("pack-digest-mismatch")
        byte_count = payload["byte_count"]
        if type(byte_count) is not int or byte_count < 0:
            raise ContextPackError("pack-byte-count")
        if byte_count != len(encoded):
            raise ContextPackError("pack-byte-count-mismatch")
        return cls(items=items, digest=digest)

    @property
    def byte_count(self) -> int:
        """Exact wire size of this pack, including every protocol field."""

        return len(self.to_bytes())

    def to_bytes(self) -> bytes:
        """Serialize this pack; byte_count is solved for its own encoded width."""

        payload: dict[str, Any] = {
            "schema": PACK_SCHEMA,
            "items": _encode_chunks(self.items),
            "digest": self.digest,
            "byte_count": 0,
        }
        size = len(_canonical(payload))
        while True:
            payload["byte_count"] = size
            measured = len(_canonical(payload))
            if measured == size:
                return _canonical(payload)
            size = measured


@dataclass(frozen=True)
class ContextPackDelta:
    """The suffix that turns one pack into another, plus the identity of both packs."""

    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack) -> ContextPackDelta:
        """Describe the longest reused item prefix of base and the target suffix."""

        if not isinstance(base, ContextPack) or not isinstance(target, ContextPack):
            raise TypeError("context pack delta requires two context packs")  # noqa: TRY003
        prefix = 0
        for reused, incoming in zip(base.items, target.items, strict=False):
            if reused != incoming:
                break
            prefix += 1
        return cls(
            base_digest=base.digest,
            target_digest=target.digest,
            prefix_items=prefix,
            appended=target.items[prefix:],
        )

    @classmethod
    def from_bytes(cls, raw: bytes | bytearray | str) -> ContextPackDelta:
        """Decode and validate one delta from its wire bytes."""

        encoded = _wire_bytes(raw)
        payload = _load_object(encoded, _DELTA_FIELDS, "delta")
        if payload["schema"] != DELTA_SCHEMA:
            raise ContextPackError("delta-schema")
        base_digest = payload["base_digest"]
        target_digest = payload["target_digest"]
        if not _is_digest(base_digest) or not _is_digest(target_digest):
            raise ContextPackError("delta-digest")
        prefix_items = payload["prefix_items"]
        if type(prefix_items) is not int or prefix_items < 0:
            raise ContextPackError("delta-prefix")
        return cls(
            base_digest=base_digest,
            target_digest=target_digest,
            prefix_items=prefix_items,
            appended=_decode_chunks(payload["appended"]),
        )

    @property
    def byte_count(self) -> int:
        """Exact wire size of this delta; never written as an extra delta field."""

        return len(self.to_bytes())

    def to_bytes(self) -> bytes:
        """Serialize this delta."""

        return _canonical({
            "schema": DELTA_SCHEMA,
            "base_digest": self.base_digest,
            "target_digest": self.target_digest,
            "prefix_items": self.prefix_items,
            "appended": _encode_chunks(self.appended),
        })


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta, /) -> ContextPack:
    """Rebuild the target pack from a base pack and one validated delta."""

    if not isinstance(base, ContextPack):
        raise TypeError("context pack delta requires a ContextPack base")  # noqa: TRY003
    if not isinstance(delta, ContextPackDelta):
        raise TypeError("context pack delta requires a ContextPackDelta")  # noqa: TRY003
    if delta.base_digest != base.digest:
        raise ContextPackError("delta-base-digest")
    if type(delta.prefix_items) is not int or delta.prefix_items < 0:
        raise ContextPackError("delta-prefix")
    if delta.prefix_items > len(base.items):
        raise ContextPackError("delta-prefix-bounds")
    target = ContextPack.build((*base.items[: delta.prefix_items], *delta.appended))
    if target.digest != delta.target_digest:
        raise ContextPackError("delta-target-digest")
    return target


def _pack_digest(items: tuple[bytes, ...]) -> str:
    unsigned = {"schema": PACK_SCHEMA, "items": _encode_chunks(items)}
    return f"{_DIGEST_PREFIX}{hashlib.sha256(_canonical(unsigned)).hexdigest()}"


def _canonical(payload: Mapping[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _wire_bytes(raw: bytes | bytearray | str) -> bytes:
    if isinstance(raw, str):
        return raw.encode("utf-8")
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw)
    raise TypeError("wire payload must be bytes or text")  # noqa: TRY003


def _load_object(encoded: bytes, fields: frozenset[str], label: str) -> dict[str, Any]:
    try:
        payload = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContextPackError(f"{label}-json") from error
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ContextPackError(f"{label}-fields")
    return payload


def _coerce_chunk(item: object) -> bytes:
    if isinstance(item, bytes):
        return item
    if isinstance(item, bytearray):
        return bytes(item)
    raise ContextPackError("item-type")


def _encode_chunks(items: tuple[bytes, ...]) -> list[str]:
    return [base64.b64encode(item).decode("ascii") for item in items]


def _decode_chunks(values: object) -> tuple[bytes, ...]:
    if not isinstance(values, list):
        raise ContextPackError("items-type")
    chunks: list[bytes] = []
    for value in values:
        if not isinstance(value, str):
            raise ContextPackError("item-type")
        try:
            chunk = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ContextPackError("item-base64") from error
        if base64.b64encode(chunk).decode("ascii") != value:
            raise ContextPackError("item-base64")
        try:
            chunk.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ContextPackError("item-utf8") from error
        chunks.append(chunk)
    return tuple(chunks)


def _is_digest(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith(_DIGEST_PREFIX):
        return False
    hexdigest = value[len(_DIGEST_PREFIX) :]
    if len(hexdigest) != _DIGEST_HEX_LENGTH:
        return False
    try:
        bytes.fromhex(hexdigest)
    except ValueError:
        return False
    return True
