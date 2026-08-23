"""Thin MCP stdio adapter exposing the Extra engine as a single tool.

The server builds the engine and database connection once at startup, then
handles ``extra_chat`` calls by delegating to the existing
:class:`ConversationService`.  No orchestration, routing, tool execution,
approval, or hook logic is duplicated here.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import signal
import sys
from pathlib import Path
from uuid import uuid4

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool

from agent_engine.engine.langgraph.engine import LangGraphEngine
from agent_engine.runtime.tool_models import ToolUsageRecord
from agent_manager.application import ConversationService
from agent_manager.composition import application_repositories
from agent_manager.config import Settings
from agentctl.session import load_and_validate, load_env

logger = logging.getLogger(__name__)

LOCAL_USER_ID = "local-user"


class ExtraChatError(Exception):
    """Base for input-level errors surfaced as MCP tool errors."""


def _tool_usage_to_dict(tool: ToolUsageRecord) -> dict[str, object]:
    data = dataclasses.asdict(tool)
    return {k: v for k, v in data.items() if v is not None}


def _validate_extra_chat_input(arguments: dict[str, object]) -> tuple[str, str | None, str | None]:
    message = arguments.get("message")
    if not isinstance(message, str) or not message.strip():
        raise ExtraChatError("'message' must be a non-empty string")

    session_id = arguments.get("session_id")
    if session_id is not None and not isinstance(session_id, str):
        raise ExtraChatError("'session_id' must be a string")

    user_id = arguments.get("user_id")
    if user_id is not None and not isinstance(user_id, str):
        raise ExtraChatError("'user_id' must be a string")

    return message, session_id, user_id


async def _handle_extra_chat(
    service: ConversationService,
    arguments: dict[str, object],
) -> dict[str, object]:
    message, session_id, user_id = _validate_extra_chat_input(arguments)

    effective_session_id = session_id or uuid4().hex[:16]
    effective_user_id = user_id or LOCAL_USER_ID

    await service.create(user_id=effective_user_id, session_id=effective_session_id)

    result = await service.send(effective_session_id, message, user_id=effective_user_id)

    return {
        "session_id": effective_session_id,
        "answer": result.answer,
        "visited": list(result.visited),
        "used_tools": [_tool_usage_to_dict(t) for t in result.used_tools],
    }


def create_mcp_server(service: ConversationService) -> Server:
    server = Server("extra-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="extra_chat",
                description=(
                    "Send a message to the Extra agent system and receive a response. "
                    "Maintains conversation history across calls via session_id."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "The user message to send to the agent system.",
                        },
                        "session_id": {
                            "type": "string",
                            "description": (
                                "Optional stable conversation session id. "
                                "Generated and returned if omitted."
                            ),
                        },
                        "user_id": {
                            "type": "string",
                            "description": "Optional user id for persisted local runs.",
                        },
                    },
                    "required": ["message"],
                },
            )
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, object]) -> dict[str, object]:
        if name != "extra_chat":
            raise ExtraChatError(f"Unknown tool: {name}")
        return await _handle_extra_chat(service, arguments)

    return server


async def _run_mcp_server(config: str) -> None:
    spec, base_dir = load_and_validate(config)
    settings = Settings()

    async with application_repositories(settings) as repositories, LangGraphEngine(
        base_dir,
        session_approval_repository=repositories.session_approvals,
    ) as engine:
        await engine.build(spec)
        service = ConversationService(
            engine,
            repositories.conversations,
            window=settings.context_window,
            max_chars=settings.context_max_chars,
            max_tokens=settings.context_max_tokens,
            snapshot_ttl_seconds=settings.snapshot_ttl_seconds,
            system_name=spec.meta.name,
            config_path=str(Path(config).resolve()),
        )
        mcp_server = create_mcp_server(service)

        shutdown_event = asyncio.Event()

        def _signal_handler() -> None:
            logger.info("shutdown signal received")
            shutdown_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _signal_handler)
            except NotImplementedError:
                signal.signal(sig, lambda *_: _signal_handler())

        async with stdio_server() as (read_stream, write_stream):
            server_task = asyncio.create_task(
                mcp_server.run(
                    read_stream,
                    write_stream,
                    mcp_server.create_initialization_options(),
                )
            )
            shutdown_task = asyncio.create_task(shutdown_event.wait())

            _, pending = await asyncio.wait(
                [server_task, shutdown_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in pending:
                task.cancel()
            try:
                for task in pending:
                    await task
            except asyncio.CancelledError:
                pass


def serve_stdio(config: str, env: str | None) -> None:
    load_env(config, env)
    try:
        asyncio.run(_run_mcp_server(config))
    except Exception as exc:
        logger.error("MCP server failed: %s", exc)
        sys.exit(1)
