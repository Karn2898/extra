"""Tool usage tracking across the Human-in-the-Loop lifecycle.

Approval decides *whether* an invocation runs; tracking records *what happened
to it*. One logical invocation — requested, suspended, approved, executed —
must leave exactly one record, under the same run, agent, and tool call id.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from langchain_core.language_models import BaseChatModel

from agent_engine.approvals.manager import ApprovalManager
from agent_engine.approvals.repository import InMemoryApprovalRepository
from agent_engine.core.spec import (
    AgentSpec,
    BasePromptSet,
    GraphNode,
    ModelConfig,
    SystemMeta,
    SystemSpec,
    ToolSpec,
)
from agent_engine.engine.langgraph.engine import LangGraphEngine
from agent_engine.runs.in_memory import InMemoryRunRepository
from agent_engine.runtime.hooks import RunContext
from agent_engine.tool_usage.in_memory import InMemoryToolUsageRepository
from tests.approvals.test_engine_hitl import ChainedApprovalModel, FakeChatModel

_MODEL = ModelConfig(provider="fake", name="fake", temperature=None)


def _factory(provider: str, name: str, temperature: float | None, **_: Any) -> BaseChatModel:
    return cast(BaseChatModel, FakeChatModel())


def _chained_factory(
    provider: str, name: str, temperature: float | None, **_: Any
) -> BaseChatModel:
    return cast(BaseChatModel, ChainedApprovalModel())


def write_counting_tool(base_dir: Path, tool_id: str, counter: Path) -> None:
    tools_dir = base_dir / "plugins" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    (tools_dir / f"{tool_id}.py").write_text(
        f"def {tool_id}(message: str) -> str:\n"
        f"    with open({str(counter)!r}, 'a') as f:\n"
        "        f.write('x')\n"
        "    return 'sent: ' + message\n",
        encoding="utf-8",
    )


def spec(tool_id: str) -> SystemSpec:
    return SystemSpec(
        meta=SystemMeta(name="hitl-usage"),
        defaults=None,
        graph=GraphNode(
            node=AgentSpec(
                id="writer",
                name="writer",
                description="writer agent",
                model=_MODEL,
                prompts=BasePromptSet(),
                tools=(ToolSpec(tool_id, f"{tool_id} description"),),
                auto_mode=False,
            )
        ),
    )


def chained_spec() -> SystemSpec:
    return SystemSpec(
        meta=SystemMeta(name="hitl-usage"),
        defaults=None,
        graph=GraphNode(
            node=AgentSpec(
                id="writer",
                name="writer",
                description="writer agent",
                model=_MODEL,
                prompts=BasePromptSet(),
                tools=(
                    ToolSpec("send_email", "Send the email."),
                    ToolSpec("archive_email", "Archive the email."),
                ),
                auto_mode=False,
            )
        ),
    )


class Harness:
    """An engine whose approval and usage stores the test can inspect."""

    def __init__(self, base_dir: Path, *, model_factory: Any = _factory) -> None:
        self.approvals = InMemoryApprovalRepository()
        self.usage = InMemoryToolUsageRepository()
        self.engine = LangGraphEngine(
            base_dir,
            model_factory=model_factory,
            approval_manager=ApprovalManager(
                run_repository=InMemoryRunRepository(),
                approval_repository=self.approvals,
            ),
            tool_usage_repository=self.usage,
        )

    async def __aenter__(self) -> Harness:
        await self.engine.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.engine.__aexit__(*args)


async def test_a_suspended_invocation_records_nothing_until_it_is_decided(
    tmp_path: Path,
) -> None:
    counter = tmp_path / "calls.log"
    write_counting_tool(tmp_path, "send_email", counter)
    async with Harness(tmp_path) as harness:
        await harness.engine.build(spec("send_email"))
        pending = await harness.engine.run("hi", context=RunContext(run_id="run-1"))

        assert pending.status == "pending_approval"
        assert list(await harness.usage.list_for_run("run-1")) == []
        assert not counter.exists()


async def test_approval_records_one_invocation_with_the_approved_identity(
    tmp_path: Path,
) -> None:
    counter = tmp_path / "calls.log"
    write_counting_tool(tmp_path, "send_email", counter)
    async with Harness(tmp_path) as harness:
        await harness.engine.build(spec("send_email"))
        pending = await harness.engine.run("hi", context=RunContext(run_id="run-1"))
        assert pending.pending_approval is not None
        approval_id = pending.pending_approval.approval_id

        resumed = await harness.engine.resume("run-1", approval_id, "allow once")

        approval = await harness.approvals.get(approval_id)
        stored = await harness.usage.list_for_run("run-1")

    assert resumed.status == "completed"
    assert len(counter.read_text()) == 1
    assert len(stored) == 1  # one logical invocation, not request + resume
    assert approval is not None
    assert stored[0].call.tool_call_id == approval.tool_call_id
    assert stored[0].call.agent_id == approval.agent_id == "writer"
    assert stored[0].status.value == "succeeded"


async def test_a_denied_invocation_is_recorded_as_denied(tmp_path: Path) -> None:
    counter = tmp_path / "calls.log"
    write_counting_tool(tmp_path, "send_email", counter)
    async with Harness(tmp_path) as harness:
        await harness.engine.build(spec("send_email"))
        pending = await harness.engine.run("hi", context=RunContext(run_id="run-1"))
        assert pending.pending_approval is not None

        resumed = await harness.engine.resume("run-1", pending.pending_approval.approval_id, "deny")
        stored = await harness.usage.list_for_run("run-1")

    assert resumed.status == "completed"
    assert not counter.exists()
    assert [r.status.value for r in stored] == ["denied"]
    assert stored[0].call.agent_id == "writer"


async def test_a_session_approval_records_each_run_under_its_own_run_id(
    tmp_path: Path,
) -> None:
    counter = tmp_path / "calls.log"
    write_counting_tool(tmp_path, "send_email", counter)

    async with Harness(tmp_path) as harness:
        await harness.engine.build(spec("send_email"))
        pending = await harness.engine.run(
            "hi", context=RunContext(run_id="run-a", conversation_id="conv-1", user_id="user-1")
        )
        assert pending.pending_approval is not None
        await harness.engine.resume(
            "run-a",
            pending.pending_approval.approval_id,
            "allow for this session",
            caller_user_id="user-1",
            caller_session_id="conv-1",
        )

        # The session permission suppresses the prompt; usage is still tracked.
        second = await harness.engine.run(
            "again", context=RunContext(run_id="run-b", conversation_id="conv-1", user_id="user-1")
        )

        first_records = await harness.usage.list_for_run("run-a")
        second_records = await harness.usage.list_for_run("run-b")

    assert second.status == "completed"
    assert len(counter.read_text()) == 2
    assert [r.status.value for r in first_records] == ["succeeded"]
    assert [r.status.value for r in second_records] == ["succeeded"]
    assert first_records[0].call.tool_call_id != second_records[0].call.tool_call_id


async def test_a_replayed_node_after_resume_does_not_add_a_second_record(
    tmp_path: Path,
) -> None:
    counter = tmp_path / "calls.log"
    write_counting_tool(tmp_path, "send_email", counter)
    async with Harness(tmp_path) as harness:
        await harness.engine.build(spec("send_email"))
        pending = await harness.engine.run("hi", context=RunContext(run_id="run-1"))
        assert pending.pending_approval is not None
        approval_id = pending.pending_approval.approval_id

        await harness.engine.resume("run-1", approval_id, "allow once")
        recovered = await harness.engine.get_processed_result("run-1", approval_id)
        stored = await harness.usage.list_for_run("run-1")

    assert recovered is not None
    assert len(stored) == 1
    assert len(counter.read_text()) == 1
    assert [t.name for t in recovered.used_tools] == ["send_email"]


async def test_second_approval_replay_reuses_the_first_tools_cached_result(
    tmp_path: Path,
) -> None:
    first_counter = tmp_path / "send.log"
    second_counter = tmp_path / "archive.log"
    write_counting_tool(tmp_path, "send_email", first_counter)
    write_counting_tool(tmp_path, "archive_email", second_counter)

    async with Harness(tmp_path, model_factory=_chained_factory) as harness:
        await harness.engine.build(chained_spec())
        first = await harness.engine.run("hi", context=RunContext(run_id="run-chained"))
        assert first.pending_approval is not None

        second = await harness.engine.resume(
            "run-chained", first.pending_approval.approval_id, "allow once"
        )
        assert second.pending_approval is not None
        assert second.pending_approval.tool_name == "archive_email"

        completed = await harness.engine.resume(
            "run-chained", second.pending_approval.approval_id, "allow once"
        )
        stored = await harness.usage.list_for_run("run-chained")

    assert completed.status == "completed"
    assert first_counter.read_text() == "x"
    assert second_counter.read_text() == "x"
    assert [(record.call.tool_name, record.status.value) for record in stored] == [
        ("send_email", "succeeded"),
        ("archive_email", "succeeded"),
    ]
