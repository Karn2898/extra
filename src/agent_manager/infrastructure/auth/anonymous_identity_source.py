"""Manager-owned visitor-pass identity source."""

from __future__ import annotations

import uuid

from agent_manager.domain.identity import Principal
from agent_manager.infrastructure.auth.identity_source import IdentitySource
from agent_manager.infrastructure.auth.issued_token import IssuedToken
from agent_manager.infrastructure.auth.static_secret_key_source import StaticSecretKeySource
from agent_manager.infrastructure.auth.token_claims import SUBJECT_CLAIM
from agent_manager.infrastructure.auth.token_error import TokenError
from agent_manager.infrastructure.auth.token_issuer import encode_token
from agent_manager.infrastructure.auth.token_verifier import TokenVerifier

ANONYMOUS_KEY_ID = "agent-chat-anonymous"


class AnonymousIdentitySource(IdentitySource):
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
        claims = self._verifier.verify(token)
        subject = claims.get(SUBJECT_CLAIM)
        if not isinstance(subject, str) or not subject:
            raise TokenError("visitor pass carries no usable subject claim")
        return Principal.anonymous(subject)
