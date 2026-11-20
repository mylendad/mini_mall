"""stock_items table

Revision ID: 0001_stock_items
Revises:
Create Date: 2026-11-19

"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_stock_items"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stock_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("catalog_product_id", UUID(as_uuid=True), nullable=True),
        sa.Column("sku", sa.String(64), nullable=False),
        sa.Column("quantity_on_hand", sa.Integer(), nullable=False),
        sa.Column("quantity_reserved", sa.Integer(), nullable=False),
        sa.Column("low_stock_threshold", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "quantity_reserved <= quantity_on_hand",
            name="ck_stock_items_reserved_le_on_hand",
        ),
        sa.CheckConstraint(
            "quantity_on_hand >= 0", name="ck_stock_items_on_hand_nonneg"
        ),
        sa.CheckConstraint(
            "quantity_reserved >= 0", name="ck_stock_items_reserved_nonneg"
        ),
        sa.CheckConstraint(
            "low_stock_threshold >= 0", name="ck_stock_items_threshold_nonneg"
        ),
    )
    op.create_index("ix_stock_items_sku", "stock_items", ["sku"], unique=True)


def downgrade() -> None:
    op.drop_table("stock_items")
