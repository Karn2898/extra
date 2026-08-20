"""Proving who a caller is: key lookup, token validation, principal resolution."""

from agent_manager.infrastructure.auth.anonymous_identity_source import (
    ANONYMOUS_KEY_ID,
    AnonymousIdentitySource,
)
from agent_manager.infrastructure.auth.claim_mapping import ClaimMapping
from agent_manager.infrastructure.auth.host_identity_source import HostIdentitySource
from agent_manager.infrastructure.auth.identity_resolver import IdentityResolver
from agent_manager.infrastructure.auth.identity_source import IdentitySource
from agent_manager.infrastructure.auth.issued_token import IssuedToken
from agent_manager.infrastructure.auth.key_source import (
    HMAC_SHA256,
    MIN_SECRET_LENGTH,
    KeySource,
)
from agent_manager.infrastructure.auth.static_secret_key_source import StaticSecretKeySource
from agent_manager.infrastructure.auth.token_error import TokenError
from agent_manager.infrastructure.auth.token_issuer import encode_token
from agent_manager.infrastructure.auth.token_policy import TokenPolicy
from agent_manager.infrastructure.auth.token_verifier import TokenVerifier

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
