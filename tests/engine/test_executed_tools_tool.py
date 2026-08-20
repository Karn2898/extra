"""The orchestrator's read-only report of what has actually executed.

Asked which tools had run, an orchestrator kept naming the child agent it had
delegated to — that name is in its own tool list, and no system instruction
reliably overrode it. These tests cover the tool that makes the answer come from
the repository instead.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest

from agent_engine.core.spec import ModelConfig, OrchestratorPromptSet, OrchestratorSpec
from agent_engine.engine.langgraph.executed_tools_tool import (
    EXECUTED_TOOLS_TOOL_NAME,
    build_executed_tools_tool,
)
from agent_engine.engine.langgraph.nodes import OrchestratorNode
from agent_engine.loaders.resolver_loader import ResolverLoader
from agent_engine.runtime.hooks import RunContext, current_run_context
from agent_engine.tool_usage.context import ToolUsageContextProvider
from agent_engine.tool_usage.in_memory import InMemoryToolUsageRepository
from agent_engine.tool_usage.models import (
    ToolCallIdentity,
    ToolInvocationKind,
    ToolInvocationRecord,
    ToolInvocationStatus,
)
from agent_engine.tool_usage.tracker import ToolUsageTracker
from tests.engine.test_shared_tool_usage import run_system
from tests.engine.usage_models import AllToolsThenAnswerModel


def usage(
    agent_id: str,
    tool_name: str,
    *,
    run_id: str = "run-1",
    kind: ToolInvocationKind = ToolInvocationKind.TOOL,
    status: ToolInvocationStatus = ToolInvocationStatus.SUCCEEDED,
) -> ToolInvocationRecord:
    return ToolInvocationRecord(
        call=ToolCallIdentity(
            run_id=run_id,
            agent_id=agent_id,
            agent_path=f"openwebui/{agent_id}",
            tool_call_id=f"call-{agent_id}-{tool_name}-{run_id}",
            tool_name=tool_name,
            conversation_id="conv-1",
            kind=kind,
        ),
        status=status,
    )


@pytest.fixture
def run_scope() -> Iterator[None]:
    """Run the tool inside a run context, as the engine always does."""
    token = current_run_context.set(RunContext(run_id="run-2", conversation_id="conv-1"))
    yield
    current_run_context.reset(token)


async def report(repository: InMemoryToolUsageRepository) -> str:
    tool = build_executed_tools_tool(ToolUsageContextProvider(repository), "openwebui")
    return str(await tool.ainvoke({}))


async def test_it_reports_the_tools_executed_across_the_conversation(run_scope: None) -> None:
    repository = InMemoryToolUsageRepository()
    await repository.record(usage("user_management", "add_new_user"))
    await repository.record(usage("group_management", "create_group", run_id="run-2"))

    answer = await report(repository)

    assert "user_management: add_new_user [succeeded]" in answer
    assert "group_management: create_group [succeeded]" in answer


async def test_it_never_reports_a_delegation_as_an_executed_tool(run_scope: None) -> None:
    repository = InMemoryToolUsageRepository()
    await repository.record(usage("user_management", "add_new_user"))
    await repository.record(usage("openwebui", "admin_management", kind=ToolInvocationKind.AGENT))

    answer = await report(repository)

    assert "add_new_user" in answer
    assert "admin_management" not in answer


async def test_it_reports_a_failed_tool_with_its_outcome(run_scope: None) -> None:
    repository = InMemoryToolUsageRepository()
    await repository.record(
        usage("user_management", "add_new_user", status=ToolInvocationStatus.FAILED)
    )

    assert "add_new_user [failed]" in await report(repository)


async def test_it_says_so_when_nothing_has_executed(run_scope: None) -> None:
    assert "No tools have been executed" in await report(InMemoryToolUsageRepository())


async def test_another_conversation_is_never_reported(run_scope: None) -> None:
    repository = InMemoryToolUsageRepository()
    other = ToolInvocationRecord(
        call=ToolCallIdentity(
            run_id="other-run",
            agent_id="user_management",
            agent_path="other/user_management",
            tool_call_id="other-call",
            tool_name="delete_user",
            conversation_id="conv-other",
        ),
        status=ToolInvocationStatus.SUCCEEDED,
    )
    await repository.record(other)

    assert "delete_user" not in await report(repository)


async def test_an_unreadable_record_is_never_reported_as_nothing_having_run(
    run_scope: None,
) -> None:
    """Saying "nothing ran" when the record cannot be read would invite an agent
    to repeat an action that already took effect."""
    from tests.tool_usage.test_tracker import BrokenRepository

    tool = build_executed_tools_tool(ToolUsageContextProvider(BrokenRepository()), "openwebui")

    answer = str(await tool.ainvoke({}))

    assert "could not be read" in answer
    assert "No tools have been executed" not in answer


# --------------------------------------------------------------------------- #
# Binding
# --------------------------------------------------------------------------- #


async def test_orchestrators_are_given_the_reporting_tool(
    tmp_path: Path, models: dict[str, AllToolsThenAnswerModel]
) -> None:
    captured: list[str] = []

    class BindingCapture(AllToolsThenAnswerModel):
        def bind_tools(self, tools: list[Any]) -> AllToolsThenAnswerModel:
            captured.extend(tool.name for tool in tools)
            return super().bind_tools(tools)

    models["root-model"] = BindingCapture("root answer")

    await run_system(tmp_path, models, repository=InMemoryToolUsageRepository(), run_id="run-1")

    assert EXECUTED_TOOLS_TOOL_NAME in captured
    assert "planner" in captured  # the children are still bound


async def test_an_orchestrator_with_no_reachable_children_is_bound_no_tools(
    tmp_path: Path,
) -> None:
    """A child filtered out for this caller must leave the model with nothing to
    call — a convenience tool must not reopen a path access control closed."""
    bound: list[list[str]] = []

    class BindingCapture(AllToolsThenAnswerModel):
        def bind_tools(self, tools: list[Any]) -> AllToolsThenAnswerModel:
            bound.append([tool.name for tool in tools])
            return super().bind_tools(tools)

    model = BindingCapture("nothing to route to")
    node = OrchestratorNode(
        spec=OrchestratorSpec(
            id="root",
            name="root",
            description="root",
            model=ModelConfig(provider="fake", name="root", temperature=None),
            prompts=OrchestratorPromptSet(),
        ),
        node_path="root",
        model=cast(Any, model),
        children=[],
        filters=[],
        resolver_loader=ResolverLoader(tmp_path),
        base_dir=tmp_path,
        usage_context=ToolUsageContextProvider(InMemoryToolUsageRepository()),
        usage_tracker=ToolUsageTracker(InMemoryToolUsageRepository()),
    )

    await node({"message": "hi", "visited": []})

    assert bound == []


async def test_calling_the_report_is_not_recorded_as_tool_usage(
    tmp_path: Path, models: dict[str, AllToolsThenAnswerModel]
) -> None:
    repository = InMemoryToolUsageRepository()

    await run_system(tmp_path, models, repository=repository, run_id="run-1")

    stored = await repository.list_for_run("run-1")
    assert EXECUTED_TOOLS_TOOL_NAME not in {r.call.tool_name for r in stored}
