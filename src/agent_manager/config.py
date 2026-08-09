"""Typed settings, read from the environment (and a .env file)."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ONE_HOUR_SECONDS = 3_600
THIRTY_DAYS_SECONDS = 2_592_000


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

    agent_db_backend: Literal["sqlite", "postgres"] = "sqlite"
    agent_db_url: str | None = None
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

    agent_auth_mode: AuthMode = AuthMode.ANONYMOUS
    agent_auth_secret: str | None = None
    # Derived from `agent_auth_secret` when unset, so visitor passes are never
    # signed with the host's key.
    agent_auth_anonymous_secret: str | None = None
    agent_auth_anonymous_ttl_seconds: int = THIRTY_DAYS_SECONDS
    agent_auth_max_ttl_seconds: int = ONE_HOUR_SECONDS
    agent_auth_issuer: str | None = None
    agent_auth_audience: str | None = None
    # Name of the host's session cookie. Only reachable when the manager is
    # served from the host's own origin — see `get_principal`.
    agent_auth_cookie: str | None = None
    agent_auth_claim_user_id: str = "sub"
    agent_auth_claim_email: str = "email"
    agent_auth_claim_display_name: str = "name"
    agent_auth_claim_roles: str = "roles"
    agent_auth_claim_organization_id: str = "org_id"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        return [o.strip() for o in v.split(",") if o.strip()] if isinstance(v, str) else v

    @model_validator(mode="after")
    def _require_secret_for_host_identity(self) -> Settings:
        if self.agent_auth_mode is not AuthMode.ANONYMOUS and not self.agent_auth_secret:
            raise ValueError(
                f"AGENT_AUTH_SECRET is required when AGENT_AUTH_MODE={self.agent_auth_mode}"
            )
        return self

    @classmethod
    def from_values(cls, **values: Any) -> Settings:
        """Explicit values only, ignoring any local `.env`, so callers that must
        be deterministic do not inherit a developer's file."""
        return cls(_env_file=None, **values)  # type: ignore[call-arg]

    @property
    def effective_database_url(self) -> str:
        return normalize_database_url(self.agent_db_url or self.database_url, self.agent_db_backend)
