"""Process-local session-approval repository."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

from agent_engine.approvals.invocation import (
    SessionApprovalGrant,
    SessionApprovalKey,
    SessionApprovalScope,
)
from agent_engine.approvals.session_approval_repository import SessionApprovalRepository


class InMemorySessionApprovalRepository(SessionApprovalRepository):
    """Async-safe session permissions held for the repository lifetime."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._grants: dict[SessionApprovalKey, SessionApprovalGrant] = {}
        self._lock = asyncio.Lock()
        self._clock = clock or (lambda: datetime.now(UTC))

    async def is_allowed(self, key: SessionApprovalKey) -> bool:
        async with self._lock:
            grant = self._grants.get(key)
            if grant is None:
                return False
            if grant.expires_at is not None and grant.expires_at <= self._clock():
                self._grants.pop(key, None)
                return False
            return True

    async def allow(
        self, key: SessionApprovalKey, *, grant: SessionApprovalGrant | None = None
    ) -> None:
        async with self._lock:
            self._grants[key] = grant or SessionApprovalGrant()

    async def revoke(self, key: SessionApprovalKey) -> None:
        async with self._lock:
            self._grants.pop(key, None)

    async def clear_session(self, scope: SessionApprovalScope) -> None:
        async with self._lock:
            matching = [key for key in self._grants if key.scope == scope]
            for key in matching:
                self._grants.pop(key, None)

    async def list_session(self, scope: SessionApprovalScope) -> tuple[SessionApprovalKey, ...]:
        """Return active permission keys for safe read-only diagnostics."""
        async with self._lock:
            now = self._clock()
            expired = [
                key
                for key, grant in self._grants.items()
                if grant.expires_at is not None and grant.expires_at <= now
            ]
            for key in expired:
                self._grants.pop(key, None)
            return tuple(sorted((key for key in self._grants if key.scope == scope), key=repr))


# Compatibility name from the first public HITL API.
InMemorySessionApprovalStore = InMemorySessionApprovalRepository
