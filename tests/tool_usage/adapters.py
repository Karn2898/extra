"""A second, genuinely persistent adapter used to pin the repository contract.

It exists so the contract suite runs against more than the shipped in-memory
store: if the contract can only be satisfied by a dict, it is not a contract.
SQLite stands in for any out-of-process backend (Redis, PostgreSQL) — none of
which may live in ``agent_engine`` itself.
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite

from agent_engine.tool_usage.models import (
    ToolCallIdentity,
    ToolInvocationKind,
    ToolInvocationRecord,
    ToolInvocationStatus,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tool_usage (
    run_id TEXT NOT NULL,
    tool_call_id TEXT NOT NULL,
    conversation_id TEXT,
    agent_id TEXT NOT NULL,
    agent_path TEXT NOT NULL,
    kind TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    server_id TEXT,
    status TEXT NOT NULL,
    error TEXT,
    recorded_at REAL NOT NULL,
    seq INTEGER NOT NULL,
    PRIMARY KEY (run_id, tool_call_id)
)
"""


class SqliteToolUsageRepository:
    """SQLite implementation of the same ``ToolUsageRepository`` contract.

    ``record`` is an upsert on ``(run_id, tool_call_id)`` that keeps the row's
    original sequence number, so call order survives a status update exactly as
    it does in memory. The sequence is global, so a conversation's records order
    across runs the same way they were made.
    """

    def __init__(self, path: Path) -> None:
        self._path = str(path)

    async def setup(self) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(_SCHEMA)
            await db.commit()

    async def record(self, record: ToolInvocationRecord) -> None:
        call = record.call
        async with aiosqlite.connect(self._path, isolation_level=None) as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                """
                INSERT INTO tool_usage (run_id, tool_call_id, conversation_id, agent_id,
                                        agent_path, kind, tool_name, provider, server_id,
                                        status, error, recorded_at, seq)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        (SELECT COALESCE(MAX(seq), 0) + 1 FROM tool_usage))
                ON CONFLICT(run_id, tool_call_id) DO UPDATE SET
                    status = excluded.status,
                    error = excluded.error,
                    recorded_at = excluded.recorded_at
                """,
                (
                    call.run_id,
                    call.tool_call_id,
                    call.conversation_id,
                    call.agent_id,
                    call.agent_path,
                    call.kind.value,
                    call.tool_name,
                    call.provider,
                    call.server_id,
                    record.status.value,
                    record.error,
                    record.recorded_at,
                ),
            )
            await db.execute("COMMIT")

    async def list_for_run(
        self,
        run_id: str,
        *,
        limit: int | None = None,
        kind: ToolInvocationKind | None = None,
    ) -> tuple[ToolInvocationRecord, ...]:
        return await self._select("run_id", run_id, limit=limit, kind=kind)

    async def list_for_conversation(
        self,
        conversation_id: str,
        *,
        limit: int | None = None,
        kind: ToolInvocationKind | None = None,
    ) -> tuple[ToolInvocationRecord, ...]:
        return await self._select("conversation_id", conversation_id, limit=limit, kind=kind)

    async def _select(
        self,
        column: str,
        value: str,
        *,
        limit: int | None,
        kind: ToolInvocationKind | None,
    ) -> tuple[ToolInvocationRecord, ...]:
        """``column`` is always one of the two literals chosen by the callers above."""
        if limit is not None and limit <= 0:
            raise ValueError("limit must be positive")
        where = f"{column} = ?" + (" AND kind = ?" if kind is not None else "")
        params: list[str | int] = [value]
        if kind is not None:
            params.append(kind.value)
        suffix = " ORDER BY seq"
        if limit is not None:
            suffix = " ORDER BY seq DESC LIMIT ?"
            params.append(limit)
        async with aiosqlite.connect(self._path) as db:
            cursor = await db.execute(
                f"""
                SELECT run_id, conversation_id, agent_id, agent_path, kind, tool_call_id,
                       tool_name, provider, server_id, status, error, recorded_at
                FROM tool_usage WHERE {where}{suffix}
                """,
                params,
            )
            rows = list(await cursor.fetchall())
        if limit is not None:
            rows.reverse()
        return tuple(
            ToolInvocationRecord(
                call=ToolCallIdentity(
                    run_id=row[0],
                    conversation_id=row[1],
                    agent_id=row[2],
                    agent_path=row[3],
                    kind=ToolInvocationKind(row[4]),
                    tool_call_id=row[5],
                    tool_name=row[6],
                    provider=row[7],
                    server_id=row[8],
                ),
                status=ToolInvocationStatus(row[9]),
                error=row[10],
                recorded_at=row[11],
            )
            for row in rows
        )
