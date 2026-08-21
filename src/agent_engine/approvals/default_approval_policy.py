"""Default deterministic tool-approval policy."""

from __future__ import annotations

from agent_engine.approvals.approval_policy import ApprovalPolicy, ApprovalQuery


class DefaultApprovalPolicy(ApprovalPolicy):
    """Require approval unless auto mode or a session grant bypasses it."""

    def requires_approval(self, query: ApprovalQuery) -> bool:
        if query.auto_mode:
            return False
        return not query.session_allowed
