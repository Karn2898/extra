"""Typed outcomes from the human-approval tool gate."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecuteTool:
    """The gate is open and the caller may execute the tool."""


@dataclass(frozen=True)
class DenyTool:
    """The gate is closed; ``message`` is returned instead of executing."""

    message: str


ToolGate = ExecuteTool | DenyTool
