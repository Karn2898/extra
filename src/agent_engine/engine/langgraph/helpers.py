from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent_engine.core.spec import AgentSpec, GraphNode, NodeSpec, OrchestratorSpec
from agent_engine.loaders.resolver_loader import ResolverLoader
from agent_engine.runtime.execution import ExecutionLimitExceeded, current_execution, log_limit
from agent_engine.runtime.hooks import current_run_context
from agent_engine.runtime.state import GraphState
from agent_engine.runtime.streaming import current_streams
from agent_engine.tool_usage.context import ToolUsageContextProvider, ToolUsageScope

logger = logging.getLogger(__name__)


def current_usage_scope(agent_id: str | None = None) -> ToolUsageScope:
    """The ambient scope to report tool usage for: this conversation, this run."""
    ctx = current_run_context.get()
    if ctx is None:
        return ToolUsageScope(agent_id=agent_id)
    return ToolUsageScope(run_id=ctx.run_id, conversation_id=ctx.conversation_id, agent_id=agent_id)


ExecutionContextRefresher = Callable[[], Awaitable[str | None]]


def execution_context_refresher(
    provider: ToolUsageContextProvider, agent_id: str
) -> ExecutionContextRefresher:
    """Bind a usage provider to one agent's ambient scope, ready to re-read.

    Nodes hold the result and know nothing about scopes, records, or wording;
    they only ask for the latest execution context.
    """

    async def refresh() -> str | None:
        context = await provider.get(current_usage_scope(agent_id))
        return context.render()

    return refresh


class ModelContext:
    """The ordered messages for one node's model turns.

    Layout: system instructions, an optional private execution-context system
    message, prior conversation turns, then the current user message. Keeping the
    execution slot beside the system prompt — never as a user or assistant turn —
    is what stops runtime metadata from entering the conversation history the
    caller persists or reaching the user. The slot can be refreshed between model
    turns, so a node learns what its children ran while it was waiting.
    """

    _EXECUTION_SLOT = 1

    def __init__(
        self,
        system_prompt: str,
        history: list[dict[str, str]],
        user_message: str,
    ) -> None:
        self._messages: list[Any] = [SystemMessage(content=system_prompt)]
        self._has_execution_context = False
        for message in history:
            role = message.get("role")
            content = message.get("content", "")
            if role == "user":
                self._messages.append(HumanMessage(content=content))
            elif role == "assistant":
                self._messages.append(AIMessage(content=content))
            else:
                raise ValueError(f"Unsupported conversation history role: {role!r}")
        self._messages.append(HumanMessage(content=user_message))

    @property
    def messages(self) -> list[Any]:
        """The live message list handed to the model."""
        return self._messages

    def append(self, message: Any) -> None:
        """Add one model response or tool result to the running turn."""
        self._messages.append(message)

    def set_execution_context(self, text: str | None) -> None:
        """Install, replace, or drop the private execution-context message.

        It stays adjacent to the system prompt, so providers that require a
        single leading system block still see consecutive system messages.
        """
        if self._has_execution_context:
            self._messages.pop(self._EXECUTION_SLOT)
            self._has_execution_context = False
        if text:
            self._messages.insert(self._EXECUTION_SLOT, SystemMessage(content=text))
            self._has_execution_context = True


def node_id(node: GraphNode, parent_path: str | None) -> str:
    return f"{parent_path}/{node.node.id}" if parent_path else node.node.id


