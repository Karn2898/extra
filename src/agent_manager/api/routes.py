"""HTTP routes — the conversation API a chat UI talks to."""

from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Iterator
from contextlib import contextmanager
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from agent_engine.approvals.errors import (
    ApprovalError,
    approval_http_status,
    approval_public_message,
)
from agent_engine.engine.types import PendingApproval, RunResult
from agent_engine.runtime.streaming import RunStreamEvent
from agent_manager.api.deps import CallerIdentity, get_caller_identity, get_principal, get_service
from agent_manager.api.schemas import (
    AnonymousPassResponse,
    ApprovalDecisionRequest,
    CancelRunResponse,
    ConversationSummary,
    CreateConversationRequest,
    CreateConversationResponse,
    LinkAnonymousRequest,
    LinkAnonymousResponse,
    MessageOut,
    PendingApprovalOut,
    SendMessageRequest,
    SendMessageResponse,
    StreamEventOut,
    TokenBudgetResponse,
    ToolRecord,
)
from agent_manager.application import (
    ConversationAccessDenied,
    ConversationAlreadyExists,
    ConversationBranchConflict,
    ConversationLinkRefused,
    ConversationMessageNotFound,
    ConversationNotFound,
    ConversationService,
    ConversationTokenBudgetExceeded,
)
from agent_manager.domain import Principal
from agent_manager.infrastructure.auth import TokenError

router = APIRouter()
logger = logging.getLogger(__name__)

Service = Annotated[ConversationService, Depends(get_service)]
Caller = Annotated[Principal, Depends(get_principal)]
Identity = Annotated[CallerIdentity, Depends(get_caller_identity)]

_BUDGET_EXCEEDED_DETAIL = {
    "error_type": "context_limit_exceeded",
    "message": ("This conversation has reached its context limit. Start a new chat to continue."),
}
_INTERNAL_ERROR_MESSAGE = "Internal server error"

_HTTP_ERRORS: dict[type[Exception], tuple[int, Any]] = {
    ConversationNotFound: (404, "conversation not found"),
    ConversationAccessDenied: (403, "conversation owned by another user"),
    ConversationAlreadyExists: (409, "conversation id already taken"),
    ConversationTokenBudgetExceeded: (429, _BUDGET_EXCEEDED_DETAIL),
    ConversationMessageNotFound: (404, "message not found on active conversation branch"),
    ConversationBranchConflict: (409, "conversation branch changed; reload and try again"),
    ConversationLinkRefused: (403, "a visitor cannot adopt another visitor"),
}


@contextmanager
def _as_http_error() -> Iterator[None]:
    try:
        yield
    except tuple(_HTTP_ERRORS) as exc:
        status, detail = _HTTP_ERRORS[type(exc)]
        raise HTTPException(status_code=status, detail=detail) from None


@router.post("/auth/anonymous", response_model=AnonymousPassResponse)
async def issue_anonymous_pass(identity: Identity) -> AnonymousPassResponse:
    """The only route without a caller. The pass is signed, so one visitor
    cannot reach another's conversations by guessing an id."""
    issued = identity.resolver.anonymous.issue()
    return AnonymousPassResponse(token=issued.token, expires_at=issued.expires_at)


@router.post("/auth/link", response_model=LinkAnonymousResponse)
async def link_anonymous_conversations(
    body: LinkAnonymousRequest, service: Service, caller: Caller, identity: Identity
) -> LinkAnonymousResponse:
    """Adopt the conversations a visitor started before signing in.

    Both tokens are verified: a visitor pass proves which conversations, the
    caller's own token proves who is adopting them. Linking happens once, so a
    replayed pass moves nothing.
    """
    try:
        visitor = identity.resolver.anonymous.resolve(body.anonymous_token)
    except TokenError as exc:
        logger.warning("visitor pass verification failed: %s", exc)
        raise HTTPException(status_code=401, detail=str(exc)) from None
    with _as_http_error():
        moved = await service.link_anonymous(visitor, caller)
    return LinkAnonymousResponse(conversations_moved=moved)


@router.post("/conversations", response_model=CreateConversationResponse)
async def create_conversation(
    service: Service, caller: Caller, body: CreateConversationRequest | None = None
) -> CreateConversationResponse:
    body = body or CreateConversationRequest()
    with _as_http_error():
        session_id = await service.create(caller, session_id=body.session_id)
    return CreateConversationResponse(conversation_id=session_id, session_id=session_id)


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(service: Service, caller: Caller) -> list[ConversationSummary]:
    sessions = await service.list_conversations(caller)

    return [
        ConversationSummary(
            conversation_id=s.session_id,
            title=s.title,
            last_message_at=s.last_message_at,
        )
        for s in sessions
    ]


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(conversation_id: str, service: Service, caller: Caller) -> list[MessageOut]:
    with _as_http_error():
        msgs = await service.history(conversation_id, caller)
    return [
        MessageOut(
            message_id=m.message_id,
            run_id=m.run_id,
            role=m.role,
            content=m.content,
            status=m.status,
            created_at=m.created_at,
        )
        for m in msgs
    ]


@router.get("/conversations/{conversation_id}/usage", response_model=TokenBudgetResponse)
async def get_usage(conversation_id: str, service: Service, caller: Caller) -> TokenBudgetResponse:
    with _as_http_error():
        usage = await service.usage(conversation_id, caller)
    return TokenBudgetResponse(
        used_tokens=usage.used_tokens,
        max_tokens=usage.max_tokens,
        percent=usage.percent,
        severity=usage.severity,
    )


