from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel

import agent_manager.infrastructure.persistence.tables  # noqa: F401
from agent_manager.application import ConversationService
from agent_manager.domain import InvalidCursorError, PageRequest
from agent_manager.infrastructure.persistence.database import create_db_engine, session_factory
from agent_manager.infrastructure.persistence.memory_repository import MemoryRepository
from agent_manager.infrastructure.persistence.pagination import (
    decode_cursor,
    encode_cursor,
)
from agent_manager.infrastructure.persistence.sql_repository import SqlRepository
from tests.agent_manager.conftest import RecordingEngine, bearer, build_test_app


@pytest.fixture
def client() -> TestClient:
    app = build_test_app(ConversationService(RecordingEngine(), MemoryRepository()))
    return TestClient(app, headers=bearer("default-user"))


def test_cursor_encode_decode_round_trip() -> None:
    now = datetime.now(UTC)
    cursor = encode_cursor(now, "sess-123")
    decoded_t, decoded_id = decode_cursor(cursor)

    assert decoded_t == now
    assert decoded_id == "sess-123"


def test_invalid_cursor_raises_invalid_cursor_error() -> None:
    with pytest.raises(InvalidCursorError):
        decode_cursor("not-a-valid-cursor!")


def test_empty_cursor_in_page_request_normalizes_to_none() -> None:
    req = PageRequest(limit=20, cursor="")
    assert req.cursor is None

    req_spaces = PageRequest(limit=20, cursor="   ")
    assert req_spaces.cursor is None


def test_limit_bounding_in_page_request() -> None:
    req_high = PageRequest(limit=10_000_000)
    assert req_high.limit == 100

    req_low = PageRequest(limit=-5)
    assert req_low.limit == 1


def test_a_malformed_cursor_is_rejected_as_client_error(client: TestClient) -> None:
    response = client.get("/conversations?cursor=garbage", headers=bearer("u1"))
    assert response.status_code == 400
    detail = response.json().get("detail", {})
    assert detail.get("error_type") == "invalid_cursor"


def test_empty_cursor_query_param_returns_first_page(client: TestClient) -> None:
    u1 = bearer("user-empty-cursor")
    client.post("/conversations", headers=u1)
    response = client.get("/conversations?cursor=", headers=u1)
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


@pytest.mark.asyncio
async def test_sql_repository_pagination_and_ordering(tmp_path: Path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'test_pag.db'}"
    engine = create_db_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    sessions = session_factory(engine)

    repo = SqlRepository(sessions)
    user_id = "user-pag-1"
    await repo.upsert_user(user_id)

    base_time = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)

    await repo.create_session("sess-1", user_id=user_id, title="Session 1")
    await repo.create_session("sess-2", user_id=user_id, title="Session 2")
    await repo.create_session("sess-3", user_id=user_id, title="Session 3")
    await repo.create_session("sess-4", user_id=user_id, title="Session 4")
    await repo.create_session("sess-5", user_id=user_id, title="Session 5")

    async with sessions() as session:
        from agent_manager.infrastructure.persistence.tables import ConversationSessionRow

        for i in range(1, 6):
            r = await session.get(ConversationSessionRow, f"sess-{i}")
            if r:
                r.created_at = base_time

        r1 = await session.get(ConversationSessionRow, "sess-1")
        assert r1 is not None
        r1.last_message_at = base_time + timedelta(hours=2)

        r2 = await session.get(ConversationSessionRow, "sess-2")
        assert r2 is not None
        r2.last_message_at = base_time + timedelta(hours=1)

        r3 = await session.get(ConversationSessionRow, "sess-3")
        assert r3 is not None
        r3.last_message_at = base_time + timedelta(hours=1)

        await session.commit()

    # Page 1: limit 2
    p1 = await repo.list_sessions(user_id, page=PageRequest(limit=2))
    assert [s.session_id for s in p1.items] == ["sess-1", "sess-3"]
    assert p1.next_cursor is not None

    # Page 2: limit 2
    p2 = await repo.list_sessions(user_id, page=PageRequest(limit=2, cursor=p1.next_cursor))
    assert [s.session_id for s in p2.items] == ["sess-2", "sess-5"]
    assert p2.next_cursor is not None

    # Page 3: limit 2
    p3 = await repo.list_sessions(user_id, page=PageRequest(limit=2, cursor=p2.next_cursor))
    assert [s.session_id for s in p3.items] == ["sess-4"]
    assert p3.next_cursor is None

    await engine.dispose()


def test_api_conversations_pagination_endpoint(client: TestClient) -> None:
    u1 = bearer("user-api-pag")
    c1 = client.post("/conversations", headers=u1).json()["conversation_id"]
    c2 = client.post("/conversations", headers=u1).json()["conversation_id"]
    c3 = client.post("/conversations", headers=u1).json()["conversation_id"]

    res1 = client.get("/conversations?limit=2", headers=u1).json()
    assert len(res1["items"]) == 2
    assert res1["next_cursor"] is not None

    cursor_q = quote(res1["next_cursor"])
    res2 = client.get(f"/conversations?limit=2&cursor={cursor_q}", headers=u1).json()
    assert len(res2["items"]) == 1
    assert res2["next_cursor"] is None

    fetched_ids = [item["conversation_id"] for item in res1["items"] + res2["items"]]
    assert fetched_ids == [c3, c2, c1]
