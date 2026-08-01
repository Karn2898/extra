"""Tests for the ``agent-manager`` startup message and bind options."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from agent_manager.cli import main


@pytest.fixture
def captured_run(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    import uvicorn

    captured: dict[str, object] = {}

    def fake_create_app(config: str, settings: object) -> object:
        captured["config"] = config
        captured["settings"] = settings
        return object()

    def fake_run(app: object, host: str, port: int) -> None:
        captured["app"] = app
        captured["host"] = host
        captured["port"] = port

    monkeypatch.setattr("agent_manager.cli.load_dotenv", lambda path, override: None)
    monkeypatch.setattr("agent_manager.api.create_app", fake_create_app)
    monkeypatch.setattr(
        "agent_manager.config.Settings",
        lambda: SimpleNamespace(host="0.0.0.0", port=8100),
    )
    monkeypatch.setattr(uvicorn, "run", fake_run)
    return captured


def test_startup_prints_clickable_playground_url(captured_run: dict[str, object]) -> None:
    result = CliRunner().invoke(main, ["--config", "agents.yml", "--no-migrate"])

    assert result.exit_code == 0, result.output
    assert "Playground: http://localhost:8100/playground" in result.output
    assert captured_run["host"] == "0.0.0.0"
    assert captured_run["port"] == 8100


def test_startup_url_uses_host_and_port_overrides(captured_run: dict[str, object]) -> None:
    result = CliRunner().invoke(
        main,
        [
            "--config",
            "agents.yml",
            "--host",
            "127.0.0.1",
            "--port",
            "8200",
            "--no-migrate",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Playground: http://127.0.0.1:8200/playground" in result.output
    assert captured_run["host"] == "127.0.0.1"
    assert captured_run["port"] == 8200


def test_startup_url_formats_ipv6_host(captured_run: dict[str, object]) -> None:
    result = CliRunner().invoke(
        main,
        ["--config", "agents.yml", "--host", "::1", "--no-migrate"],
    )

    assert result.exit_code == 0, result.output
    assert "Playground: http://[::1]:8100/playground" in result.output
    assert captured_run["host"] == "::1"
    assert captured_run["port"] == 8100
