"""FastAPI dependencies. The composition root puts the service on app.state."""

from __future__ import annotations

from fastapi import HTTPException, Request

from agent_manager.application import ConversationService


def get_service(request: Request) -> ConversationService:
    return request.app.state.service


CALLER_HEADER = "X-Agent-Chat-User"
# Matches the conversation_users.user_id column, which the id becomes.
MAX_CALLER_ID = 64


def get_caller_id(request: Request) -> str | None:
    """The principal every conversation route authorizes against.

    Anonymous by default — the header is whatever the browser generated for
    itself, so it scopes conversations but proves nothing. Being the only source
    of caller identity is what makes it replaceable: a deployment that needs a
    real boundary overrides this dependency with a verified principal, and every
    route tightens with it.

    An absent and an empty header both mean anonymous. They have to agree: an
    id of "" would otherwise own conversations that no listing could reach.
    """
    caller_id = request.headers.get(CALLER_HEADER, "").strip()
    if len(caller_id) > MAX_CALLER_ID:
        raise HTTPException(status_code=400, detail=f"{CALLER_HEADER} too long")
    return caller_id or None
