"""initial categories, products and index_outbox tables

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-18

"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_categories_name", "categories", ["name"], unique=True)

    op.create_table(
        "products",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "category_id",
            UUID(as_uuid=True),
            sa.ForeignKey("categories.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("sku", sa.String(64), nullable=False),
        sa.Column(
            "attributes", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("price > 0", name="ck_products_price_positive"),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name="ck_products_currency_iso4217"
        ),
    )
    op.create_index("ix_products_category_id", "products", ["category_id"])
    op.create_index("ix_products_sku", "products", ["sku"], unique=True)
    op.create_index(
        "ix_products_is_active",
        "products",
        ["is_active"],
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "index_outbox",
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
        "ix_index_outbox_event_id", "index_outbox", ["event_id"], unique=True
    )
    op.create_index(
        "ix_index_outbox_status_created_at", "index_outbox", ["status", "created_at"]
    )
    op.create_index("ix_index_outbox_processed_at", "index_outbox", ["processed_at"])


def downgrade() -> None:
    op.drop_table("index_outbox")
    op.drop_table("products")
    op.drop_table("categories")
