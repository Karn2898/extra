"""FastAPI dependencies. The composition root puts collaborators on app.state."""

from __future__ import annotations

from fastapi import HTTPException, Request

from agent_manager.application import ConversationService
from agent_manager.domain import Principal
from agent_manager.infrastructure.auth import IdentityResolver, TokenError

BEARER_PREFIX = "Bearer "
UNAUTHENTICATED_DETAIL = "a verified identity is required"


def get_service(request: Request) -> ConversationService:
    return request.app.state.service


def get_identity_resolver(request: Request) -> IdentityResolver:
    return request.app.state.identity_resolver


def get_principal(request: Request) -> Principal:
    """The proven caller every conversation route authorizes against.

    A bearer token first, then the host's session cookie. Trusting that cookie is
    safe because it only reaches us from the host's own origin: cross-site
    requests cannot read a JSON response, and the widget's `application/json`
    writes are preflighted against a CORS allowlist that denies by default.
    """
    token = _bearer_token(request) or _cookie_token(request)
    if token is None:
        raise HTTPException(status_code=401, detail=UNAUTHENTICATED_DETAIL)
    try:
        return get_identity_resolver(request).resolve(token)
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from None


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if not header.startswith(BEARER_PREFIX):
        return None
    return header.removeprefix(BEARER_PREFIX).strip() or None


def _cookie_token(request: Request) -> str | None:
    cookie_name = request.app.state.settings.agent_auth_cookie
    return request.cookies.get(cookie_name) if cookie_name else None
