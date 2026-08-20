"""Select and invoke the correct verified identity source."""

from __future__ import annotations

import jwt

from agent_manager.domain.identity import Principal
from agent_manager.infrastructure.auth.anonymous_identity_source import (
    ANONYMOUS_KEY_ID,
    AnonymousIdentitySource,
)
from agent_manager.infrastructure.auth.identity_source import IdentitySource
from agent_manager.infrastructure.auth.token_error import TokenError


class IdentityResolver:
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

    def names_a_host_user(self, token: str) -> bool:
        try:
            return not _is_anonymous_pass(token)
        except TokenError:
            return False


def _is_anonymous_pass(token: str) -> bool:
    try:
        return jwt.get_unverified_header(token).get("kid") == ANONYMOUS_KEY_ID
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
