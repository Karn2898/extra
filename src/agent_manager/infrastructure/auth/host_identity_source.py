"""Identity source for tokens issued by the host product."""

from __future__ import annotations

from agent_manager.domain.identity import Principal
from agent_manager.infrastructure.auth.claim_mapping import ClaimMapping
from agent_manager.infrastructure.auth.identity_source import IdentitySource
from agent_manager.infrastructure.auth.token_verifier import TokenVerifier


class HostIdentitySource(IdentitySource):
    def __init__(self, verifier: TokenVerifier, claims: ClaimMapping | None = None) -> None:
        self._verifier = verifier
        self._claims = claims or ClaimMapping()

    def resolve(self, token: str) -> Principal:
        return self._claims.to_principal(self._verifier.verify(token))
