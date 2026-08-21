"""Optional engine capability exposing authoritative run lifecycle state."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_engine.approvals.models import RunStatus


@runtime_checkable
class RunStatusEngine(Protocol):
    async def get_run_status(self, run_id: str) -> RunStatus: ...
