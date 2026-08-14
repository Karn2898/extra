"""Process-local tool-usage repository for development and tests."""

from __future__ import annotations

import asyncio

from agent_engine.tool_usage.models import ToolInvocationRecord

_Key = tuple[str, str]


class InMemoryToolUsageRepository:
    """Process-local implementation of :class:`ToolUsageRepository`.

    An ``asyncio.Lock`` guards the store, matching the approval repositories, so
    concurrent agents in one run cannot lose a write. Records live once, keyed by
    ``(run_id, tool_call_id)``; the run and conversation indexes hold keys in
    first-seen order, which gives the upsert-on-identity and call-order
    guarantees the contract requires. Callers receive tuples of frozen records,
    never the internal mapping.
    """

    def __init__(self) -> None:
        self._records: dict[_Key, ToolInvocationRecord] = {}
        self._by_run: dict[str, list[_Key]] = {}
        self._by_conversation: dict[str, list[_Key]] = {}
        self._lock = asyncio.Lock()

    async def record(self, record: ToolInvocationRecord) -> None:
        key = record.key
        async with self._lock:
            if key not in self._records:
                self._by_run.setdefault(key[0], []).append(key)
                conversation_id = record.call.conversation_id
                if conversation_id:
                    self._by_conversation.setdefault(conversation_id, []).append(key)
            self._records[key] = record

    async def list_for_run(self, run_id: str) -> tuple[ToolInvocationRecord, ...]:
        return await self._snapshot(self._by_run, run_id)

    async def list_for_conversation(self, conversation_id: str) -> tuple[ToolInvocationRecord, ...]:
        return await self._snapshot(self._by_conversation, conversation_id)

    async def _snapshot(
        self, index: dict[str, list[_Key]], scope_id: str
    ) -> tuple[ToolInvocationRecord, ...]:
        async with self._lock:
            return tuple(self._records[key] for key in index.get(scope_id, ()))
