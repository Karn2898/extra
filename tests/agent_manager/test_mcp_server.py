"""Unit tests for the MCP server adapter."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.types import CallToolRequest, CallToolRequestParams, ListToolsRequest

from agent_engine.engine.types import ChatMessage, RunResult, ToolUsageRecord
from agent_engine.runtime.hooks.models import RunContext
from agent_engine.runtime.streaming import RunStreamEvent
from agent_manager.application import ConversationService
from agent_manager.application.service import ConversationNotFound
from agent_manager.domain import Repository
from agentctl.mcp.server import (
    ExtraChatError,
    _handle_extra_chat,
    _tool_usage_to_dict,
    _validate_extra_chat_input,
    create_mcp_server,
)


class FakeEngine:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.histories: list[tuple[ChatMessage, ...]] = []
        self.contexts: list[RunContext | None] = []

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
        self.contexts.append(context)
        return RunResult(
            system_name="Fake System",
            visited=["root", "knowledge_agent"],
            answer="The relevant documentation is...",
            used_tools=(
                ToolUsageRecord(
                    name="search_internal_documents",
                    provider="mcp",
                    status="succeeded",
                    agent_id="enterprise_docs_agent",
                    server_id="local_knowledge_mcp",
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
        self.contexts.append(context)
        yield RunStreamEvent(type="answer_delta", content="chunk")
        yield RunStreamEvent(
            type="final",
            content="answer",
            route=("root",),
            system_name="Fake System",
        )

    async def close(self) -> None: ...


def _make_service() -> tuple[ConversationService, FakeEngine, Repository]:
    engine = FakeEngine()
    repo = MagicMock(spec=Repository)
    repo.conversation_exists = AsyncMock(return_value=True)
    repo.create_session = AsyncMock(return_value=MagicMock(session_id="sess-1"))
    repo.get_context = AsyncMock(return_value=MagicMock(messages=[]))
    repo.append_message = AsyncMock()
    repo.list_messages = AsyncMock(return_value=[])
    repo.get_token_usage = AsyncMock(return_value=0)
    repo.upsert_user = AsyncMock()
    service = ConversationService(engine, repo, window=10)
    return service, engine, repo


class TestValidateExtraChatInput:
    def test_valid_input(self) -> None:
        message, session_id, user_id = _validate_extra_chat_input(
            {"message": "hello", "session_id": "s1", "user_id": "u1"}
        )
        assert message == "hello"
        assert session_id == "s1"
        assert user_id == "u1"

    def test_minimal_input(self) -> None:
        message, session_id, user_id = _validate_extra_chat_input({"message": "hello"})
        assert message == "hello"
        assert session_id is None
        assert user_id is None

    def test_empty_message_raises(self) -> None:
        with pytest.raises(ExtraChatError, match="non-empty string"):
            _validate_extra_chat_input({"message": "   "})

    def test_missing_message_raises(self) -> None:
        with pytest.raises(ExtraChatError, match="non-empty string"):
            _validate_extra_chat_input({})

    def test_non_string_message_raises(self) -> None:
        with pytest.raises(ExtraChatError, match="non-empty string"):
            _validate_extra_chat_input({"message": 123})

    def test_non_string_session_id_raises(self) -> None:
        with pytest.raises(ExtraChatError, match=r"session_id.*string"):
            _validate_extra_chat_input({"message": "hi", "session_id": 123})

    def test_non_string_user_id_raises(self) -> None:
        with pytest.raises(ExtraChatError, match=r"user_id.*string"):
            _validate_extra_chat_input({"message": "hi", "user_id": []})


class TestToolUsageToDict:
    def test_filters_none_values(self) -> None:
        record = ToolUsageRecord(
            name="search",
            provider="mcp",
            status="succeeded",
            agent_id=None,
            server_id="srv",
            error=None,
        )
        result = _tool_usage_to_dict(record)
        assert result == {
            "name": "search",
            "provider": "mcp",
            "status": "succeeded",
            "server_id": "srv",
        }

    def test_includes_all_non_none_fields(self) -> None:
        record = ToolUsageRecord(
            name="tool",
            provider="local",
            status="failed",
            agent_id="agent-a",
            server_id="srv",
            error="timeout",
        )
        result = _tool_usage_to_dict(record)
        assert result["agent_id"] == "agent-a"
        assert result["error"] == "timeout"


class TestHandleExtraChat:
    async def test_generates_session_id_when_missing(self) -> None:
        service, _engine, repo = _make_service()

        result = await _handle_extra_chat(service, {"message": "hello"})

        assert "session_id" in result
        assert len(result["session_id"]) == 16
        repo.create_session.assert_called_once()
        repo.append_message.assert_called()

    async def test_uses_provided_session_id(self) -> None:
        service, _engine, repo = _make_service()

        result = await _handle_extra_chat(service, {"message": "hello", "session_id": "my-sess"})

        assert result["session_id"] == "my-sess"
        repo.create_session.assert_called_once()
        assert repo.create_session.call_args.args[0] == "my-sess"
        assert repo.create_session.call_args.kwargs["user_id"] == "local-user"

    async def test_maps_run_result_to_output(self) -> None:
        service, _engine, _repo = _make_service()

        result = await _handle_extra_chat(service, {"message": "docs?"})

        assert result["answer"] == "The relevant documentation is..."
        assert result["visited"] == ["root", "knowledge_agent"]
        assert len(result["used_tools"]) == 1
        tool = result["used_tools"][0]
        assert tool["name"] == "search_internal_documents"
        assert tool["provider"] == "mcp"
        assert tool["status"] == "succeeded"
        assert tool["agent_id"] == "enterprise_docs_agent"
        assert tool["server_id"] == "local_knowledge_mcp"

    async def test_uses_provided_user_id(self) -> None:
        service, _engine, repo = _make_service()

        await _handle_extra_chat(service, {"message": "hi", "user_id": "u42"})

        repo.upsert_user.assert_called_with("u42")

    async def test_raises_on_conversation_not_found(self) -> None:
        service, _engine, repo = _make_service()
        repo.conversation_exists = AsyncMock(return_value=False)
        repo.create_session = AsyncMock(side_effect=ConversationNotFound("missing"))

        with pytest.raises(ConversationNotFound):
            await _handle_extra_chat(service, {"message": "hi", "session_id": "missing"})


class TestCreateMcpServer:
    async def test_lists_extra_chat_tool(self) -> None:
        service, _, _ = _make_service()
        server = create_mcp_server(service)

        req = ListToolsRequest(method="tools/list")
        handler = server.request_handlers[type(req)]
        result = await handler(req)

        tools = result.root.tools
        assert len(tools) == 1
        assert tools[0].name == "extra_chat"
        assert "message" in tools[0].inputSchema["properties"]
        assert "session_id" in tools[0].inputSchema["properties"]
        assert "user_id" in tools[0].inputSchema["properties"]
        assert tools[0].inputSchema["required"] == ["message"]

    async def test_call_tool_delegates_to_handler(self) -> None:
        service, engine, _repo = _make_service()
        server = create_mcp_server(service)

        req = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name="extra_chat", arguments={"message": "hello"}),
        )
        handler = server.request_handlers[type(req)]
        result = await handler(req)

        assert not result.root.isError
        content = result.root.structuredContent
        assert "session_id" in content
        assert len(content["session_id"]) == 16
        assert content["answer"] == "The relevant documentation is..."
        assert engine.prompts == ["hello"]

    async def test_call_tool_errors_on_unknown_tool(self) -> None:
        service, _, _ = _make_service()
        server = create_mcp_server(service)

        req = CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name="unknown_tool", arguments={}),
        )
        handler = server.request_handlers[type(req)]
        result = await handler(req)

        assert result.root.isError is True
        assert "Unknown tool" in (result.root.content[0].text if result.root.content else "")
