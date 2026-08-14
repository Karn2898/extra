"""Where a token's verifying key comes from.

PyJWT implements the algorithms; only key *lookup* differs between HS256,
RS256/ES256 and JWKS. Isolating it here keeps `TokenVerifier` branch-free, so an
asymmetric issuer is a new implementation in this module and nothing else.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

HMAC_SHA256 = "HS256"
MIN_SECRET_LENGTH = 32


class KeySource(Protocol):
    """`key_for` sees the *unverified* header so it can select on `kid`. That is
    only a hint; the signature check that follows is what decides."""

    @property
    def algorithms(self) -> tuple[str, ...]: ...

    def key_for(self, header: Mapping[str, Any]) -> Any: ...


@dataclass(frozen=True)
class StaticSecretKeySource:
    """One shared HMAC secret — what every host we support today uses."""

    secret: str
    algorithms: tuple[str, ...] = (HMAC_SHA256,)

    def __post_init__(self) -> None:
        if len(self.secret) < MIN_SECRET_LENGTH:
            raise ValueError(
                f"signing secret must be at least {MIN_SECRET_LENGTH} characters,"
                f" got {len(self.secret)}"
            )

    def key_for(self, header: Mapping[str, Any]) -> str:
        return self.secret
