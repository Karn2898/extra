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
