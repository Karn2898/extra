"""HTTP routes via TestClient — stub engine + in-memory repo, no DB or LLM."""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator, Sequence

import pytest
from fastapi.testclient import TestClient

from agent_engine.engine.engine import Engine
from agent_engine.engine.types import ChatMessage, RunResult
from agent_engine.runtime.hooks.models import RunContext
from agent_engine.runtime.streaming import RunStreamEvent
from agent_engine.runtime.tool_models import ToolUsageRecord
from agent_manager.application import ConversationService
from agent_manager.config import AuthMode
from agent_manager.domain import TokenBudgetUsage, thread_title
from agent_manager.infrastructure.persistence.memory_repository import MemoryRepository
from tests.agent_manager.conftest import (
    HOST_COOKIE,
    RecordingEngine,
    bearer,
    build_test_app,
    session_cookie,
)


@pytest.fixture
def client() -> TestClient:
    """Authenticated by default; tests that care about identity pass their own."""
    app = build_test_app(ConversationService(RecordingEngine(), MemoryRepository()))
    return TestClient(app, headers=bearer("default-user"))


def test_create_send_history_round_trip(client: TestClient) -> None:
    cid = client.post("/conversations").json()["conversation_id"]

    sent = client.post(f"/conversations/{cid}/messages", json={"message": "hello"})
    assert sent.status_code == 200
    assert sent.json()["answer"] == "answer:hello"

    msgs = client.get(f"/conversations/{cid}/messages").json()
    assert [(m["role"], m["content"]) for m in msgs] == [
        ("user", "hello"),
        ("assistant", "answer:hello"),
    ]


def test_list_conversations_returns_titled_threads_scoped_to_user(client: TestClient) -> None:
    u1 = bearer("u1")
    a = client.post("/conversations", headers=u1).json()["conversation_id"]
    client.post(f"/conversations/{a}/messages", json={"message": "first thread"}, headers=u1)
    b = client.post("/conversations", headers=u1).json()["conversation_id"]
    client.post(f"/conversations/{b}/messages", json={"message": "second thread"}, headers=u1)

    threads = client.get("/conversations", headers=u1).json()
    assert {t["conversation_id"]: t["title"] for t in threads} == {
        a: "first thread",
        b: "second thread",
    }
    assert client.get("/conversations", headers=bearer("u2")).json() == []


def test_another_caller_cannot_touch_a_conversation_it_does_not_own(client: TestClient) -> None:
    """The conversation id is not a credential — every route checks the caller."""
    u1 = bearer("u1")
    cid = client.post("/conversations", headers=u1).json()["conversation_id"]
    client.post(f"/conversations/{cid}/messages", json={"message": "secret"}, headers=u1)

    u2 = bearer("u2")
    assert client.get(f"/conversations/{cid}/messages", headers=u2).status_code == 403
    assert client.get(f"/conversations/{cid}/usage", headers=u2).status_code == 403
    send = client.post(f"/conversations/{cid}/messages", json={"message": "hi"}, headers=u2)
    assert send.status_code == 403
    stream = client.post(
        f"/conversations/{cid}/messages/stream", json={"message": "hi"}, headers=u2
    )
    assert stream.status_code == 403


def test_create_cannot_claim_a_conversation_id_owned_by_another_caller(
    client: TestClient,
) -> None:
    alice = bearer("alice")
    client.post("/conversations", json={"session_id": "sess-1"}, headers=alice)
    client.post("/conversations/sess-1/messages", json={"message": "secret"}, headers=alice)

    bob = bearer("bob")
    taken = client.post("/conversations", json={"session_id": "sess-1"}, headers=bob)
    assert taken.status_code == 409
    assert client.get("/conversations/sess-1/messages", headers=bob).status_code == 403

    assert client.get("/conversations", headers=alice).json()[0]["conversation_id"] == "sess-1"


@pytest.fixture
def unauthenticated() -> TestClient:
    return TestClient(build_test_app(ConversationService(RecordingEngine(), MemoryRepository())))


