"""Synchronize canonical .ai instructions into tool-specific adapters."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tools.skills.adapter_files import read_source
from tools.skills.claude_target import ClaudeTarget
from tools.skills.codex_target import CodexTarget
from tools.skills.target import Target

ROOT = Path(__file__).parent.parent.parent

SOURCE_KINDS: dict[str, str] = {
    "skills": "skill",
    "roles": "role",
    "workflows": "workflow",
}

TARGETS: dict[str, Target] = {
    "claude": ClaudeTarget(),
    "codex": CodexTarget(),
}


def sync(
    root: Path | None = None,
    *,
    targets: list[str] | None = None,
) -> int:
    """Generate adapters. targets=None means all registered targets."""
    root = root or ROOT

    active_targets = (
        [TARGETS[t] for t in targets if t in TARGETS] if targets else list(TARGETS.values())
    )

    if not active_targets:
        known = ", ".join(TARGETS)
        print(f"error: unknown target(s). Known targets: {known}", file=sys.stderr)
        return 1

    generated: list[Path] = []
    removed: list[Path] = []
    source_names_by_kind: dict[str, set[str]] = {}

    for source_kind, kind_label in SOURCE_KINDS.items():
        source_dir = root / ".ai" / source_kind
        names: set[str] = set()
        for source_file in sorted(source_dir.glob("*.md")):
            ai_name, description, body = read_source(source_file, kind=kind_label)
            names.add(ai_name)
            for target in active_targets:
                path = target.generate(root, source_kind, ai_name, description, body)
                generated.append(path)
        source_names_by_kind[source_kind] = names

    for target in active_targets:
        target.remove_stale(root, source_names_by_kind, removed)

    target_names = ", ".join(t.name for t in active_targets)
    total_sources = sum(len(v) for v in source_names_by_kind.values())
    print(
        f"generated {len(generated)} adapter(s) for [{target_names}] from {total_sources} source(s)"
    )
    for path in sorted(generated, key=lambda p: str(p.relative_to(root))):
        print(f"  + {path.relative_to(root)}")
    if removed:
        print(f"removed {len(removed)} stale adapter(s)")
        for path in sorted(removed, key=lambda p: str(p.relative_to(root))):
            print(f"  - {path.relative_to(root)}")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate tool adapters from .ai/ (single source of truth).",
    )
    parser.add_argument(
        "--target",
        metavar="NAME",
        action="append",
        dest="targets",
        help=(
            f"target to generate (choices: {', '.join(TARGETS)}); repeat for multiple; omit for all"
        ),
    )
    args = parser.parse_args(argv)
    return sync(targets=args.targets)


if __name__ == "__main__":
    sys.exit(main())
