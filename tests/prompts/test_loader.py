"""Tests for the prompt template loader/renderer."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from agent_engine.prompts import MissingVariableError, TemplateLoader


class TestParsedTemplate:
    def test_empty_template(self) -> None:
        parsed = TemplateLoader._parse("")
        assert parsed.literals == ("",)
        assert parsed.variables == ()

    def test_single_variable(self) -> None:
        parsed = TemplateLoader._parse("Hello {{name}}!")
        assert parsed.literals == ("Hello ", "!")
        assert parsed.variables == ("name",)

    def test_multiple_variables(self) -> None:
        parsed = TemplateLoader._parse("{{greeting}} {{name}}")
        assert parsed.literals == ("", " ", "")
        assert parsed.variables == ("greeting", "name")

    def test_whitespace_stripped(self) -> None:
        parsed = TemplateLoader._parse("{{  name  }}")
        assert parsed.variables == ("name",)


class TestTemplateLoaderRender:
    def test_render_success(self) -> None:
        loader = TemplateLoader(Path("/tmp"))
        parsed = loader._parse("Hello {{name}}!")
        assert loader.render(parsed, {"name": "World"}) == "Hello World!"

    def test_render_missing_variable_raises(self) -> None:
        loader = TemplateLoader(Path("/tmp"))
        parsed = loader._parse("Hello {{name}}!")
        with pytest.raises(MissingVariableError, match="name"):
            loader.render(parsed, {})

    def test_render_extra_context_ignored(self) -> None:
        loader = TemplateLoader(Path("/tmp"))
        parsed = loader._parse("Hello {{name}}!")
        assert loader.render(parsed, {"name": "World", "extra": "x"}) == "Hello World!"

    def test_render_empty_template(self) -> None:
        loader = TemplateLoader(Path("/tmp"))
        parsed = loader._parse("")
        assert loader.render(parsed, {}) == ""


class TestTemplateLoaderLoad:
    def test_load_missing_file_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            loader = TemplateLoader(Path(tmp))
            parsed = loader.load("nonexistent.md")
            assert parsed.literals == ("",)
            assert parsed.variables == ()

    def test_load_caches_by_mtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prompt.md"
            path.write_text("v1: {{x}}", encoding="utf-8")
            loader = TemplateLoader(Path(tmp))
            loader.load("prompt.md")
            assert loader._cache["prompt.md"][1].literals == ("v1: ", "")

            path.write_text("v2: {{x}}", encoding="utf-8")
            p2 = loader.load("prompt.md")
            assert p2.literals == ("v2: ", "")
            assert loader._cache["prompt.md"][1].literals == ("v2: ", "")

    def test_load_empty_path(self) -> None:
        loader = TemplateLoader(Path("/tmp"))
        parsed = loader.load("")
        assert parsed.literals == ("",)
        assert parsed.variables == ()