def render_prompt(template: str, ctx: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        return ctx.get(match.group(1).strip(), match.group(0))

    return re.sub(r"\{\{\s*(\w+)\s*\}\}", replace, template)


def resolve_prompt_context(loader: ResolverLoader, spec: NodeSpec) -> dict[str, str]:
    """Run a node's declared resolvers and return the accumulated key→value map.

    Resolvers are invoked in declaration order; each receives the values
    produced by previous ones so they can build on one another. Resolution
    happens per run and is never cached — a resolver may answer differently
    for each caller.
    """
    ctx: dict[str, str] = {}
    for resolver in spec.resolvers:
        ctx[resolver.id] = str(loader.load(spec.id, resolver.id)(ctx))
    return ctx


def load_file(base_dir: Path, rel_path: str | None) -> str:
    if not rel_path:
        return ""
    path = base_dir / rel_path
    return path.read_text(encoding="utf-8") if path.is_file() else ""


async def invoke_model(model: Any, messages: list[Any], state: GraphState) -> Any:
    sinks = current_streams.get()
    answer_stream = sinks.answer
    if answer_stream is None:
        response = await model.ainvoke(messages)
        usage = getattr(response, "usage_metadata", None)
        if sinks.token is not None and usage:
            sinks.token(usage.get("input_tokens", 0), usage.get("output_tokens", 0))
        return response

    streamed = None
    try:
        async for chunk in model.astream(messages):
            streamed = chunk if streamed is None else streamed + chunk
            text = as_text(getattr(chunk, "content", ""))
            if text:
                answer_stream(text)
    finally:
        # Providers commonly attach usage to a final stream chunk. Reading the
        # accumulated partial response in ``finally`` preserves any usage they
        # reported even when the consumer cancels before normal completion.
        usage = getattr(streamed, "usage_metadata", None)
        if sinks.token is not None and usage:
            sinks.token(usage.get("input_tokens", 0), usage.get("output_tokens", 0))
    return streamed or AIMessage(content="")


async def run_tool_loop(
    model: Any,
    context: ModelContext,
    state: GraphState,
    node_path: str,
    invoke_tool: Callable[[dict[str, Any]], Awaitable[str]],
    *,
    refresh_execution_context: ExecutionContextRefresher | None = None,
) -> Any:
    """Drive the model → tools → model loop until the model stops calling tools.

    ``invoke_tool`` executes one tool call and returns its result as text. Each
    caller supplies its own: an agent runs real/MCP tools, an orchestrator runs
    child agents exposed as tools. The final (tool-call-free) model response is
    returned.

    ``refresh_execution_context`` is re-read before every model turn, so the turn
    that synthesises an answer reflects what the tools (or child agents) called in
    this same turn actually did.
    """
    limiter = current_execution.get()
    await _refresh(context, refresh_execution_context)
    response = await invoke_model(model, context.messages, state)
    while getattr(response, "tool_calls", None):
        if limiter is not None:
            try:
                limiter.register_iteration(node_path)
            except ExecutionLimitExceeded as exc:
                log_limit(exc)
                break
        context.append(response)
        for tc in response.tool_calls:
            logger.debug("[%s] ← tool_call: %s(%s)", node_path, tc["name"], tc["args"])
            content = await invoke_tool(tc)
            logger.debug("[%s] → tool_result[%s]: %s", node_path, tc["name"], content[:300])
            context.append(ToolMessage(content=content, tool_call_id=tc["id"], name=tc["name"]))
        await _refresh(context, refresh_execution_context)
        response = await invoke_model(model, context.messages, state)
    return response


async def _refresh(
    context: ModelContext,
    refresh_execution_context: ExecutionContextRefresher | None,
) -> None:
    if refresh_execution_context is not None:
        context.set_execution_context(await refresh_execution_context())


def emit_route(state: GraphState, route: tuple[str, ...]) -> None:
    fn = current_streams.get().route
    if fn is not None:
        fn(route)


def as_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b["text"] for b in content if isinstance(b, dict) and isinstance(b.get("text"), str)
        )
    return str(content)


def has_protected_nodes(node: GraphNode) -> bool:
    if node.node.protected:
        return True
    return any(has_protected_nodes(c) for c in node.children)


def walk(node: GraphNode) -> list[GraphNode]:
    """Flatten the spec tree, parents before children."""
    out = [node]
    for child in node.children:
        out.extend(walk(child))
    return out


def render_graph(node: GraphNode, depth: int = 0) -> list[str]:
    """Render the spec tree as indented lines (e.g. for the startup log)."""
    spec = node.node
    kind = "orchestrator" if isinstance(spec, OrchestratorSpec) else "agent"
    label = f"{'  ' * (depth + 1)}{kind} '{spec.name or spec.id}'"
    if isinstance(spec, AgentSpec):
        extras = []
        if spec.tools:
            extras.append("tools: " + ", ".join(t.id for t in spec.tools))
        if spec.mcps:
            extras.append("mcps: " + ", ".join(m.id for m in spec.mcps))
        if extras:
            label += f" [{'; '.join(extras)}]"
    if spec.protected:
        label += " (protected)"
    lines = [label]
    for child in node.children:
        lines.extend(render_graph(child, depth + 1))
    return lines


def collect_mcp_specs(node: GraphNode) -> dict[str, Any]:
    """Return {server_id: MCPSpec} for every unique MCP server in the graph."""
    from agent_engine.core.spec import MCPSpec

    result: dict[str, MCPSpec] = {}
    if isinstance(node.node, AgentSpec):
        for mcp in node.node.mcps:
            result.setdefault(mcp.id, mcp)
    for child in node.children:
        result.update(collect_mcp_specs(child))
    return result
