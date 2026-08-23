"""CLI tests for the MCP serve command."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from agent_engine.engine.types import RunResult, ToolUsageRecord
from agent_manager.domain import Repository
from agentctl.main import cli


def _write_spec(tmp_path: Path) -> Path:
    spec = tmp_path / "agents.yml"
    spec.write_text(
        "system: {name: Fake System}\n"
        "agents: {fake_agent: {description: fake}}\n"
        "graph: {fake_agent: null}\n",
        encoding="utf-8",
    )
    return spec


class FakeEngine:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.build_calls: list[object] = []

    async def __aenter__(self) -> FakeEngine:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def build(self, spec: object) -> None:
        self.build_calls.append(spec)

    async def run(
        self,
        message: str,
        *,
        history: tuple = (),
        context: object = None,
    ) -> RunResult:
        self.prompts.append(message)
        return RunResult(
            system_name="Fake System",
            visited=["fake_agent"],
            answer=f"answer-{message}",
            used_tools=(
                ToolUsageRecord(
                    name="search_internal_documents",
                    provider="mcp",
                    status="succeeded",
                ),
            ),
        )

    async def close(self) -> None: ...


@contextmanager
def _patch_mcp_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    spec = _write_spec(tmp_path)
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'chat.db'}"
    monkeypatch.setenv("AGENT_DB_BACKEND", "sqlite")
    monkeypatch.setenv("AGENT_DB_URL", db_url)

    fake_engine = FakeEngine()

    fake_repo = MagicMock(spec=Repository)
    fake_repo.conversation_exists = AsyncMock(return_value=True)
    fake_repo.create_session = AsyncMock(return_value=MagicMock(session_id="sess-1"))
    fake_repo.get_context = AsyncMock(return_value=MagicMock(messages=[]))
    fake_repo.append_message = AsyncMock()
    fake_repo.list_messages = AsyncMock(return_value=[])
    fake_repo.get_token_usage = AsyncMock(return_value=0)
    fake_repo.upsert_user = AsyncMock()

    def _fake_repositories(settings: object) -> MagicMock:
        repos = MagicMock()
        repos.conversations = fake_repo
        repos.session_approvals = MagicMock()
        return repos

    with (
        patch("agentctl.mcp.server.LangGraphEngine", return_value=fake_engine),
        patch("agentctl.mcp.server.application_repositories", side_effect=_fake_repositories),
        patch("agentctl.mcp.server.Settings", return_value=MagicMock(
            context_window=10,
            context_max_chars=None,
            context_max_tokens=None,
            snapshot_ttl_seconds=86_400,
        )),
    ):
        yield spec, fake_engine, fake_repo


def test_mcp_serve_starts_stdio_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with _patch_mcp_runtime(tmp_path, monkeypatch) as (spec, fake_engine, _fake_repo), patch(
        "agentctl.mcp.server.stdio_server"
    ) as mock_stdio:
        mock_stdio.return_value.__aenter__ = AsyncMock(
            return_value=(MagicMock(), MagicMock())
        )
        mock_stdio.return_value.__aexit__ = AsyncMock(return_value=False)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--log-level", "WARNING", "mcp", "serve", "--config", str(spec)],
        )

        assert result.exit_code == 0, result.output
        assert len(fake_engine.build_calls) == 1


def test_mcp_serve_invalid_config_exits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = tmp_path / "bad.yml"
    spec.write_text("invalid: yaml: [", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--log-level", "WARNING", "mcp", "serve", "--config", str(spec)],
    )

    assert result.exit_code != 0
