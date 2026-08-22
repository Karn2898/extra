"""Ordered model messages for a single graph-node turn."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage


class ModelContext:
    """The ordered messages for one node's model turns.

    Layout: system instructions, an optional private execution-context system
    message, prior conversation turns, then the current user message. The
    execution slot can be refreshed between model turns without entering the
    persisted conversation history.
    """

    _EXECUTION_SLOT = 1

    def __init__(
        self,
        system_prompt: str,
        history: list[dict[str, str]],
        user_message: str,
    ) -> None:
        self._messages: list[Any] = [SystemMessage(content=system_prompt)]
        self._has_execution_context = False
        for message in history:
            role = message.get("role")
            content = message.get("content", "")
            if role == "user":
                self._messages.append(HumanMessage(content=content))
            elif role == "assistant":
                self._messages.append(AIMessage(content=content))
            else:
                raise ValueError(f"Unsupported conversation history role: {role!r}")
        self._messages.append(HumanMessage(content=user_message))

    @property
    def messages(self) -> list[Any]:
        """The live message list handed to the model."""
        return self._messages

    def append(self, message: Any) -> None:
        """Add one model response or tool result to the running turn."""
        self._messages.append(message)

    def set_execution_context(self, text: str | None) -> None:
        """Install, replace, or drop the private execution-context message."""
        if self._has_execution_context:
            self._messages.pop(self._EXECUTION_SLOT)
            self._has_execution_context = False
        if text:
            self._messages.insert(self._EXECUTION_SLOT, SystemMessage(content=text))
            self._has_execution_context = True
