<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/logo-dark.svg">
    <img src=".github/assets/logo-light.svg" alt="Extra" height="60">
  </picture>
</p>

<h1 align="center">Turn your product into an AI-powered assistant that understands your business.</h1>

<p align="center">
  Extra lets you build AI-powered assistants that understand your workflows, use your existing APIs and business logic, and delegate work to AI specialists.
</p>

<p align="center">
  <a href="https://docs.extra-ai.co/docs/introduction"><img alt="Docs" src="https://img.shields.io/badge/docs-available-blue"></a>
  <img alt="Version" src="https://img.shields.io/badge/version-beta-orange">
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-green"></a>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> ·
  <a href="#why-extra">Why Extra</a> ·
  <a href="https://docs.extra-ai.co/docs/introduction">Documentation</a> ·
  <a href="#contributing">Contributing</a>
</p>

---
Instead of navigating complex UIs, users simply ask.

Extra translates those requests into your existing APIs, business logic,
and workflows.


## Why Extra

Most AI frameworks start with prompts.

Extra starts with your product.

It connects your existing backend to a network of focused AI specialists.

* **Specialized by design.** Each specialist understands one part of your business.

* **Built on your backend.** Your existing APIs, tools, and services remain the source of truth.

* **Explicit workflows.** Requests move through predictable, inspectable execution paths.

* **Authorization outside the model.** Access decisions stay in trusted code.

* **Easy to embed.** Expose Extra through an API or add it directly to your product.


## Quick Start

You need Docker and an API key for your model provider.

Create `agents.yml` — an orchestrator that routes to two focused agents:

```yaml
system:
  name: "Support Assistant"

defaults:
  model:
    provider: anthropic
    name: claude-sonnet-4-6

orchestrators:
  support_router:
    description: "Routes each request to the agent that owns it."
    prompts:
      orchestrator: prompts/support_router/orchestrator.md

agents:
  orders_agent:
    description: "Answers questions about orders, shipping, and returns."
    prompts:
      system: prompts/orders_agent/system.md

  billing_agent:
    description: "Answers questions about invoices, plans, and refunds."
    prompts:
      system: prompts/billing_agent/system.md

# Indentation is the hierarchy: the orchestrator routes to both agents.
graph:
  support_router:
    orders_agent:
    billing_agent:
```

Scaffold the prompt and plugin stubs the YAML references. It never overwrites a
file you already wrote:

```bash
agentctl generate --config agents.yml

# or via the Docker image, which supplies the `agentctl` prefix for you:
docker run --rm -v "$(pwd):/workspace" -w /workspace \
  ghcr.io/extra-org/extra:latest generate --config agents.yml
```

Fill in the three prompt stubs it created:

```markdown
<!-- prompts/support_router/orchestrator.md -->
Route orders, shipping, and returns to orders_agent.
Route invoices, plans, and refunds to billing_agent.

<!-- prompts/orders_agent/system.md -->
You answer questions about orders, shipping, and returns.

<!-- prompts/billing_agent/system.md -->
You answer questions about invoices, plans, and refunds.
```

Run it with Agent Manager, which serves the conversation API, history, and the
chat widget:

```bash
docker run -p 8100:8100 -v "$(pwd):/workspace" -w /workspace \
  -e ANTHROPIC_API_KEY=sk-... \
  ghcr.io/extra-org/extra:latest \
  agent-manager --config agents.yml --port 8100
```

Talk to it in the browser at **http://localhost:8100/playground**, or over the
API — create a conversation with an id you choose, then send it a message:

```bash
curl -X POST http://localhost:8100/conversations \
  -H "Content-Type: application/json" \
  -d '{"session_id":"readme-demo"}'

curl -X POST http://localhost:8100/conversations/readme-demo/messages \
  -H "Content-Type: application/json" \
  -d '{"message":"Tell me about my system"}'
```

Tools, MCP servers, deeper routing, per-node authorization, and embedding the
chat widget are covered in the
[Quickstart](https://docs.extra-ai.co/docs/quickstart).

## Features

- AI specialists
- Workflow orchestration
- Local tools and MCP
- Authorization outside the LLM
- Human approvals
- Streaming API
- Embeddable chat widget
- Anthropic, OpenAI, Gemini, and Bedrock
- Langfuse tracing

## Architecture

Extra executes an explicit graph.

Orchestrators route requests to AI specialists. Each specialist owns its own prompts, tools, MCP servers, and authorization.

Your business logic stays in your backend. Extra only orchestrates execution.

```mermaid
flowchart TD
    U([User request]) --> R{{Orchestrator<br/>routes by domain}}
    R -->|billing| A1[Billing agent]
    R -->|orders| A2[Orders agent]
    R -->|docs| A3[Docs agent]

    A1 --- P1[/prompt · tools · MCP · auth/]
    A2 --- P2[/prompt · tools · MCP · auth/]
    A3 --- P3[/prompt · tools · MCP · auth/]

    A1 --> RESP([Grounded response])
    A2 --> RESP
    A3 --> RESP
```

Extra runs the graph. Your project's plugins hold the trusted business logic —
tools, access checks, and the values resolved into prompts.

- **[Tutorial](https://docs.extra-ai.co/docs/tutorial)** — build a complete multi-agent system step by step.
- **[YAML reference](https://docs.extra-ai.co/docs/yaml-spec)** — every field you can declare.
- **[Architecture](https://docs.extra-ai.co/docs/architecture)** — how routing and execution work.
- **[`examples/`](examples/)** — runnable specs, including an enterprise knowledge assistant.


## Contributing

This repository is **agent-first** — if you're an AI coding agent, read
[AGENTS.md](AGENTS.md) before making changes. Human contributors should
start there too, then run `make check` before opening a PR.

## License

[MIT](LICENSE)
