"""add session pagination composite index

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "idx_conversation_sessions_user_active_session",
        "conversation_sessions",
        ["user_id", sa.text("COALESCE(last_message_at, created_at)"), "session_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_conversation_sessions_user_active_session",
        table_name="conversation_sessions",
    )
