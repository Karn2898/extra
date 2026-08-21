"""Startup-time MCP client construction and remote tool discovery."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from langchain_mcp_adapters import client as mcp_client

from agent_engine.core.spec import MCPSpec
from agent_engine.loaders.mcp_auth_loader import MCPAuthLoader
from agent_engine.loaders.mcp_tags import apply_tool_tags, effective_tool_tag_transport
from agent_engine.logging_config import log
from agent_engine.runtime.hooks import HookedMCPAuth, HookManager

logger = logging.getLogger(__name__)


def _root_cause(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        for nested in exc.exceptions:
            return _root_cause(nested)
    return str(exc)


class MCPConnector:
    """Connect configured MCP servers and retain their clients for engine life."""

    def __init__(self, base_dir: Path, hook_manager: HookManager) -> None:
        self._auth_loader = MCPAuthLoader(base_dir)
        self._hook_manager = hook_manager
        self._clients: dict[str, Any] = {}

    async def connect(self, specs: Mapping[str, MCPSpec]) -> dict[str, list[BaseTool]]:
        tools_by_server: dict[str, list[BaseTool]] = {}
        hook_mcp_auth = self._hook_manager.has("before_mcp_request")
        for server_id, mcp_spec in specs.items():
            config: dict[str, Any] = {
                "url": mcp_spec.url,
                "transport": "streamable_http",
            }
            auth = self._auth_loader.get_auth(server_id)
            if hook_mcp_auth:
                auth = HookedMCPAuth(self._hook_manager, server_id, base=auth)
            if auth is not None:
                config["auth"] = auth

            if mcp_spec.tool_tags:
                transport = effective_tool_tag_transport(mcp_spec)
                config = apply_tool_tags(
                    config,
                    mcp_spec.tool_tags,
                    transport,
                    server_id=server_id,
                )
                log(
                    logger,
                    logging.INFO,
                    "mcp tool_tags configured",
                    server=server_id,
                    tags=len(mcp_spec.tool_tags),
                    transport=transport.type if transport else "",
                    default_transport=mcp_spec.tool_tag_transport is None,
                )

            client = mcp_client.MultiServerMCPClient(
                {server_id: config}  # type: ignore[dict-item]
            )
            self._clients[server_id] = client
            try:
                log(logger, logging.INFO, "mcp discovery started", server=server_id)
                tools_by_server[server_id] = await client.get_tools()
                log(
                    logger,
                    logging.INFO,
                    "mcp connected",
                    server=server_id,
                    tools=len(tools_by_server[server_id]),
                )
            except Exception as exc:
                log(
                    logger,
                    logging.WARNING,
                    "mcp unreachable",
                    server=server_id,
                    reason=_root_cause(exc),
                )
                tools_by_server[server_id] = []
        return tools_by_server

    def clear(self) -> None:
        """Release references to clients during engine shutdown."""
        self._clients.clear()
