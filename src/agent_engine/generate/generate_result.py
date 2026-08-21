"""Outcome of generating plugin and prompt stubs."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GenerateResult:
    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)
