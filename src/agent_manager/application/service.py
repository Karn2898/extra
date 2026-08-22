"""Application service — the use cases that give the stateless engine memory.

Depends only on ports: the engine (`agent_engine.Engine`) and the repository.
Both the engine transport and the database backend can change with no edits here.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from agent_engine.engine.engine import Engine
from agent_engine.engine.types import ChatMessage, RunResult
from agent_engine.runtime.hooks import RunContext
from agent_engine.runtime.streaming import RunStreamEvent
from agent_engine.runtime.tool_models import ToolUsageRecord
from agent_manager.application.context import build_history
from agent_manager.domain import (
    ConversationMessage,
    ConversationSession,
    Message,
    PaginatedSessions,
    Principal,
    Repository,
    Role,
    TokenBudgetUsage,
    thread_title,
)


class ConversationNotFound(Exception):
    """Raised when an operation targets a conversation id that does not exist."""


class ConversationAccessDenied(Exception):
    """Raised when a caller acts on a conversation owned by a different user."""


class ConversationAlreadyExists(Exception):
    """Raised when a caller asks to create a conversation id someone else owns."""


class ConversationTokenBudgetExceeded(Exception):
    """Raised when a conversation's lifetime token budget is exhausted."""


class ConversationLinkRefused(Exception):
    """Raised when a visitor's conversations cannot be handed to the caller."""


@dataclass(frozen=True)
class PreparedConversationTurn:
    """A persisted user turn plus the prior structured model context."""

    session_id: str
    run_id: str
    user_id: str
    message: str
    history: tuple[ChatMessage, ...]


