"""Conversation-scoped approval decision, streaming, and cancellation endpoints."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from typing import cast

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from agent_engine.approvals.errors import (
    ApprovalError,
    approval_http_status,
    approval_public_message,
)
from agent_engine.runtime.streaming import RunStreamEvent
from agent_manager.api.deps import Caller, Service
from agent_manager.api.errors import INTERNAL_ERROR_MESSAGE, as_http_error
from agent_manager.api.presenters import run_response, to_stream_event
from agent_manager.api.schemas import (
    ApprovalDecisionRequest,
    CancelRunResponse,
    SendMessageResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/conversations/{conversation_id}/runs/{run_id}/approvals/{approval_id}/decision",
    response_model=SendMessageResponse,
)
async def decide_approval(
    conversation_id: str,
    run_id: str,
    approval_id: str,
    body: ApprovalDecisionRequest,
    service: Service,
    caller: Caller,
) -> SendMessageResponse:
    try:
        with as_http_error():
            result = await service.decide_approval(
                conversation_id,
                run_id,
                approval_id,
                body.decision,
                caller,
            )
    except HTTPException:
        raise
    except ApprovalError as exc:
        logger.info(
            "approval decision rejected",
            extra={"run_id": run_id, "approval_id": approval_id},
        )
        raise HTTPException(
            status_code=approval_http_status(exc),
            detail=approval_public_message(exc),
        ) from None
    except Exception:
        logger.exception(
            "approval decision failed",
            extra={"run_id": run_id, "approval_id": approval_id},
        )
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_MESSAGE) from None
    return run_response(result)


@router.post(
    "/conversations/{conversation_id}/runs/{run_id}/approvals/{approval_id}/decision/stream"
)
async def stream_approval_decision(
    conversation_id: str,
    run_id: str,
    approval_id: str,
    body: ApprovalDecisionRequest,
    service: Service,
    caller: Caller,
) -> StreamingResponse:
    with as_http_error():
        stream = cast(
            AsyncGenerator[RunStreamEvent, None],
            await service.stream_approval(
                conversation_id,
                run_id,
                approval_id,
                body.decision,
                caller,
            ),
        )

    async def event_source() -> AsyncIterator[str]:
        try:
            async for event in stream:
                payload = to_stream_event(event).model_dump(exclude_none=True)
                yield f"event: {event.type}\ndata: {json.dumps(payload)}\n\n"
        except ApprovalError as exc:
            logger.info(
                "approval resume stream rejected",
                extra={"run_id": run_id, "approval_id": approval_id},
            )
            payload = {"type": "error", "error": approval_public_message(exc)}
            yield f"event: error\ndata: {json.dumps(payload)}\n\n"
        except Exception:
            logger.exception(
                "approval resume stream failed",
                extra={"run_id": run_id, "approval_id": approval_id},
            )
            payload = {"type": "error", "error": INTERNAL_ERROR_MESSAGE}
            yield f"event: error\ndata: {json.dumps(payload)}\n\n"
        finally:
            await stream.aclose()
        yield "event: done\ndata: [DONE]\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")


@router.post(
    "/conversations/{conversation_id}/runs/{run_id}/approvals/{approval_id}/cancel",
    response_model=CancelRunResponse,
)
async def cancel_pending_approval(
    conversation_id: str,
    run_id: str,
    approval_id: str,
    service: Service,
    caller: Caller,
) -> CancelRunResponse:
    try:
        with as_http_error():
            await service.cancel_pending_approval(
                conversation_id,
                run_id,
                approval_id,
                caller,
            )
    except HTTPException:
        raise
    except ApprovalError as exc:
        logger.info(
            "approval cancellation rejected",
            extra={"run_id": run_id, "approval_id": approval_id},
        )
        raise HTTPException(
            status_code=approval_http_status(exc),
            detail=approval_public_message(exc),
        ) from None
    except Exception:
        logger.exception(
            "approval cancellation failed",
            extra={"run_id": run_id, "approval_id": approval_id},
        )
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_MESSAGE) from None
    return CancelRunResponse(run_id=run_id)
