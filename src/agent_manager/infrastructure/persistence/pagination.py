"""Pagination token encoding, decoding, and error types."""

from __future__ import annotations

import base64
import binascii
import json
from datetime import UTC, datetime


class InvalidCursorError(Exception):
    """Raised when a pagination cursor token is malformed or unparseable."""


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def encode_cursor(active_at: datetime, session_id: str) -> str:
    """Encode an active timestamp and session ID into an opaque base64 cursor token."""
    utc_dt = _utc(active_at)
    if utc_dt is None:
        raise ValueError("active_at timestamp cannot be None")
    payload = {
        "t": utc_dt.isoformat(),
        "id": session_id,
    }
    raw_bytes = json.dumps(payload).encode("utf-8")
    return base64.urlsafe_b64encode(raw_bytes).decode("ascii")


def decode_cursor(cursor_str: str) -> tuple[datetime, str]:
    """Decode a cursor token into (active_at_utc, session_id)."""
    if not cursor_str or not cursor_str.strip():
        raise InvalidCursorError("Pagination cursor token cannot be empty")
    try:
        raw_bytes = base64.urlsafe_b64decode(cursor_str.encode("ascii"))
        data = json.loads(raw_bytes.decode("utf-8"))
        if not isinstance(data, dict) or "id" not in data or "t" not in data or data["t"] is None:
            raise ValueError("Invalid cursor payload structure")
        parsed_dt = datetime.fromisoformat(data["t"])
        active_at = _utc(parsed_dt)
        if active_at is None:
            raise ValueError("Failed to parse active_at timestamp")
        session_id = str(data["id"])
        return active_at, session_id
    except (
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:
        raise InvalidCursorError("Invalid pagination cursor token") from exc
