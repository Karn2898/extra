"""Runtime descriptor for a child exposed by an orchestrator."""

from __future__ import annotations

from dataclasses import dataclass

from agent_engine.engine.langgraph.execution.node_executor import NodeExecutor


@dataclass(frozen=True)
class ChildEntry:
    """A concrete child node exposed to its parent orchestrator as a delegation."""

    id: str
    name: str
    protected: bool
    node: NodeExecutor
    description: str = ""

    @property
    def tool_description(self) -> str:
        summary = self.description or self.name
        return f"Delegate this request to the '{self.name}' agent. {summary}"
