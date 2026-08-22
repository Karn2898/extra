"""Issue the manager's HMAC-signed visitor and development tokens."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from agent_manager.infrastructure.auth.issued_token import IssuedToken
from agent_manager.infrastructure.auth.key_source import HMAC_SHA256
from agent_manager.infrastructure.auth.token_claims import (
    EXPIRY_CLAIM,
    ISSUED_AT_CLAIM,
    SUBJECT_CLAIM,
)


def encode_token(
    secret: str,
    *,
    subject: str,
    ttl_seconds: int,
    key_id: str | None = None,
    claims: Mapping[str, Any] | None = None,
    algorithm: str = HMAC_SHA256,
) -> IssuedToken:
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
