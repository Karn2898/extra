"""Tests for the ``agentctl serve`` command's port defaulting/override.

The real ``create_app`` and ``uvicorn.run`` are stubbed out — these tests only
assert how the CLI resolves the bind port, not that a server actually starts.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from agentctl.diagnostics import ValidationResult
from agentctl.main import cli

DEFAULT_PORT = 8090


@pytest.fixture
def captured_run(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Stub the serve command's side effects and capture what uvicorn.run gets."""
    import uvicorn

    captured: dict[str, object] = {}

    def fake_run(app: object, host: str, port: int) -> None:
        captured["host"] = host
        captured["port"] = port

    def fake_create_app(config: str) -> object:
        captured["app_created"] = config
        return object()

    monkeypatch.setattr("agentctl.main.load_env", lambda config, env: None)
    monkeypatch.setattr(
        "agentctl.diagnostics.validate_spec", lambda config: ValidationResult(ok=True)
    )
    monkeypatch.setattr("agent_engine.api.app.create_app", fake_create_app)
    monkeypatch.setattr(uvicorn, "run", fake_run)
    return captured


def test_serve_defaults_to_8090(captured_run: dict[str, object]) -> None:
    res = CliRunner().invoke(cli, ["serve", "--config", "agents.yml"])
    assert res.exit_code == 0, res.output
    assert captured_run["port"] == DEFAULT_PORT


def test_serve_port_flag_overrides_default(captured_run: dict[str, object]) -> None:
    res = CliRunner().invoke(cli, ["serve", "--config", "agents.yml", "--port", "8080"])
    assert res.exit_code == 0, res.output
    assert captured_run["port"] == 8080


def test_serve_port_env_var_overrides_default(captured_run: dict[str, object]) -> None:
    res = CliRunner().invoke(cli, ["serve", "--config", "agents.yml"], env={"PORT": "9000"})
    assert res.exit_code == 0, res.output
    assert captured_run["port"] == 9000


def test_serve_rejects_invalid_config_before_startup(
    captured_run: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "agentctl.diagnostics.validate_spec",
        lambda config: ValidationResult(
            ok=False,
            errors=[
                "[openwebui.prompts.system] prompt is not implemented",
                "[tools.add_new_user] tool is not implemented",
            ],
        ),
    )

    res = CliRunner().invoke(cli, ["serve", "--config", "agents.yml"])

    assert res.exit_code == 1
    assert "Validation failed:" in res.output
    assert "[openwebui.prompts.system] prompt is not implemented" in res.output
    assert "[tools.add_new_user] tool is not implemented" in res.output
    assert "Traceback" not in res.output
    assert "app_created" not in captured_run
    assert "host" not in captured_run
