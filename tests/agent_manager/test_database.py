"""Database setup runs migrations only against a database that outlives the process."""

from __future__ import annotations

import pytest

from agent_manager.config import Settings
from agent_manager.infrastructure.persistence.database import upgrade_database


def test_upgrade_is_a_noop_for_an_in_memory_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "agent_manager.config.Settings",
        lambda: Settings.from_values(database_url="sqlite+aiosqlite:///:memory:"),
    )

    assert upgrade_database() is False
