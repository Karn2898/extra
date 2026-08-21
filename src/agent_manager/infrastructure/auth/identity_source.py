"""Contract for resolving tokens issued by one identity provider."""

from __future__ import annotations

from abc import ABC, abstractmethod

from agent_manager.domain.identity import Principal


class IdentitySource(ABC):
    @abstractmethod
    def resolve(self, token: str) -> Principal:
        raise NotImplementedError
