"""Translate application failures into the conversation API's HTTP contract."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import HTTPException

from agent_engine.approvals.errors import (
    ApprovalError,
    approval_http_status,
    approval_public_message,
)
from agent_manager.application import (
    ConversationAccessDenied,
    ConversationAlreadyExists,
    ConversationBranchConflict,
    ConversationLinkRefused,
    ConversationMessageNotFound,
    ConversationNotFound,
    ConversationTokenBudgetExceeded,
)

BUDGET_EXCEEDED_DETAIL = {
    "error_type": "context_limit_exceeded",
    "message": "This conversation has reached its context limit. Start a new chat to continue.",
}
INTERNAL_ERROR_MESSAGE = "Internal server error"

_HTTP_ERRORS: dict[type[Exception], tuple[int, Any]] = {
    ConversationNotFound: (404, "conversation not found"),
    ConversationAccessDenied: (403, "conversation owned by another user"),
    ConversationAlreadyExists: (409, "conversation id already taken"),
    ConversationTokenBudgetExceeded: (429, BUDGET_EXCEEDED_DETAIL),
    ConversationMessageNotFound: (404, "message not found on active conversation branch"),
    ConversationBranchConflict: (409, "conversation branch changed; reload and try again"),
    ConversationLinkRefused: (403, "a visitor cannot adopt another visitor"),
}


@contextmanager
def as_http_error() -> Iterator[None]:
    """Map known application exceptions to their existing public HTTP errors."""
    try:
        yield
    except tuple(_HTTP_ERRORS) as exc:
        status, detail = _HTTP_ERRORS[type(exc)]
        raise HTTPException(status_code=status, detail=detail) from None


@contextmanager
def as_internal_http_error(logger: logging.Logger, message: str) -> Iterator[None]:
    """Preserve HTTP errors and sanitize unexpected failures."""
    try:
        yield
    except HTTPException:
        raise
    except Exception:
        logger.exception(message)
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_MESSAGE) from None


@contextmanager
def as_approval_http_error(
    logger: logging.Logger,
    action: str,
    *,
    run_id: str,
    approval_id: str,
) -> Iterator[None]:
    """Map approval failures while preserving the established HTTP contract."""
    extra = {"run_id": run_id, "approval_id": approval_id}
    try:
        yield
    except HTTPException:
        raise
    except ApprovalError as exc:
        logger.info(f"approval {action} rejected", extra=extra)
        raise HTTPException(
            status_code=approval_http_status(exc),
            detail=approval_public_message(exc),
        ) from None
    except Exception:
        logger.exception(f"approval {action} failed", extra=extra)
        raise HTTPException(status_code=500, detail=INTERNAL_ERROR_MESSAGE) from None
