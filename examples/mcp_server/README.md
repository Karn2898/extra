# MCP Server Example

Run the Extra agent system as an MCP server over stdio, then connect any
MCP-compatible client to it.

## Prerequisites

- `agentctl` installed in your environment (`pip install -e .`)
- An LLM provider configured (e.g. `ANTHROPIC_API_KEY` in `.env`)

## 1. Start the server

```bash
agentctl mcp serve --config ./agents.yml
```

The server starts on stdio and exposes one tool: `extra_chat`.

## 2. Connect with an MCP client

### Using the MCP Python SDK

Save this as `client.py` and run it while the server is running:

```python
import asyncio
from mcp import ClientSession
from mcp.client.stdio import stdio_client
from mcp.types import StdioServerParameters


async def main():
    server_params = StdioServerParameters(
        command="agentctl",
        args=["mcp", "serve", "--config", "examples/mcp_server/agents.yml"],
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # Call without session_id — a new session is created
            result = await session.call_tool(
                "extra_chat",
                {"message": "Say hello in one sentence."},
            )
            print(result.structuredContent)

            # Reuse the returned session_id for the next call
            sid = result.structuredContent["session_id"]
            follow_up = await session.call_tool(
                "extra_chat",
                {"message": "What did I just ask?", "session_id": sid},
            )
            print(follow_up.structuredContent)


if __name__ == "__main__":
    asyncio.run(main())
```

### Expected output

```json
{
  "session_id": "a1b2c3d4e5f67890",
  "status": "completed",
  "answer": "Hello! How can I assist you today?",
  "visited": ["echo_agent"],
  "used_tools": []
}
```

## Notes

- Omit `session_id` to create a new conversation.
- Reuse `session_id` to continue an existing conversation.
- Provide `user_id` to tag messages with a stable user identity.
- Autonomous execution: by default in this example, `auto: true` is configured on the agent so tool calls execute immediately without pausing for human approval.
- Human-in-the-Loop: for agents configured without `auto: true`, if a tool call requires confirmation, `extra_chat` returns `"status": "pending_approval"` along with a `pending_approval` metadata object containing the suspended `run_id`, `approval_id`, tool name, and arguments.

