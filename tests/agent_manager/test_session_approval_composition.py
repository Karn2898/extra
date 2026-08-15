"""Application composition behavior for in-memory session approvals."""

from __future__ import annotations

import pytest

from agent_engine.approvals.invocation import SessionApprovalKey
from agent_engine.approvals.session_store import InMemorySessionApprovalRepository
from agent_engine.runs.in_memory import InMemoryRunRepository
from agent_manager.composition import application_repositories, build_session_approval_repository
from agent_manager.config import Settings
from agent_manager.infrastructure.persistence.memory_repository import MemoryRepository


def test_composition_builds_the_in_memory_adapter() -> None:
    repository = build_session_approval_repository()
    assert isinstance(repository, InMemorySessionApprovalRepository)


async def test_composed_repository_retains_grant_for_its_lifetime() -> None:
    repository = build_session_approval_repository()
    key = SessionApprovalKey(
        system_namespace="system",
        organization_id="org",
        user_id="user",
        session_id="session",
        agent_id="agent",
        tool_identity="local:local:send",
    )

    await repository.allow(key)

    assert await repository.is_allowed(key) is True


async def test_new_application_repository_starts_without_prior_grants() -> None:
    first = build_session_approval_repository()
    second = build_session_approval_repository()
    key = SessionApprovalKey(
        session_id="session",
        agent_id="agent",
        tool_identity="local:local:send",
    )
    await first.allow(key)

    assert await first.is_allowed(key) is True
    assert await second.is_allowed(key) is False


async def test_unconfigured_application_uses_only_process_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_sql_engine_is_created(_url: str) -> None:
        raise AssertionError("unconfigured storage must not create a database engine")

    monkeypatch.setattr(
        "agent_manager.composition.create_db_engine",
        fail_if_sql_engine_is_created,
    )

    async with application_repositories(Settings.from_values()) as repositories:
        assert isinstance(repositories.conversations, MemoryRepository)
        assert isinstance(repositories.runs, InMemoryRunRepository)
