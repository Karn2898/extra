"""What the model is told about prior tool usage — and what it is not told."""

from __future__ import annotations

import logging

import pytest

from agent_engine.tool_usage.context_models import (
    ToolUsageScope,
    format_executed_tools,
)
from agent_engine.tool_usage.context_provider import ToolUsageContextProvider
from agent_engine.tool_usage.in_memory import InMemoryToolUsageRepository
from agent_engine.tool_usage.models import (
    ToolCallIdentity,
    ToolInvocationKind,
    ToolInvocationRecord,
    ToolInvocationStatus,
)
from tests.tool_usage.test_tracker import BrokenRepository

RUN = ToolUsageScope(run_id="run-1")
CONVERSATION = ToolUsageScope(run_id="run-2", conversation_id="conv-1")


def usage(
    agent_id: str,
    tool_name: str,
    *,
    run_id: str = "run-1",
    conversation_id: str | None = "conv-1",
    kind: ToolInvocationKind = ToolInvocationKind.TOOL,
    status: ToolInvocationStatus = ToolInvocationStatus.SUCCEEDED,
    error: str | None = None,
    tool_call_id: str | None = None,
) -> ToolInvocationRecord:
    return ToolInvocationRecord(
        call=ToolCallIdentity(
            run_id=run_id,
            agent_id=agent_id,
            agent_path=f"root/{agent_id}",
            tool_call_id=tool_call_id or f"call-{agent_id}-{tool_name}",
            tool_name=tool_name,
            provider="mcp",
            server_id="github",
            conversation_id=conversation_id,
            kind=kind,
        ),
        status=status,
        error=error,
    )


async def filled_repository() -> InMemoryToolUsageRepository:
    repository = InMemoryToolUsageRepository()
    await repository.record(usage("planner", "github.search"))
    await repository.record(usage("planner", "context7.query"))
    await repository.record(usage("developer", "github.get_file"))
    return repository


async def test_context_groups_invocations_by_agent() -> None:
    provider = ToolUsageContextProvider(await filled_repository())

    rendered = (await provider.get(RUN)).render()

    assert rendered is not None
    assert "planner:\n- github.search [succeeded]\n- context7.query [succeeded]" in rendered
    assert "developer:\n- github.get_file [succeeded]" in rendered


async def test_context_carries_agent_tool_and_status_only() -> None:
    repository = InMemoryToolUsageRepository()
    await repository.record(
        usage("developer", "deploy", status=ToolInvocationStatus.FAILED, error="secret-token-leak")
    )
    provider = ToolUsageContextProvider(repository)

    rendered = (await provider.get(RUN)).render()

    assert rendered is not None
    assert "deploy [failed]" in rendered
    for internal in ("secret-token-leak", "call-developer-deploy", "github", "recorded_at"):
        assert internal not in rendered


async def test_a_run_with_no_usage_adds_nothing_to_the_prompt() -> None:
    provider = ToolUsageContextProvider(InMemoryToolUsageRepository())

    context = await provider.get(RUN)

    assert context.is_empty
    assert context.render() is None


async def delegating_repository() -> InMemoryToolUsageRepository:
    repository = InMemoryToolUsageRepository()
    await repository.record(usage("user_management", "add_new_user"))
    await repository.record(usage("openwebui", "admin_management", kind=ToolInvocationKind.AGENT))
    return repository


async def test_an_executed_tool_and_a_delegation_are_reported_apart() -> None:
    """Regression: an orchestrator answered "the tool I ran is admin_management"
    — the name of the child agent it had merely routed to. Its own children are
    bound to it as tools, so the record has to name both levels and say which
    is which."""
    provider = ToolUsageContextProvider(await delegating_repository())

    rendered = (await provider.get(RUN)).render()

    assert rendered is not None
    tools, delegations = rendered.split("### Agents delegated to")
    assert "add_new_user [succeeded]" in tools
    assert "admin_management" not in tools
    assert "openwebui -> admin_management" in delegations


async def test_successful_routing_is_reported_without_an_outcome() -> None:
    provider = ToolUsageContextProvider(await delegating_repository())

    rendered = (await provider.get(RUN)).render()

    assert rendered is not None
    # A path that worked is not an outcome the model should read as a tool result.
    assert "openwebui -> admin_management\n" in f"{rendered}\n"


async def test_routing_that_failed_is_reported_with_its_outcome() -> None:
    repository = InMemoryToolUsageRepository()
    await repository.record(
        usage(
            "openwebui",
            "admin_management",
            kind=ToolInvocationKind.AGENT,
            status=ToolInvocationStatus.FAILED,
        )
    )
    provider = ToolUsageContextProvider(repository)

    rendered = (await provider.get(RUN)).render()

    assert rendered is not None
    assert "openwebui -> admin_management [failed]" in rendered


async def test_a_conversation_of_pure_routing_shows_no_tool_section() -> None:
    repository = InMemoryToolUsageRepository()
    await repository.record(usage("openwebui", "admin_management", kind=ToolInvocationKind.AGENT))
    provider = ToolUsageContextProvider(repository)

    rendered = (await provider.get(RUN)).render()

    assert rendered is not None
    assert "### Tools executed" not in rendered
    assert "openwebui -> admin_management" in rendered


