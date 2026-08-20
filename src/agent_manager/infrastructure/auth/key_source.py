"""Contract for selecting a token verification key."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

HMAC_SHA256 = "HS256"
MIN_SECRET_LENGTH = 32


class KeySource(ABC):
    algorithms: tuple[str, ...]

    @abstractmethod
    def key_for(self, header: Mapping[str, Any]) -> Any:
        raise NotImplementedError
