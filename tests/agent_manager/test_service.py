"""ConversationService use cases — pure: in-memory repository + stub engine."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from typing import cast

import pytest

from agent_engine.engine.types import ChatMessage, ChatRole
from agent_engine.runtime.hooks.models import RunContext
from agent_engine.runtime.streaming import RunStreamEvent
from agent_manager.application import (
    ConversationAccessDenied,
    ConversationAlreadyExists,
    ConversationLinkRefused,
    ConversationNotFound,
    ConversationService,
)
from agent_manager.domain import Principal, Role
from agent_manager.infrastructure.persistence.memory_repository import MemoryRepository
from tests.agent_manager.conftest import RecordingEngine

ALICE = Principal.external("alice")
BOB = Principal.external("bob")
VISITOR = Principal.anonymous("visitor-1")


class CleanupAfterFinalError(RuntimeError):
    """Distinct failure type used to verify transparent propagation."""


class FinalThenCleanupErrorEngine(RecordingEngine):
    async def stream(
        self,
        message: str,
        *,
        history: Sequence[ChatMessage] = (),
        context: RunContext | None = None,
    ) -> AsyncIterator[RunStreamEvent]:
        yield RunStreamEvent(type="final", content="persisted", route=("agent",))
        raise CleanupAfterFinalError("cleanup after final")


def _service(window: int = 10) -> tuple[ConversationService, RecordingEngine]:
    engine = RecordingEngine()
    return ConversationService(engine, MemoryRepository(), window=window), engine


async def test_send_persists_user_and_assistant_in_order() -> None:
    service, _ = _service()
    cid = await service.create(ALICE)
    await service.send(cid, "hello", ALICE)

    msgs = await service.history(cid, ALICE)
    assert [(m.role, m.content) for m in msgs] == [
        (Role.USER, "hello"),
        (Role.ASSISTANT, "answer:hello"),
    ]


async def test_stream_persists_final_before_propagating_late_engine_failure() -> None:
    repository = MemoryRepository()
    service = ConversationService(FinalThenCleanupErrorEngine(), repository)
    cid = await service.create(ALICE)

    with pytest.raises(CleanupAfterFinalError, match="cleanup after final"):
        async for _event in service.stream(cid, "hello", ALICE):
            pass

    messages = await service.history(cid, ALICE)
    assert [(message.role, message.content) for message in messages] == [
        (Role.USER, "hello"),
        (Role.ASSISTANT, "persisted"),
    ]


async def test_stream_persists_final_when_consumer_closes_generator() -> None:
    repository = MemoryRepository()
    service = ConversationService(FinalThenCleanupErrorEngine(), repository)
    cid = await service.create(ALICE)
    events = cast(AsyncGenerator[RunStreamEvent, None], service.stream(cid, "hello", ALICE))

    final = await events.__anext__()
    assert final.type == "final"
    await events.aclose()

    messages = await service.history(cid, ALICE)
    assert [(message.role, message.content) for message in messages] == [
        (Role.USER, "hello"),
        (Role.ASSISTANT, "persisted"),
    ]


async def test_prior_history_passed_to_engine_as_structured_messages() -> None:
    service, engine = _service()
    cid = await service.create(ALICE)
    await service.send(cid, "turn on kitchen lights", ALICE)
    await service.send(cid, "now turn it off", ALICE)

    assert engine.prompts[0] == "turn on kitchen lights"
    assert engine.prompts[1] == "now turn it off"
    assert engine.histories[0] == ()
    assert engine.histories[1] == (
        ChatMessage(ChatRole.USER, "turn on kitchen lights"),
        ChatMessage(ChatRole.ASSISTANT, "answer:turn on kitchen lights"),
    )


async def test_window_caps_history_sent_to_engine() -> None:
    service, engine = _service(window=2)
    cid = await service.create(ALICE)
    for i in range(4):
        await service.send(cid, f"msg{i}", ALICE)

    assert engine.prompts[-1] == "msg3"
    assert [message.content for message in engine.histories[-1]] == [
        "msg2",
        "answer:msg2",
    ]


async def test_unknown_conversation_raises() -> None:
    service, _ = _service()
    with pytest.raises(ConversationNotFound):
        await service.send("missing", "hi", ALICE)
    with pytest.raises(ConversationNotFound):
        await service.history("missing", ALICE)


async def test_send_uses_stable_session_and_unique_run_id() -> None:
    service, engine = _service()
    cid = await service.create(ALICE, session_id="sess-1")
    await service.send(cid, "first", ALICE)
    await service.send(cid, "second", ALICE)

    contexts = [ctx for ctx in engine.contexts if ctx is not None]
    assert [ctx.conversation_id for ctx in contexts] == ["sess-1", "sess-1"]
    assert [ctx.user_id for ctx in contexts] == [ALICE.user_id, ALICE.user_id]
    assert contexts[0].run_id is not None
    assert contexts[1].run_id is not None
    assert contexts[0].run_id != contexts[1].run_id


async def test_turn_refuses_a_caller_who_does_not_own_the_conversation() -> None:
    """Knowing a conversation id must not confer its owner's identity — the turn
    runs as the owner, and hooks and tools authorize on RunContext.user_id."""
    service, engine = _service()
    cid = await service.create(ALICE, session_id="sess-1")

    with pytest.raises(ConversationAccessDenied):
        await service.send(cid, "hi", BOB)
    with pytest.raises(ConversationAccessDenied):
        await service.send(cid, "hi", VISITOR)

    assert engine.contexts == []
    assert await service.history(cid, ALICE) == []


async def test_reads_of_an_owned_conversation_refuse_other_callers() -> None:
    service, _ = _service()
    cid = await service.create(ALICE, session_id="sess-1")
    await service.send(cid, "hi", ALICE)

    for caller in (BOB, VISITOR):
        with pytest.raises(ConversationAccessDenied):
            await service.history(cid, caller)
        with pytest.raises(ConversationAccessDenied):
            await service.usage(cid, caller)

    assert await service.list_conversations(BOB) == []
    assert await service.list_conversations(VISITOR) == []


async def test_create_refuses_a_session_id_owned_by_someone_else() -> None:
    service, _ = _service()
    await service.create(ALICE, session_id="sess-1")

    with pytest.raises(ConversationAlreadyExists):
        await service.create(BOB, session_id="sess-1")
    with pytest.raises(ConversationAlreadyExists):
        await service.create(VISITOR, session_id="sess-1")

    session = await service._repository.get_session("sess-1")
    assert session is not None
    assert session.user_id == ALICE.user_id


async def test_create_is_idempotent_for_the_owner() -> None:
    """agentctl reuses a --session id across runs, so the owner re-creating is
    the normal path, not an attack."""
    service, _ = _service()
    first = await service.create(ALICE, session_id="sess-1")

    assert await service.create(ALICE, session_id="sess-1") == first


async def test_service_creates_user_and_session_metadata() -> None:
    service, _ = _service()
    cid = await service.create(ALICE, session_id="sess-1")

    assert cid == "sess-1"
    repo = service._repository
    assert await repo.get_user(ALICE.user_id) is not None
    session = await repo.get_session("sess-1")
    assert session is not None
    assert session.user_id == ALICE.user_id


async def test_new_session_receives_no_previous_history() -> None:
    service, engine = _service()
    first = await service.create(ALICE, session_id="session-one")
    await service.send(first, "offer numbered options", ALICE)
    second = await service.create(ALICE, session_id="session-two")

    await service.send(second, "1", ALICE)

    assert engine.prompts[-1] == "1"
    assert engine.histories[-1] == ()


async def test_concurrent_sessions_do_not_leak_history() -> None:
    service, engine = _service()
    first = await service.create(ALICE, session_id="session-one")
    second = await service.create(ALICE, session_id="session-two")
    await service.send(first, "first private context", ALICE)
    await service.send(second, "second private context", ALICE)

    await asyncio.gather(
        service.send(first, "follow up one", ALICE),
        service.send(second, "follow up two", ALICE),
    )

    contexts_and_histories = zip(engine.contexts[-2:], engine.histories[-2:], strict=True)
    history_by_session = {
        context.conversation_id: tuple(message.content for message in history)
        for context, history in contexts_and_histories
        if context is not None
    }
    assert history_by_session["session-one"] == (
        "first private context",
        "answer:first private context",
    )
    assert history_by_session["session-two"] == (
        "second private context",
        "answer:second private context",
    )


async def test_signing_in_moves_a_visitors_conversations_onto_their_account() -> None:
    """A visitor who chats before logging in keeps that history afterwards."""
    service, _ = _service()
    before_login = await service.create(VISITOR, session_id="pre-login")
    await service.send(before_login, "how much does it cost?", VISITOR)

    moved = await service.link_anonymous(VISITOR, ALICE)

    assert moved == 1
    assert [s.session_id for s in await service.list_conversations(ALICE)] == ["pre-login"]
    assert await service.list_conversations(VISITOR) == []
    assert [m.content for m in await service.history(before_login, ALICE)] == [
        "how much does it cost?",
        "answer:how much does it cost?",
    ]


async def test_a_visitor_pass_can_only_be_adopted_once() -> None:
    """Replaying a pass must not attach the same chats to a second account."""
    service, _ = _service()
    await service.create(VISITOR, session_id="pre-login")

    assert await service.link_anonymous(VISITOR, ALICE) == 1
    assert await service.link_anonymous(VISITOR, BOB) == 0

    assert [s.session_id for s in await service.list_conversations(ALICE)] == ["pre-login"]
    assert await service.list_conversations(BOB) == []


async def test_a_visitor_cannot_adopt_another_visitor() -> None:
    service, _ = _service()
    await service.create(VISITOR, session_id="pre-login")

    with pytest.raises(ConversationLinkRefused):
        await service.link_anonymous(VISITOR, Principal.anonymous("visitor-2"))


async def test_adopting_merges_into_conversations_the_account_already_had() -> None:
    service, _ = _service()
    await service.create(ALICE, session_id="signed-in")
    await service.create(VISITOR, session_id="pre-login")

    await service.link_anonymous(VISITOR, ALICE)

    assert {s.session_id for s in await service.list_conversations(ALICE)} == {
        "signed-in",
        "pre-login",
    }
