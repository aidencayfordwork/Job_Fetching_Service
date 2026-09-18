"""make jobs array columns non-null with empty-array default

Revision ID: 18a1520ba1e1
Revises: c4715c01a3f7
Create Date: 2026-09-18 15:13:58.489766

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '18a1520ba1e1'
down_revision: Union[str, None] = 'c4715c01a3f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ARRAY_COLUMNS = [
    "main_stack",
    "full_technology_stack",
    "eligible_states",
    "excluded_states",
    "responsibilities",
    "required_skills",
    "preferred_skills",
    "matched_keywords",
]


def upgrade() -> None:
    for column in ARRAY_COLUMNS:
        # Autogenerate doesn't backfill existing NULLs or set a server
        # default on its own - both are needed before NOT NULL is safe to
        # apply against rows inserted before this migration.
        op.execute(f"UPDATE jobs SET {column} = '{{}}' WHERE {column} IS NULL")
        op.alter_column(
            'jobs', column,
            existing_type=postgresql.ARRAY(sa.VARCHAR()),
            nullable=False,
            server_default=sa.text("'{}'"),
        )


def downgrade() -> None:
    for column in reversed(ARRAY_COLUMNS):
        op.alter_column(
            'jobs', column,
            existing_type=postgresql.ARRAY(sa.VARCHAR()),
            nullable=True,
            server_default=None,
        )
