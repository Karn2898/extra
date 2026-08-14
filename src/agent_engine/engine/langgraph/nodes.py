"""LangGraph node callables.

``AgentNode``        — runs a single agent: resolve context → build prompt → tool loop.
``OrchestratorNode`` — supervisor agent that calls child agents as tools and synthesizes.

Neither node owns tool-execution or tool-usage state: a node asks its
:class:`ToolInvoker` to run a call, and asks its
:class:`ToolUsageContextProvider` what the run has already done.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.errors import GraphInterrupt
from pydantic import BaseModel

from agent_engine.core.spec import AgentSpec, OrchestratorSpec
from agent_engine.engine.langgraph.executed_tools_tool import (
    EXECUTED_TOOLS_TOOL_NAME,
    build_executed_tools_tool,
)
from agent_engine.engine.langgraph.filters import RouteFilter
from agent_engine.engine.langgraph.helpers import (
    ModelContext,
    as_text,
    current_usage_scope,
    emit_route,
    execution_context_refresher,
    load_file,
    render_prompt,
    run_tool_loop,
)
from agent_engine.engine.langgraph.tool_invoker import ToolInvoker
from agent_engine.loaders.resolver_loader import ResolverLoader
from agent_engine.runtime.execution import (
    ExecutionLimitExceeded,
    blocked_message,
    current_execution,
    log_limit,
)
from agent_engine.runtime.state import GraphState
from agent_engine.runtime.streaming import current_streams
from agent_engine.tool_usage.context import ToolUsageContextProvider
from agent_engine.tool_usage.models import (
    ToolCallIdentity,
    ToolInvocationKind,
    stable_tool_call_id,
)
from agent_engine.tool_usage.tracker import ToolUsageTracker

logger = logging.getLogger(__name__)


_ORCHESTRATOR_CONTRACT = """
## Instructions
- You MUST use the available agent tools to answer requests. Never answer from general knowledge.
- Only call a tool if its name/description clearly matches the request.
  Do NOT call a tool for something outside its stated scope.
- If no appropriate tool exists for part of the request, say: "I'm not able to help with that."
- You may call multiple tools if the request covers several topics.
- The tools available to you are other AGENTS, not actions. Calling one hands the request
  to that agent; the agent, not you, performs the work with its own tools. Never describe an
  agent you called as a tool that ran.
- When the user asks which tools have run or what has already been done, call
  `list_executed_tools` and answer from its result — never from your own tool list.
