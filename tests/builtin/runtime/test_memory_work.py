# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import asyncio

from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.persistence.work import WorkRepository
from powercontext.builtin.runtime import BuiltinConfig, open_builtin_contexts
from powercontext.builtin.runtime.models import MemoryFlushResult
from powercontext.builtin.runtime.work_handlers import (
    MEMORY_WORK_KIND,
    MemoryWorkHandler,
    memory_work_spec,
)
from powercontext.builtin.sources import ContentCapture, SourceCursor
from powercontext.builtin.triggers import SOURCE_WINDOW_TRIGGER_NAME


def _config(tmp_path):
    return BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}"))


async def _claim(contexts, spec):
    repository = WorkRepository()
    async with contexts.database.transaction() as connection:
        await repository.enqueue(connection, spec)
        claims = await repository.claim(
            connection,
            worker_id="worker-a",
            supported={MEMORY_WORK_KIND: frozenset({1})},
            lease_seconds=30,
            limit=1,
        )
    return claims[0]


def test_memory_work_spec_tracks_the_unconsumed_source_window(tmp_path) -> None:
    async def scenario() -> None:
        async with open_builtin_contexts(_config(tmp_path)) as contexts:
            assert await memory_work_spec(contexts, "project", limit=10, max_attempts=3, payload_version=1) is None
            context = await contexts.get("project")
            await context.sources.capture(ContentCapture(source_id="one", content="remember this"))

            spec = await memory_work_spec(contexts, "project", limit=10, max_attempts=3, payload_version=1)
            assert spec is not None
            assert spec.kind == MEMORY_WORK_KIND
            assert spec.scope_id == "project"
            assert spec.payload["cursor_name"] == SOURCE_WINDOW_TRIGGER_NAME
            assert spec.payload["after"] == 0
            assert spec.payload["through"] == 1

    asyncio.run(scenario())


def test_memory_work_handler_runs_the_atomic_memory_flush(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        async with open_builtin_contexts(_config(tmp_path)) as contexts:
            context = await contexts.get("project")
            await context.sources.capture(ContentCapture(source_id="one", content="remember this"))
            spec = await memory_work_spec(contexts, "project", limit=10, max_attempts=3, payload_version=1)
            assert spec is not None
            claim = await _claim(contexts, spec)

            seen: list[tuple[str, int]] = []

            async def fake_process_memory(scope_id: str, limit: int, **_: object) -> MemoryFlushResult:
                seen.append((scope_id, limit))
                return MemoryFlushResult(
                    previous_cursor=0,
                    current_cursor=1,
                    high_watermark=1,
                    source_count=1,
                    memory_ref=None,
                )

            monkeypatch.setattr(contexts, "process_memory", fake_process_memory)
            prepared = await MemoryWorkHandler(contexts, window_limit=10).prepare(claim)
            # The Atomic Memory flush owns the domain commit, so the fenced Work
            # commit only records the outcome.
            assert prepared.commit is None
            assert prepared.result is not None
            assert prepared.result.code == "processed"
            assert prepared.result.payload["current_cursor"] == 1
            assert seen == [("project", 10)]

            async with contexts.database.transaction() as connection:
                await contexts.repositories.cursors.save(
                    connection,
                    "project",
                    SOURCE_WINDOW_TRIGGER_NAME,
                    SourceCursor(sequence=1),
                    expected_generation=None,
                )
            repeated = await MemoryWorkHandler(contexts, window_limit=10).prepare(claim)
            assert repeated.result is not None
            assert repeated.result.code == "already_committed"

    asyncio.run(scenario())
