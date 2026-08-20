"""Execution contract shared by compiled LangGraph nodes."""

from __future__ import annotations

from abc import ABC, abstractmethod

from agent_engine.runtime.state import GraphState


class NodeExecutor(ABC):
    @abstractmethod
    async def execute(self, state: GraphState) -> GraphState:
        raise NotImplementedError
