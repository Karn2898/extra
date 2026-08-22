from __future__ import annotations

import pytest

from agent_manager.config import Settings, normalize_database_url


def test_default_database_is_persistent_sqlite_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EXTRA_DB_BACKEND", raising=False)
    monkeypatch.delenv("EXTRA_DB_URL", raising=False)
    monkeypatch.delenv("AGENT_DB_BACKEND", raising=False)
    monkeypatch.delenv("AGENT_DB_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = Settings.from_values()

    assert settings.extra_db_backend == "sqlite"
    assert settings.extra_db_url is None
    assert settings.effective_database_url == "sqlite+aiosqlite:///chat.db"
    assert settings.uses_process_memory is False
    assert settings.context_max_tokens is None


def test_explicit_legacy_database_url_selects_sql_storage() -> None:
    settings = Settings.from_values(database_url="sqlite:///chat.db")

    assert settings.effective_database_url == "sqlite+aiosqlite:///chat.db"
    assert settings.uses_process_memory is False


def test_explicit_in_memory_sqlite_url_selects_process_memory() -> None:
    settings = Settings.from_values(database_url="sqlite+aiosqlite:///:memory:")

    assert settings.uses_process_memory is True


def test_sqlite_url_without_a_database_selects_process_memory() -> None:
    assert Settings.from_values(database_url="sqlite+aiosqlite://").uses_process_memory is True


def test_shared_cache_memory_uri_selects_process_memory() -> None:
    settings = Settings.from_values(
        database_url="sqlite+aiosqlite:///file:chat?mode=memory&cache=shared&uri=true"
    )

    assert settings.uses_process_memory is True


def test_on_disk_path_containing_memory_marker_stays_persistent() -> None:
    """A substring test would drop persistence for this perfectly valid path."""
    settings = Settings.from_values(database_url="sqlite+aiosqlite:////var/lib/:memory:/chat.db")

    assert settings.uses_process_memory is False


def test_postgres_is_never_process_memory() -> None:
    settings = Settings.from_values(
        extra_db_backend="postgres", extra_db_url="postgresql://u:p@localhost/:memory:"
    )

    assert settings.uses_process_memory is False


def test_extra_db_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXTRA_DB_BACKEND", "postgres")
    monkeypatch.setenv("EXTRA_DB_URL", "postgresql://u:p@localhost/db")

    settings = Settings()

    assert settings.extra_db_backend == "postgres"
    assert settings.extra_db_url == "postgresql://u:p@localhost/db"
    assert settings.effective_database_url == "postgresql+asyncpg://u:p@localhost/db"


def test_extra_auth_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXTRA_AUTH_MODE", "mint")
    monkeypatch.setenv("EXTRA_AUTH_SECRET", "super-secret-key-32-chars-long!")

    settings = Settings()

    assert settings.extra_auth_mode == "mint"
    assert settings.extra_auth_secret == "super-secret-key-32-chars-long!"


def test_agent_db_deprecated_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EXTRA_DB_BACKEND", raising=False)
    monkeypatch.delenv("EXTRA_DB_URL", raising=False)
    monkeypatch.setenv("AGENT_DB_BACKEND", "postgres")
    monkeypatch.setenv("AGENT_DB_URL", "postgresql://u:p@localhost/db")

    with pytest.deprecated_call():
        settings = Settings()

    assert settings.extra_db_backend == "postgres"
    assert settings.extra_db_url == "postgresql://u:p@localhost/db"


def test_agent_auth_deprecated_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EXTRA_AUTH_MODE", raising=False)
    monkeypatch.delenv("EXTRA_AUTH_SECRET", raising=False)
    monkeypatch.setenv("AGENT_AUTH_MODE", "mint")
    monkeypatch.setenv("AGENT_AUTH_SECRET", "super-secret-key-32-chars-long!")

    with pytest.deprecated_call():
        settings = Settings()

    assert settings.extra_auth_mode == "mint"
    assert settings.extra_auth_secret == "super-secret-key-32-chars-long!"


def test_extra_vars_take_precedence_over_deprecated_agent_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EXTRA_DB_URL", raising=False)
    monkeypatch.delenv("AGENT_DB_URL", raising=False)
    monkeypatch.delenv("EXTRA_AUTH_SECRET", raising=False)
    monkeypatch.delenv("AGENT_AUTH_SECRET", raising=False)
    monkeypatch.setenv("EXTRA_DB_BACKEND", "sqlite")
    monkeypatch.setenv("AGENT_DB_BACKEND", "postgres")
    monkeypatch.setenv("EXTRA_AUTH_MODE", "anonymous")
    monkeypatch.setenv("AGENT_AUTH_MODE", "mint")

    settings = Settings()

    assert settings.extra_db_backend == "sqlite"
    assert settings.extra_auth_mode == "anonymous"


def test_sqlite_url_normalizes_to_async_driver() -> None:
    assert normalize_database_url("sqlite:///chat.db", "sqlite") == "sqlite+aiosqlite:///chat.db"


def test_postgres_url_normalizes_to_async_driver() -> None:
    assert (
        normalize_database_url("postgresql://u:p@localhost/db", "postgres")
        == "postgresql+asyncpg://u:p@localhost/db"
    )


def test_already_async_urls_pass_through() -> None:
    assert (
        normalize_database_url("sqlite+aiosqlite:///chat.db", "sqlite")
        == "sqlite+aiosqlite:///chat.db"
    )
    assert (
        normalize_database_url("postgresql+asyncpg://u:p@localhost/db", "postgres")
        == "postgresql+asyncpg://u:p@localhost/db"
    )


def test_mismatched_sqlite_scheme_raises() -> None:
    with pytest.raises(ValueError, match="EXTRA_DB_URL"):
        normalize_database_url("postgres://u:p@localhost/db", "sqlite")


def test_mismatched_postgres_scheme_raises() -> None:
    with pytest.raises(ValueError, match="EXTRA_DB_URL"):
        normalize_database_url("sqlite:///chat.db", "postgres")
