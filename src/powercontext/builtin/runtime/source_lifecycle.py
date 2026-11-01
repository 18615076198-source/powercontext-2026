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

"""Source-driven lifecycle propagation for Memory and Topic Memory.

A lifecycle graph is registered explicitly per Scope: roots are captured Source references,
and every derived node names its parents plus the support policy that makes the whole node
available. Source events change only root availability; the service then propagates each
derived node through its all/any policy and reconciles the native Memory entry state or the
native Topic Memory governance state. Bodies are never rewritten, so exact citations keep
resolving to the bytes that were committed before a withdrawal.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.persistence.artifact_governance import (
    ArtifactGovernanceRepository,
    ArtifactLifecycleState,
)
from powercontext.builtin.persistence.tables import SOURCE_LIFECYCLE_TABLE
from powercontext.builtin.runtime.models import GetMemoryEntryRequest
from powercontext.builtin.sources import validate_scope_id
from powercontext.errors import PowerContextError
from powercontext.limits import MAX_LIFECYCLE_NODE_ID_LENGTH
from powercontext.sources import SourceRef

if TYPE_CHECKING:
    from powercontext.builtin.runtime.application import BuiltinRuntime

LifecycleFamily = Literal["source", "memory", "topic"]
LifecyclePolicy = Literal["all", "any"]
LifecycleReference = SourceRef | MemoryCitation | ArtifactRef

_WITHDRAWAL_REASON = "source lifecycle withdrawal"
_RESTORE_REASON = "source lifecycle restore"
_TOPIC_MEMORY_FAMILY = "topic-memory"


class SourceLifecycleError(PowerContextError, ValueError):
    """Raised when a lifecycle registration, event, or resolution is invalid."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class SourceLifecycleEvent(BaseModel):
    """One validated root availability event at a lifecycle revision and sequence.

    The wire value rejects extra fields deliberately: a mistyped field must not silently
    become a default, because an event changes which Memory content may be generated from.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    revision: int
    sequence: int
    available: bool
    reason: str

    @field_validator("node_id", "reason")
    @classmethod
    def validate_text(cls, value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("lifecycle text fields must be non-empty and not only whitespace")  # noqa: TRY003
        return value

    @field_validator("revision", "sequence", mode="before")
    @classmethod
    def validate_counter(cls, value: object) -> int:
        if type(value) is not int or value < 1:
            raise ValueError("lifecycle counters must be positive integers")  # noqa: TRY003
        return value

    @field_validator("available", mode="before")
    @classmethod
    def validate_available(cls, value: object) -> bool:
        if type(value) is not bool:
            raise ValueError("available must be a boolean")  # noqa: TRY003
        return value


class _NodeRecord(BaseModel):
    """One persisted lifecycle graph node with its last known availability."""

    node_id: str
    family: LifecycleFamily
    reference: dict[str, Any]
    revision: int
    sequence: int
    available: bool
    policy: LifecyclePolicy
    parents: tuple[str, ...]

    def registration(self) -> tuple[dict[str, Any], int, str, tuple[str, ...]]:
        return (self.reference, self.revision, self.policy, self.parents)


class ScopedSourceLifecycleApplication:
    """Register one scope lifecycle graph and propagate Source availability through it."""

    def __init__(self, runtime: BuiltinRuntime, scope_id: str) -> None:
        self._runtime = runtime
        self.scope_id = validate_scope_id(scope_id)

    async def register_source(self, node_id: str, source_ref: SourceRef, /, *, revision: int) -> None:
        """Register one captured Source as a lifecycle root."""

        node = _require_node_id(node_id)
        version = _require_positive("revision", revision)
        if not isinstance(source_ref, SourceRef):
            raise SourceLifecycleError("source-reference")
        await self._require_source(source_ref)
        await self._register(
            node,
            family="source",
            reference=source_ref.model_dump(mode="json"),
            revision=version,
            policy="all",
            parents=(),
        )

    async def register_memory(
        self,
        node_id: str,
        citation: MemoryCitation,
        /,
        *,
        parents: Sequence[str],
        policy: LifecyclePolicy,
    ) -> None:
        """Register one exact Memory entry with its support policy."""

        node = _require_node_id(node_id)
        if not isinstance(citation, MemoryCitation):
            raise SourceLifecycleError("memory-citation")
        await self._require_memory(citation)
        await self._register(
            node,
            family="memory",
            reference=citation.model_dump(mode="json"),
            revision=0,
            policy=_require_policy(policy),
            parents=tuple(parents),
        )

    async def register_topic(
        self,
        node_id: str,
        artifact: ArtifactRef,
        /,
        *,
        parents: Sequence[str],
        policy: LifecyclePolicy,
    ) -> None:
        """Register one exact Topic Memory Artifact with its support policy."""

        node = _require_node_id(node_id)
        if not isinstance(artifact, ArtifactRef) or artifact.family != _TOPIC_MEMORY_FAMILY:
            raise SourceLifecycleError("topic-reference")
        await self._require_topic(artifact)
        await self._register(
            node,
            family="topic",
            reference=artifact.model_dump(mode="json"),
            revision=0,
            policy=_require_policy(policy),
            parents=tuple(parents),
        )

    async def apply(self, event: SourceLifecycleEvent, /) -> list[str]:
        """Apply one root event, propagate it, and report every currently available node."""

        if not isinstance(event, SourceLifecycleEvent):
            raise SourceLifecycleError("event")
        database = self._database()
        async with database.transaction() as connection:
            nodes = await _load_nodes(connection, self.scope_id)
            root = nodes.get(event.node_id)
            if root is None or root.family != "source":
                raise SourceLifecycleError("unknown-source")
            if root.revision != event.revision:
                raise SourceLifecycleError("revision-mismatch")
            replayed = event.sequence == root.sequence and event.available == root.available
            if event.sequence < root.sequence or (event.sequence == root.sequence and not replayed):
                raise SourceLifecycleError("sequence")
            if not replayed:
                await _save_source_state(connection, self.scope_id, event)
                nodes[event.node_id] = root.model_copy(
                    update={"sequence": event.sequence, "available": event.available}
                )
            available = _propagate(nodes)
        # Native state is reconciled after the root event commits, so a retry of the same
        # event completes any propagation interrupted by a failed native write. Nodes that
        # already match need no write, which keeps a successful replay free of new revisions.
        for node_id in sorted(nodes):
            node = nodes[node_id]
            if node.family == "source":
                continue
            await self._reconcile_native(node, available[node_id])
            if node.available != available[node_id]:
                async with database.transaction() as connection:
                    await _save_available(connection, self.scope_id, node_id, available[node_id])
        return sorted(node_id for node_id, state in available.items() if state)

    async def resolve(self, node_id: str, /, *, purpose: Literal["generation", "audit"]) -> LifecycleReference:
        """Return the original reference for generation or audit eligibility."""

        if purpose not in {"generation", "audit"}:
            raise SourceLifecycleError("purpose")
        async with self._database().transaction() as connection:
            node = (await _load_nodes(connection, self.scope_id)).get(node_id)
        if node is None:
            raise SourceLifecycleError("unknown-node")
        if purpose == "generation" and not node.available:
            raise SourceLifecycleError("unavailable-node")
        return _decode_reference(node.family, node.reference)

    async def _register(
        self,
        node_id: str,
        *,
        family: LifecycleFamily,
        reference: dict[str, Any],
        revision: int,
        policy: LifecyclePolicy,
        parents: tuple[str, ...],
    ) -> None:
        database = self._database()
        async with database.transaction() as connection:
            existing = (await _load_nodes(connection, self.scope_id)).get(node_id)
            registration = (reference, revision, policy, parents)
            if existing is not None:
                if existing.family == family and existing.registration() == registration:
                    return
                raise SourceLifecycleError("node-conflict")
            nodes = await _load_nodes(connection, self.scope_id)
            _validate_parents(node_id, family, parents, nodes)
            if any(other.reference == reference for other in nodes.values()):
                raise SourceLifecycleError("reference-conflict")
            available = _policy_state(policy, parents, {name: item.available for name, item in nodes.items()})
            node = _NodeRecord(
                node_id=node_id,
                family=family,
                reference=reference,
                revision=revision,
                sequence=0,
                available=available,
                policy=policy,
                parents=parents,
            )
        if family != "source":
            await self._reconcile_native(node, available)
        async with database.transaction() as connection:
            await connection.execute(
                insert(SOURCE_LIFECYCLE_TABLE).values(
                    scope_id=self.scope_id,
                    node_id=node_id,
                    family=family,
                    reference=_dump_json(reference),
                    revision=revision,
                    sequence=0,
                    available=available,
                    policy=policy,
                    parents=_dump_json(list(parents)),
                )
            )

    async def _reconcile_native(self, node: _NodeRecord, available: bool) -> None:
        if node.family == "memory":
            citation = cast(MemoryCitation, _decode_reference(node.family, node.reference))
            await self._set_memory_state(citation, available=available)
        elif node.family == "topic":
            artifact = cast(ArtifactRef, _decode_reference(node.family, node.reference))
            await self._set_topic_state(artifact, available=available)

    async def _set_memory_state(self, citation: MemoryCitation, *, available: bool) -> None:
        async with self._runtime._context(self.scope_id) as context, self._runtime._locked(self.scope_id):
            service = context.artifacts.memory
            current = await service.head(context.artifacts.memory_artifact_id)
            entries = {entry.entry_id: entry for entry in await service.entries(current)}
            entry = entries.get(citation.entry_id)
            if entry is None or entry.entry_version_id != citation.entry_version_id:
                raise SourceLifecycleError("memory-entry-mismatch")
            state = next(item.state for item in current.content.manifest.entries if item.entry_id == citation.entry_id)
            if state == ("active" if available else "inactive"):
                return
            reason = _RESTORE_REASON if available else _WITHDRAWAL_REASON
            if available:
                await service.reactivate(current, entries=(entry,), reason=reason)
            else:
                await service.forget(current, entries=(entry,), reason=reason)

    async def _set_topic_state(self, artifact: ArtifactRef, *, available: bool) -> None:
        database = self._database()
        async with database.transaction() as connection:
            repository = ArtifactGovernanceRepository()
            governance = await repository.get(connection, self.scope_id, artifact.family, artifact.artifact_id)
            desired = ArtifactLifecycleState.ACTIVE if available else ArtifactLifecycleState.DEPRECATED
            if governance.lifecycle_state is desired:
                return
            await repository.transition(
                connection,
                self.scope_id,
                artifact.family,
                artifact.artifact_id,
                governance.governance_generation,
                desired,
                None,
            )

    async def _require_source(self, source_ref: SourceRef) -> None:
        try:
            await self._runtime.records.for_scope(self.scope_id).get_source(
                source_ref.source_type, source_ref.source_id
            )
        except Exception as error:
            raise SourceLifecycleError("unreadable-source") from error

    async def _require_memory(self, citation: MemoryCitation) -> None:
        try:
            await self._runtime.memory.for_scope(self.scope_id).get(GetMemoryEntryRequest(citation=citation))
        except Exception as error:
            raise SourceLifecycleError("unreadable-memory") from error

    async def _require_topic(self, artifact: ArtifactRef) -> None:
        try:
            await self._runtime.records.for_scope(self.scope_id).get_artifact_revision(
                artifact.family, artifact.artifact_id, artifact.revision
            )
        except Exception as error:
            raise SourceLifecycleError("unreadable-topic") from error

    def _database(self):
        database = self._runtime.database
        if database is None:
            raise SourceLifecycleError("lifecycle-unavailable")
        return database


class SourceLifecycleApplication:
    """Select the lifecycle service for one Scope."""

    def __init__(self, runtime: BuiltinRuntime) -> None:
        self._runtime = runtime

    def for_scope(self, scope_id: str, /) -> ScopedSourceLifecycleApplication:
        return ScopedSourceLifecycleApplication(self._runtime, scope_id)


def _require_node_id(node_id: object) -> str:
    if (
        not isinstance(node_id, str)
        or not node_id.strip()
        or node_id != node_id.strip()
        or len(node_id) > MAX_LIFECYCLE_NODE_ID_LENGTH
    ):
        raise SourceLifecycleError("node-id")
    return node_id


def _require_positive(field: str, value: object) -> int:
    if type(value) is not int or value < 1:
        raise SourceLifecycleError(field)
    return value


def _require_policy(policy: object) -> LifecyclePolicy:
    if policy not in {"all", "any"}:
        raise SourceLifecycleError("policy")
    return policy  # type: ignore[return-value]


def _validate_parents(
    node_id: str, family: Literal["source", "memory", "topic"], parents: tuple[str, ...], nodes: dict[str, _NodeRecord]
) -> None:
    # A Source root has no parent; every derived node must name at least one.
    if not parents:
        if family == "source":
            return
        raise SourceLifecycleError("parents")
    if len(set(parents)) != len(parents):
        raise SourceLifecycleError("duplicate-parent")
    for parent in parents:
        if parent == node_id:
            raise SourceLifecycleError("cycle")
        if parent not in nodes:
            raise SourceLifecycleError("missing-parent")


def _policy_state(policy: str, parents: tuple[str, ...], available: dict[str, bool]) -> bool:
    support = [available.get(parent, False) for parent in parents]
    return all(support) if policy == "all" else any(support)


def _propagate(nodes: dict[str, _NodeRecord]) -> dict[str, bool]:
    available = {node_id: node.available for node_id, node in nodes.items()}
    changed = True
    while changed:
        changed = False
        for node_id, node in nodes.items():
            if node.family == "source":
                continue
            state = _policy_state(node.policy, node.parents, available)
            if available[node_id] != state:
                available[node_id] = state
                changed = True
    return available


def _decode_reference(family: str, payload: dict[str, Any]) -> LifecycleReference:
    if family == "source":
        return SourceRef.model_validate(payload)
    if family == "memory":
        return MemoryCitation.model_validate(payload)
    return ArtifactRef.model_validate(payload)


async def _load_nodes(connection: AsyncConnection, scope_id: str) -> dict[str, _NodeRecord]:
    table = SOURCE_LIFECYCLE_TABLE
    rows = await connection.execute(select(table).where(table.c.scope_id == scope_id))
    return {str(row["node_id"]): _node_from_row(row) for row in rows.mappings()}


def _node_from_row(row) -> _NodeRecord:
    return _NodeRecord(
        node_id=str(row["node_id"]),
        family=str(row["family"]),
        reference=json.loads(_as_bytes(row["reference"])),
        revision=int(row["revision"]),
        sequence=int(row["sequence"]),
        available=bool(row["available"]),
        policy=str(row["policy"]),
        parents=tuple(json.loads(_as_bytes(row["parents"]))),
    )


async def _save_source_state(connection: AsyncConnection, scope_id: str, event: SourceLifecycleEvent) -> None:
    table = SOURCE_LIFECYCLE_TABLE
    await connection.execute(
        update(table)
        .where(table.c.scope_id == scope_id, table.c.node_id == event.node_id)
        .values(sequence=event.sequence, available=event.available)
    )


async def _save_available(connection: AsyncConnection, scope_id: str, node_id: str, available: bool) -> None:
    table = SOURCE_LIFECYCLE_TABLE
    await connection.execute(
        update(table).where(table.c.scope_id == scope_id, table.c.node_id == node_id).values(available=available)
    )


def _dump_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _as_bytes(value: object) -> bytes:
    return value if isinstance(value, bytes) else bytes(value)  # type: ignore[arg-type]


__all__ = [
    "ScopedSourceLifecycleApplication",
    "SourceLifecycleApplication",
    "SourceLifecycleError",
    "SourceLifecycleEvent",
]