def test_every_conversation_route_needs_a_proven_caller(unauthenticated: TestClient) -> None:
    """Identity is the gate: without a token there is nothing to authorize."""
    assert unauthenticated.post("/conversations").status_code == 401
    assert unauthenticated.get("/conversations").status_code == 401
    assert unauthenticated.get("/conversations/sess-1/messages").status_code == 401
    assert unauthenticated.get("/conversations/sess-1/usage").status_code == 401
    send = unauthenticated.post("/conversations/sess-1/messages", json={"message": "hi"})
    assert send.status_code == 401


def test_a_token_signed_with_another_key_is_not_an_identity(unauthenticated: TestClient) -> None:
    """Asserting a user id is free; signing it is not."""
    forged = bearer("alice", secret="an-attacker-secret-of-sufficient-length")

    assert unauthenticated.post("/conversations", headers=forged).status_code == 401


def test_a_forged_token_is_logged_server_side(
    unauthenticated: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """The client sees only the generic 401; the attempt still leaves a trail."""
    forged = bearer("alice", secret="an-attacker-secret-of-sufficient-length")

    with caplog.at_level("WARNING"):
        unauthenticated.post("/conversations", headers=forged)

    assert "token verification failed" in caplog.text


def test_the_host_session_cookie_authenticates_a_same_origin_deployment() -> None:
    """The zero-host-code path: proxied under the host's origin, its own cookie
    arrives on our requests and we verify it with the host's own secret."""
    app = build_test_app(
        ConversationService(RecordingEngine(), MemoryRepository()),
        agent_auth_mode=AuthMode.HOST_TOKEN,
        agent_auth_cookie=HOST_COOKIE,
        agent_auth_claim_user_id="id",
    )
    dana = TestClient(app, cookies=session_cookie("u_8412", id="u_8412"))

    cid = dana.post("/conversations").json()["conversation_id"]
    dana.post(f"/conversations/{cid}/messages", json={"message": "hi"})

    assert [t["conversation_id"] for t in dana.get("/conversations").json()] == [cid]
    assert TestClient(app).get(f"/conversations/{cid}/messages").status_code == 401


def test_a_visitor_pass_is_an_identity_of_its_own(unauthenticated: TestClient) -> None:
    """Products with no login still get isolation: passes are signed, not guessed."""
    client = unauthenticated
    first = client.post("/auth/anonymous").json()["token"]
    second = client.post("/auth/anonymous").json()["token"]
    visitor = {"Authorization": f"Bearer {first}"}
    other_visitor = {"Authorization": f"Bearer {second}"}

    cid = client.post("/conversations", headers=visitor).json()["conversation_id"]
    client.post(f"/conversations/{cid}/messages", json={"message": "hi"}, headers=visitor)

    assert client.get(f"/conversations/{cid}/messages", headers=visitor).status_code == 200
    assert client.get(f"/conversations/{cid}/messages", headers=other_visitor).status_code == 403
    assert client.get("/conversations", headers=other_visitor).json() == []


def test_signing_in_adopts_the_conversations_a_visitor_already_started() -> None:
    """The whole point: a pre-login chat is still there after logging in."""
    app = build_test_app(ConversationService(RecordingEngine(), MemoryRepository()))
    client = TestClient(app)
    pass_token = client.post("/auth/anonymous").json()["token"]
    visitor = {"Authorization": f"Bearer {pass_token}"}
    cid = client.post("/conversations", headers=visitor).json()["conversation_id"]
    client.post(f"/conversations/{cid}/messages", json={"message": "hi"}, headers=visitor)

    alice = bearer("alice")
    linked = client.post("/auth/link", json={"anonymous_token": pass_token}, headers=alice)

    assert linked.json() == {"conversations_moved": 1}
    assert [t["conversation_id"] for t in client.get("/conversations", headers=alice).json()] == [
        cid
    ]
    assert client.get(f"/conversations/{cid}/messages", headers=alice).status_code == 200
    assert client.get(f"/conversations/{cid}/messages", headers=visitor).status_code == 403


def test_linking_refuses_a_pass_that_is_not_ours_or_already_spent() -> None:
    app = build_test_app(ConversationService(RecordingEngine(), MemoryRepository()))
    client = TestClient(app)
    pass_token = client.post("/auth/anonymous").json()["token"]

    forged = client.post(
        "/auth/link", json={"anonymous_token": "not-a-token"}, headers=bearer("alice")
    )
    assert forged.status_code == 401

    client.post("/auth/link", json={"anonymous_token": pass_token}, headers=bearer("alice"))
    replayed = client.post(
        "/auth/link", json={"anonymous_token": pass_token}, headers=bearer("bob")
    )
    assert replayed.json() == {"conversations_moved": 0}

    visitor = {"Authorization": f"Bearer {client.post('/auth/anonymous').json()['token']}"}
    assert (
        client.post("/auth/link", json={"anonymous_token": pass_token}, headers=visitor).status_code
        == 403
    )


def test_thread_title_collapses_whitespace_and_truncates() -> None:
    assert thread_title("  hi   there  ") == "hi there"
    assert thread_title("") == "New chat"
    truncated = thread_title("x" * 60)
    assert len(truncated) == 48 and truncated.endswith("…")


def test_unknown_conversation_returns_404(client: TestClient) -> None:
    assert client.get("/conversations/nope/messages").status_code == 404
    assert client.post("/conversations/nope/messages", json={"message": "x"}).status_code == 404
    assert client.get("/conversations/nope/usage").status_code == 404


def test_usage_reports_null_budget_when_unset(client: TestClient) -> None:
    cid = client.post("/conversations").json()["conversation_id"]
    assert client.get(f"/conversations/{cid}/usage").json() == {
        "used_tokens": 0,
        "max_tokens": None,
        "percent": 0.0,
        "severity": "normal",
    }


def test_usage_reports_cumulative_tokens_and_severity_against_budget() -> None:
    class TokenEngine(RecordingEngine):
        async def run(
            self,
            message: str,
            *,
            history: Sequence[ChatMessage] = (),
            context: RunContext | None = None,
        ) -> RunResult:
            return RunResult(
                system_name="stub",
                visited=["agent"],
                answer="ok",
                input_tokens=600,
                output_tokens=100,
            )

    client = TestClient(
        build_test_app(ConversationService(TokenEngine(), MemoryRepository(), max_tokens=1000)),
        headers=bearer("default-user"),
    )

    cid = client.post("/conversations").json()["conversation_id"]
    client.post(f"/conversations/{cid}/messages", json={"message": "hi"})

    body = client.get(f"/conversations/{cid}/usage").json()
    assert body["used_tokens"] == 700
    assert body["max_tokens"] == 1000
    assert body["percent"] == pytest.approx(70.0)
    assert body["severity"] == "warning"


def test_token_budget_severity_thresholds() -> None:
    assert TokenBudgetUsage.from_totals(0, None).severity == "normal"
    assert TokenBudgetUsage.from_totals(640, 1000).severity == "normal"
    # Both thresholds are inclusive: exactly 65% warns, exactly 85% is critical.
    assert TokenBudgetUsage.from_totals(650, 1000).severity == "warning"
    assert TokenBudgetUsage.from_totals(849, 1000).severity == "warning"
    assert TokenBudgetUsage.from_totals(850, 1000).severity == "critical"
    assert TokenBudgetUsage.from_totals(5000, 1000).percent == 100.0


class _SubAgentEngine(Engine):
    """Stub that mimics a parent orchestrator routing to a sub-agent.

    The route visits the root orchestrator and then a sub-agent path. Lets us
    assert the real conversation API surfaces sub-agent participation without an
    LLM.
    """

    async def build(self, _spec: object) -> None: ...

    async def run(
        self,
        message: str,
        *,
        history: Sequence[ChatMessage] = (),
        context: RunContext | None = None,
    ) -> RunResult:
        return RunResult(
            system_name="Knowledge Assistant",
            visited=["knowledge_router", "knowledge_router/documentation_agent"],
            answer="The available document tags are: finance, legal, hr.",
        )

    async def stream(
        self,
        message: str,
        *,
        history: Sequence[ChatMessage] = (),
        context: RunContext | None = None,
    ) -> AsyncIterator[RunStreamEvent]:
        yield RunStreamEvent(type="final", content="unused")


class _FinalThenCleanupErrorEngine(Engine):
    async def build(self, _spec: object) -> None: ...

    async def run(
        self,
        message: str,
        *,
        history: Sequence[ChatMessage] = (),
        context: RunContext | None = None,
    ) -> RunResult:
        raise RuntimeError("private run failure")

    async def stream(
        self,
        message: str,
        *,
        history: Sequence[ChatMessage] = (),
        context: RunContext | None = None,
    ) -> AsyncIterator[RunStreamEvent]:
        yield RunStreamEvent(type="answer_delta", content="done")
        yield RunStreamEvent(type="final", content="done", route=("agent",))
        raise RuntimeError("cleanup after final")


def test_send_surfaces_sub_agent_in_visited_without_mocking() -> None:
    """End-to-end through the real routes + service: the response exposes the
    sub-agent routing path (the evidence the demo page renders)."""
    client = TestClient(
        build_test_app(ConversationService(_SubAgentEngine(), MemoryRepository())),
        headers=bearer("default-user"),
    )

    cid = client.post("/conversations").json()["conversation_id"]
    body = client.post(f"/conversations/{cid}/messages", json={"message": "tags?"}).json()

    assert body["visited"] == ["knowledge_router", "knowledge_router/documentation_agent"]
    assert any("/" in hop for hop in body["visited"]), "expected a sub-agent hop"
    assert "finance" in body["answer"]


def test_stream_surfaces_sse_events_and_persists_final_answer(client: TestClient) -> None:
    cid = client.post("/conversations").json()["conversation_id"]

    with client.stream(
        "POST", f"/conversations/{cid}/messages/stream", json={"message": "hello"}
    ) as response:
        text = "".join(response.iter_text())

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert 'event: answer_delta\ndata: {"type": "answer_delta", "content": "x"}' in text
    assert 'event: final\ndata: {"type": "final", "content": "answer:hello"' in text
    assert "event: done\ndata: [DONE]" in text

    messages = client.get(f"/conversations/{cid}/messages").json()
    assert [(m["role"], m["content"]) for m in messages] == [
        ("user", "hello"),
        ("assistant", "answer:hello"),
    ]


def test_stream_sanitizes_late_engine_error_and_persists_final_answer(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The engine's own generator failing after `final` is a real failure: it
    is logged server-side and reaches the client only as a generic error."""
    client = TestClient(
        build_test_app(ConversationService(_FinalThenCleanupErrorEngine(), MemoryRepository())),
        headers=bearer("default-user"),
    )
    cid = client.post("/conversations").json()["conversation_id"]

    with client.stream(
        "POST", f"/conversations/{cid}/messages/stream", json={"message": "x"}
    ) as response:
        text = "".join(response.iter_text())

    assert response.status_code == 200
    assert 'event: final\ndata: {"type": "final", "content": "done", "route": ["agent"]}' in text
    assert 'event: error\ndata: {"type": "error", "error": "Internal server error"}' in text
    assert "cleanup after final" not in text
    assert "event: done\ndata: [DONE]" in text
    assert "cleanup after final" in caplog.text
    messages = client.get(f"/conversations/{cid}/messages").json()
    assert [(m["role"], m["content"]) for m in messages] == [
        ("user", "x"),
        ("assistant", "done"),
    ]


def test_send_sanitizes_engine_failure() -> None:
    client = TestClient(
        build_test_app(ConversationService(_FinalThenCleanupErrorEngine(), MemoryRepository())),
        headers=bearer("default-user"),
    )
    cid = client.post("/conversations").json()["conversation_id"]

    response = client.post(f"/conversations/{cid}/messages", json={"message": "x"})

    assert response.status_code == 500
    assert response.json()["detail"] == "Internal server error"
    assert "private run failure" not in response.text


def test_create_accepts_a_stable_session_id_owned_by_the_caller(client: TestClient) -> None:
    u1 = bearer("u1")
    created = client.post("/conversations", json={"session_id": "sess-1"}, headers=u1).json()
    assert created["conversation_id"] == "sess-1"
    assert created["session_id"] == "sess-1"

    sent = client.post("/conversations/sess-1/messages", json={"message": "hello"}, headers=u1)

    assert sent.status_code == 200


class _BudgetEngine(RecordingEngine):
    async def run(
        self,
        message: str,
        *,
        history: Sequence[ChatMessage] = (),
        context: RunContext | None = None,
    ) -> RunResult:
        res = await super().run(message, history=history, context=context)
        return dataclasses.replace(res, input_tokens=5, output_tokens=5)


def test_send_returns_429_when_token_budget_exceeded() -> None:
    """send_message returns 429 when the conversation token budget is exhausted."""
    service = ConversationService(_BudgetEngine(), MemoryRepository(), max_tokens=1)
    client = TestClient(build_test_app(service), headers=bearer("default-user"))

    cid = client.post("/conversations").json()["conversation_id"]
    client.post(f"/conversations/{cid}/messages", json={"message": "first"})
    response = client.post(f"/conversations/{cid}/messages", json={"message": "second"})

    assert response.status_code == 429
    detail = response.json()["detail"]
    assert detail["error_type"] == "context_limit_exceeded"
    assert (
        detail["message"]
        == "This conversation has reached its context limit. Start a new chat to continue."
    )


def test_stream_returns_429_when_token_budget_exceeded() -> None:
    """stream_message returns 429 when the conversation token budget is exhausted."""
    service = ConversationService(_BudgetEngine(), MemoryRepository(), max_tokens=1)
    client = TestClient(build_test_app(service), headers=bearer("default-user"))

    cid = client.post("/conversations").json()["conversation_id"]
    client.post(f"/conversations/{cid}/messages", json={"message": "first"})
    response = client.post(f"/conversations/{cid}/messages/stream", json={"message": "second"})

    assert response.status_code == 429
    detail = response.json()["detail"]
    assert detail["error_type"] == "context_limit_exceeded"
    assert (
        detail["message"]
        == "This conversation has reached its context limit. Start a new chat to continue."
    )


class _ToolErrorEngine(RecordingEngine):
    async def run(
        self,
        message: str,
        *,
        history: Sequence[ChatMessage] = (),
        context: RunContext | None = None,
    ) -> RunResult:
        res = await super().run(message, history=history, context=context)
        err_msg = (
            "HTTPConnectionPool(host='localhost', port=3000): "
            "Max retries exceeded with url: /api/v1/auths/add"
        )
        tool_err = ToolUsageRecord(
            name="add_new_user",
            provider="local",
            status="failed",
            error=err_msg,
        )
        return dataclasses.replace(res, used_tools=(tool_err,))

    async def stream(
        self,
        message: str,
        *,
        history: Sequence[ChatMessage] = (),
        context: RunContext | None = None,
    ) -> AsyncIterator[RunStreamEvent]:
        err_msg = (
            "HTTPConnectionPool(host='localhost', port=3000): "
            "Max retries exceeded with url: /api/v1/auths/add"
        )
        tool_err = ToolUsageRecord(
            name="add_new_user",
            provider="local",
            status="failed",
            error=err_msg,
        )
        yield RunStreamEvent(type="final", content="done", used_tools=(tool_err,))


def test_tool_error_text_is_sanitized_in_send_message() -> None:
    """Raw tool exception details must be sanitized to generic text in API responses."""

    service = ConversationService(_ToolErrorEngine(), MemoryRepository())
    client = TestClient(build_test_app(service), headers=bearer("default-user"))

    cid = client.post("/conversations").json()["conversation_id"]
    response = client.post(f"/conversations/{cid}/messages", json={"message": "trigger tool"})

    assert response.status_code == 200
    used_tools = response.json()["used_tools"]
    assert len(used_tools) == 1
    assert used_tools[0]["error"] == "Tool execution failed"
    assert "localhost" not in used_tools[0]["error"]


def test_tool_error_text_is_sanitized_in_stream_message() -> None:
    """Raw tool exception details must be sanitized to generic text in stream SSE events."""
    service = ConversationService(_ToolErrorEngine(), MemoryRepository())
    client = TestClient(build_test_app(service), headers=bearer("default-user"))

    cid = client.post("/conversations").json()["conversation_id"]
    url = f"/conversations/{cid}/messages/stream"
    response = client.post(url, json={"message": "trigger tool"})

    assert response.status_code == 200
    assert "Tool execution failed" in response.text
    assert "localhost" not in response.text
