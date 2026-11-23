"""stocktake batch id

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-23 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("stock_movements", sa.Column("count_batch_id", sa.Uuid(), nullable=True))
    op.create_index(
        "ix_stock_movements_count_batch", "stock_movements", ["count_batch_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_stock_movements_count_batch", table_name="stock_movements")
    op.drop_column("stock_movements", "count_batch_id")
