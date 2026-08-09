"""FastAPI dependencies. The composition root puts collaborators on app.state."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request

from agent_manager.application import ConversationService
from agent_manager.domain import Principal
from agent_manager.infrastructure.auth import IdentityResolver, TokenError

BEARER_PREFIX = "Bearer "
UNAUTHENTICATED_DETAIL = "a verified identity is required"


@dataclass(frozen=True)
class CallerIdentity:
    """Everything the HTTP edge needs to name a caller: where a token may be
    found, and who can verify it."""

    resolver: IdentityResolver
    cookie_name: str | None = None


def get_service(request: Request) -> ConversationService:
    return request.app.state.service


def get_caller_identity(request: Request) -> CallerIdentity:
    return request.app.state.caller_identity


def get_principal(request: Request) -> Principal:
    """The proven caller every conversation route authorizes against.

    A bearer token first, then the host's session cookie. Trusting that cookie is
    safe because it only reaches us from the host's own origin: cross-site
    requests cannot read a JSON response, and the widget's `application/json`
    writes are preflighted against a CORS allowlist that denies by default.
    """
    identity = get_caller_identity(request)
    token = _bearer_token(request) or _cookie_token(request, identity.cookie_name)
    if token is None:
        raise HTTPException(status_code=401, detail=UNAUTHENTICATED_DETAIL)
    try:
        return identity.resolver.resolve(token)
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from None


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if not header.startswith(BEARER_PREFIX):
        return None
    return header.removeprefix(BEARER_PREFIX).strip() or None


def _cookie_token(request: Request, cookie_name: str | None) -> str | None:
    return request.cookies.get(cookie_name) if cookie_name else None