class ConversationService:
    def __init__(
        self,
        engine: Engine,
        repository: Repository,
        *,
        window: int = 10,
        max_chars: int | None = None,
        max_tokens: int | None = None,
        snapshot_ttl_seconds: int | None = 86_400,
        system_name: str | None = None,
        config_path: str | None = None,
    ) -> None:
        self._engine = engine
        self._repository = repository
        self._window = window
        self._max_chars = max_chars
        self._max_tokens = max_tokens
        self._snapshot_ttl_seconds = snapshot_ttl_seconds
        self._system_name = system_name
        self._config_path = config_path

    async def create(self, principal: Principal, *, session_id: str | None = None) -> str:
        """Create a conversation, or return the caller's own existing one.

        A caller-supplied `session_id` may already exist. Handing it back to its
        owner keeps creation idempotent; handing it to anyone else would be a
        takeover.
        """
        await self._register(principal)
        session = await self._repository.create_session(
            session_id,
            user_id=principal.user_id,
            system_name=self._system_name,
            config_path=self._config_path,
        )
        # Checked after the write, not before: a check first lets two callers
        # racing for one id both pass it.
        if session.user_id != principal.user_id:
            raise ConversationAlreadyExists(session.session_id)
        return session.session_id

    async def link_anonymous(self, visitor: Principal, principal: Principal) -> int:
        """Hand a visitor's conversations to the account they just signed into.

        One direction only: a signed-in user adopts a visitor's history, never
        the reverse, or one browser could push conversations onto another.
        """
        if principal.is_anonymous:
            raise ConversationLinkRefused(visitor.user_id)
        await self._register(principal)
        return await self._repository.link_anonymous_user(visitor.user_id, principal.user_id)

    async def history(self, conversation_id: str, principal: Principal) -> list[Message]:
        await self._authorize(conversation_id, principal)
        return await self._repository.list_messages(conversation_id)

    async def usage(self, conversation_id: str, principal: Principal) -> TokenBudgetUsage:
        await self._authorize(conversation_id, principal)
        used = await self._repository.get_token_usage(conversation_id)
        return TokenBudgetUsage.from_totals(used, self._max_tokens)

    async def list_conversations(
        self, principal: Principal, *, limit: int = 50, cursor: str | None = None
    ) -> PaginatedSessions:
        return await self._repository.list_sessions(principal.user_id, limit=limit, cursor=cursor)

    async def send(self, conversation_id: str, text: str, principal: Principal) -> RunResult:
        turn = await self.prepare_turn(conversation_id, text, principal)
        result = await self._engine.run(
            turn.message,
            history=turn.history,
            context=RunContext(
                run_id=turn.run_id,
                conversation_id=turn.session_id,
                user_id=turn.user_id,
            ),
        )
        if result.pending_approval is None:
            await self.complete_turn(turn, result)
        return result

    async def prepare_turn(
        self,
        conversation_id: str,
        text: str,
        principal: Principal,
    ) -> PreparedConversationTurn:
        """Persist a user message and return its isolated prior model context."""
        await self._authorize(conversation_id, principal)
        user_id = principal.user_id
        await self._register(principal)

        if self._max_tokens is not None:
            used = await self._repository.get_token_usage(conversation_id)
            if used >= self._max_tokens:
                raise ConversationTokenBudgetExceeded(conversation_id)

        # Load prior history before saving the new message, or it gets inlined twice.
        prior_context = await self._repository.get_context(
            conversation_id,
            max_messages=self._window,
            max_chars=self._max_chars,
        )
        if not prior_context.messages:
            await self._repository.rename_session(conversation_id, thread_title(text))
        run_id = uuid.uuid4().hex
        now = datetime.now(UTC)
        await self._repository.append_message(
            ConversationMessage(
                message_id=uuid.uuid4().hex,
                session_id=conversation_id,
                run_id=run_id,
                user_id=user_id,
                role=Role.USER,
                content=text,
                created_at=now,
            ),
            snapshot_ttl_seconds=self._snapshot_ttl_seconds,
        )

        return PreparedConversationTurn(
            session_id=conversation_id,
            run_id=run_id,
            user_id=user_id,
            message=text,
            history=build_history(prior_context.messages, self._window),
        )

    async def complete_turn(
        self,
        turn: PreparedConversationTurn,
        result: RunResult,
    ) -> None:
        """Persist the final assistant response after any approval resumes finish."""
        if result.pending_approval is not None:
            raise ValueError("cannot complete a conversation turn while approval is pending")
        await self._persist_assistant_turn(
            turn,
            content=result.answer,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            visited=result.visited,
            used_tools=result.used_tools,
        )

    async def stream(
        self, conversation_id: str, text: str, principal: Principal
    ) -> AsyncIterator[RunStreamEvent]:
        turn = await self.prepare_turn(conversation_id, text, principal)

        final: RunStreamEvent | None = None
        try:
            async for event in self._engine.stream(
                turn.message,
                history=turn.history,
                context=RunContext(
                    run_id=turn.run_id,
                    conversation_id=turn.session_id,
                    user_id=turn.user_id,
                ),
            ):
                if event.type == "final":
                    final = event

                yield event
        finally:
            if final is not None:
                await self._persist_assistant_turn(
                    turn,
                    content=final.content or "",
                    input_tokens=final.input_tokens,
                    output_tokens=final.output_tokens,
                    visited=final.route or (),
                    used_tools=final.used_tools,
                )

    async def _persist_assistant_turn(
        self,
        turn: PreparedConversationTurn,
        *,
        content: str,
        input_tokens: int | None,
        output_tokens: int | None,
        visited: Sequence[str],
        used_tools: Sequence[ToolUsageRecord],
    ) -> None:
        """Persist one normalized final assistant response."""
        await self._repository.append_message(
            ConversationMessage(
                message_id=uuid.uuid4().hex,
                session_id=turn.session_id,
                run_id=turn.run_id,
                user_id=turn.user_id,
                role=Role.ASSISTANT,
                content=content,
                created_at=datetime.now(UTC),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                metadata={
                    "visited": list(visited),
                    "used_tools": [dataclasses.asdict(tool) for tool in used_tools],
                },
            ),
            snapshot_ttl_seconds=self._snapshot_ttl_seconds,
        )

    async def _register(self, principal: Principal) -> None:
        await self._repository.upsert_user(
            principal.user_id,
            external_user_id=principal.external_id,
            display_name=principal.display_name,
        )

    async def _require(self, conversation_id: str) -> ConversationSession:
        session = await self._repository.get_session(conversation_id)
        if session is None:
            raise ConversationNotFound(conversation_id)
        return session

    async def _authorize(self, conversation_id: str, principal: Principal) -> ConversationSession:
        """Resolve a conversation the caller owns.

        A turn runs as the session owner and hooks and tools authorize on
        `RunContext.user_id`, so knowing the conversation id must not be enough
        to reach it.
        """
        session = await self._require(conversation_id)
        if session.user_id != principal.user_id:
            raise ConversationAccessDenied(conversation_id)
        return session
