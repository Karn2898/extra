"""Composition root + `agent-manager` console entrypoint.

Self-contained: does not import `agentctl`, so `agent_manager` depends only on
`agent_engine`.
"""

from __future__ import annotations

from pathlib import Path

import click
from dotenv import load_dotenv


def _playground_url(host: str, port: int) -> str:
    if host in {"0.0.0.0", "::"}:
        display_host = "localhost"
    elif ":" in host and not host.startswith("["):
        display_host = f"[{host}]"
    else:
        display_host = host
    return f"http://{display_host}:{port}/playground"


@click.command()
@click.option("--config", required=True, help="Path to agents.yml")
@click.option("--host", default=None, help="Host to bind to (overrides settings)")
@click.option("--port", default=None, type=int, help="Port to listen on (overrides settings)")
@click.option("--env", default=None, help="Path to .env file (defaults to .env beside config)")
@click.option("--migrate/--no-migrate", default=True, help="Run DB migrations before serving")
def main(config: str, host: str | None, port: int | None, env: str | None, migrate: bool) -> None:
    """Serve the chat lifecycle API (sessions + history) over HTTP."""
    import uvicorn

    from agent_manager.api import create_app
    from agent_manager.config import Settings

    env_path = Path(env) if env else Path(config).resolve().parent / ".env"
    load_dotenv(env_path, override=True)

    settings = Settings()
    if migrate:
        from agent_manager.infrastructure.persistence.database import upgrade_database

        upgrade_database()

    app = create_app(config, settings)
    bind_host = host or settings.host
    bind_port = port or settings.port
    click.echo(f"Playground: {_playground_url(bind_host, bind_port)}")
    uvicorn.run(app, host=bind_host, port=bind_port)


if __name__ == "__main__":
    main()
