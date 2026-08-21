"""Validity rules applied after token signature verification."""

from __future__ import annotations

from dataclasses import dataclass

from agent_manager.infrastructure.auth.token_claims import CLOCK_SKEW_LEEWAY_SECONDS


@dataclass(frozen=True)
class TokenPolicy:
    issuer: str | None = None
    audience: str | None = None
    require_expiry: bool = True
    max_ttl_seconds: int | None = None
    leeway_seconds: int = CLOCK_SKEW_LEEWAY_SECONDS
