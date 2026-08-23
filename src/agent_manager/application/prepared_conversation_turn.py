"""Prepared input for one persisted conversation turn."""

from __future__ import annotations

import asyncio
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
    #: Title generation started alongside this turn, on a conversation's first
    #: message only. Held here so whoever delivers the turn can also deliver
    #: its title, and so the handle dies with the turn rather than outliving it
    #: in service-level state.
    title_task: asyncio.Task[str | None] | None = None
