"""Tests for rejecting unknown/misplaced YAML keys during parser validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_engine.parsers.errors import ParseError
from agent_engine.parsers.yaml.parser import YAMLParser


def _parse(tmp_path: Path, body: str) -> None:
    cfg = tmp_path / "spec.yml"
    cfg.write_text(body, encoding="utf-8")
    YAMLParser().parse(str(cfg))


def test_misplaced_tools_and_auto_in_prompts_rejected(tmp_path: Path) -> None:
    """Keys nested under prompts instead of agent must be rejected with ParseError."""
    spec = """
system:
  name: test
orchestrators:
  router:
    description: "Routes requests"
    prompts:
      orchestrator: prompts/router.md
agents:
  admin_agent:
    description: "Admin agent"
    prompts:
      system: prompts/admin.md
      tools: [add_new_user]
      auto: true
graph:
  router:
    admin_agent:
"""
    with pytest.raises(ParseError) as exc_info:
        _parse(tmp_path, spec)

    err_msgs = [e.message for e in exc_info.value.errors]
    assert any("Unknown key 'tools'" in msg for msg in err_msgs)
    assert any("Unknown key 'auto'" in msg for msg in err_msgs)


def test_unknown_top_level_key_rejected(tmp_path: Path) -> None:
    """Unknown top-level YAML keys must be rejected."""
    spec = """
system:
  name: test
invalid_top_level: true
orchestrators:
  router:
    prompts:
      orchestrator: prompts/router.md
graph:
  router: null
"""
    with pytest.raises(ParseError) as exc_info:
        _parse(tmp_path, spec)

    assert any("Unknown key 'invalid_top_level'" in e.message for e in exc_info.value.errors)


def test_unknown_key_in_model_config_rejected(tmp_path: Path) -> None:
    """Model config typos like 'temparature' must be rejected."""
    spec = """
system:
  name: test
agents:
  worker:
    model:
      provider: openai
      name: gpt-4o
      temparature: 0.7
    prompts:
      system: prompts/worker.md
graph:
  worker: null
"""
    with pytest.raises(ParseError) as exc_info:
        _parse(tmp_path, spec)

    assert any("Unknown key 'temparature'" in e.message for e in exc_info.value.errors)


def test_unknown_key_in_execution_block_rejected(tmp_path: Path) -> None:
    """Unknown keys in the execution block must be rejected."""
    spec = """
system:
  name: test
execution:
  max_iterations: 10
  invalid_setting: 5
agents:
  worker:
    prompts:
      system: prompts/worker.md
graph:
  worker: null
"""
    with pytest.raises(ParseError) as exc_info:
        _parse(tmp_path, spec)

    assert any("Unknown key 'invalid_setting'" in e.message for e in exc_info.value.errors)


def test_valid_spec_parses_successfully(tmp_path: Path) -> None:
    """Valid YAML specification must parse without validation errors."""
    spec = """
system:
  name: test
agents:
  admin_agent:
    description: "Admin agent"
    tools: [add_new_user]
    auto: true
    prompts:
      system: prompts/admin.md
tools:
  add_new_user:
    description: "Add user"
graph:
  admin_agent: null
"""
    _parse(tmp_path, spec)
