"""Integration tests for the MCP server stdio round trip."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from anyio import create_memory_object_stream
from mcp import ClientSession

from agent_engine.engine.types import ChatMessage, ChatRole, RunResult, ToolUsageRecord
from agent_engine.runtime.hooks.models import RunContext
from agent_engine.runtime.streaming import RunStreamEvent
from agent_manager.application import ConversationService
from agent_manager.infrastructure.persistence.memory_repository import MemoryRepository
from agentctl.mcp.server import create_mcp_server
from agentctl.session import load_and_validate


class FakeEngine:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.histories: list[tuple[ChatMessage, ...]] = []

    async def build(self, _spec: object) -> None: ...

    async def run(
        self,
        message: str,
        *,
        history: Sequence[ChatMessage] = (),
        context: RunContext | None = None,
    ) -> RunResult:
        self.prompts.append(message)
        self.histories.append(tuple(history))
        return RunResult(
            system_name="Fake System",
            visited=["root", "knowledge_agent"],
            answer=f"answer-{message}",
            used_tools=(
                ToolUsageRecord(
                    name="search_internal_documents",
                    provider="mcp",
                    status="succeeded",
                ),
            ),
        )

    async def stream(
        self,
        message: str,
        *,
        history: Sequence[ChatMessage] = (),
        context: RunContext | None = None,
    ) -> AsyncIterator[RunStreamEvent]:
        self.prompts.append(message)
        self.histories.append(tuple(history))
        yield RunStreamEvent(type="answer_delta", content="chunk")
        yield RunStreamEvent(
            type="final",
            content=f"answer-{message}",
            route=("root",),
            system_name="Fake System",
        )

    async def close(self) -> None: ...


def _make_service() -> tuple[ConversationService, FakeEngine]:
    engine = FakeEngine()
    repo = MemoryRepository()
    service = ConversationService(engine, repo, window=10)
    return service, engine


def _write_spec(tmp_path: Path) -> Path:
    spec = tmp_path / "agents.yml"
    spec.write_text(
        "system: {name: Fake System}\n"
        "agents: {fake_agent: {description: fake}}\n"
        "graph: {fake_agent: null}\n",
        encoding="utf-8",
    )
    return spec


async def _run_server_with_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    spec = _write_spec(tmp_path)
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'chat.db'}"
    monkeypatch.setenv("AGENT_DB_BACKEND", "sqlite")
    monkeypatch.setenv("AGENT_DB_URL", db_url)

    service, engine = _make_service()

    with (
        patch("agentctl.mcp.server.LangGraphEngine", return_value=engine),
        patch("agentctl.mcp.server.application_repositories") as mock_repos,
        patch("agentctl.mcp.server.Settings", return_value=MagicMock(
            context_window=10,
            context_max_chars=None,
            context_max_tokens=None,
            snapshot_ttl_seconds=86_400,
        )),
    ):
        mock_repos.return_value.__aenter__ = AsyncMock(
            return_value=MagicMock(
                conversations=service._repository,
                session_approvals=MagicMock(),
            )
        )
        mock_repos.return_value.__aexit__ = AsyncMock(return_value=False)

        _spec_obj, _base_dir = load_and_validate(str(spec))

        mcp_server = create_mcp_server(service)

        c2s_send, c2s_receive = create_memory_object_stream(0)
        s2c_send, s2c_receive = create_memory_object_stream(0)

        async def server_task() -> None:
            try:
                await mcp_server.run(
                    c2s_receive,
                    s2c_send,
                    mcp_server.create_initialization_options(),
                )
            except Exception:
                pass
            finally:
                await s2c_send.aclose()
                await c2s_receive.aclose()

        task = asyncio.create_task(server_task())

        session = ClientSession(s2c_receive, c2s_send)
        await session.__aenter__()
        await session.initialize()
        return session, engine, task


class TestMcpServerIntegration:
    async def test_full_stdio_round_trip_returns_session_and_answer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session, _engine, task = await _run_server_with_client(tmp_path, monkeypatch)
        try:
            result = await session.call_tool(
                "extra_chat",
                {"message": "hello"},
            )
            assert not result.isError
            content = result.structuredContent
            assert "session_id" in content
            assert len(content["session_id"]) == 16
            assert content["answer"] == "answer-hello"
            assert content["visited"] == ["root", "knowledge_agent"]
        finally:
            await session.__aexit__(None, None, None)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def test_reusing_session_continues_conversation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session, _engine, task = await _run_server_with_client(tmp_path, monkeypatch)
        try:
            first = await session.call_tool(
                "extra_chat",
                {"message": "hello"},
            )
            assert not first.isError
            sid = first.structuredContent["session_id"]

            second = await session.call_tool(
                "extra_chat",
                {"message": "follow up", "session_id": sid},
            )
            assert not second.isError
            assert second.structuredContent["answer"] == "answer-follow up"
            assert len(_engine.histories) == 2
            assert _engine.histories[1] == (
                ChatMessage(ChatRole.USER, "hello"),
                ChatMessage(ChatRole.ASSISTANT, "answer-hello"),
            )
        finally:
            await session.__aexit__(None, None, None)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def test_different_sessions_are_isolated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session, engine, task = await _run_server_with_client(tmp_path, monkeypatch)
        try:
            first = await session.call_tool(
                "extra_chat",
                {"message": "session one message"},
            )
            assert not first.isError
            sid1 = first.structuredContent["session_id"]

            second = await session.call_tool(
                "extra_chat",
                {"message": "session two message"},
            )
            assert not second.isError
            sid2 = second.structuredContent["session_id"]

            assert sid1 != sid2

            follow_up_1 = await session.call_tool(
                "extra_chat",
                {"message": "follow up one", "session_id": sid1},
            )
            follow_up_2 = await session.call_tool(
                "extra_chat",
                {"message": "follow up two", "session_id": sid2},
            )

            assert not follow_up_1.isError
            assert not follow_up_2.isError

            history_by_session = {
                sid1: engine.histories[2],
                sid2: engine.histories[3],
            }
            assert history_by_session[sid1] == (
                ChatMessage(ChatRole.USER, "session one message"),
                ChatMessage(ChatRole.ASSISTANT, "answer-session one message"),
            )
            assert history_by_session[sid2] == (
                ChatMessage(ChatRole.USER, "session two message"),
                ChatMessage(ChatRole.ASSISTANT, "answer-session two message"),
            )
        finally:
            await session.__aexit__(None, None, None)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def test_input_validation_returns_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session, _engine, task = await _run_server_with_client(tmp_path, monkeypatch)
        try:
            result = await session.call_tool(
                "extra_chat",
                {"message": ""},
            )
            assert result.isError
            assert "non-empty string" in (result.content[0].text if result.content else "")
        finally:
            await session.__aexit__(None, None, None)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
