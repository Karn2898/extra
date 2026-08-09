"""Who a request runs as: what a proven caller looks like, and how their id is
spelled. Proving the claim is `infrastructure.auth`'s job."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# A host subject may be an email or a long OIDC subject, and
# `conversation_users.user_id` is a 64-char primary key, so ids are digested to a
# fixed width rather than carried raw.
USER_ID_MAX_LENGTH = 64
EXTERNAL_DIGEST_LENGTH = 32


class IdentityNamespace(StrEnum):
    """Stops a host id that happens to look like ours from addressing another
    namespace's conversations."""

    EXTERNAL = "ext"
    ANONYMOUS = "anon"

    def qualify(self, value: str) -> str:
        return f"{self.value}:{value}"


def external_user_id(external_id: str) -> str:
    digest = hashlib.sha256(external_id.encode()).hexdigest()[:EXTERNAL_DIGEST_LENGTH]
    return IdentityNamespace.EXTERNAL.qualify(digest)


def anonymous_user_id(anonymous_id: str) -> str:
    return IdentityNamespace.ANONYMOUS.qualify(anonymous_id)


@dataclass(frozen=True)
class Principal:
    """A caller whose identity has already been proven."""

    user_id: str
    namespace: IdentityNamespace
    external_id: str
    email: str | None = None
    display_name: str | None = None
    roles: tuple[str, ...] = ()
    organization_id: str | None = None
    claims: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_anonymous(self) -> bool:
        return self.namespace is IdentityNamespace.ANONYMOUS

    @classmethod
    def external(
        cls,
        external_id: str,
        *,
        email: str | None = None,
        display_name: str | None = None,
        roles: tuple[str, ...] = (),
        organization_id: str | None = None,
        claims: Mapping[str, Any] | None = None,
    ) -> Principal:
        """A user the host product vouched for."""
        if not external_id.strip():
            raise ValueError("external user id must not be empty")
        return cls(
            user_id=external_user_id(external_id),
            namespace=IdentityNamespace.EXTERNAL,
            external_id=external_id,
            email=email,
            display_name=display_name,
            roles=roles,
            organization_id=organization_id,
            claims=claims or {},
        )

    @classmethod
    def anonymous(cls, anonymous_id: str) -> Principal:
        """A visitor the manager itself issued a pass to."""
        if not anonymous_id.strip():
            raise ValueError("anonymous id must not be empty")
        return cls(
            user_id=anonymous_user_id(anonymous_id),
            namespace=IdentityNamespace.ANONYMOUS,
            external_id=anonymous_id,
        )
