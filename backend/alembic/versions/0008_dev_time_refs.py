"""dev time refs

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-23 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "dev_time_refs",
        sa.Column("film_id", sa.Uuid(), nullable=False),
        sa.Column("ei", sa.Numeric(precision=7, scale=2), nullable=False),
        sa.Column("developer_id", sa.Uuid(), nullable=False),
        sa.Column("minutes", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("ei > 0", name=op.f("ck_dev_time_refs_ei_positive")),
        sa.CheckConstraint("minutes > 0", name=op.f("ck_dev_time_refs_minutes_positive")),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_dev_time_refs_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["developer_id"],
            ["developers.id"],
            name=op.f("fk_dev_time_refs_developer_id_developers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["film_id"],
            ["films.id"],
            name=op.f("fk_dev_time_refs_film_id_films"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_dev_time_refs_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dev_time_refs")),
        sa.UniqueConstraint("film_id", "ei", "developer_id", name=op.f("uq_dev_time_refs_film_id")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("dev_time_refs")
