"""Prepared input for one persisted conversation turn."""

from __future__ import annotations

from dataclasses import dataclass

from agent_engine.engine.types import ChatMessage


@dataclass(frozen=True)
class PreparedConversationTurn:
    session_id: str
    run_id: str
    message_id: str
    user_id: str
    message: str
    history: tuple[ChatMessage, ...]
