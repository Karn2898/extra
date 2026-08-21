"""Claude Code adapter-generation target."""

from __future__ import annotations

from pathlib import Path

from tools.skills.adapter_files import (
    MARKDOWN_HEADER,
    build_adapter,
    remove_generated,
    remove_if_empty,
    remove_stale_in,
    write_adapter,
)
from tools.skills.target import Target


class ClaudeTarget(Target):
    name = "claude"

    def generate(
        self, root: Path, source_kind: str, ai_name: str, description: str, body: str
    ) -> Path:
        if source_kind == "skills":
            path = root / ".claude" / "skills" / ai_name / "SKILL.md"
        elif source_kind == "roles":
            path = root / ".claude" / "agents" / f"{ai_name}.md"
        else:
            path = root / ".claude" / "workflows" / f"{ai_name}.md"
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
        skill_names = source_names_by_kind.get("skills", set())
        skills_dir = root / ".claude" / "skills"
        if skills_dir.exists():
            for file in skills_dir.glob("*.md"):
                remove_generated(file, removed)
            for skill_dir in skills_dir.iterdir():
                if not skill_dir.is_dir():
                    continue
                skill_file = skill_dir / "SKILL.md"
                if skill_dir.name not in skill_names and skill_file.exists():
                    remove_generated(skill_file, removed)
                    remove_if_empty(skill_dir, removed)

        remove_stale_in(
            root / ".claude" / "agents", source_names_by_kind.get("roles", set()), removed
        )
        remove_stale_in(
            root / ".claude" / "workflows",
            source_names_by_kind.get("workflows", set()),
            removed,
        )
