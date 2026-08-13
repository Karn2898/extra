"""Is this JWT authentic and still valid? Claims in, claims out — turning them
into a `Principal` is the resolver's job, so neither module knows both."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from agent_manager.infrastructure.auth.keys import HMAC_SHA256, KeySource

CLOCK_SKEW_LEEWAY_SECONDS = 60
EXPIRY_CLAIM = "exp"
ISSUED_AT_CLAIM = "iat"
# The claim `encode_token` names its subject with. Verification never requires
# it: which claim carries identity is per-host configuration (`ClaimMapping`),
# not something `TokenVerifier` should know or enforce.
SUBJECT_CLAIM = "sub"


class TokenError(Exception):
    """Raised when a token is missing, malformed, expired, or not ours."""


@dataclass(frozen=True)
class TokenPolicy:
    """Validity rules beyond the signature. A token minted for us is held to
    `max_ttl_seconds`; a host's own session token is not — that lifetime is
    theirs to choose."""

    issuer: str | None = None
    audience: str | None = None
    require_expiry: bool = True
    max_ttl_seconds: int | None = None
    leeway_seconds: int = CLOCK_SKEW_LEEWAY_SECONDS


@dataclass(frozen=True)
class IssuedToken:
    token: str
    expires_at: datetime


class TokenVerifier:
    def __init__(self, key_source: KeySource, policy: TokenPolicy | None = None) -> None:
        self._key_source = key_source
        self._policy = policy or TokenPolicy()

    def verify(self, token: str) -> Mapping[str, Any]:
        policy = self._policy
        try:
            key = self._key_source.key_for(jwt.get_unverified_header(token))
            claims: dict[str, Any] = jwt.decode(
                token,
                key,
                # The explicit allowlist is what rejects `alg: none` and
                # algorithm confusion.
                algorithms=list(self._key_source.algorithms),
                leeway=policy.leeway_seconds,
                issuer=policy.issuer,
                audience=policy.audience,
                options={
                    "require": self._required_claims(),
                    "verify_aud": policy.audience is not None,
                },
            )
        except jwt.PyJWTError as exc:
            raise TokenError(str(exc)) from exc

        self._reject_overlong_lifetime(claims)
        return claims

    def _required_claims(self) -> list[str]:
        required = []
        if self._policy.require_expiry:
            required.append(EXPIRY_CLAIM)
        if self._policy.max_ttl_seconds is not None:
            required.append(ISSUED_AT_CLAIM)
        return required

    def _reject_overlong_lifetime(self, claims: Mapping[str, Any]) -> None:
        """A long-lived token is a long-lived impersonation window."""
        max_ttl = self._policy.max_ttl_seconds
        if max_ttl is None:
            return
        lifetime = int(claims[EXPIRY_CLAIM]) - int(claims[ISSUED_AT_CLAIM])
        if lifetime > max_ttl:
            raise TokenError(f"token lifetime {lifetime}s exceeds the {max_ttl}s maximum")


def encode_token(
    secret: str,
    *,
    subject: str,
    ttl_seconds: int,
    key_id: str | None = None,
    claims: Mapping[str, Any] | None = None,
    algorithm: str = HMAC_SHA256,
) -> IssuedToken:
    """Mint an HMAC token: the passes we issue, and dev tokens."""
    issued_at = datetime.now(UTC)
    expires_at = issued_at + timedelta(seconds=ttl_seconds)
    payload = {
        **(claims or {}),
        SUBJECT_CLAIM: subject,
        ISSUED_AT_CLAIM: issued_at,
        EXPIRY_CLAIM: expires_at,
    }
    headers = {"kid": key_id} if key_id else None
    return IssuedToken(
        token=jwt.encode(payload, secret, algorithm=algorithm, headers=headers),
        expires_at=expires_at,
    )
