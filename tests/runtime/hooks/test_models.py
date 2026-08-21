"""AuthContext.inbound_access_token must never appear in a repr — reprs reach
logs and tracebacks by accident, and this is a credential."""

from __future__ import annotations

from agent_engine.runtime.hooks.models import AuthContext, RunContext

TOKEN = "super-secret-token"


def test_the_token_is_not_in_auth_context_repr() -> None:
    auth = AuthContext(inbound_access_token=TOKEN)

    assert TOKEN not in repr(auth)


def test_the_token_is_not_in_run_context_repr() -> None:
    ctx = RunContext(auth_context=AuthContext(inbound_access_token=TOKEN))

    assert TOKEN not in repr(ctx)
