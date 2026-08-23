# ADR 0003 — Cursor pagination and list response envelope

- **Status:** Accepted
- **Date:** 2026-08-23

## Context

`GET /conversations` previously returned a flat, unbounded list of all conversations for a user. As conversation counts grow per user, loading the complete list in one request causes high latency, database scan overhead, and excessive payload sizes for clients.

Additionally, simple offset pagination (`OFFSET N`) suffers from severe database performance degradation on large offsets and produces inconsistent results (skipped or duplicated rows) if conversations receive messages or are created while a user is paginating.

## Decision

1. **Keyset Cursor Pagination**:
   - `GET /conversations` uses keyset pagination based on the composite ordering key `(COALESCE(last_message_at, created_at) DESC, session_id DESC)`.
   - The active timestamp `COALESCE(last_message_at, created_at)` ensures empty conversations without messages sort predictably by their creation time alongside active threads.

2. **Opaque Base64 Cursor Token**:
   - Cursors are opaque server tokens containing base64-encoded JSON `{"t": "<iso8601_utc_timestamp>", "id": "<session_id>"}`.
   - The pagination token codec (`encode_cursor`, `decode_cursor`) and exception `InvalidCursorError` live in `agent_manager.domain.pagination` (pure Python domain value objects and utilities with zero framework dependencies).
   - Malformed or invalid cursor tokens raise `InvalidCursorError`, which is mapped by `as_http_error()` to `HTTP 400 Bad Request` with payload `{ "error_type": "invalid_cursor", "message": "invalid pagination cursor" }`.

3. **Domain Layer Bounds**:
   - `PageRequest` value object encapsulates pagination parameters (`limit`, `cursor`).
   - Default page size is 20 (`DEFAULT_PAGE_LIMIT`) and maximum page limit is 100 (`MAX_PAGE_LIMIT`), enforced at domain instantiation time in `PageRequest.__post_init__`.

4. **Database Indexing**:
   - Migration `0005_add_session_pagination_index.py` and `tables.py` add an expression index `idx_conversation_sessions_user_active_session` on `(user_id, COALESCE(last_message_at, created_at), session_id)` to enable fast index range seeks for keyset pagination.

## Contract changes

- **BREAKING CHANGE**: `GET /conversations` response shape changed from a flat list `[ConversationSummary, ...]` to a paginated envelope object `{ "items": [ConversationSummary, ...], "next_cursor": "..." | null }`.
- `GET /conversations` accepts optional query parameters `limit` (integer, 1..100) and `cursor` (opaque string).

## Consequences

- Clients fetch subsequent pages using `next_cursor` until `next_cursor` is `null`.
- Keyset range seeks eliminate `OFFSET` database performance degradation and prevent skipped/duplicated sessions when thread activity changes mid-page.
- Frontends deduplicate threads by `conversation_id` to handle live thread updates gracefully.
