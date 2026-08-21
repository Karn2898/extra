"""Codex adapter-generation target."""

from __future__ import annotations

from pathlib import Path

from tools.skills.adapter_files import (
    MARKDOWN_HEADER,
    build_adapter,
    remove_stale_in,
    write_adapter,
)
from tools.skills.target import Target


class CodexTarget(Target):
    name = "codex"

    @staticmethod
    def _adapter_subdir(source_kind: str) -> str:
        return "agents" if source_kind == "roles" else source_kind

    def generate(
        self, root: Path, source_kind: str, ai_name: str, description: str, body: str
    ) -> Path:
        path = root / ".codex" / self._adapter_subdir(source_kind) / f"{ai_name}.md"
        write_adapter(
            path,
            build_adapter(
                MARKDOWN_HEADER,
                name=ai_name,
                description=description,
                body=body,
                source_kind=source_kind,
            ),
        )
        return path

    def remove_stale(
        self, root: Path, source_names_by_kind: dict[str, set[str]], removed: list[Path]
    ) -> None:
        remove_stale_in(
            root / ".codex" / "skills", source_names_by_kind.get("skills", set()), removed
        )
        remove_stale_in(
            root / ".codex" / "agents", source_names_by_kind.get("roles", set()), removed
        )
        remove_stale_in(
            root / ".codex" / "workflows",
            source_names_by_kind.get("workflows", set()),
            removed,
        )