async def test_delegations_can_be_switched_off_for_a_deployment() -> None:
    provider = ToolUsageContextProvider(await delegating_repository(), include_delegations=False)

    rendered = (await provider.get(RUN)).render()

    assert rendered is not None
    assert "add_new_user [succeeded]" in rendered
    assert "admin_management" not in rendered


async def test_a_scope_without_any_identity_yields_empty_context() -> None:
    provider = ToolUsageContextProvider(await filled_repository())

    assert (await provider.get(ToolUsageScope())).is_empty


async def test_records_of_other_runs_never_leak_into_context() -> None:
    provider = ToolUsageContextProvider(await filled_repository())

    assert (await provider.get(ToolUsageScope(run_id="other-run"))).is_empty


async def test_a_later_turn_sees_the_conversations_earlier_runs() -> None:
    repository = await filled_repository()
    provider = ToolUsageContextProvider(repository)

    # A follow-up user message is a new run in the same conversation.
    context = await provider.get(CONVERSATION)

    assert [entry.tool_name for entry in context.entries] == [
        "github.search",
        "context7.query",
        "github.get_file",
    ]


async def test_another_conversation_is_never_visible() -> None:
    provider = ToolUsageContextProvider(await filled_repository())

    scope = ToolUsageScope(run_id="run-9", conversation_id="conv-other")

    assert (await provider.get(scope)).is_empty


async def test_a_run_outside_any_conversation_falls_back_to_its_own_run() -> None:
    repository = InMemoryToolUsageRepository()
    await repository.record(usage("planner", "github.search", conversation_id=None))
    provider = ToolUsageContextProvider(repository)

    context = await provider.get(ToolUsageScope(run_id="run-1"))

    assert [entry.tool_name for entry in context.entries] == ["github.search"]


async def test_context_is_bounded_to_the_most_recent_invocations() -> None:
    repository = InMemoryToolUsageRepository()
    for index in range(10):
        await repository.record(usage("planner", f"tool_{index}"))
    provider = ToolUsageContextProvider(repository, max_entries=3)

    context = await provider.get(RUN)

    assert [entry.tool_name for entry in context.entries] == ["tool_7", "tool_8", "tool_9"]


async def test_an_unreadable_repository_degrades_to_empty_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = ToolUsageContextProvider(BrokenRepository())

    with caplog.at_level(logging.WARNING):
        context = await provider.get(RUN)

    assert context.is_empty
    assert "tool usage context unavailable" in caplog.text


async def test_a_trimmed_record_says_it_is_incomplete() -> None:
    repository = InMemoryToolUsageRepository()
    for index in range(5):
        await repository.record(usage("planner", f"tool_{index}"))
    provider = ToolUsageContextProvider(repository, max_entries=2)

    context = await provider.get(RUN)
    rendered = context.render()

    assert context.truncated
    assert rendered is not None
    assert "not complete" in rendered


async def test_a_complete_record_does_not_claim_to_be_trimmed() -> None:
    repository = InMemoryToolUsageRepository()
    await repository.record(usage("planner", "github.search"))
    provider = ToolUsageContextProvider(repository, max_entries=2)

    context = await provider.get(RUN)

    assert not context.truncated
    assert "not complete" not in str(context.render())


async def test_the_report_is_bounded_and_says_so() -> None:
    repository = InMemoryToolUsageRepository()
    for index in range(5):
        await repository.record(usage("planner", f"tool_{index}"))
    provider = ToolUsageContextProvider(repository, report_max_entries=2)

    report = format_executed_tools(await provider.get_executed_tools(RUN))

    assert "tool_3" in report and "tool_4" in report
    assert "tool_0" not in report
    assert "not complete" in report


async def test_repeated_same_named_calls_remain_distinct_context_entries() -> None:
    repository = InMemoryToolUsageRepository()
    await repository.record(usage("planner", "github.search", tool_call_id="call-1"))
    await repository.record(usage("planner", "github.search", tool_call_id="call-2"))
    provider = ToolUsageContextProvider(repository)

    context = await provider.get(RUN)

    assert [entry.tool_name for entry in context.entries] == ["github.search", "github.search"]


async def test_tool_only_context_does_not_underfill_after_many_delegations() -> None:
    repository = InMemoryToolUsageRepository()
    await repository.record(usage("worker", "first-tool", tool_call_id="tool-1"))
    for index in range(10):
        await repository.record(
            usage(
                "root",
                f"child-{index}",
                kind=ToolInvocationKind.AGENT,
                tool_call_id=f"delegate-{index}",
            )
        )
    await repository.record(usage("worker", "last-tool", tool_call_id="tool-2"))
    provider = ToolUsageContextProvider(repository, max_entries=2, include_delegations=False)

    context = await provider.get(RUN)

    assert [entry.tool_name for entry in context.entries] == ["first-tool", "last-tool"]


async def test_a_read_failure_propagates_from_the_report() -> None:
    """The caller must be able to tell "unreadable" from "nothing ran"."""
    provider = ToolUsageContextProvider(BrokenRepository())

    with pytest.raises(RuntimeError):
        await provider.get_executed_tools(RUN)


def test_entry_limits_must_be_positive() -> None:
    with pytest.raises(ValueError):
        ToolUsageContextProvider(InMemoryToolUsageRepository(), max_entries=0)
    with pytest.raises(ValueError):
        ToolUsageContextProvider(InMemoryToolUsageRepository(), report_max_entries=0)
