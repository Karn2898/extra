"""Turning a verified token into the `Principal` a request runs as.

Two issuers exist — the host product and this manager — so each source reads its
own tokens and `IdentityResolver` only picks between them.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import jwt

from agent_manager.domain.identity import Principal
from agent_manager.infrastructure.auth.keys import StaticSecretKeySource
from agent_manager.infrastructure.auth.tokens import (
    SUBJECT_CLAIM,
    IssuedToken,
    TokenError,
    TokenVerifier,
    encode_token,
)

ANONYMOUS_KEY_ID = "agent-chat-anonymous"
ROLE_SEPARATORS = re.compile(r"[,;\s]+")


class IdentitySource(Protocol):
    """Reads the tokens issued by one party."""

    def resolve(self, token: str) -> Principal: ...


@dataclass(frozen=True)
class ClaimMapping:
    """Which claim carries each identity fact. Data, not code, because hosts
    disagree: Open WebUI puts the user id in `id`, an OIDC provider in `sub`."""

    user_id: str = SUBJECT_CLAIM
    email: str = "email"
    display_name: str = "name"
    roles: str = "roles"
    organization_id: str = "org_id"

    def to_principal(self, claims: Mapping[str, Any]) -> Principal:
        external_id = claims.get(self.user_id)
        if not isinstance(external_id, str) or not external_id.strip():
            raise TokenError(f"token carries no usable {self.user_id!r} claim")
        return Principal.external(
            external_id,
            email=_text(claims.get(self.email)),
            display_name=_text(claims.get(self.display_name)),
            roles=_roles(claims.get(self.roles)),
            organization_id=_text(claims.get(self.organization_id)),
            claims=claims,
        )


class HostIdentitySource:
    """Reads the host product's tokens, whatever shape their claims take."""

    def __init__(self, verifier: TokenVerifier, claims: ClaimMapping | None = None) -> None:
        self._verifier = verifier
        self._claims = claims or ClaimMapping()

    def resolve(self, token: str) -> Principal:
        return self._claims.to_principal(self._verifier.verify(token))


class AnonymousIdentitySource:
    """The visitor passes the manager hands out itself, signed with a
    manager-owned secret: ours to issue, and still working when the host key
    source is asymmetric."""

    def __init__(self, secret: str, *, ttl_seconds: int) -> None:
        self._secret = secret
        self._ttl_seconds = ttl_seconds
        self._verifier = TokenVerifier(StaticSecretKeySource(secret))

    def issue(self) -> IssuedToken:
        return encode_token(
            self._secret,
            subject=uuid.uuid4().hex,
            ttl_seconds=self._ttl_seconds,
            key_id=ANONYMOUS_KEY_ID,
        )

    def resolve(self, token: str) -> Principal:
        return Principal.anonymous(str(self._verifier.verify(token)[SUBJECT_CLAIM]))


class IdentityResolver:
    """Turns a bearer token into a `Principal`, whoever issued it."""

    def __init__(
        self, anonymous: AnonymousIdentitySource, host: IdentitySource | None = None
    ) -> None:
        self._anonymous = anonymous
        self._host = host

    @property
    def anonymous(self) -> AnonymousIdentitySource:
        return self._anonymous

    def resolve(self, token: str) -> Principal:
        if _is_anonymous_pass(token):
            return self._anonymous.resolve(token)
        if self._host is None:
            raise TokenError("no host identity is configured; only visitor passes are accepted")
        return self._host.resolve(token)


def _is_anonymous_pass(token: str) -> bool:
    """Route on `kid` only — the signature check that follows is what decides."""
    try:
        return jwt.get_unverified_header(token).get("kid") == ANONYMOUS_KEY_ID
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _roles(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(role for role in ROLE_SEPARATORS.split(value) if role)
    if isinstance(value, Sequence):
        return tuple(role for role in value if isinstance(role, str) and role.strip())
    return ()
