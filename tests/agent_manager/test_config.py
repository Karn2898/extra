from __future__ import annotations

from agent_manager.config import Settings, normalize_database_url


def test_default_storage_is_process_memory() -> None:
    settings = Settings.from_values()

    assert settings.agent_db_backend == "sqlite"
    assert settings.agent_db_url is None
    assert settings.database_url is None
    assert settings.effective_database_url is None
    assert settings.uses_process_memory is True
    assert settings.context_max_tokens is None


def test_explicit_legacy_database_url_selects_sql_storage() -> None:
    settings = Settings.from_values(database_url="sqlite:///chat.db")

    assert settings.effective_database_url == "sqlite+aiosqlite:///chat.db"
    assert settings.uses_process_memory is False


def test_explicit_in_memory_sqlite_url_still_selects_process_memory() -> None:
    settings = Settings.from_values(database_url="sqlite+aiosqlite:///:memory:")

    assert settings.uses_process_memory is True


def test_sqlite_url_normalizes_to_async_driver() -> None:
    assert normalize_database_url("sqlite:///chat.db", "sqlite") == "sqlite+aiosqlite:///chat.db"


def test_postgres_url_normalizes_to_async_driver() -> None:
    assert (
        normalize_database_url("postgresql://u:p@localhost/db", "postgres")
        == "postgresql+asyncpg://u:p@localhost/db"
    )
