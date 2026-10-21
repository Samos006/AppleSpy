import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tg_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=64)),
        sa.Column("first_name", sa.String(length=128)),
        sa.Column("language_code", sa.String(length=8)),
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_users_tg_id", "users", ["tg_id"], unique=True)

    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("item_id", sa.String(length=32), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("name", sa.Text()),
        sa.Column("brand", sa.String(length=255)),
        sa.Column("image_url", sa.Text()),
        sa.Column("variant", sa.String(length=255)),
        sa.Column("price", sa.Numeric(12, 2)),
        sa.Column("old_price", sa.Numeric(12, 2)),
        sa.Column("in_stock", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rating", sa.Numeric(3, 2)),
        sa.Column("reviews_count", sa.Integer()),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("fail_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("raw", postgresql.JSONB()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_products_item_id", "products", ["item_id"], unique=True)
    op.create_index("ix_products_last_checked", "products", ["last_checked_at"])

    op.create_table(
        "price_points",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("price", sa.Numeric(12, 2)),
        sa.Column("old_price", sa.Numeric(12, 2)),
        sa.Column("in_stock", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_price_points_product_id", "price_points", ["product_id"])
    op.create_index(
        "ix_price_points_product_time", "price_points", ["product_id", "captured_at"]
    )

    op.create_table(
        "watches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "notify_price_drop", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "notify_price_rise", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "notify_back_in_stock",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("target_price", sa.Numeric(12, 2)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "product_id", name="uq_watch"),
    )
    op.create_index("ix_watches_user_id", "watches", ["user_id"])
    op.create_index("ix_watches_product_id", "watches", ["product_id"])

    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("old_value", sa.Numeric(12, 2)),
        sa.Column("new_value", sa.Numeric(12, 2)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_events_product_id", "events", ["product_id"])
    op.create_index("ix_events_product_time", "events", ["product_id", "created_at"])

def downgrade() -> None:
    op.drop_table("events")
    op.drop_table("watches")
    op.drop_table("price_points")
    op.drop_table("products")
    op.drop_table("users")
