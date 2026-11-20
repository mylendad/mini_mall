"""inventory_outbox table

Revision ID: 0004_inventory_outbox
Revises: 0003_processed_commands
Create Date: 2026-11-19

"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

# revision identifiers, used by Alembic.
revision = "0004_inventory_outbox"
down_revision = "0003_processed_commands"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_id", UUID(as_uuid=True), nullable=False),
        sa.Column("envelope", JSONB(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_inventory_outbox_event_id", "inventory_outbox", ["event_id"], unique=True
    )
    op.create_index(
        "ix_inventory_outbox_status_created_at",
        "inventory_outbox",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_inventory_outbox_processed_at", "inventory_outbox", ["processed_at"]
    )


def downgrade() -> None:
    op.drop_table("inventory_outbox")
