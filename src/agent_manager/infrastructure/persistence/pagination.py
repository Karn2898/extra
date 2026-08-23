"""Infrastructure alias re-exporting pagination utilities from domain."""

from agent_manager.domain.pagination import (
    InvalidCursorError,
    decode_cursor,
    encode_cursor,
    ensure_utc,
)

# Backward-compatibility private alias
_utc = ensure_utc

__all__ = [
    "InvalidCursorError",
    "decode_cursor",
    "encode_cursor",
    "ensure_utc",
]
