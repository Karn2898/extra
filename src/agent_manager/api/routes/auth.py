"""Authentication and anonymous-conversation adoption endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from agent_manager.api.deps import Caller, Identity, Service
from agent_manager.api.errors import as_http_error
from agent_manager.api.schemas import (
    AnonymousPassResponse,
    LinkAnonymousRequest,
    LinkAnonymousResponse,
)
from agent_manager.infrastructure.auth import TokenError

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/auth/anonymous", response_model=AnonymousPassResponse)
async def issue_anonymous_pass(identity: Identity) -> AnonymousPassResponse:
    """The only route without a caller. The pass is signed, so one visitor
    cannot reach another's conversations by guessing an id."""
    issued = identity.resolver.anonymous.issue()
    return AnonymousPassResponse(token=issued.token, expires_at=issued.expires_at)


@router.post("/auth/link", response_model=LinkAnonymousResponse)
async def link_anonymous_conversations(
    body: LinkAnonymousRequest,
    service: Service,
    caller: Caller,
    identity: Identity,
) -> LinkAnonymousResponse:
    """Adopt the conversations a visitor started before signing in.

    Both tokens are verified: a visitor pass proves which conversations, the
    caller's own token proves who is adopting them. Linking happens once, so a
    replayed pass moves nothing.
    """
    try:
        visitor = identity.resolver.anonymous.resolve(body.anonymous_token)
    except TokenError as exc:
        logger.warning("visitor pass verification failed: %s", exc)
        raise HTTPException(status_code=401, detail=str(exc)) from None
    with as_http_error():
        moved = await service.link_anonymous(visitor, caller)
    return LinkAnonymousResponse(conversations_moved=moved)
