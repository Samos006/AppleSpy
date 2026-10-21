import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("products", sa.Column("pending_in_stock", sa.Boolean()))
    op.add_column(
        "products",
        sa.Column("pending_count", sa.Integer(), nullable=False, server_default="0"),
    )

def downgrade() -> None:
    op.drop_column("products", "pending_count")
    op.drop_column("products", "pending_in_stock")
