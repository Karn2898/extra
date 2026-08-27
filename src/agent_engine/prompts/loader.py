"""Template loading, parsing, and strict rendering.

Parsed templates are cached by file path plus modification time; rendered
output is never cached. Missing variables raise ``MissingVariableError``.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from pathlib import Path

from agent_engine.prompts.errors import MissingVariableError

logger = logging.getLogger(__name__)

_VAR_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


@dataclasses.dataclass(frozen=True)
class ParsedTemplate:
    """A parsed prompt template.

    ``literals`` holds the literal text segments; ``variables`` holds the
    variable names in the order they appear.  Rendering interleaves them as::

        literals[0] + variables[0] + literals[1] + ... + variables[N-1] + literals[N]

    An empty template is represented as ``literals=("",)`` and ``variables=()``.
    """

    literals: tuple[str, ...]
    variables: tuple[str, ...]


class TemplateLoader:
    """Loads, parses, and renders prompt templates.

    Templates are parsed once and cached by ``(rel_path, mtime)``.  The cache
    is invalidated automatically when the underlying file changes.  Rendered
    strings are never cached.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._cache: dict[str, tuple[float, ParsedTemplate]] = {}

    def load(self, rel_path: str) -> ParsedTemplate:
        """Return the parsed template for *rel_path*, reading and caching if needed."""
        if not rel_path:
            return ParsedTemplate(("",), ())

        path = self._base_dir / rel_path
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return ParsedTemplate(("",), ())

        cached = self._cache.get(rel_path)
        if cached and cached[0] == mtime:
            return cached[1]

        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        parsed = self._parse(text)
        self._cache[rel_path] = (mtime, parsed)
        logger.debug("parsed template %s (%d variables)", rel_path, len(parsed.variables))
        return parsed

    @staticmethod
    def _parse(text: str) -> ParsedTemplate:
        literals: list[str] = []
        variables: list[str] = []
        last_end = 0
        for match in _VAR_RE.finditer(text):
            literals.append(text[last_end : match.start()])
            variables.append(match.group(1).strip())
            last_end = match.end()
        literals.append(text[last_end:])
        return ParsedTemplate(tuple(literals), tuple(variables))

    def render(self, parsed: ParsedTemplate, ctx: dict[str, str]) -> str:
        """Interpolate *parsed* with values from *ctx*.

        Strict mode: every variable must be present in *ctx*.
        """
        parts: list[str] = []
        for literal, var in zip(parsed.literals, parsed.variables, strict=False):
            parts.append(literal)
            if var not in ctx:
                raise MissingVariableError(var)
            parts.append(ctx[var])
        parts.append(parsed.literals[-1])
        return "".join(parts)
