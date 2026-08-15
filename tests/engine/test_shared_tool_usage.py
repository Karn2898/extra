"""Tool usage is shared across the agents of one run, through the repository.

Two agents run under one orchestrator in a single run. What the first agent did
must reach the second one without any of it travelling through ``GraphState`` —
and without ever becoming conversation history or user-visible text.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.messages.tool import ToolCall

from agent_engine.core.spec import (
    AgentSpec,
    BasePromptSet,
    GraphNode,
    ModelConfig,
    OrchestratorPromptSet,
    OrchestratorSpec,
    SystemMeta,
    SystemSpec,
    ToolSpec,
)
from agent_engine.engine.langgraph.engine import LangGraphEngine
from agent_engine.engine.types import ChatMessage, ChatRole, RunResult
from agent_engine.runtime.hooks import RunContext
from agent_engine.tool_usage.in_memory import InMemoryToolUsageRepository
from agent_engine.tool_usage.models import ToolInvocationKind
from tests.engine.usage_models import AllToolsThenAnswerModel

AGENT = ToolInvocationKind.AGENT
TOOL = ToolInvocationKind.TOOL

USAGE_HEADER = "Execution record for this conversation"


def model_config(name: str) -> ModelConfig:
    return ModelConfig(provider="fake", name=name, temperature=None)


def agent(node_id: str, tool_id: str, *, model_name: str | None = None) -> GraphNode:
    return GraphNode(
        node=AgentSpec(
            id=node_id,
            name=node_id,
            description=f"{node_id} agent",
            model=model_config(model_name or f"{node_id}-model"),
            prompts=BasePromptSet(),
            tools=(ToolSpec(tool_id, f"{tool_id} description"),),
            auto_mode=True,
        )
    )


def two_agent_system(children: list[GraphNode]) -> SystemSpec:
    root = OrchestratorSpec(
        id="root",
        name="root",
        description="root orchestrator",
        model=model_config("root-model"),
        prompts=OrchestratorPromptSet(),
    )
    return SystemSpec(
        meta=SystemMeta(name="shared-usage"),
        defaults=None,
        graph=GraphNode(node=root, children=tuple(children)),
    )


def write_tool(base_dir: Path, tool_id: str, *, fails: bool = False) -> None:
    tools_dir = base_dir / "plugins" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    body = (
        "    raise RuntimeError('provider exploded')\n"
        if fails
        else "    return 'did: ' + message\n"
    )
    (tools_dir / f"{tool_id}.py").write_text(
        f"def {tool_id}(message: str) -> str:\n{body}", encoding="utf-8"
    )


def model_factory_for(models: dict[str, AllToolsThenAnswerModel]) -> Callable[..., BaseChatModel]:
    def factory(provider: str, name: str, temperature: float | None, **_: Any) -> BaseChatModel:
        return cast(BaseChatModel, models[name])

    return factory


async def run_system(
    tmp_path: Path,
    models: dict[str, AllToolsThenAnswerModel],
    *,
    repository: InMemoryToolUsageRepository,
    run_id: str,
    conversation_id: str | None = None,
    failing_tool: bool = False,
    history: Sequence[ChatMessage] = (),
) -> RunResult:
    write_tool(tmp_path, "search")
    write_tool(tmp_path, "get_file", fails=failing_tool)
    spec = two_agent_system([agent("planner", "search"), agent("developer", "get_file")])
    async with LangGraphEngine(
        tmp_path,
        model_factory=model_factory_for(models),
        tool_usage_repository=repository,
    ) as engine:
        await engine.build(spec)
        return await engine.run(
            "please handle this",
            history=history,
            context=RunContext(run_id=run_id, conversation_id=conversation_id),
        )


def messages_of(model: AllToolsThenAnswerModel) -> list[Any]:
    """The last message list this model was asked to complete."""
    return model.seen[-1]


def first_messages_of(model: AllToolsThenAnswerModel) -> list[Any]:
    return model.seen[0]


# --------------------------------------------------------------------------- #
# Persistence: run → agent → tool call
# --------------------------------------------------------------------------- #


async def test_every_agents_tool_call_is_persisted_against_the_same_run(
    tmp_path: Path, models: dict[str, AllToolsThenAnswerModel]
) -> None:
    repository = InMemoryToolUsageRepository()

    await run_system(
        tmp_path, models, repository=repository, run_id="run-1", conversation_id="conv-1"
    )

    stored = [r for r in await repository.list_for_run("run-1") if r.call.kind is TOOL]
    assert [(r.call.agent_id, r.call.tool_name, r.status.value) for r in stored] == [
        ("planner", "search", "succeeded"),
        ("developer", "get_file", "succeeded"),
    ]


async def test_a_record_carries_its_conversation_run_agent_and_call(
    tmp_path: Path, models: dict[str, AllToolsThenAnswerModel]
) -> None:
    repository = InMemoryToolUsageRepository()

    await run_system(
        tmp_path, models, repository=repository, run_id="run-1", conversation_id="conv-1"
    )

    call = next(
        r.call for r in await repository.list_for_run("run-1") if r.call.tool_name == "get_file"
    )
    assert call.conversation_id == "conv-1"
    assert call.run_id == "run-1"
    assert call.agent_id == "developer"
    assert call.agent_path == "root/developer"
    assert call.tool_call_id


async def test_delegating_to_a_child_agent_is_recorded_as_an_action(
    tmp_path: Path, models: dict[str, AllToolsThenAnswerModel]
) -> None:
    repository = InMemoryToolUsageRepository()

    result = await run_system(tmp_path, models, repository=repository, run_id="run-1")

    delegations = [r for r in await repository.list_for_run("run-1") if r.call.kind is AGENT]
    assert [(r.call.agent_id, r.call.tool_name) for r in delegations] == [
        ("root", "planner"),
        ("root", "developer"),
    ]
    # The caller-facing trace still means real tool/MCP calls only.
    assert [t.name for t in result.used_tools] == ["search", "get_file"]


async def test_repeated_delegations_to_the_same_agent_are_both_visible(
    tmp_path: Path,
) -> None:
    class DelegateTwiceModel(AllToolsThenAnswerModel):
        def bind_tools(self, tools: list[Any]) -> AllToolsThenAnswerModel:
            return DelegateTwiceModel(self._answer, [tool.name for tool in tools], self.seen)

        def _respond(self, messages: list[Any]) -> AIMessage:
            self.seen.append(list(messages))
            if self._tool_names and not any(
                isinstance(message, ToolMessage) for message in messages
            ):
                name = self._tool_names[0]
                return AIMessage(
                    content="",
                    tool_calls=[
                        ToolCall(name=name, args={"message": "first"}, id="delegate-1"),
                        ToolCall(name=name, args={"message": "second"}, id="delegate-2"),
                    ],
                )
            return AIMessage(content=self._answer)

    models = {
        "root-model": DelegateTwiceModel("synthesized"),
        "planner-model": AllToolsThenAnswerModel("planned"),
    }
    write_tool(tmp_path, "search")
    repository = InMemoryToolUsageRepository()
    system = two_agent_system([agent("planner", "search")])

    async with LangGraphEngine(
        tmp_path,
        model_factory=model_factory_for(models),
        tool_usage_repository=repository,
    ) as engine:
        await engine.build(system)
        await engine.run("please plan twice", context=RunContext(run_id="run-repeat"))

    delegations = [
        record
        for record in await repository.list_for_run("run-repeat")
        if record.call.kind is AGENT
    ]
    assert [record.call.tool_name for record in delegations] == ["planner", "planner"]
    synthesis = "\n".join(str(message.content) for message in messages_of(models["root-model"]))
    assert synthesis.count("root -> planner") == 2


async def test_records_do_not_leak_between_runs(
    tmp_path: Path, models: dict[str, AllToolsThenAnswerModel]
) -> None:
    repository = InMemoryToolUsageRepository()

    await run_system(tmp_path, models, repository=repository, run_id="run-1")
    await run_system(tmp_path, models, repository=repository, run_id="run-2")

    for run_id in ("run-1", "run-2"):
        stored = [r for r in await repository.list_for_run(run_id) if r.call.kind is TOOL]
        assert {r.call.run_id for r in stored} == {run_id}
        assert len(stored) == 2


async def test_a_failed_tool_call_is_recorded_as_failed(
    tmp_path: Path, models: dict[str, AllToolsThenAnswerModel]
) -> None:
    repository = InMemoryToolUsageRepository()

    await run_system(tmp_path, models, repository=repository, run_id="run-1", failing_tool=True)

    failed = [r for r in await repository.list_for_run("run-1") if r.status.value == "failed"]
    assert [r.call.tool_name for r in failed] == ["get_file"]
    assert failed[0].error is not None and "provider exploded" in failed[0].error


# --------------------------------------------------------------------------- #
# Model context: the later agent knows what the earlier one did
# --------------------------------------------------------------------------- #


async def test_a_later_agent_sees_the_earlier_agents_tool_usage(
    tmp_path: Path, models: dict[str, AllToolsThenAnswerModel]
) -> None:
    await run_system(tmp_path, models, repository=InMemoryToolUsageRepository(), run_id="run-1")

    developer_context = "\n".join(
        str(m.content) for m in first_messages_of(models["developer-model"])
    )
    assert USAGE_HEADER in developer_context
    assert "planner:\n- search [succeeded]" in developer_context


async def test_the_orchestrator_sees_what_its_children_ran_before_synthesising(
    tmp_path: Path, models: dict[str, AllToolsThenAnswerModel]
) -> None:
    await run_system(tmp_path, models, repository=InMemoryToolUsageRepository(), run_id="run-1")

    # The orchestrator's last turn is the synthesis, after both children returned.
    synthesis = "\n".join(str(m.content) for m in messages_of(models["root-model"]))
    assert USAGE_HEADER in synthesis
    assert "planner:\n- search [succeeded]" in synthesis
    assert "developer:\n- get_file [succeeded]" in synthesis


async def test_a_later_turn_of_the_conversation_sees_the_earlier_turns_usage(
    tmp_path: Path, models: dict[str, AllToolsThenAnswerModel]
) -> None:
    repository = InMemoryToolUsageRepository()

    await run_system(
        tmp_path, models, repository=repository, run_id="run-1", conversation_id="conv-1"
    )
    models["root-model"].seen.clear()
    await run_system(
        tmp_path, models, repository=repository, run_id="run-2", conversation_id="conv-1"
    )

    # A follow-up message is a new run: without conversation scope this would be empty.
    opening_turn = "\n".join(str(m.content) for m in first_messages_of(models["root-model"]))
    assert USAGE_HEADER in opening_turn
    assert "planner:\n- search [succeeded]" in opening_turn


async def test_another_conversation_never_sees_this_ones_usage(
    tmp_path: Path, models: dict[str, AllToolsThenAnswerModel]
) -> None:
    repository = InMemoryToolUsageRepository()

    await run_system(
        tmp_path, models, repository=repository, run_id="run-1", conversation_id="conv-1"
    )
    models["root-model"].seen.clear()
    await run_system(
        tmp_path, models, repository=repository, run_id="run-2", conversation_id="conv-other"
    )

    opening_turn = "\n".join(str(m.content) for m in first_messages_of(models["root-model"]))
    assert USAGE_HEADER not in opening_turn


async def test_the_first_agent_starts_without_execution_context(
    tmp_path: Path, models: dict[str, AllToolsThenAnswerModel]
) -> None:
    await run_system(tmp_path, models, repository=InMemoryToolUsageRepository(), run_id="run-1")

    planner_context = "\n".join(str(m.content) for m in first_messages_of(models["planner-model"]))
    assert USAGE_HEADER not in planner_context


async def test_execution_context_is_private_to_the_model_not_conversation_history(
    tmp_path: Path, models: dict[str, AllToolsThenAnswerModel]
) -> None:
    result = await run_system(
        tmp_path, models, repository=InMemoryToolUsageRepository(), run_id="run-1"
    )

    conversational = [
        m
        for m in first_messages_of(models["developer-model"])
        if isinstance(m, HumanMessage | AIMessage)
    ]
    assert conversational
    assert all(USAGE_HEADER not in str(m.content) for m in conversational)
    assert any(
        USAGE_HEADER in str(m.content)
        for m in first_messages_of(models["developer-model"])
        if isinstance(m, SystemMessage)
    )
    assert USAGE_HEADER not in result.answer


async def test_the_conversation_the_model_sees_is_exactly_the_supplied_history(
    tmp_path: Path, models: dict[str, AllToolsThenAnswerModel]
) -> None:
    history = (
        ChatMessage(role=ChatRole.USER, content="earlier question"),
        ChatMessage(role=ChatRole.ASSISTANT, content="earlier answer"),
    )

    await run_system(
        tmp_path,
        models,
        repository=InMemoryToolUsageRepository(),
        run_id="run-1",
        history=history,
    )

    conversational = [
        str(m.content)
        for m in first_messages_of(models["root-model"])
        if isinstance(m, HumanMessage | AIMessage)
    ]
    assert conversational == ["earlier question", "earlier answer", "please handle this"]


async def test_the_user_facing_answer_never_carries_execution_metadata(
    tmp_path: Path, models: dict[str, AllToolsThenAnswerModel]
) -> None:
    result = await run_system(
        tmp_path, models, repository=InMemoryToolUsageRepository(), run_id="run-1"
    )

    assert result.answer == "synthesized"
    for record in result.used_tools:
        assert record.name not in result.answer


# --------------------------------------------------------------------------- #
# Every level of the graph receives the context
# --------------------------------------------------------------------------- #


def nested_system() -> SystemSpec:
    """root orchestrator → intermediate orchestrator → leaf agent."""
    leaf = agent("user_management", "create_user", model_name="leaf-model")
    middle = GraphNode(
        node=OrchestratorSpec(
            id="admin_management",
            name="admin_management",
            description="admin orchestrator",
            model=model_config("mid-model"),
            prompts=OrchestratorPromptSet(),
        ),
        children=(leaf,),
    )
    root = OrchestratorSpec(
        id="openwebui",
        name="openwebui",
        description="root orchestrator",
        model=model_config("root-model"),
        prompts=OrchestratorPromptSet(),
    )
    return SystemSpec(
        meta=SystemMeta(name="nested-usage"),
        defaults=None,
        graph=GraphNode(node=root, children=(middle,)),
    )


async def test_every_level_of_the_graph_sees_the_conversations_usage(tmp_path: Path) -> None:
    models = {
        "root-model": AllToolsThenAnswerModel("root answer"),
        "mid-model": AllToolsThenAnswerModel("mid answer"),
        "leaf-model": AllToolsThenAnswerModel("leaf answer"),
    }
    write_tool(tmp_path, "create_user")
    repository = InMemoryToolUsageRepository()

    async with LangGraphEngine(
        tmp_path,
        model_factory=model_factory_for(models),
        tool_usage_repository=repository,
    ) as engine:
        await engine.build(nested_system())
        await engine.run("create a user", context=RunContext(run_id="r1", conversation_id="c1"))
        for model in models.values():
            model.seen.clear()
        # A new user message: a new run, the same conversation.
        await engine.run("who did what?", context=RunContext(run_id="r2", conversation_id="c1"))

    for name in ("root-model", "mid-model", "leaf-model"):
        opening_turn = "\n".join(str(m.content) for m in first_messages_of(models[name]))
        assert USAGE_HEADER in opening_turn, name
        tools, delegations = opening_turn.split("### Agents delegated to")
        assert "user_management:\n- create_user [succeeded]" in tools, name
        # The child agent belongs to routing, never to the tools that ran.
        assert "admin_management" not in tools, name
        assert "openwebui -> admin_management" in delegations, name


async def test_a_child_agent_is_bound_as_a_delegation_not_as_an_action(
    tmp_path: Path, models: dict[str, AllToolsThenAnswerModel]
) -> None:
    """An orchestrator reported a child agent as a tool it had run. Its own tool
    list is where that belief came from, so the binding has to say otherwise."""
    captured: list[str] = []

    class BindingCapture(AllToolsThenAnswerModel):
        def bind_tools(self, tools: list[Any]) -> AllToolsThenAnswerModel:
            captured.extend(t.description for t in tools)
            return super().bind_tools(tools)

    models["root-model"] = BindingCapture("root answer")

    await run_system(tmp_path, models, repository=InMemoryToolUsageRepository(), run_id="run-1")

    assert any("Delegate this request to the 'planner' agent" in d for d in captured)


# --------------------------------------------------------------------------- #
# Freshness: the context tracks what happened during the turn
# --------------------------------------------------------------------------- #


async def test_a_tool_that_ran_between_model_turns_appears_in_the_next_one(
    tmp_path: Path, models: dict[str, AllToolsThenAnswerModel]
) -> None:
    await run_system(tmp_path, models, repository=InMemoryToolUsageRepository(), run_id="run-1")

    # The developer's second model turn follows the planner's tool call and its own.
    developer = models["developer-model"]
    assert len(developer.seen) == 2
    second_turn = "\n".join(str(m.content) for m in developer.seen[1])
    assert "planner:\n- search [succeeded]" in second_turn


async def test_the_turns_own_tool_call_remains_in_repository_context(
    tmp_path: Path, models: dict[str, AllToolsThenAnswerModel]
) -> None:
    await run_system(tmp_path, models, repository=InMemoryToolUsageRepository(), run_id="run-1")

    developer = models["developer-model"]
    second_turn = developer.seen[1]
    # The normal protocol and repository projection serve different purposes:
    # one carries a result; the other is the authoritative execution record.
    assert any(isinstance(m, ToolMessage) for m in second_turn)
    execution_context = next(
        str(m.content)
        for m in second_turn
        if isinstance(m, SystemMessage) and USAGE_HEADER in str(m.content)
    )
    assert "get_file [succeeded]" in execution_context
    assert "search [succeeded]" in execution_context


async def test_an_agents_own_call_from_an_earlier_run_is_still_shown(
    tmp_path: Path, models: dict[str, AllToolsThenAnswerModel]
) -> None:
    repository = InMemoryToolUsageRepository()

    await run_system(
        tmp_path, models, repository=repository, run_id="run-1", conversation_id="conv-1"
    )
    models["developer-model"].seen.clear()
    await run_system(
        tmp_path, models, repository=repository, run_id="run-2", conversation_id="conv-1"
    )

    # Its own earlier work is not in this turn's messages, so it must be reported.
    opening_turn = "\n".join(str(m.content) for m in first_messages_of(models["developer-model"]))
    assert "developer:\n- get_file [succeeded]" in opening_turn


# --------------------------------------------------------------------------- #
# The public run trace stays a projection of the same records
# --------------------------------------------------------------------------- #


async def test_the_run_trace_is_projected_from_the_repository(
    tmp_path: Path, models: dict[str, AllToolsThenAnswerModel]
) -> None:
    result = await run_system(
        tmp_path, models, repository=InMemoryToolUsageRepository(), run_id="run-1"
    )

    assert [(t.agent_id, t.name, t.status) for t in result.used_tools] == [
        ("planner", "search", "succeeded"),
        ("developer", "get_file", "succeeded"),
    ]


async def test_the_normal_tool_result_still_reaches_the_model(
    tmp_path: Path, models: dict[str, AllToolsThenAnswerModel]
) -> None:
    await run_system(tmp_path, models, repository=InMemoryToolUsageRepository(), run_id="run-1")

    tool_results = [
        str(m.content) for m in messages_of(models["planner-model"]) if isinstance(m, ToolMessage)
    ]
    assert tool_results == ["did: go"]
