"""reservations table

Revision ID: 0002_reservations
Revises: 0001_stock_items
Create Date: 2026-11-19

"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_reservations"
down_revision = "0001_stock_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reservations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "stock_item_id",
            UUID(as_uuid=True),
            sa.ForeignKey("stock_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("holder_ref", sa.String(255), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "quantity > 0", name="ck_reservations_quantity_positive"
        ),
        sa.CheckConstraint(
            "status ~ '^(active|confirmed|released|expired)$'",
            name="ck_reservations_status_domain",
        ),
    )
    op.create_index(
        "ix_reservations_stock_item_id", "reservations", ["stock_item_id"]
    )
    op.create_index(
        "ix_reservations_idempotency_key",
        "reservations",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_reservations_active_expires_at",
        "reservations",
        ["expires_at"],
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_table("reservations")
