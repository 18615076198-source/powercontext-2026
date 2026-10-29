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
from types import SimpleNamespace
from typing import Literal, cast

from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import BuiltinConfig, open_builtin_contexts
from powercontext.builtin.runtime.artifact_processing import ArtifactProcessingBinding
from powercontext.builtin.runtime.composition import (
    _ledger_families,
    _open_work_background,
    _supervisor_bindings,
    _work_background_requested,
    _work_discoverers,
    _work_handlers,
    _work_role_components,
)
from powercontext.builtin.runtime.config import DeploymentConfig, RuntimeConfig
from powercontext.builtin.runtime.relational import RelationalContexts
from powercontext.builtin.runtime.work_handlers import (
    EXPERIENCE_WORK_KIND,
    MAINTENANCE_WORK_KIND,
    MEMORY_WORK_KIND,
    PROFILE_WORK_KIND,
)


def _config(tmp_path, **overrides):
    return BuiltinConfig(
        database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'work.db'}"),
        **overrides,
    )


def _distributed(runtime: RuntimeConfig, role: Literal["api", "scheduler", "worker"] = "worker") -> BuiltinConfig:
    """A distributed config without an OceanBase handle: only top-level helpers read it."""

    return cast(
        "BuiltinConfig",
        SimpleNamespace(
            deployment=DeploymentConfig(mode="distributed", role=role),
            runtime=runtime,
        ),
    )


def test_ledger_only_starts_for_a_distributed_deployment() -> None:
    # A single-node install keeps its APScheduler supervisors: RFC 1430 moves
    # single_node/all onto the ledger only once that path has fully retired.
    assert _work_background_requested(BuiltinConfig()) is False
    assert _work_background_requested(BuiltinConfig(runtime=RuntimeConfig(memory_schedule_seconds=30))) is False
    assert _work_background_requested(BuiltinConfig(runtime=RuntimeConfig(profile_schedule_enabled=True))) is False
    assert _work_background_requested(_distributed(RuntimeConfig(memory_schedule_seconds=30))) is True


def test_ledger_owned_families_follow_the_configured_schedules() -> None:
    assert _ledger_families(BuiltinConfig(runtime=RuntimeConfig(memory_schedule_seconds=30))) == frozenset()

    families = _ledger_families(
        _distributed(
            RuntimeConfig(
                memory_schedule_seconds=30,
                experience_schedule_seconds=30,
                profile_schedule_enabled=True,
            )
        )
    )
    assert families == {"memory", "experience", "profile"}

    # An unscheduled Family stays with the supervisor even in a distributed run.
    assert _ledger_families(_distributed(RuntimeConfig(memory_schedule_seconds=30))) == {"memory"}


def test_supervisor_drops_only_the_families_the_ledger_owns() -> None:
    fakes = [SimpleNamespace(artifact_family=family) for family in ("memory", "experience", "skill")]
    bindings = cast("list[ArtifactProcessingBinding]", fakes)
    config = _distributed(RuntimeConfig(memory_schedule_seconds=30, profile_schedule_enabled=True))

    kept = _supervisor_bindings(config, bindings)
    assert [binding.artifact_family for binding in kept] == ["experience", "skill"]

    # A single-node config owns nothing, so every binding reaches the supervisor.
    assert len(_supervisor_bindings(BuiltinConfig(), bindings)) == 3


def test_work_roles_split_scanning_from_claiming() -> None:
    assert _work_role_components("all") == (True, True)
    assert _work_role_components("api") == (False, False)
    assert _work_role_components("scheduler") == (True, False)
    assert _work_role_components("worker") == (False, True)


def test_composition_registers_every_discoverer_and_handler(tmp_path) -> None:
    sentinel = object()
    config = _config(
        tmp_path,
        runtime=RuntimeConfig(
            memory_schedule_seconds=30,
            experience_schedule_seconds=30,
            profile_schedule_enabled=True,
        ),
    )

    discoverers = _work_discoverers(config, cast("RelationalContexts", sentinel))
    assert [discoverer.name for discoverer in discoverers] == [
        MEMORY_WORK_KIND,
        EXPERIENCE_WORK_KIND,
        PROFILE_WORK_KIND,
        MAINTENANCE_WORK_KIND,
    ]

    class _Profiles:
        """Stand-in for the shared Profile service the handler only stores."""

    fake_contexts = cast("RelationalContexts", type("Contexts", (), {"profiles": _Profiles()})())
    handlers = _work_handlers(config, fake_contexts)
    assert [handler.kind for handler in handlers] == [
        MEMORY_WORK_KIND,
        EXPERIENCE_WORK_KIND,
        PROFILE_WORK_KIND,
        MAINTENANCE_WORK_KIND,
    ]


def test_single_node_runtime_exposes_operations_without_ledger_execution(tmp_path) -> None:
    async def scenario() -> None:
        config = _config(tmp_path, runtime=RuntimeConfig(memory_schedule_seconds=30))
        async with (
            open_builtin_contexts(config) as contexts,
            _open_work_background(config, contexts) as background,
        ):
            assert background.operations is not None
            # The supervisor owns every Family here, so the ledger stays idle.
            assert background.scheduler is None
            assert background.worker is None
            assert background.membership is None

    asyncio.run(scenario())
