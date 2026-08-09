"""HTTP-level regression coverage for the approval endpoints.

``ApprovalDecisionRequest`` declares every field optional, so a bare POST
with no JSON body should be accepted by ``/approve`` and ``/reject`` exactly
like ``{}`` is. Uses a deterministic fake chat model (no LLM/network) wired
through ``create_app`` via a real, minimal ``agents.yaml``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.messages.tool import ToolCall as LCToolCall

from agent_engine.api.app import create_app


class FakeChatModel:
    """Calls a fixed tool once, then answers from its result."""

    def __init__(self, tool_names: list[str] | None = None) -> None:
        self._tool_names = tool_names or []

    def bind_tools(self, tools: list[Any]) -> FakeChatModel:
        return FakeChatModel([t.name for t in tools])

    async def ainvoke(self, messages: list[Any]) -> AIMessage:
        return self._respond(messages)

    async def astream(self, messages: list[Any]) -> AsyncIterator[AIMessage]:
        yield self._respond(messages)

    def _respond(self, messages: list[Any]) -> AIMessage:
        if self._tool_names and not any(isinstance(m, ToolMessage) for m in messages):
            input_text = next(
                (str(m.content) for m in messages if isinstance(m, HumanMessage)), "message"
            )
            return AIMessage(
                content="",
                tool_calls=[
                    LCToolCall(
                        name=self._tool_names[0],
                        args={"message": "go"},
                        id=f"call_{input_text}",
                    )
                ],
            )
        for m in reversed(messages):
            if isinstance(m, ToolMessage):
                return AIMessage(content=f"done: {m.content}")
        return AIMessage(content="done")


def _write_config(base_dir: Path) -> Path:
    tools_dir = base_dir / "plugins" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    (tools_dir / "send_email.py").write_text(
        "def send_email(message: str) -> str:\n    return 'sent: ' + message\n",
        encoding="utf-8",
    )

    config_path = base_dir / "agents.yaml"
    config_path.write_text(
        """
system:
  name: Approval Test System

tools:
  send_email:
    description: Send an email.

agents:
  writer:
    description: Writes and sends emails.
    model:
      provider: openai
      name: gpt-4o-mini
    tools: [send_email]

graph:
  writer:
""",
        encoding="utf-8",
    )
    return config_path


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    # ``LangGraphEngine.__init__`` binds its default ``model_factory`` to the
    # real ``build_chat_model`` at class-definition time, so patching that name
    # after import has no effect. Instead, let the real factory construct a
    # genuine (but never-called) ``ChatOpenAI`` instance, and patch its
    # ``bind_tools`` at the class level — that's looked up per-call via the
    # class, not bound early, so it intercepts regardless of construction time.
    from langchain_openai import ChatOpenAI

    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-a-real-credential")
    monkeypatch.setattr(
        ChatOpenAI, "bind_tools", lambda self, tools, **_: FakeChatModel([t.name for t in tools])
    )

    config_path = _write_config(tmp_path)
    app = create_app(str(config_path))
    with TestClient(app) as test_client:
        yield test_client


def _trigger_pending_approval(client: TestClient) -> tuple[str, str]:
    response = client.post("/invoke", json={"message": "hi"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending_approval"
    pending = body["pending_approval"]
    return body["run_id"], pending["approval_id"]


def test_approve_with_empty_json_body_succeeds(client: TestClient) -> None:
    run_id, approval_id = _trigger_pending_approval(client)

    response = client.post(f"/runs/{run_id}/approvals/{approval_id}/approve", json={})

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_approve_with_no_body_at_all_succeeds(client: TestClient) -> None:
    run_id, approval_id = _trigger_pending_approval(client)

    response = client.post(f"/runs/{run_id}/approvals/{approval_id}/approve")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_reject_with_no_body_at_all_succeeds(client: TestClient) -> None:
    run_id, approval_id = _trigger_pending_approval(client)

    response = client.post(f"/runs/{run_id}/approvals/{approval_id}/reject")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_decision_endpoint_still_requires_a_body(client: TestClient) -> None:
    run_id, approval_id = _trigger_pending_approval(client)

    response = client.post(f"/runs/{run_id}/approvals/{approval_id}/decision")

    assert response.status_code == 422
