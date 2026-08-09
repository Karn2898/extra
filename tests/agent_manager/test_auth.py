"""Token verification — the security core. Everything else trusts this module."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from pydantic import ValidationError

from agent_manager.composition import anonymous_secret, build_identity_resolver
from agent_manager.config import AuthMode, Settings
from agent_manager.domain import IdentityNamespace, Principal
from agent_manager.infrastructure.auth import (
    ClaimMapping,
    HostIdentitySource,
    StaticSecretKeySource,
    TokenError,
    TokenPolicy,
    TokenVerifier,
    encode_token,
)

SECRET = "a-signing-secret-of-more-than-32-characters"
OTHER_SECRET = "an-attacker-secret-of-sufficient-length"


def _verifier(policy: TokenPolicy | None = None, secret: str = SECRET) -> TokenVerifier:
    return TokenVerifier(StaticSecretKeySource(secret), policy)


def _encode(secret: str = SECRET, **claims: Any) -> str:
    now = datetime.now(UTC)
    payload = {"sub": "alice", "iat": now, "exp": now + timedelta(minutes=5), **claims}
    return jwt.encode(payload, secret, algorithm="HS256")


def test_an_unsigned_token_is_not_a_token() -> None:
    """`alg: none` is the oldest JWT bypass; the allowlist is what stops it."""
    unsigned = jwt.encode({"sub": "alice", "exp": 9_999_999_999}, "", algorithm="none")

    with pytest.raises(TokenError):
        _verifier().verify(unsigned)


def test_a_token_signed_with_another_key_is_rejected() -> None:
    with pytest.raises(TokenError):
        _verifier().verify(_encode(OTHER_SECRET))


def test_an_expired_token_is_rejected() -> None:
    stale = datetime.now(UTC) - timedelta(hours=2)
    with pytest.raises(TokenError):
        _verifier().verify(_encode(iat=stale, exp=stale + timedelta(minutes=5)))


def test_a_token_without_an_expiry_is_rejected_when_the_policy_requires_one() -> None:
    forever = jwt.encode({"sub": "alice"}, SECRET, algorithm="HS256")

    with pytest.raises(TokenError):
        _verifier().verify(forever)

    assert _verifier(TokenPolicy(require_expiry=False)).verify(forever)["sub"] == "alice"


def test_a_long_lived_token_is_rejected_when_the_policy_caps_lifetime() -> None:
    """A long-lived token is a long-lived impersonation window."""
    policy = TokenPolicy(max_ttl_seconds=3600)
    now = datetime.now(UTC)

    with pytest.raises(TokenError, match="exceeds"):
        _verifier(policy).verify(_encode(iat=now, exp=now + timedelta(days=1)))

    assert _verifier(policy).verify(_encode(iat=now, exp=now + timedelta(minutes=5)))


def test_a_token_from_another_issuer_is_rejected() -> None:
    policy = TokenPolicy(issuer="https://acme.example")

    with pytest.raises(TokenError):
        _verifier(policy).verify(_encode(iss="https://evil.example"))

    assert _verifier(policy).verify(_encode(iss="https://acme.example"))


def test_verification_takes_its_algorithms_from_the_key_source() -> None:
    """The seam that keeps RS256/ES256 a new `KeySource` and nothing else."""

    class Hmac512KeySource:
        algorithms = ("HS512",)

        def key_for(self, header: Mapping[str, Any]) -> str:
            return SECRET

    now = datetime.now(UTC)
    payload = {"sub": "alice", "iat": now, "exp": now + timedelta(minutes=5)}
    token = jwt.encode(payload, SECRET, algorithm="HS512")

    assert TokenVerifier(Hmac512KeySource()).verify(token)["sub"] == "alice"
    with pytest.raises(TokenError):
        _verifier().verify(token)


def test_a_short_secret_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="at least"):
        StaticSecretKeySource("too-short")


def test_host_claims_are_mapped_by_configuration_not_by_code() -> None:
    """Open WebUI puts the user id in `id`; an OIDC provider puts it in `sub`."""
    source = HostIdentitySource(
        _verifier(),
        ClaimMapping(user_id="id", display_name="username", roles="groups"),
    )

    principal = source.resolve(_encode(id="u_8412", username="Dana", groups=["admin", "billing"]))

    assert principal.external_id == "u_8412"
    assert principal.display_name == "Dana"
    assert principal.roles == ("admin", "billing")
    assert principal.namespace is IdentityNamespace.EXTERNAL


def test_a_token_missing_the_mapped_user_id_is_rejected() -> None:
    source = HostIdentitySource(_verifier(), ClaimMapping(user_id="id"))

    with pytest.raises(TokenError, match="'id'"):
        source.resolve(_encode())


def test_roles_are_read_from_a_list_or_a_delimited_string() -> None:
    source = HostIdentitySource(_verifier())

    assert source.resolve(_encode(roles="admin, billing")).roles == ("admin", "billing")
    assert source.resolve(_encode(roles=["admin"])).roles == ("admin",)
    assert source.resolve(_encode()).roles == ()


def _settings(**overrides: Any) -> Settings:
    return Settings.from_values(**overrides)


def test_host_identity_requires_a_configured_secret() -> None:
    with pytest.raises(ValidationError, match="AGENT_AUTH_SECRET"):
        _settings(agent_auth_mode=AuthMode.HOST_TOKEN)


def test_visitor_passes_are_not_signed_with_the_host_key() -> None:
    """A host that can mint tokens still must not be able to mint passes."""
    settings = _settings(agent_auth_mode=AuthMode.MINT, agent_auth_secret=SECRET)

    assert anonymous_secret(settings) != SECRET


def test_a_visitor_pass_round_trips_but_a_host_token_does_not_become_one() -> None:
    resolver = build_identity_resolver(
        _settings(agent_auth_mode=AuthMode.MINT, agent_auth_secret=SECRET)
    )

    visitor = resolver.resolve(resolver.anonymous.issue().token)
    assert visitor.is_anonymous
    assert visitor.user_id.startswith(f"{IdentityNamespace.ANONYMOUS.value}:")

    host_user = resolver.resolve(encode_token(SECRET, subject="alice", ttl_seconds=300).token)
    assert not host_user.is_anonymous
    assert host_user.external_id == "alice"


def test_without_a_host_secret_only_visitor_passes_are_accepted() -> None:
    resolver = build_identity_resolver(_settings())

    assert resolver.resolve(resolver.anonymous.issue().token).is_anonymous
    with pytest.raises(TokenError, match="visitor passes"):
        resolver.resolve(encode_token(SECRET, subject="alice", ttl_seconds=300).token)


def test_a_derived_user_id_is_stable_namespaced_and_fits_the_key_column() -> None:
    """The stored key is a digest; the readable id stays searchable alongside it."""
    long_subject = "a-very-long-oidc-subject@" + "x" * 200

    principal = Principal.external(long_subject)

    assert principal == Principal.external(long_subject)
    assert principal.user_id.startswith(f"{IdentityNamespace.EXTERNAL.value}:")
    assert len(principal.user_id) <= 64
    assert principal.external_id == long_subject
    assert Principal.external("alice").user_id != Principal.anonymous("alice").user_id
