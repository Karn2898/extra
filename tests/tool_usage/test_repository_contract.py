"""One behavioral contract, two persistence backends.

Every consumer of ``ToolUsageRepository`` — tracker, context provider, run
trace — depends on these guarantees and nothing else, so an adapter that passes
here is substitutable (Liskov) for the one the engine ships with.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agent_engine.tool_usage.in_memory import InMemoryToolUsageRepository
from agent_engine.tool_usage.models import (
    ToolCallIdentity,
    ToolInvocationKind,
    ToolInvocationRecord,
    ToolInvocationStatus,
)
from agent_engine.tool_usage.repository import ToolUsageRepository
from tests.tool_usage.adapters import SqliteToolUsageRepository


def usage(
    run_id: str,
    agent_id: str,
    tool_name: str,
    *,
    tool_call_id: str | None = None,
    conversation_id: str | None = None,
    status: ToolInvocationStatus = ToolInvocationStatus.SUCCEEDED,
    error: str | None = None,
    kind: ToolInvocationKind = ToolInvocationKind.TOOL,
) -> ToolInvocationRecord:
    return ToolInvocationRecord(
        call=ToolCallIdentity(
            run_id=run_id,
            agent_id=agent_id,
            agent_path=f"root/{agent_id}",
            tool_call_id=tool_call_id or f"{agent_id}:{tool_name}",
            tool_name=tool_name,
            conversation_id=conversation_id,
            kind=kind,
        ),
        status=status,
        error=error,
    )


@pytest.fixture(params=["memory", "sqlite"])
async def repository(
    request: pytest.FixtureRequest, tmp_path: Path
) -> AsyncIterator[ToolUsageRepository]:
    if request.param == "memory":
        yield InMemoryToolUsageRepository()
        return
    sqlite_repository = SqliteToolUsageRepository(tmp_path / "usage.db")
    await sqlite_repository.setup()
    yield sqlite_repository


async def test_implements_the_repository_protocol(repository: ToolUsageRepository) -> None:
    assert isinstance(repository, ToolUsageRepository)


async def test_records_are_grouped_by_run_and_kept_in_call_order(
    repository: ToolUsageRepository,
) -> None:
    await repository.record(usage("run-1", "planner", "github.search"))
    await repository.record(usage("run-1", "developer", "github.get_file"))

    stored = await repository.list_for_run("run-1")

    assert [(r.call.agent_id, r.call.tool_name) for r in stored] == [
        ("planner", "github.search"),
        ("developer", "github.get_file"),
    ]


async def test_runs_are_isolated(repository: ToolUsageRepository) -> None:
    await repository.record(usage("run-1", "planner", "github.search"))
    await repository.record(usage("run-2", "planner", "context7.query"))

    assert [r.call.tool_name for r in await repository.list_for_run("run-1")] == ["github.search"]
    assert [r.call.tool_name for r in await repository.list_for_run("run-2")] == ["context7.query"]


async def test_unknown_run_has_no_records(repository: ToolUsageRepository) -> None:
    assert list(await repository.list_for_run("never-ran")) == []


async def test_a_conversation_spans_the_runs_it_contains(
    repository: ToolUsageRepository,
) -> None:
    await repository.record(usage("run-1", "planner", "github.search", conversation_id="conv-1"))
    await repository.record(usage("run-2", "developer", "deploy", conversation_id="conv-1"))
    await repository.record(usage("run-3", "planner", "other", conversation_id="conv-2"))

    stored = await repository.list_for_conversation("conv-1")

    assert [(r.call.run_id, r.call.tool_name) for r in stored] == [
        ("run-1", "github.search"),
        ("run-2", "deploy"),
    ]


async def test_unknown_conversation_has_no_records(repository: ToolUsageRepository) -> None:
    assert list(await repository.list_for_conversation("never-chatted")) == []


async def test_a_record_without_a_conversation_is_reachable_by_run_only(
    repository: ToolUsageRepository,
) -> None:
    await repository.record(usage("run-1", "planner", "github.search"))

    assert len(await repository.list_for_run("run-1")) == 1
    assert list(await repository.list_for_conversation("conv-1")) == []


async def test_an_updated_record_keeps_its_place_in_the_conversation(
    repository: ToolUsageRepository,
) -> None:
    await repository.record(
        usage("run-1", "planner", "first", tool_call_id="a", conversation_id="conv-1")
    )
    await repository.record(
        usage("run-2", "developer", "second", tool_call_id="b", conversation_id="conv-1")
    )
    await repository.record(
        usage(
            "run-1",
            "planner",
            "first",
            tool_call_id="a",
            conversation_id="conv-1",
            status=ToolInvocationStatus.FAILED,
        )
    )

    stored = await repository.list_for_conversation("conv-1")

    assert [(r.call.tool_name, r.status.value) for r in stored] == [
        ("first", "failed"),
        ("second", "succeeded"),
    ]


async def test_same_tool_from_two_agents_keeps_both_attributions(
    repository: ToolUsageRepository,
) -> None:
    await repository.record(usage("run-1", "developer", "github.get_file"))
    await repository.record(usage("run-1", "reviewer", "github.get_file"))

    stored = await repository.list_for_run("run-1")

    assert {r.call.agent_id for r in stored} == {"developer", "reviewer"}
    assert len(stored) == 2


async def test_recording_the_same_invocation_twice_updates_it_in_place(
    repository: ToolUsageRepository,
) -> None:
    call_id = "call-abc"
    await repository.record(usage("run-1", "developer", "deploy", tool_call_id=call_id))
    await repository.record(
        usage(
            "run-1",
            "developer",
            "deploy",
            tool_call_id=call_id,
            status=ToolInvocationStatus.FAILED,
            error="boom",
        )
    )

    stored = await repository.list_for_run("run-1")

    assert len(stored) == 1
    assert stored[0].status is ToolInvocationStatus.FAILED
    assert stored[0].error == "boom"


async def test_concurrent_writes_do_not_lose_records(repository: ToolUsageRepository) -> None:
    await asyncio.gather(
        *(
            repository.record(usage("run-1", f"agent-{i}", "tool", tool_call_id=f"call-{i}"))
            for i in range(50)
        )
    )

    stored = await repository.list_for_run("run-1")

    assert len({r.call.tool_call_id for r in stored}) == 50


async def test_listing_returns_a_snapshot_that_later_writes_do_not_change(
    repository: ToolUsageRepository,
) -> None:
    await repository.record(usage("run-1", "planner", "github.search"))
    snapshot = await repository.list_for_run("run-1")

    await repository.record(usage("run-1", "developer", "github.get_file"))

    assert len(snapshot) == 1


@pytest.mark.parametrize("scope", ["run", "conversation"])
async def test_bounded_listing_returns_the_latest_records_in_chronological_order(
    repository: ToolUsageRepository,
    scope: str,
) -> None:
    for index in range(5):
        await repository.record(
            usage(
                "run-1",
                "planner",
                f"tool-{index}",
                tool_call_id=f"call-{index}",
                conversation_id="conv-1",
            )
        )

    stored = (
        await repository.list_for_run("run-1", limit=2)
        if scope == "run"
        else await repository.list_for_conversation("conv-1", limit=2)
    )

    assert [record.call.tool_name for record in stored] == ["tool-3", "tool-4"]


@pytest.mark.parametrize("scope", ["run", "conversation"])
async def test_kind_filter_is_applied_before_the_limit(
    repository: ToolUsageRepository,
    scope: str,
) -> None:
    await repository.record(
        usage("run-1", "worker", "first-tool", tool_call_id="a", conversation_id="conv-1")
    )
    for index in range(4):
        await repository.record(
            usage(
                "run-1",
                "root",
                f"child-{index}",
                tool_call_id=f"child-{index}",
                conversation_id="conv-1",
                kind=ToolInvocationKind.AGENT,
            )
        )
    await repository.record(
        usage("run-1", "worker", "last-tool", tool_call_id="z", conversation_id="conv-1")
    )

    stored = (
        await repository.list_for_run("run-1", limit=2, kind=ToolInvocationKind.TOOL)
        if scope == "run"
        else await repository.list_for_conversation("conv-1", limit=2, kind=ToolInvocationKind.TOOL)
    )

    assert [record.call.tool_name for record in stored] == ["first-tool", "last-tool"]


async def test_limit_must_be_positive(repository: ToolUsageRepository) -> None:
    with pytest.raises(ValueError, match="limit must be positive"):
        await repository.list_for_run("run-1", limit=0)
