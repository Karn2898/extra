"""Optional engine capability exposing authoritative run lifecycle state."""

from __future__ import annotations

from abc import ABC, abstractmethod


class RunStatusEngine(ABC):
    @abstractmethod
    async def get_run_status(self, run_id: str) -> str:
        raise NotImplementedError
