"""Shared test doubles and app wiring for the agent_manager layers."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
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
from agent_manager.infrastructure.auth import HMAC_SHA256, encode_token

AUTH_SECRET = "conftest-signing-secret-of-sufficient-length"
TOKEN_TTL_SECONDS = 300
HOST_COOKIE = "token"


def build_test_app(service: ConversationService, **settings: Any) -> FastAPI:
    """A manager app wired like `create_app`, minus the engine lifespan."""
    app = FastAPI()
    app.state.service = service
    config = Settings.from_values(
        **{"extra_auth_mode": AuthMode.MINT, "extra_auth_secret": AUTH_SECRET, **settings}
    )
    app.state.caller_identity = CallerIdentity(
        resolver=build_identity_resolver(config), cookie_name=config.extra_auth_cookie
    )
    app.include_router(router)
    return app


def bearer(user: str, *, secret: str = AUTH_SECRET, **claims: Any) -> dict[str, str]:
    """Headers carrying a token `build_test_app` accepts as `user`."""
    issued = encode_token(secret, subject=user, ttl_seconds=TOKEN_TTL_SECONDS, claims=claims)
    return {"Authorization": f"Bearer {issued.token}"}


def session_cookie(**claims: Any) -> dict[str, str]:
    """A host's own session token, carrying only the claims the host actually sets.

    Deliberately does not add `sub`: Open WebUI's real tokens name the user in
    `id` and never carry `sub`, and a helper that quietly supplies one lets a
    token shape we cannot actually verify pass as if we could.
    """
    now = datetime.now(UTC)
    payload = {**claims, "iat": now, "exp": now + timedelta(seconds=TOKEN_TTL_SECONDS)}
    return {HOST_COOKIE: jwt.encode(payload, AUTH_SECRET, algorithm=HMAC_SHA256)}


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
