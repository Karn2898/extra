"""Typed settings, read from the environment (and a .env file)."""

from __future__ import annotations

import os
import warnings
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ONE_HOUR_SECONDS = 3_600
THIRTY_DAYS_SECONDS = 2_592_000

_DEPRECATED_ENV_VARS: tuple[tuple[str, str, str], ...] = (
    ("AGENT_DB_BACKEND", "EXTRA_DB_BACKEND", "extra_db_backend"),
    ("AGENT_DB_URL", "EXTRA_DB_URL", "extra_db_url"),
    ("AGENT_AUTH_MODE", "EXTRA_AUTH_MODE", "extra_auth_mode"),
    ("AGENT_AUTH_SECRET", "EXTRA_AUTH_SECRET", "extra_auth_secret"),
    ("AGENT_AUTH_ANONYMOUS_SECRET", "EXTRA_AUTH_ANONYMOUS_SECRET", "extra_auth_anonymous_secret"),
    (
        "AGENT_AUTH_ANONYMOUS_TTL_SECONDS",
        "EXTRA_AUTH_ANONYMOUS_TTL_SECONDS",
        "extra_auth_anonymous_ttl_seconds",
    ),
    ("AGENT_AUTH_MAX_TTL_SECONDS", "EXTRA_AUTH_MAX_TTL_SECONDS", "extra_auth_max_ttl_seconds"),
    ("AGENT_AUTH_ISSUER", "EXTRA_AUTH_ISSUER", "extra_auth_issuer"),
    ("AGENT_AUTH_AUDIENCE", "EXTRA_AUTH_AUDIENCE", "extra_auth_audience"),
    ("AGENT_AUTH_COOKIE", "EXTRA_AUTH_COOKIE", "extra_auth_cookie"),
    ("AGENT_AUTH_CLAIM_USER_ID", "EXTRA_AUTH_CLAIM_USER_ID", "extra_auth_claim_user_id"),
    ("AGENT_AUTH_CLAIM_EMAIL", "EXTRA_AUTH_CLAIM_EMAIL", "extra_auth_claim_email"),
    (
        "AGENT_AUTH_CLAIM_DISPLAY_NAME",
        "EXTRA_AUTH_CLAIM_DISPLAY_NAME",
        "extra_auth_claim_display_name",
    ),
    ("AGENT_AUTH_CLAIM_ROLES", "EXTRA_AUTH_CLAIM_ROLES", "extra_auth_claim_roles"),
    (
        "AGENT_AUTH_CLAIM_ORGANIZATION_ID",
        "EXTRA_AUTH_CLAIM_ORGANIZATION_ID",
        "extra_auth_claim_organization_id",
    ),
)


class AuthMode(StrEnum):
    """How the host product proves who the caller is — the single knob a
    deployment turns, selecting a token policy rather than restating it."""

    ANONYMOUS = "anonymous"
    """No host identity. Every visitor gets a manager-issued pass."""

    HOST_TOKEN = "host_token"
    """Verify the host's own session token. Its lifetime is the host's call."""

    MINT = "mint"
    """The host mints a dedicated short-lived token for us, TTL capped here."""


def normalize_database_url(url: str, backend: str) -> str:
    if backend == "sqlite" and url.startswith("sqlite:///"):
        return "sqlite+aiosqlite:///" + url.removeprefix("sqlite:///")
    if backend == "postgres" and url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    extra_db_backend: Literal["sqlite", "postgres"] = "sqlite"
    extra_db_url: str | None = None
    database_url: str = "sqlite+aiosqlite:///chat.db"
    context_window: int = 10
    context_max_chars: int | None = None
    context_max_tokens: int | None = None
    snapshot_ttl_seconds: int = 86_400
    host: str = "0.0.0.0"
    port: int = 8100
    # Deny cross-origin by default; each deployment sets its own site(s),
    # e.g. CORS_ORIGINS=https://acmecorp.com,https://www.acmecorp.com
    cors_origins: Annotated[list[str], NoDecode] = []

    extra_auth_mode: AuthMode = AuthMode.ANONYMOUS
    extra_auth_secret: str | None = None
    # Derived from `extra_auth_secret` when unset, so visitor passes are never
    # signed with the host's key.
    extra_auth_anonymous_secret: str | None = None
    extra_auth_anonymous_ttl_seconds: int = THIRTY_DAYS_SECONDS
    extra_auth_max_ttl_seconds: int = ONE_HOUR_SECONDS
    extra_auth_issuer: str | None = None
    extra_auth_audience: str | None = None
    # Name of the host's session cookie. Only reachable when the manager is
    # served from the host's own origin — see `get_principal`.
    extra_auth_cookie: str | None = None
    extra_auth_claim_user_id: str = "sub"
    extra_auth_claim_email: str = "email"
    extra_auth_claim_display_name: str = "name"
    extra_auth_claim_roles: str = "roles"
    extra_auth_claim_organization_id: str = "org_id"

    @model_validator(mode="before")
    @classmethod
    def _backfill_deprecated_agent_vars(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        for old_env, new_env, new_key in _DEPRECATED_ENV_VARS:
            if new_key in data:
                continue
            old_key = old_env.lower()
            if old_key in data:
                warnings.warn(
                    f"{old_key} is deprecated; rename it to {new_key}.",
                    DeprecationWarning,
                    stacklevel=1,
                )
                data[new_key] = data[old_key]
                continue
            old_val = os.getenv(old_env)
            if old_val is not None:
                warnings.warn(
                    f"{old_env} is deprecated; rename it to {new_env}.",
                    DeprecationWarning,
                    stacklevel=1,
                )
                data[new_key] = old_val
        return data

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        return [o.strip() for o in v.split(",") if o.strip()] if isinstance(v, str) else v

    @model_validator(mode="after")
    def _require_secret_for_host_identity(self) -> Settings:
        if self.extra_auth_mode is not AuthMode.ANONYMOUS and not self.extra_auth_secret:
            raise ValueError(
                f"EXTRA_AUTH_SECRET is required when EXTRA_AUTH_MODE={self.extra_auth_mode}"
            )
        return self

    @classmethod
    def from_values(cls, **values: Any) -> Settings:
        """Explicit values only, ignoring any local `.env`, so callers that must
        be deterministic do not inherit a developer's file."""
        return cls(_env_file=None, **values)  # type: ignore[call-arg]

    @property
    def effective_database_url(self) -> str:
        return normalize_database_url(self.extra_db_url or self.database_url, self.extra_db_backend)
