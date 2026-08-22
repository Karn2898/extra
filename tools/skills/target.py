"""Generation-target contract for AI instruction adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class Target(ABC):
    name: str

    @abstractmethod
    def generate(
        self, root: Path, source_kind: str, ai_name: str, description: str, body: str
    ) -> Path:
        raise NotImplementedError

    @abstractmethod
    def remove_stale(
        self, root: Path, source_names_by_kind: dict[str, set[str]], removed: list[Path]
    ) -> None:
        raise NotImplementedError
