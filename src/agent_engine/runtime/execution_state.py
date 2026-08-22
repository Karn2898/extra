"""Mutable, request-scoped counters used by the execution limiter."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExecutionState:
    """Counts and opaque signatures only; never prompts, arguments, or results."""

    iterations_by_node: dict[str, int] = field(default_factory=dict)
    total_tool_calls: int = 0
    tool_calls_by_agent: dict[str, int] = field(default_factory=dict)
    child_agent_calls: int = 0
    seen_signatures: set[str] = field(default_factory=set)
