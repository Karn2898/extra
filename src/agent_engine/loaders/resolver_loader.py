from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_engine.loaders._import import import_from_path, register_shared_module


class ResolverLoaderError(RuntimeError):
    pass


class ResolverLoader:
    """Loads per-node resolver classes from plugins/resolvers/{node_id}.py.

    Each file must contain a class named Resolver. The class is instantiated
    once per node_id and cached — shared resources (DB connections, clients)
    are initialized in __init__ and reused across resolver calls. Resolved
    values are never cached; every run resolves again.

    If plugins/resolvers/shared.py exists, it is loaded first and registered in
    sys.modules as "shared" so node files can inherit from SharedResolver via
    `from shared import SharedResolver`.

    Resolver methods are named after resolver IDs and accept a single ctx dict.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._instances: dict[str, Any] = {}
        self._shared_loaded = False

    def load(self, node_id: str, resolver_id: str) -> Callable[[dict[str, Any]], Any]:
        instance = self._get_or_create(node_id)
        method = getattr(instance, resolver_id, None)
        if method is None or not callable(method):
            cls_name = type(instance).__name__
            raise ResolverLoaderError(
                f"Resolver class '{cls_name}' for node '{node_id}' has no method '{resolver_id}'"
            )
        return method

    def _get_or_create(self, node_id: str) -> Any:
        if node_id not in self._instances:
            self._instances[node_id] = self._instantiate(node_id)
        return self._instances[node_id]

    def _instantiate(self, node_id: str) -> Any:
        resolvers_dir = self._base_dir / "plugins" / "resolvers"
        self._ensure_shared_module(resolvers_dir)
        path = resolvers_dir / f"{node_id}.py"
        if not path.is_file():
            raise ResolverLoaderError(
                f"Resolver plugin not found: {path}\nRun `agentctl generate` to create the stub."
            )
        module = import_from_path(path)
        cls = getattr(module, "Resolver", None)
        if cls is None or not isinstance(cls, type):
            raise ResolverLoaderError(f"{path} must define a class named 'Resolver'")
        try:
            return cls()
        except Exception as exc:
            raise ResolverLoaderError(
                f"Failed to instantiate Resolver for node '{node_id}': {exc}"
            ) from exc

    def _ensure_shared_module(self, resolvers_dir: Path) -> None:
        """Load shared.py once and register it as sys.modules['shared'].

        This lets node resolver files do `from shared import SharedResolver`
        without needing shared.py on the Python path.
        """
        if self._shared_loaded:
            return
        self._shared_loaded = True
        register_shared_module(resolvers_dir)