def _client_tool_record(t: Any) -> ToolRecord:
    fields = dataclasses.asdict(t)
    if fields.get("error"):
        fields["error"] = "Tool execution failed"
    return ToolRecord(**fields)


def _pending_approval(pa: PendingApproval | None) -> PendingApprovalOut | None:
    if pa is None:
        return None
    return PendingApprovalOut(
        run_id=pa.run_id,
        approval_id=pa.approval_id,
        agent_id=pa.agent_id,
        tool_name=pa.tool_name,
        description=pa.description,
        provider=pa.provider,
        server_id=pa.server_id,
        arguments=pa.arguments,
    )


def _run_response(result: RunResult) -> SendMessageResponse:
    pending = _pending_approval(result.pending_approval)
    return SendMessageResponse(
        answer=result.answer,
        visited=list(result.visited),
        used_tools=[_client_tool_record(t) for t in result.used_tools],
        status=result.status,
        run_id=pending.run_id if pending is not None else None,
        pending_approval=pending,
    )


@router.post("/conversations/{conversation_id}/messages", response_model=SendMessageResponse)
async def send_message(
    conversation_id: str, body: SendMessageRequest, service: Service, caller: Caller
) -> SendMessageResponse:
    try:
        with _as_http_error():
            result = await service.send(
                conversation_id,
                body.message,
                caller,
                edit_message_id=body.edit_message_id,
            )
    except HTTPException:
        raise

    except Exception:  # engine failure
        logger.exception("conversation request failed")
        raise HTTPException(status_code=500, detail=_INTERNAL_ERROR_MESSAGE) from None
    return _run_response(result)


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
        with _as_http_error():
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
        raise HTTPException(status_code=500, detail=_INTERNAL_ERROR_MESSAGE) from None
    return _run_response(result)


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
    with _as_http_error():
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
                payload = _to_stream_event(event).model_dump(exclude_none=True)
                yield f"event: {event.type}\ndata: {json.dumps(payload)}\n\n"
        except ApprovalError as exc:
            logger.info(
                "approval resume stream rejected",
                extra={"run_id": run_id, "approval_id": approval_id},
            )
            _, detail = _APPROVAL_HTTP_ERRORS.get(
                type(exc), (409, "approval could not be processed")
            )
            payload = {"type": "error", "error": detail}
            yield f"event: error\ndata: {json.dumps(payload)}\n\n"
        except Exception:
            logger.exception(
                "approval resume stream failed",
                extra={"run_id": run_id, "approval_id": approval_id},
            )
            payload = {"type": "error", "error": _INTERNAL_ERROR_MESSAGE}
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
        with _as_http_error():
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
        status, detail = _APPROVAL_HTTP_ERRORS.get(
            type(exc), (409, "approval could not be cancelled")
        )
        raise HTTPException(status_code=status, detail=detail) from None
    except Exception:
        logger.exception(
            "approval cancellation failed",
            extra={"run_id": run_id, "approval_id": approval_id},
        )
        raise HTTPException(status_code=500, detail=_INTERNAL_ERROR_MESSAGE) from None
    return CancelRunResponse(run_id=run_id)


def _to_stream_event(event: RunStreamEvent) -> StreamEventOut:
    return StreamEventOut(
        type=event.type,
        content=event.content,
        route=list(event.route) if event.route is not None else None,
        tool_name=event.tool_name,
        provider=event.provider,
        server_id=event.server_id,
        status=event.status,
        error=event.error,
        system_name=event.system_name,
        used_tools=(
            [_client_tool_record(tool) for tool in event.used_tools] if event.used_tools else None
        ),
        run_id=event.run_id,
        approval_id=event.approval_id,
        agent_id=event.agent_id,
        description=event.description,
        arguments=event.arguments,
    )


@router.post("/conversations/{conversation_id}/messages/stream")
async def stream_message(
    conversation_id: str, body: SendMessageRequest, service: Service, caller: Caller
) -> StreamingResponse:
    with _as_http_error():
        turn = await service.prepare_turn(
            conversation_id,
            body.message,
            caller,
            edit_message_id=body.edit_message_id,
        )
    stream = cast(
        AsyncGenerator[RunStreamEvent, None],
        service.stream_turn(turn),
    )

    async def event_source() -> AsyncIterator[str]:
        suspended = False
        exhausted = False
        try:
            started = StreamEventOut(
                type="turn_started",
                run_id=turn.run_id,
                message_id=turn.message_id,
            ).model_dump(exclude_none=True)
            yield f"event: turn_started\ndata: {json.dumps(started)}\n\n"
            async for event in stream:
                suspended = suspended or event.type == "pending_approval"
                payload = _to_stream_event(event).model_dump(exclude_none=True)
                yield f"event: {event.type}\ndata: {json.dumps(payload)}\n\n"
            exhausted = True
        except Exception:
            await service.fail_turn(turn)
            logger.exception("conversation stream failed")
            payload = {"type": "error", "error": _INTERNAL_ERROR_MESSAGE}
            yield f"event: error\ndata: {json.dumps(payload)}\n\n"
        finally:
            # StreamingResponse cancellation closes the application-owned
            # generator, which in turn cancels and awaits the graph producer.
            try:
                await stream.aclose()
            finally:
                if not exhausted and not suspended:
                    await service.cancel_turn(turn)
        yield "event: done\ndata: [DONE]\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")
