"""Verify a JWT signature and configured validity policy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import jwt

from agent_manager.infrastructure.auth.key_source import KeySource
from agent_manager.infrastructure.auth.token_claims import EXPIRY_CLAIM, ISSUED_AT_CLAIM
from agent_manager.infrastructure.auth.token_error import TokenError
from agent_manager.infrastructure.auth.token_policy import TokenPolicy


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
                # The allowlist is what rejects `alg: none` and algorithm confusion.
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
