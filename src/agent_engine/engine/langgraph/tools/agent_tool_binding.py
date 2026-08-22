"""One agent's resolved tools and their provider metadata."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from langchain_core.tools import BaseTool

from agent_engine.runtime.tool_models import ToolProviderName


@dataclass(frozen=True)
class AgentToolBinding:
    tools: dict[str, BaseTool] = field(default_factory=dict)
    mcp_tool_names: frozenset[str] = frozenset()
    mcp_server_by_tool: Mapping[str, str] = field(default_factory=dict)

    def get(self, name: str) -> BaseTool | None:
        return self.tools.get(name)

    def provider_of(self, name: str) -> ToolProviderName:
        return "mcp" if name in self.mcp_tool_names else "local"

    def server_of(self, name: str) -> str | None:
        return self.mcp_server_by_tool.get(name)
