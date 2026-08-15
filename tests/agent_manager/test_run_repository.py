from __future__ import annotations

import asyncio

from sqlmodel import SQLModel

import agent_manager.infrastructure.persistence.tables  # noqa: F401
from agent_engine.approvals.models import RunRecord, RunStatus
from agent_manager.infrastructure.persistence.database import create_db_engine, session_factory
from agent_manager.infrastructure.persistence.run_repository import SqlRunRepository


async def test_sql_run_repository_persists_status_and_usage_atomically() -> None:
    engine = create_db_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    repository = SqlRunRepository(session_factory(engine))
    record = RunRecord("run-1", "run-1", "system")

    assert await repository.create_if_absent(record) is True
    assert await repository.create_if_absent(record) is False
    assert await repository.add_token_usage("run-1", input_tokens=4, output_tokens=2) is not None
    completed, cancelled = await asyncio.gather(
        repository.transition_if_allowed("run-1", RunStatus.COMPLETED),
        repository.transition_if_allowed("run-1", RunStatus.CANCELLED),
    )

    assert sum((completed, cancelled)) == 1
    stored = await repository.get("run-1")
    assert stored is not None
    assert stored.status in {RunStatus.COMPLETED, RunStatus.CANCELLED}
    assert (stored.input_tokens, stored.output_tokens) == (4, 2)
    await engine.dispose()
