"""Resolved runtime hook ready for ordered execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_engine.runtime.hooks.models import HookPoint


@dataclass(frozen=True)
class LoadedHook:
    point: HookPoint
    ref: str
    func: Any
    failure_policy: str = "fail"
    plugin: str | None = None
    method: str | None = None
    event_mode: bool = False
