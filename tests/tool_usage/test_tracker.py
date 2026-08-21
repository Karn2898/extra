"""The tracker's job: one execution event in, one domain record out."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

import pytest

from agent_engine.tool_usage.in_memory import InMemoryToolUsageRepository
from agent_engine.tool_usage.models import (
    ToolCallIdentity,
    ToolInvocationKind,
    ToolInvocationRecord,
    ToolInvocationStatus,
)
from agent_engine.tool_usage.repository import ToolUsageRepository
from agent_engine.tool_usage.tracker import ToolUsageTracker


def call(agent_id: str = "developer", tool_name: str = "github.get_file") -> ToolCallIdentity:
    return ToolCallIdentity(
        run_id="run-1",
        agent_id=agent_id,
        agent_path=f"root/{agent_id}",
        tool_call_id="call-abc",
        tool_name=tool_name,
        provider="mcp",
        server_id="github",
    )


class BrokenRepository(ToolUsageRepository):
    """A repository whose backend is down, for the degradation policies."""

    async def record(self, record: ToolInvocationRecord) -> None:
        raise RuntimeError("backend unreachable")

    async def list_for_run(
        self,
        run_id: str,
        *,
        limit: int | None = None,
        kind: ToolInvocationKind | None = None,
    ) -> tuple[ToolInvocationRecord, ...]:
        raise RuntimeError("backend unreachable")

    async def list_for_conversation(
        self,
        conversation_id: str,
        *,
        limit: int | None = None,
        kind: ToolInvocationKind | None = None,
    ) -> tuple[ToolInvocationRecord, ...]:
        raise RuntimeError("backend unreachable")


@pytest.mark.parametrize(
    ("record_call", "expected"),
    [
        (lambda t: t.record_success(call()), ToolInvocationStatus.SUCCEEDED),
        (lambda t: t.record_denied(call()), ToolInvocationStatus.DENIED),
    ],
)
async def test_outcomes_are_persisted_with_their_status(
    record_call: Callable[[ToolUsageTracker], Awaitable[None]],
    expected: ToolInvocationStatus,
) -> None:
    repository = InMemoryToolUsageRepository()

    await record_call(ToolUsageTracker(repository))

    stored = await repository.list_for_run("run-1")
    assert [r.status for r in stored] == [expected]


async def test_failure_keeps_the_error_and_the_call_identity() -> None:
    repository = InMemoryToolUsageRepository()

    await ToolUsageTracker(repository).record_failure(call(), error="connection refused")

    stored = await repository.list_for_run("run-1")
    assert stored[0].status is ToolInvocationStatus.FAILED
    assert stored[0].error == "connection refused"
    assert stored[0].call.agent_id == "developer"
    assert stored[0].call.provider == "mcp"
    assert stored[0].call.server_id == "github"


async def test_error_text_is_bounded() -> None:
    repository = InMemoryToolUsageRepository()

    await ToolUsageTracker(repository).record_failure(call(), error="x" * 5_000)

    stored = await repository.list_for_run("run-1")
    assert stored[0].error is not None
    assert len(stored[0].error) == 200


async def test_a_repository_failure_never_breaks_the_tool_call(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tracker = ToolUsageTracker(BrokenRepository())

    with caplog.at_level(logging.WARNING):
        await tracker.record_success(call())

    assert "tool usage not recorded" in caplog.text
    fields = getattr(caplog.records[0], "fields", {})
    assert fields["tool_call_id"] == "call-abc"
