"""Contract tests for run repository implementations."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from agent_engine.approvals.models import RunRecord, RunStatus
from agent_engine.runs.in_memory import InMemoryRunRepository
from agent_engine.runs.repository import RunRepository

pytestmark = pytest.mark.asyncio


@pytest.fixture
def run_repository() -> RunRepository:
    """Repository contract fixture; future adapters can reuse these tests."""
    return InMemoryRunRepository()


def _run(run_id: str, *, system_name: str = "system") -> RunRecord:
    return RunRecord(run_id=run_id, thread_id=run_id, system_name=system_name)


async def test_in_memory_run_repository_implements_contract() -> None:
    assert issubclass(InMemoryRunRepository, RunRepository)
    assert isinstance(InMemoryRunRepository(), RunRepository)


async def test_run_repository_cannot_be_instantiated() -> None:
    repository_type = cast(Any, RunRepository)
    with pytest.raises(TypeError, match="abstract"):
        repository_type()


async def test_run_repository_registers_new_run(run_repository: RunRepository) -> None:
    record = _run("r1")

    created = await run_repository.create_if_absent(record)

    assert created is True
    assert await run_repository.get("r1") == record


async def test_run_repository_does_not_overwrite_existing_run(
    run_repository: RunRepository,
) -> None:
    original = _run("r1", system_name="original")
    await run_repository.create_if_absent(original)
    assert await run_repository.transition_if_allowed("r1", RunStatus.COMPLETED) is True

    created = await run_repository.create_if_absent(_run("r1", system_name="replacement"))

    assert created is False
    stored = await run_repository.get("r1")
    assert stored is not None
    assert stored == original
    assert stored.system_name == "original"
    assert stored.status == RunStatus.COMPLETED


async def test_run_repository_registers_different_ids(
    run_repository: RunRepository,
) -> None:
    first_created = await run_repository.create_if_absent(_run("r1"))
    second_created = await run_repository.create_if_absent(_run("r2"))

    assert first_created is True
    assert second_created is True
    assert await run_repository.get("r1") is not None
    assert await run_repository.get("r2") is not None


async def test_in_memory_run_registration_has_one_process_local_winner() -> None:
    repository = InMemoryRunRepository()

    async def register(index: int) -> bool:
        return await repository.create_if_absent(_run("shared", system_name=f"system-{index}"))

    results = await asyncio.gather(*(register(index) for index in range(20)))

    assert sum(results) == 1
    assert await repository.get("shared") is not None


async def test_transition_if_allowed_is_a_single_process_local_operation() -> None:
    repository = InMemoryRunRepository()
    await repository.create_if_absent(_run("shared"))

    completed, cancelled = await asyncio.gather(
        repository.transition_if_allowed("shared", RunStatus.COMPLETED),
        repository.transition_if_allowed("shared", RunStatus.CANCELLED),
    )

    assert sum((completed, cancelled)) == 1
    stored = await repository.get("shared")
    assert stored is not None
    assert stored.status in {RunStatus.COMPLETED, RunStatus.CANCELLED}


async def test_transition_if_allowed_leaves_missing_or_terminal_runs_unchanged() -> None:
    repository = InMemoryRunRepository()

    assert await repository.transition_if_allowed("missing", RunStatus.COMPLETED) is False

    await repository.create_if_absent(_run("finished"))
    assert await repository.transition_if_allowed("finished", RunStatus.COMPLETED) is True
    assert await repository.transition_if_allowed("finished", RunStatus.CANCELLED) is False
    stored = await repository.get("finished")
    assert stored is not None
    assert stored.status == RunStatus.COMPLETED
