"""Mapping host-specific token claims into the manager identity model."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from agent_manager.domain.identity import Principal
from agent_manager.infrastructure.auth.token_claims import SUBJECT_CLAIM
from agent_manager.infrastructure.auth.token_error import TokenError

ROLE_SEPARATORS = re.compile(r"[,;\s]+")


@dataclass(frozen=True)
class ClaimMapping:
    user_id: str = SUBJECT_CLAIM
    email: str = "email"
    display_name: str = "name"
    roles: str = "roles"
    organization_id: str = "org_id"

    def to_principal(self, claims: Mapping[str, Any]) -> Principal:
        external_id = _identifier(claims.get(self.user_id))
        if external_id is None:
            raise TokenError(f"token carries no usable {self.user_id!r} claim")
        return Principal.external(
            external_id,
            email=_text(claims.get(self.email)),
            display_name=_text(claims.get(self.display_name)),
            roles=_roles(claims.get(self.roles)),
            organization_id=_identifier(claims.get(self.organization_id)),
            claims=claims,
        )


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _identifier(value: Any) -> str | None:
    """Return a usable textual identity claim; booleans are never identities."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    return _text(value)


def _roles(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(role for role in ROLE_SEPARATORS.split(value) if role)
    if isinstance(value, Sequence):
        return tuple(role for role in value if isinstance(role, str) and role.strip())
    return ()
