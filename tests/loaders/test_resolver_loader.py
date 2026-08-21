"""Coverage for resolver instance caching and missing-method failures."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_engine.loaders.resolver_loader import ResolverLoader, ResolverLoaderError


def _write_resolver(base_dir: Path) -> None:
    resolvers = base_dir / "plugins" / "resolvers"
    resolvers.mkdir(parents=True)
    (resolvers / "researcher.py").write_text(
        """
class Resolver:
    def __init__(self):
        self.calls = 0

    def topic(self, context):
        self.calls += 1
        return f"{context['topic']}:{self.calls}"
""",
        encoding="utf-8",
    )


def test_load_reuses_one_cached_instance_per_node(tmp_path: Path) -> None:
    _write_resolver(tmp_path)
    loader = ResolverLoader(tmp_path)

    first = loader.load("researcher", "topic")({"topic": "runtime"})
    second = loader.load("researcher", "topic")({"topic": "security"})

    assert (first, second) == ("runtime:1", "security:2")


def test_load_rejects_an_unknown_resolver_id(tmp_path: Path) -> None:
    _write_resolver(tmp_path)
    loader = ResolverLoader(tmp_path)

    with pytest.raises(ResolverLoaderError, match="has no method 'missing'"):
        loader.load("researcher", "missing")
