"""Static HMAC token-verification key source."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from agent_manager.infrastructure.auth.key_source import (
    HMAC_SHA256,
    MIN_SECRET_LENGTH,
    KeySource,
)


@dataclass(frozen=True)
class StaticSecretKeySource(KeySource):
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
