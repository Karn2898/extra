"""An MCP tool's result reaches the model as clean text, not a repr string.

MCP tools are LangChain ``StructuredTool``s built with
``response_format="content_and_artifact"``: their real return value is a list
of content blocks (``[{"type": "text", "text": "..."}]``), not a plain string.
Calling them the wrong way (a bare args dict, no ``tool_call_id``) makes
LangChain hand back that raw list unwrapped, and blindly ``str()``-ing it
produces Python-repr punctuation instead of the text itself. These tests drive
a real ``content_and_artifact`` tool through the engine (the same way
``tests/runtime/test_tool_hooks.py`` injects a fake MCP tool) and inspect the
exact text the model received.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.messages.tool import ToolCall
from langchain_core.tools import StructuredTool

from agent_engine.core.spec import (
    AgentSpec,
    BasePromptSet,
    GraphNode,
    HooksConfig,
    MCPSpec,
    ModelConfig,
    SystemMeta,
    SystemSpec,
    ToolSpec,
)
from agent_engine.engine.langgraph.engine import LangGraphEngine

_MODEL = ModelConfig(provider="fake", name="fake", temperature=None)


class EchoToolResultModel:
    """Calls the tool once, then answers with exactly the tool result text it
    was given — lets a test see precisely what reached the conversation.
    """

    def __init__(
        self, tool_names: list[str] | None = None, tool_args: dict[str, Any] | None = None
    ) -> None:
        self._tool_names = tool_names or []
        self._tool_args = tool_args or {}

    def bind_tools(self, tools: list[Any]) -> EchoToolResultModel:
        return EchoToolResultModel([t.name for t in tools], self._tool_args)

    async def ainvoke(self, messages: list[Any]) -> AIMessage:
        return self._respond(messages)

    async def astream(self, messages: list[Any]) -> AsyncIterator[AIMessage]:
        yield self._respond(messages)

    def _respond(self, messages: list[Any]) -> AIMessage:
        tool_msgs = [m for m in messages if isinstance(m, ToolMessage)]
        if self._tool_names and not tool_msgs:
            return AIMessage(
                content="",
                tool_calls=[ToolCall(name=self._tool_names[0], args=self._tool_args, id="c1")],
            )
        return AIMessage(content=tool_msgs[-1].content if tool_msgs else "no-tool")


def _model_factory(
    tool_args: dict[str, Any] | None = None,
) -> Any:
    def factory(provider: str, name: str, temperature: float | None) -> BaseChatModel:
        return cast(BaseChatModel, EchoToolResultModel(tool_args=tool_args))

    return factory


def _agent(node_id: str, **kw: Any) -> GraphNode:
    kw.setdefault("auto_mode", True)
    return GraphNode(
        node=AgentSpec(
            id=node_id,
            name=node_id,
            description=f"{node_id} agent",
            model=_MODEL,
            prompts=BasePromptSet(),
            **kw,
        )
    )


def _system(graph: GraphNode) -> SystemSpec:
    return SystemSpec(
        meta=SystemMeta(name="mcp-result-extraction"),
        defaults=None,
        graph=graph,
        hooks=HooksConfig(hooks=()),
    )


async def _run_with_mcp_tool(tmp_path: Path, mcp_tool: StructuredTool) -> str:
    spec = _system(_agent("research", mcps=(MCPSpec(id="wiki", url="https://wiki.test/mcp"),)))
    async with LangGraphEngine(tmp_path, model_factory=_model_factory()) as engine:
        await engine.build(spec)
        engine._mcp_tools["wiki"] = [mcp_tool]
        engine._app = engine._build_graph(spec)
        result = await engine.run("search please")
    return result.answer


async def test_mcp_text_result_is_not_garbled(tmp_path: Path) -> None:
    def fake_mcp_tool() -> tuple[list[dict[str, str]], dict[str, Any]]:
        return [{"type": "text", "text": "clean text", "id": "lc_1"}], {
            "structuredContent": {"value": "clean text"}
        }

    mcp_tool = StructuredTool.from_function(
        fake_mcp_tool,
        name="wiki_search",
        description="search",
        response_format="content_and_artifact",
    )

    answer = await _run_with_mcp_tool(tmp_path, mcp_tool)

    assert answer == "clean text"
    assert "'type':" not in answer
    assert "'text':" not in answer


async def test_mcp_multi_block_text_result_is_joined(tmp_path: Path) -> None:
    def fake_mcp_tool() -> tuple[list[dict[str, str]], dict[str, Any]]:
        return [
            {"type": "text", "text": "first block", "id": "lc_1"},
            {"type": "text", "text": "second block", "id": "lc_2"},
        ], {}

    mcp_tool = StructuredTool.from_function(
        fake_mcp_tool,
        name="wiki_search",
        description="search",
        response_format="content_and_artifact",
    )

    answer = await _run_with_mcp_tool(tmp_path, mcp_tool)

    assert "first block" in answer
    assert "second block" in answer
    assert "'type':" not in answer


def _write_tool(base_dir: Path, tool_id: str) -> None:
    body = f"def {tool_id}(message: str) -> str:\n    return 'did: ' + message\n"
    tools_dir = base_dir / "plugins" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    (tools_dir / f"{tool_id}.py").write_text(body, encoding="utf-8")


async def test_local_tool_result_unaffected(tmp_path: Path) -> None:
    # Local tools default to response_format="content" (a plain string, not
    # MCP content blocks) — regression guard that this fix leaves that path
    # exactly as before.
    _write_tool(tmp_path, "book_flight")
    spec = _system(_agent("flights", tools=(ToolSpec("book_flight", "book"),)))

    factory = _model_factory(tool_args={"message": "go"})
    async with LangGraphEngine(tmp_path, model_factory=factory) as engine:
        await engine.build(spec)
        result = await engine.run("book please")

    assert result.answer == "did: go"
