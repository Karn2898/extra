"""Prompt rendering errors."""

from __future__ import annotations


class PromptRenderError(Exception):
    """Base error for prompt template loading or rendering failures."""


class MissingVariableError(PromptRenderError):
    """Raised when a template contains a variable that is not present in the render context."""

    def __init__(self, variable: str, template: str | None = None) -> None:
        self.variable = variable
        self.template = template
        if template:
            message = f"Missing required variable {variable!r} in template {template!r}"
        else:
            message = f"Missing required variable {variable!r}"
        super().__init__(message)
