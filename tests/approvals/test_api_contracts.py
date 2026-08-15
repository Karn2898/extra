"""API-layer contract logic: approval-error → HTTP mapping and the sanitized
pending-approval response model."""

from __future__ import annotations

from agent_engine.api.app import _pending_model
from agent_engine.approvals.errors import (
    ApprovalAlreadyProcessed,
    ApprovalError,
    ApprovalNotFound,
    ApprovalRunMismatch,
    InvalidDecision,
    RunNotFound,
    UnauthorizedApprover,
    approval_http_status,
    approval_public_message,
)
from agent_engine.engine.types import PendingApproval


def test_error_status_mapping() -> None:
    assert approval_http_status(RunNotFound("r")) == 404
    assert approval_http_status(ApprovalNotFound("a")) == 404
    assert approval_http_status(ApprovalRunMismatch("a", "r")) == 404
    assert approval_http_status(UnauthorizedApprover("a")) == 403
    assert approval_http_status(ApprovalAlreadyProcessed("a", "approved")) == 409
    assert approval_http_status(InvalidDecision("maybe")) == 400


def test_error_messages_are_stable_and_sanitized() -> None:
    exc = ApprovalRunMismatch("private-approval-id", "private-run-id")
    assert approval_public_message(exc) == "approval not found"
    assert "private" not in approval_public_message(exc)
    assert approval_public_message(ApprovalError("private internal failure")) == (
        "approval could not be processed"
    )


def test_pending_model_none_passthrough() -> None:
    assert _pending_model(None) is None


def test_pending_model_carries_sanitized_fields() -> None:
    pa = PendingApproval(
        run_id="r1",
        approval_id="ap1",
        agent_id="writer",
        tool_name="send_email",
        description="agent 'writer' wants to call 'send_email'",
        provider="mcp",
        server_id="srv",
        arguments={"to": "x@y.com", "api_key": "***redacted***"},
    )
    model = _pending_model(pa)
    assert model is not None
    assert model.run_id == "r1"
    assert model.approval_id == "ap1"
    assert model.tool_name == "send_email"
    assert model.description == "agent 'writer' wants to call 'send_email'"
    assert model.provider == "mcp"
    assert model.arguments["api_key"] == "***redacted***"
