"""Prepared input for one persisted conversation turn."""

from __future__ import annotations

from dataclasses import dataclass

from agent_engine.engine.types import ChatMessage
from agent_manager.domain import Principal


@dataclass(frozen=True)
class PreparedConversationTurn:
    session_id: str
    run_id: str
    message_id: str
    user_id: str
    message: str
    history: tuple[ChatMessage, ...]
    #: Kept on the turn because `stream_turn` executes it with nothing else in
    #: hand, and the run must still act as whoever asked for it.
    principal: Principal
