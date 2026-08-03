from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from agentctl.main import cli


def test_generate_reports_unused_declared_tools(tmp_path: Path) -> None:
    config = tmp_path / "agents.yaml"
    config.write_text(
        """
system:
  name: test
defaults:
  model: {provider: anthropic, name: claude-test}
tools:
  used_tool:
    description: Used tool
  unused_tool:
    description: Unused tool
agents:
  worker:
    description: Worker
    tools: [used_tool]
graph:
  worker:
""".lstrip(),
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["generate", "--config", str(config)])

    assert result.exit_code == 0
    assert "  ignore  unused_tool  (declared but not referenced by any agent)" in result.output
    assert (tmp_path / "plugins" / "tools" / "used_tool.py").is_file()
    assert not (tmp_path / "plugins" / "tools" / "unused_tool.py").exists()

    second = CliRunner().invoke(cli, ["generate", "--config", str(config)])

    assert second.exit_code == 0
    assert "  ignore  unused_tool  (declared but not referenced by any agent)" in second.output
    assert "Nothing to generate — no referenced stubs are missing." in second.output
