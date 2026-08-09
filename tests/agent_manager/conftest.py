"""Shared test doubles and app wiring for the agent_manager layers."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

from fastapi import FastAPI

from agent_engine.engine.engine import Engine
from agent_engine.engine.types import ChatMessage, RunResult
from agent_engine.runtime.hooks.models import RunContext
from agent_engine.runtime.streaming import RunStreamEvent
from agent_manager.api.deps import CallerIdentity
from agent_manager.api.routes import router
from agent_manager.application import ConversationService
from agent_manager.composition import build_identity_resolver
from agent_manager.config import AuthMode, Settings
from agent_manager.infrastructure.auth import encode_token

AUTH_SECRET = "conftest-signing-secret-of-sufficient-length"
TOKEN_TTL_SECONDS = 300
HOST_COOKIE = "token"


def build_test_app(service: ConversationService, **settings: Any) -> FastAPI:
    """A manager app wired like `create_app`, minus the engine lifespan."""
    app = FastAPI()
    app.state.service = service
    config = Settings.from_values(
        **{"agent_auth_mode": AuthMode.MINT, "agent_auth_secret": AUTH_SECRET, **settings}
    )
    app.state.caller_identity = CallerIdentity(
        resolver=build_identity_resolver(config), cookie_name=config.agent_auth_cookie
    )
    app.include_router(router)
    return app


def bearer(user: str, *, secret: str = AUTH_SECRET, **claims: Any) -> dict[str, str]:
    """Headers carrying a token `build_test_app` accepts as `user`."""
    issued = encode_token(secret, subject=user, ttl_seconds=TOKEN_TTL_SECONDS, claims=claims)
    return {"Authorization": f"Bearer {issued.token}"}


def session_cookie(user: str, **claims: Any) -> dict[str, str]:
    """A host's own session token, as it arrives on a same-origin deployment."""
    issued = encode_token(AUTH_SECRET, subject=user, ttl_seconds=TOKEN_TTL_SECONDS, claims=claims)
    return {HOST_COOKIE: issued.token}


class RecordingEngine(Engine):
    """A stub Engine that records prompts and echoes a canned answer."""

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.histories: list[tuple[ChatMessage, ...]] = []
        self.contexts: list[RunContext | None] = []

    async def build(self, _spec: object) -> None: ...

    async def run(
        self,
        message: str,
        *,
        history: Sequence[ChatMessage] = (),
        context: RunContext | None = None,
    ) -> RunResult:
        self.prompts.append(message)
        self.histories.append(tuple(history))
        self.contexts.append(context)
        return RunResult(system_name="stub", visited=["agent"], answer=f"answer:{message}")

    async def stream(
        self,
        message: str,
        *,
        history: Sequence[ChatMessage] = (),
        context: RunContext | None = None,
    ) -> AsyncIterator[RunStreamEvent]:
        self.prompts.append(message)
        self.histories.append(tuple(history))
        self.contexts.append(context)
        yield RunStreamEvent(type="answer_delta", content="x")
        yield RunStreamEvent(type="final", content=f"answer:{message}", route=("agent",))
