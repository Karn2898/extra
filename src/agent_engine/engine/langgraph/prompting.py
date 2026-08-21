"""Prompt-template loading and request-time placeholder rendering."""

from __future__ import annotations

import re
from pathlib import Path

from agent_engine.core.spec import NodeSpec
from agent_engine.loaders.resolver_loader import ResolverLoader


def render_prompt(template: str, context: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        return context.get(match.group(1).strip(), match.group(0))

    return re.sub(r"\{\{\s*(\w+)\s*\}\}", replace, template)


def resolve_prompt_context(loader: ResolverLoader, spec: NodeSpec) -> dict[str, str]:
    """Run a node's declared resolvers and return the accumulated key→value map.

    Resolvers run in declaration order, each seeing earlier values, and are
    never cached — a resolver may answer differently for each caller.
    """
    context: dict[str, str] = {}
    for resolver in spec.resolvers:
        context[resolver.id] = str(loader.load(spec.id, resolver.id)(context))
    return context


def load_file(base_dir: Path, relative_path: str | None) -> str:
    if not relative_path:
        return ""
    path = base_dir / relative_path
    return path.read_text(encoding="utf-8") if path.is_file() else ""
