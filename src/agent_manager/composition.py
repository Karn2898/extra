"""Application-level composition: settings in, wired collaborators out."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from agent_engine.approvals.in_memory_session_approval_repository import (
    InMemorySessionApprovalRepository,
)
from agent_engine.approvals.session_approval_repository import SessionApprovalRepository
from agent_engine.runs.in_memory import InMemoryRunRepository
from agent_engine.runs.repository import RunRepository
from agent_engine.tool_usage.in_memory import InMemoryToolUsageRepository
from agent_engine.tool_usage.repository import ToolUsageRepository
from agent_manager.config import AuthMode, Settings
from agent_manager.domain import Repository
from agent_manager.infrastructure.auth.anonymous_identity_source import AnonymousIdentitySource
from agent_manager.infrastructure.auth.claim_mapping import ClaimMapping
from agent_manager.infrastructure.auth.host_identity_source import HostIdentitySource
from agent_manager.infrastructure.auth.identity_resolver import IdentityResolver
from agent_manager.infrastructure.auth.identity_source import IdentitySource
from agent_manager.infrastructure.auth.static_secret_key_source import StaticSecretKeySource
from agent_manager.infrastructure.auth.token_policy import TokenPolicy
from agent_manager.infrastructure.auth.token_verifier import TokenVerifier
from agent_manager.infrastructure.persistence.database import create_db_engine, session_factory
from agent_manager.infrastructure.persistence.memory_repository import MemoryRepository
from agent_manager.infrastructure.persistence.run_repository import SqlRunRepository
from agent_manager.infrastructure.persistence.sql_repository import SqlRepository

logger = logging.getLogger(__name__)

ANONYMOUS_KEY_DERIVATION_INFO = b"agent-chat-anonymous-pass"
EPHEMERAL_SECRET_BYTES = 32


@dataclass(frozen=True)
class ApplicationRepositories:
    conversations: Repository
    session_approvals: SessionApprovalRepository
    tool_usage: ToolUsageRepository
    runs: RunRepository


def build_session_approval_repository() -> SessionApprovalRepository:
    """Create the process-lifetime adapter used by the current application."""
    return InMemorySessionApprovalRepository()


def build_tool_usage_repository() -> ToolUsageRepository:
    """Select the tool-usage backend for this deployment.

    The only place the concrete adapter is named: a distributed deployment
    swaps the implementation here, and no agent, node, or tool-execution code
    changes with it.
    """
    return InMemoryToolUsageRepository()


def build_identity_resolver(settings: Settings) -> IdentityResolver:
    """Assemble the token sources a deployment's auth mode calls for."""
    return IdentityResolver(
        anonymous=AnonymousIdentitySource(
            anonymous_secret(settings),
            ttl_seconds=settings.extra_auth_anonymous_ttl_seconds,
        ),
        host=_build_host_identity_source(settings),
    )


def anonymous_secret(settings: Settings) -> str:
    """Derived from the host secret rather than reused, so a host that can mint
    tokens still cannot mint passes."""
    if settings.extra_auth_anonymous_secret:
        return settings.extra_auth_anonymous_secret
    if settings.extra_auth_secret:
        return hmac.new(
            settings.extra_auth_secret.encode(),
            ANONYMOUS_KEY_DERIVATION_INFO,
            hashlib.sha256,
        ).hexdigest()
    logger.warning(
        "No EXTRA_AUTH_SECRET or EXTRA_AUTH_ANONYMOUS_SECRET set;"
        " signing visitor passes with an ephemeral key that will not survive a restart."
    )
    return secrets.token_hex(EPHEMERAL_SECRET_BYTES)


def _build_host_identity_source(settings: Settings) -> IdentitySource | None:
    if settings.extra_auth_mode is AuthMode.ANONYMOUS:
        return None
    if not settings.extra_auth_secret:
        raise ValueError(f"EXTRA_AUTH_SECRET is required for auth mode {settings.extra_auth_mode}")

    mints_for_us = settings.extra_auth_mode is AuthMode.MINT
    verifier = TokenVerifier(
        StaticSecretKeySource(settings.extra_auth_secret),
        TokenPolicy(
            issuer=settings.extra_auth_issuer,
            audience=settings.extra_auth_audience,
            require_expiry=mints_for_us,
            max_ttl_seconds=settings.extra_auth_max_ttl_seconds if mints_for_us else None,
        ),
    )
    return HostIdentitySource(
        verifier,
        ClaimMapping(
            user_id=settings.extra_auth_claim_user_id,
            email=settings.extra_auth_claim_email,
            display_name=settings.extra_auth_claim_display_name,
            roles=settings.extra_auth_claim_roles,
            organization_id=settings.extra_auth_claim_organization_id,
        ),
    )


@asynccontextmanager
async def application_repositories(
    settings: Settings,
) -> AsyncIterator[ApplicationRepositories]:
    """Own application repositories for one complete process lifespan."""
    database_url = settings.effective_database_url
    session_approvals = build_session_approval_repository()
    tool_usage = build_tool_usage_repository()
    if settings.uses_process_memory:
        yield ApplicationRepositories(
            conversations=MemoryRepository(),
            session_approvals=session_approvals,
            tool_usage=tool_usage,
            runs=InMemoryRunRepository(),
        )
        return

    db_engine = create_db_engine(database_url)
    sessions = session_factory(db_engine)
    try:
        yield ApplicationRepositories(
            conversations=SqlRepository(sessions),
            session_approvals=session_approvals,
            tool_usage=tool_usage,
            runs=SqlRunRepository(sessions),
        )
    finally:
        await db_engine.dispose()
