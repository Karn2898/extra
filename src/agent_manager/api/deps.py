"""FastAPI dependencies. The composition root puts the service on app.state."""

from __future__ import annotations

from fastapi import Request

from agent_manager.application import ConversationService


def get_service(request: Request) -> ConversationService:
    return request.app.state.service


CALLER_HEADER = "X-Agent-Chat-User"


def get_caller_id(request: Request) -> str | None:
    """The principal every conversation route authorizes against.

    Anonymous by default — the header is whatever the browser generated for
    itself, so it scopes conversations but proves nothing. Being the only source
    of caller identity is what makes it replaceable: a deployment that needs a
    real boundary overrides this dependency with a verified principal, and every
    route tightens with it.
    """
    return request.headers.get(CALLER_HEADER)
