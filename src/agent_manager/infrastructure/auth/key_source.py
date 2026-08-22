"""Where a token's verifying key comes from."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

HMAC_SHA256 = "HS256"


class KeySource(ABC):
    """Select a verification key from the unverified header, which is only a hint."""

    algorithms: tuple[str, ...]

    @abstractmethod
    def key_for(self, header: Mapping[str, Any]) -> Any:
        raise NotImplementedError
