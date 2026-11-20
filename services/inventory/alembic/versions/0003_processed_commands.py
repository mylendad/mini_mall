"""processed_commands table

Revision ID: 0003_processed_commands
Revises: 0002_reservations
Create Date: 2026-11-19

"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

# revision identifiers, used by Alembic.
revision = "0003_processed_commands"
down_revision = "0002_reservations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "processed_commands",
        sa.Column("event_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("processed_commands")
