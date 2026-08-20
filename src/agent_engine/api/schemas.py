"""HTTP request and response schemas for the stateless engine API."""

from __future__ import annotations

from typing import Annotated, Any, TypeAlias

from pydantic import BaseModel, WithJsonSchema

from agent_engine.approvals.models import RunStatus

_RUN_STATUS_FIELD: TypeAlias = Annotated[
    RunStatus,
    WithJsonSchema({"title": "Status", "type": "string"}),
]


class InvokeRequest(BaseModel):
    message: str


class ToolRecord(BaseModel):
    name: str
    provider: str
    status: str
    agent_id: str | None = None
    server_id: str | None = None
    error: str | None = None


class PendingApprovalModel(BaseModel):
    """Sanitized pending-approval payload returned to the client/UI."""

    run_id: str
    approval_id: str
    agent_id: str
    tool_name: str
    description: str
    provider: str
    server_id: str | None = None
    arguments: dict[str, Any] = {}


class InvokeResponse(BaseModel):
    system_name: str
    answer: str
    visited: list[str]
    used_tools: list[ToolRecord]
    run_id: str
    status: _RUN_STATUS_FIELD = RunStatus.COMPLETED
    pending_approval: PendingApprovalModel | None = None


class ApprovalDecisionRequest(BaseModel):
    user_id: str | None = None


class ApprovalDecisionBody(ApprovalDecisionRequest):
    decision: str


class RunStatusResponse(BaseModel):
    run_id: str
    status: _RUN_STATUS_FIELD
    pending_approval: PendingApprovalModel | None = None
