"""Database setup selects persistence only when explicitly configured."""

from __future__ import annotations

import pytest

from agent_manager.config import Settings
from agent_manager.infrastructure.persistence.database import upgrade_database


def test_upgrade_is_a_noop_without_a_configured_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agent_manager.config.Settings", lambda: Settings.from_values())

    assert upgrade_database() is False
