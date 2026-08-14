# ADR 0001 — Tool usage is execution metadata, not graph state

- **Status:** Accepted
- **Date:** 2026-08-15

## Context

Tool usage was collected in a Python list seeded from `GraphState["used_tools"]`,
merged upward by `OrchestratorNode` after each child returned, and handed back as
a state delta. Three problems followed from that ownership model:

- an agent could not see what another agent had already run, because the merge
  happened only after the child finished;
- nothing survived the run, so a later turn of the same conversation started
  blind;
- the node owned persistence, approval, execution, hooks, and tracking at once,
  and a distributed backend had nowhere to plug in.

## Decision

Execution metadata is owned by a dedicated subsystem, `agent_engine/tool_usage/`,
with the repository as its source of truth.

- `ToolUsageRepository` (Protocol) persists one record per logical invocation,
  identified by `(run_id, tool_call_id)` and carrying
  `conversation → run → agent → tool call`. `record` is an upsert on that
  identity, so an approval resume updates rather than duplicates.
- `ToolUsageTracker` writes execution outcomes; it decides nothing else.
- `ToolUsageContextProvider` projects persisted records into a private
  system-role block for the model, refreshed before every model turn.
- `as_usage_records` projects the same records into the caller-facing
  `RunResult.used_tools` trace.
- `ToolInvoker` owns the single tool-execution path (identity, limits, the
  approval gate, idempotency, provider execution, hooks, recording), leaving
  nodes with prompt building and the model loop.

Approval and tool usage stay separate subsystems that share identifiers
(`run_id`, `tool_call_id`, agent, tool) and no responsibilities.

## Contract changes

- `GraphState["used_tools"]` is **removed**. `RunResult.used_tools` is unchanged
  for callers, but is now projected from the repository rather than carried
  through graph state.
- `ToolUsageStatus` gains `"denied"`. The HTTP and widget field is a free string,
  so no client breaks.
- `LangGraphEngine.__init__` gains `tool_usage_repository`, defaulting to the
  process-local adapter.
- Orchestrators are bound one engine-provided read-only tool,
  `list_executed_tools`. A configured child of the same name wins.
- Child agents are described to their parent as delegations rather than actions.

## Consequences

- Replacing the in-memory adapter with Redis or PostgreSQL is a new adapter plus
  one line in the composition root; agents, nodes, the tool loop, and the model
  context are untouched.
- Two identical calls by one agent in one run now collapse to a single record,
  because they are one logical invocation. The previous list appended twice.
- Recording is observability: a repository write failure is logged and swallowed
  so a metadata problem cannot fail a completed tool call. A *read* failure on
  the explicit report is not swallowed — reporting "nothing ran" when the record
  is unreadable would invite repeating an action that already took effect.
- Delegations are recorded as `kind = agent`. They are excluded from the run
  trace, which has always meant real tool/MCP calls.
