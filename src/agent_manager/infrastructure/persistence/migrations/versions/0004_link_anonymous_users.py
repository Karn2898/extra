"""record which account a visitor's conversations were handed to

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-09

A visitor chatting before they log in owns their conversations under an
anonymous id. When they sign in, those conversations move to their account.
This column marks the visitor as spent, so a replayed visitor pass cannot
attach the same conversations to a second account.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversation_users",
        sa.Column("linked_to_user_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversation_users", "linked_to_user_id")
