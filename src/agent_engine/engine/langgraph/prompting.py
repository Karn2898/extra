"""Prompt-template loading and request-time placeholder rendering."""

from __future__ import annotations

import re
from pathlib import Path


def render_prompt(template: str, context: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        return context.get(match.group(1).strip(), match.group(0))

    return re.sub(r"\{\{\s*(\w+)\s*\}\}", replace, template)


def load_file(base_dir: Path, relative_path: str | None) -> str:
    if not relative_path:
        return ""
    path = base_dir / relative_path
    return path.read_text(encoding="utf-8") if path.is_file() else ""