"""


class _AgentCall(BaseModel):
    """Input schema for a child-agent tool."""

    message: str


@dataclass(frozen=True)
class ChildEntry:
    """A child node ready to be exposed as a tool by its parent orchestrator.

    Decoupled from the spec layer (``GraphNode``): the orchestrator only needs
    the child's identity, a human-readable description, its protection flag (for
    access filtering), and the runtime callable to invoke.
    """

    id: str
    name: str
    protected: bool
    callable: AgentNode | OrchestratorNode
    description: str = ""

    @property
    def tool_description(self) -> str:
        """How this child is described to the parent's model.

        Named as a delegation rather than an action, because a child bound as a
        plain tool reads to the model as something it performs itself — which is
        how an orchestrator comes to report a child agent as a tool it ran.
        """
        summary = self.description or self.name
        return f"Delegate this request to the '{self.name}' agent. {summary}"


class AgentNode:
    """Callable that implements one agent turn inside a LangGraph node.

    Dependencies are injected at construction time so the node is a plain
    callable with no hidden closure state.
    """

    def __init__(
        self,
        spec: AgentSpec,
        node_path: str,
        bound_model: Any,
        resolver_loader: ResolverLoader,
        base_dir: Path,
        tool_invoker: ToolInvoker,
        usage_context: ToolUsageContextProvider,
    ) -> None:
        self._spec = spec
        self._node_path = node_path
        self._bound_model = bound_model
        self._resolver_loader = resolver_loader
        self._base_dir = base_dir
        self._tool_invoker = tool_invoker
        self._refresh_execution_context = execution_context_refresher(usage_context, spec.id)

    async def __call__(self, state: GraphState) -> GraphState:
        ctx = self._resolve_context()
        system_prompt = self._build_prompt(ctx)
        return await self._run(system_prompt, state)

    def _resolve_context(self) -> dict[str, str]:
        """Run every declared resolver and return the accumulated key→value map.

        Resolvers are invoked in declaration order; each receives the values
        produced by previous resolvers so they can build on one another.
        """
        ctx: dict[str, str] = {}
        for r in self._spec.resolvers:
            ctx[r.id] = str(self._resolver_loader.load(self._spec.id, r.id)(ctx))
        return ctx

    def _build_prompt(self, ctx: dict[str, str]) -> str:
        """Load the system-prompt template and interpolate resolver values."""
        template = load_file(self._base_dir, self._spec.prompts.system) or self._spec.description
        return render_prompt(template, ctx)

    async def _run(self, system_prompt: str, state: GraphState) -> GraphState:
        """Drive the model + tool loop until the model stops requesting tools.

        The execution context is re-read from the usage repository before every
        model turn, so an agent knows what other agents did without any of it
        travelling through the graph state.
        """
        user_msg: str = state.get("message", "")
        context = ModelContext(system_prompt, state.get("history", []), user_msg)
        logger.debug("[%s] system:\n%s", self._node_path, system_prompt)
        logger.debug("[%s] → user: %s", self._node_path, user_msg)

        visited: list[str] = [*state.get("visited", []), self._node_path]
        emit_route(state, tuple(visited))

        response = await run_tool_loop(
            self._bound_model,
            context,
            state,
            self._node_path,
            self._tool_invoker.invoke,
            refresh_execution_context=self._refresh_execution_context,
        )
        answer = as_text(response.content)
        logger.debug("[%s] ← response: %s", self._node_path, answer[:300])

        return {"visited": visited, "answer": answer}


class OrchestratorNode:
    """Supervisor-pattern orchestrator.

    Child agents (AgentNode or nested OrchestratorNode) are exposed as tools
    to the orchestrator LLM.  The LLM reads its system prompt, decides which
    tool(s) to call, collects their answers, and synthesises a final response.

    Access filters control which child tools are made available — if a child is
    filtered out the LLM simply does not have that tool and responds naturally
    (e.g. "I can't help with domestic flights").

    Like an agent, it receives the conversation's tool usage as private context,
    refreshed before each model turn — so its synthesis knows what the children
    it just called actually ran, and it can answer a user asking what has been
    done so far.
    """

    def __init__(
        self,
        spec: OrchestratorSpec,
        node_path: str,
        model: BaseChatModel,
        children: list[ChildEntry],
        filters: list[RouteFilter],
        base_dir: Path,
        usage_context: ToolUsageContextProvider,
        usage_tracker: ToolUsageTracker,
        fallback_model: BaseChatModel | None = None,
    ) -> None:
        self._spec = spec
        self._node_path = node_path
        self._model = model
        self._fallback_model = fallback_model
        self._children = children
        self._filters = filters
        self._base_dir = base_dir
        self._usage = usage_tracker
        self._usage_context = usage_context
        self._refresh_execution_context = execution_context_refresher(usage_context, spec.id)

    async def __call__(self, state: GraphState) -> GraphState:
        candidates = self._filter_children(state)
        base_prompt = load_file(self._base_dir, self._spec.prompts.system) or self._spec.description
        orchestrator_content = load_file(self._base_dir, self._spec.prompts.orchestrator)
        base_prompt = f"{base_prompt}\n\n{orchestrator_content}"
        system_prompt = f"{base_prompt}\n{_ORCHESTRATOR_CONTRACT}"
        return await self._run(system_prompt, candidates, state)

    def _filter_children(self, state: GraphState) -> list[ChildEntry]:
        """Apply every RouteFilter to narrow down which child tools are available."""
        ctx: dict[str, Any] = state.get("run_context", {})
        candidates = list(self._children)
        for f in self._filters:
            candidates = f.filter(ctx, candidates)
        return candidates

    def _make_tool(
        self,
        entry: ChildEntry,
        parent_state: GraphState,
        visited_acc: list[str],
    ) -> StructuredTool:
        """Wrap a child node as a StructuredTool the orchestrator LLM can call.

        ``visited_acc`` is the parent's live route list: when the child returns we
        merge its new path segments back into it, so the final route reflects the
        whole call-chain. The child's tool usage needs no merging — it is already
        recorded against the same run in the usage repository.

        Delegating to a child is itself an action this orchestrator took, so it
        is recorded too — that is how a later turn knows the routing that already
        happened. Execution still goes through the child node, unchanged.
        """

        async def invoke(message: str) -> str:
            snapshot = list(visited_acc)
            identity = self._child_identity(entry, message)
            # Children never stream their answer to the user — only the root
            # orchestrator's final synthesis does. The stream sinks are ambient
            # (current_streams); clear the answer sink for the child while keeping
            # route/token, so the live route still reflects the full chain.
            sub_state: GraphState = {
                "message": message,
                "visited": snapshot,
                "run_context": parent_state.get("run_context", {}),
            }
            child_sinks = replace(current_streams.get(), answer=None)
            sink_token = current_streams.set(child_sinks)
            try:
                result = await entry.callable(sub_state)
            except GraphInterrupt:
                # An approval interrupt raised inside a nested child must bubble up
                # to the LangGraph runtime so the checkpoint is taken — it is
                # control flow, not a child failure. Never swallow it, and record
                # nothing: the invocation has not reached an outcome yet.
                raise
            except Exception as exc:
                await self._usage.record_failure(identity, error=str(exc))
                return f"Agent error: {exc}"
            finally:
                current_streams.reset(sink_token)

            for path in result.get("visited", [])[len(snapshot) :]:
                visited_acc.append(path)
            await self._usage.record_success(identity)
            return result.get("answer", "")

        return StructuredTool.from_function(
            coroutine=invoke,
            name=entry.id,
            description=entry.tool_description,
            args_schema=_AgentCall,
        )

    def _reporting_tools(self, child_names: set[str]) -> list[BaseTool]:
        """The engine's own read-only tools, added unless a child claims the name.

        A configured child always wins: the system's own graph outranks a
        convenience the engine provides. Callers add these only when the
        orchestrator has children to expose, so an orchestrator whose children
        were all filtered out still faces the model with no tools at all.
        """
        if EXECUTED_TOOLS_TOOL_NAME in child_names:
            return []
        return [build_executed_tools_tool(self._usage_context, self._spec.id)]

    def _child_identity(self, entry: ChildEntry, message: str) -> ToolCallIdentity:
        """Name one delegation the same way a tool call is named.

        Derived from the run, this orchestrator's position, the child, and the
        message, so a replay after resume reaches the same identity instead of
        recording a second delegation.
        """
        scope = current_usage_scope(self._spec.id)
        run_id = scope.run_id or self._node_path
        return ToolCallIdentity(
            run_id=run_id,
            agent_id=self._spec.id,
            agent_path=self._node_path,
            tool_call_id=stable_tool_call_id(run_id, self._node_path, "agent", entry.id, message),
            tool_name=entry.id,
            conversation_id=scope.conversation_id,
            kind=ToolInvocationKind.AGENT,
        )

    async def _run(
        self,
        system_prompt: str,
        candidates: list[ChildEntry],
        state: GraphState,
    ) -> GraphState:
        """Drive the orchestrator LLM tool loop and return the synthesised answer."""
        visited: list[str] = [*state.get("visited", []), self._node_path]

        # Build tools here so they share the live `visited` list.
        child_tools = [self._make_tool(e, state, visited) for e in candidates]
        child_names = {tool.name for tool in child_tools}
        tools = [*child_tools, *self._reporting_tools(child_names)] if child_tools else []
        bound_model = self._model.bind_tools(tools) if tools else self._model
        if self._fallback_model is not None:
            bound_fallback = (
                self._fallback_model.bind_tools(tools) if tools else self._fallback_model
            )
            bound_model = bound_model.with_fallbacks(
                [bound_fallback], exceptions_to_handle=(Exception,)
            )
        tool_by_name = {t.name: t for t in tools}

        user_msg: str = state.get("message", "")
        context = ModelContext(system_prompt, state.get("history", []), user_msg)
        logger.debug(
            "[%s] system:\n%s\ntools: %s", self._node_path, system_prompt, list(tool_by_name)
        )
        logger.debug("[%s] → user: %s", self._node_path, user_msg)

        emit_route(state, tuple(visited))

        async def invoke_tool(tc: dict[str, Any]) -> str:
            tool = tool_by_name.get(tc["name"])
            if tool is None:
                return f"Unknown agent: {tc['name']}"
            # Limit orchestrator→child-agent invocations. A blocked call returns a
            # controlled message instead of running the child. Reporting on past
            # execution is not a delegation, so it is not counted or recorded.
            limiter = current_execution.get()
            if limiter is not None and tc["name"] in child_names:
                try:
                    limiter.register_child_call(self._node_path, tc["name"])
                except ExecutionLimitExceeded as exc:
                    log_limit(exc)
                    return blocked_message(exc)
            return cast(str, await tool.ainvoke(tc["args"]))

        response = await run_tool_loop(
            bound_model,
            context,
            state,
            self._node_path,
            invoke_tool,
            refresh_execution_context=self._refresh_execution_context,
        )
        answer = as_text(response.content)
        logger.debug("[%s] ← response: %s", self._node_path, answer[:300])

        return {"visited": visited, "answer": answer}
