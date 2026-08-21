"""Pure traversal and rendering operations over compiled graph specifications."""

from __future__ import annotations

from agent_engine.core.spec import AgentSpec, GraphNode, MCPSpec, OrchestratorSpec


def node_id(node: GraphNode, parent_path: str | None) -> str:
    return f"{parent_path}/{node.node.id}" if parent_path else node.node.id


def has_protected_nodes(node: GraphNode) -> bool:
    if node.node.protected:
        return True
    return any(has_protected_nodes(child) for child in node.children)


def walk(node: GraphNode) -> list[GraphNode]:
    """Flatten the spec tree, parents before children."""
    nodes = [node]
    for child in node.children:
        nodes.extend(walk(child))
    return nodes


def render_graph(node: GraphNode, depth: int = 0) -> list[str]:
    """Render the spec tree as indented lines, for example in startup logs."""
    spec = node.node
    kind = "orchestrator" if isinstance(spec, OrchestratorSpec) else "agent"
    label = f"{'  ' * (depth + 1)}{kind} '{spec.name or spec.id}'"
    if isinstance(spec, AgentSpec):
        extras = []
        if spec.tools:
            extras.append("tools: " + ", ".join(tool.id for tool in spec.tools))
        if spec.mcps:
            extras.append("mcps: " + ", ".join(mcp.id for mcp in spec.mcps))
        if extras:
            label += f" [{'; '.join(extras)}]"
    if spec.protected:
        label += " (protected)"
    lines = [label]
    for child in node.children:
        lines.extend(render_graph(child, depth + 1))
    return lines


def collect_mcp_specs(node: GraphNode) -> dict[str, MCPSpec]:
    """Return every unique MCP server specification in the graph by id."""
    result: dict[str, MCPSpec] = {}
    if isinstance(node.node, AgentSpec):
        for mcp in node.node.mcps:
            result.setdefault(mcp.id, mcp)
    for child in node.children:
        result.update(collect_mcp_specs(child))
    return result
