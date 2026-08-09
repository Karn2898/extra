"""Abstract persistence contract for run lifecycle state."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_engine.approvals.models import RunRecord, RunStatus


@runtime_checkable
class RunRepository(Protocol):
    """Persistence contract for run records.

    ``create_if_absent`` is the atomic semantic boundary: implementations must
    store ``record`` only when its ``run_id`` is unknown, must never overwrite
    an existing record, and must report whether this call created it. Atomicity
    applies to the implementation's consistency scope.
    The in-memory adapter is process-local; a future shared adapter must provide
    the same semantics across processes.
    """

    async def create_if_absent(self, record: RunRecord) -> bool:
        """Return ``True`` if created, or ``False`` without replacing existing state.

        An existing ``run_id`` is an idempotent outcome, not an error. Backend
        failures may still propagate from an implementation.
        """
        ...

    async def get(self, run_id: str) -> RunRecord | None:
        """Return the stored run, or ``None`` when ``run_id`` is unknown."""
        ...

    async def transition_if_allowed(self, run_id: str, target: RunStatus) -> bool:
        """Atomically apply an allowed transition.

        Return ``True`` only when this call changed the stored status. Return
        ``False`` when the run is absent or the transition is not allowed,
        without modifying stored state.
        """
        ...
