"""Deterministic chat model shared by the engine tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.messages.tool import ToolCall


class AllToolsThenAnswerModel:
    """Calls every bound tool once, then answers. Records what it was asked."""

    def __init__(
        self,
        answer: str,
        tool_names: list[str] | None = None,
        seen: list[list[Any]] | None = None,
    ) -> None:
        self._answer = answer
        self._tool_names = tool_names or []
        self.seen: list[list[Any]] = [] if seen is None else seen

    def bind_tools(self, tools: list[Any]) -> AllToolsThenAnswerModel:
        return AllToolsThenAnswerModel(self._answer, [t.name for t in tools], self.seen)

    async def ainvoke(self, messages: list[Any]) -> AIMessage:
        return self._respond(messages)

    async def astream(self, messages: list[Any]) -> AsyncIterator[AIMessage]:
        yield self._respond(messages)

    def _respond(self, messages: list[Any]) -> AIMessage:
        self.seen.append(list(messages))
        if self._tool_names and not any(isinstance(m, ToolMessage) for m in messages):
            return AIMessage(
                content="",
                tool_calls=[
                    ToolCall(name=name, args={"message": "go"}, id=f"call_{name}")
                    for name in self._tool_names
                ],
            )
        return AIMessage(content=self._answer)
