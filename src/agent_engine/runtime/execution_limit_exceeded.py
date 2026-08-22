"""Safe failure raised when a configured execution limit is reached."""

from __future__ import annotations


class ExecutionLimitExceeded(Exception):
    def __init__(
        self,
        limit_name: str,
        count: int,
        limit: int,
        *,
        node_id: str | None = None,
        agent_id: str | None = None,
        tool_name: str | None = None,
    ) -> None:
        self.limit_name = limit_name
        self.count = count
        self.limit = limit
        self.node_id = node_id
        self.agent_id = agent_id
        self.tool_name = tool_name
        super().__init__(f"execution limit '{limit_name}' reached ({count} > {limit})")
