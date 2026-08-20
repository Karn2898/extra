"""Translate application failures into the conversation API's HTTP contract."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import HTTPException

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
