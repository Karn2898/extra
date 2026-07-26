from __future__ import annotations

import pytest
from tests.fixtures.support import FakeEngine, load_test_system


def test_spec_validates_offline() -> None:
    load_test_system()


@pytest.mark.asyncio
async def test_engine_builds_from_fixture() -> None:
    async with FakeEngine():
        pass


@pytest.mark.asyncio
async def test_orchestrator_routes_to_greeting() -> None:
    async with FakeEngine() as engine:
        result = await engine.run("greeting_agent hello")
        assert "root_router/greeting_agent" in result.visited
        assert result.answer


@pytest.mark.asyncio
async def test_orchestrator_routes_to_echo_and_calls_tool() -> None:
    async with FakeEngine() as engine:
        result = await engine.run("echo_agent echo test")
        assert "root_router/echo_agent" in result.visited
        assert any(record.name == "echo_tool" for record in result.used_tools)
        assert result.answer


@pytest.mark.asyncio
async def test_resolvers_resolve_at_runtime() -> None:
    async with FakeEngine() as engine:
        result = await engine.run("hello")
        assert result.status == "completed"
