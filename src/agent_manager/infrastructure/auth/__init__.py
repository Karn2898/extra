"""Proving who a caller is: key lookup, token validation, principal resolution."""

from agent_manager.infrastructure.auth.keys import (
    HMAC_SHA256,
    MIN_SECRET_LENGTH,
    KeySource,
    StaticSecretKeySource,
)
from agent_manager.infrastructure.auth.resolver import (
    ANONYMOUS_KEY_ID,
    AnonymousIdentitySource,
    ClaimMapping,
    HostIdentitySource,
    IdentityResolver,
    IdentitySource,
)
from agent_manager.infrastructure.auth.tokens import (
    IssuedToken,
    TokenError,
    TokenPolicy,
    TokenVerifier,
    encode_token,
)

__all__ = [
    "ANONYMOUS_KEY_ID",
    "HMAC_SHA256",
    "MIN_SECRET_LENGTH",
    "AnonymousIdentitySource",
    "ClaimMapping",
    "HostIdentitySource",
    "IdentityResolver",
    "IdentitySource",
    "IssuedToken",
    "KeySource",
    "StaticSecretKeySource",
    "TokenError",
    "TokenPolicy",
    "TokenVerifier",
    "encode_token",
]
