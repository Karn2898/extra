"""Static app used by Playwright widget smoke tests."""

from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from agent_manager.api.web import mount_web
from agent_manager.config import Settings

app = FastAPI()
mount_web(app, Settings())

_title_settled = False
_title_turn_count = 0


@app.post("/e2e-title/reset")
async def reset_title_scenario() -> dict[str, bool]:
    global _title_settled, _title_turn_count
    _title_settled = False
    _title_turn_count = 0
    return {"ok": True}


@app.post("/e2e-title/conversations")
async def create_title_scenario_conversation() -> dict[str, str]:
    return {"conversation_id": "conv-title", "session_id": "conv-title"}


@app.get("/e2e-title/conversations")
async def list_title_scenario_conversations() -> dict[str, object]:
    return {
        "items": [
            {
                "conversation_id": "conv-title",
                "title": "A long opening message used as fallback"
                if not _title_settled
                else "Generated Conversation Title",
                "last_message_at": "2026-08-28T00:00:00Z",
            }
        ],
        "next_cursor": None,
    }


@app.get("/e2e-title/conversations/{conversation_id}/messages")
async def title_scenario_messages(conversation_id: str) -> list[object]:
    del conversation_id
    return []


@app.get("/e2e-title/conversations/{conversation_id}/usage")
async def title_scenario_usage(conversation_id: str) -> dict[str, object]:
    del conversation_id
    return {
        "used_tokens": 0,
        "max_tokens": None,
        "percent": 0,
        "severity": "normal",
    }


@app.post("/e2e-title/conversations/{conversation_id}/messages/stream")
async def delayed_title_stream(conversation_id: str) -> StreamingResponse:
    """Finish the answer now, then deliver the first turn's title later."""
    global _title_turn_count
    del conversation_id
    _title_turn_count += 1
    turn_number = _title_turn_count

    async def events():
        started = json.dumps(
            {
                "type": "turn_started",
                "run_id": f"run-title-{turn_number}",
                "message_id": f"message-title-{turn_number}",
            }
        )
        yield f"event: turn_started\ndata: {started}\n\n"
        final = json.dumps(
            {
                "type": "final",
                "content": f"Answer {turn_number}",
                "route": [],
                "used_tools": [],
            }
        )
        yield f"event: final\ndata: {final}\n\n"
        if turn_number == 1:
            await asyncio.sleep(2)
            global _title_settled
            _title_settled = True
            title = json.dumps({"type": "title", "title": "Generated Conversation Title"})
            yield f"event: title\ndata: {title}\n\n"
        yield "event: done\ndata: [DONE]\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@app.post("/conversations/{conversation_id}/runs/{run_id}/approvals/{approval_id}/decision/stream")
async def blocking_approval_resume(
    conversation_id: str,
    run_id: str,
    approval_id: str,
) -> StreamingResponse:
    """Test-only stream that stays active until Playwright aborts it."""
    del conversation_id, approval_id

    async def events():
        started = json.dumps({"type": "resume_started", "run_id": run_id})
        yield f"event: resume_started\ndata: {started}\n\n"
        partial = json.dumps({"type": "answer_delta", "content": "partial"})
        yield f"event: answer_delta\ndata: {partial}\n\n"
        await asyncio.Event().wait()

    return StreamingResponse(events(), media_type="text/event-stream")
