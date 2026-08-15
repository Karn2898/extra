from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from typing import Protocol, Self, runtime_checkable

from agent_engine.approvals.decision import ApprovalDecision
from agent_engine.core.spec import SystemSpec
from agent_engine.engine.types import ChatMessage, PendingApproval, RunResult
from agent_engine.runtime.hooks.models import RunContext
from agent_engine.runtime.streaming import RunStreamEvent


class Engine(ABC):
    @abstractmethod
    async def build(self, spec: SystemSpec) -> None: ...

    @abstractmethod
    async def run(
        self,
        message: str,
        *,
        history: Sequence[ChatMessage] = (),
        context: RunContext | None = None,
    ) -> RunResult: ...

    @abstractmethod
    def stream(
        self,
        message: str,
        *,
        history: Sequence[ChatMessage] = (),
        context: RunContext | None = None,
    ) -> AsyncIterator[RunStreamEvent]: ...

    async def close(self) -> None:  # noqa: B027
        pass

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()


@runtime_checkable
class ApprovalEngine(Protocol):
    """Optional engine capability for inspecting and resuming HITL runs."""

    async def get_pending_approval(self, run_id: str) -> PendingApproval | None: ...

    async def get_processed_result(
        self,
        run_id: str,
        approval_id: str,
        *,
        caller_user_id: str | None = None,
        caller_session_id: str | None = None,
    ) -> RunResult | None: ...

    async def resume(
        self,
        run_id: str,
        approval_id: str,
        decision: ApprovalDecision | str,
        *,
        caller_user_id: str | None = None,
        caller_session_id: str | None = None,
    ) -> RunResult: ...
