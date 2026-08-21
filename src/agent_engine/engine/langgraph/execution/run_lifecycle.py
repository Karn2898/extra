"""Lifecycle coordination for one engine run."""

from __future__ import annotations

import logging
import uuid

from agent_engine.approvals.models import RunRecord, RunStatus
from agent_engine.engine.types import RunResult
from agent_engine.logging_config import log
from agent_engine.runs.repository import RunRepository
from agent_engine.runtime.hooks import HookManager, RunContext, RunEndContext

logger = logging.getLogger(__name__)


class RunLifecycle:
    """Coordinates run registration, lifecycle hooks, and lifecycle logging."""

    def __init__(
        self,
        *,
        system_name: str,
        hook_manager: HookManager,
        run_repository: RunRepository,
    ) -> None:
        self._system_name = system_name
        self._hooks = hook_manager
        self._runs = run_repository

    # -- start ---------------------------------------------------------------

    @staticmethod
    def identify(context: RunContext | None) -> RunContext:
        """Return the caller's context with a run id guaranteed."""
        ctx = context or RunContext()
        if ctx.run_id is None:
            ctx = ctx.replace(run_id=str(uuid.uuid4()))
        return ctx

    async def begin(self, context: RunContext | None) -> RunContext:
        """Open a run. ``on_run_start`` may replace the context, so it runs
        before registration."""
        identified = self.identify(context)
        ctx = await self._hooks.run_run_start(identified)
        if ctx.run_id != identified.run_id:
            raise ValueError("on_run_start hooks cannot replace the authoritative run_id")
        await self._register(ctx)
        log(logger, logging.INFO, "run started", run_id=ctx.run_id, system=self._system_name)
        return ctx

    async def _register(self, ctx: RunContext) -> None:
        """Express one idempotent registration operation to the repository."""
        assert ctx.run_id is not None
        await self._runs.create_if_absent(
            RunRecord(
                run_id=ctx.run_id,
                thread_id=ctx.run_id,
                system_name=self._system_name,
                status=RunStatus.RUNNING,
            )
        )

    async def succeed(self, ctx: RunContext, result: RunResult) -> None:
        """Close a run that produced an answer. The terminal-event handshake that
        used to interleave here now lives in ``StreamChannel``."""
        await self._mark(ctx.run_id, RunStatus.COMPLETED)
        await self._hooks.run_run_end(ctx, self._end_context(ctx, result))
        log(
            logger,
            logging.INFO,
            "run ended",
            run_id=ctx.run_id,
            system=self._system_name,
            visited=len(result.visited),
            tools=len(result.used_tools),
        )

    async def activate_resume(self, ctx: RunContext) -> None:
        """Move a claimed suspended run back into active execution."""
        if not await self._mark(ctx.run_id, RunStatus.RUNNING):
            raise RuntimeError(f"run {ctx.run_id!r} cannot enter running state after resume")
        log(
            logger,
            logging.INFO,
            "run resumed",
            run_id=ctx.run_id,
            system=self._system_name,
        )

    async def fail(self, ctx: RunContext, error: Exception) -> None:
        """Close a run that raised. Never raises, so the original error survives."""
        log(
            logger,
            logging.WARNING,
            "run failed",
            run_id=ctx.run_id,
            system=self._system_name,
            error=type(error).__name__,
        )
        await self._mark(ctx.run_id, RunStatus.FAILED)
        await self._hooks.run_run_error(ctx, error)

    async def cancel(self, ctx: RunContext, *, reason: str = "consumer abandoned stream") -> None:
        """Terminally close a running, resuming, or explicitly cancelled pending run."""
        if await self._mark(ctx.run_id, RunStatus.CANCELLED):
            log(
                logger,
                logging.INFO,
                "run cancelled",
                run_id=ctx.run_id,
                system=self._system_name,
                reason=reason,
            )

    async def _mark(self, run_id: str | None, target: RunStatus) -> bool:
        """Request one atomic transition, leaving absent or terminal runs alone."""
        return False if run_id is None else await self._runs.transition_if_allowed(run_id, target)

    def _end_context(self, ctx: RunContext, result: RunResult) -> RunEndContext:
        """Safe summary of a completed run for ``on_run_end`` (no answer text)."""
        return RunEndContext(
            run_id=ctx.run_id,
            system_name=self._system_name,
            status="succeeded",
            visited=tuple(result.visited),
            used_tool_count=len(result.used_tools),
        )
