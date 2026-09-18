"""rename extracted_keywords to matched_keywords

Revision ID: c4715c01a3f7
Revises: 71ecdb7d359c
Create Date: 2026-09-18 13:16:31.896595

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c4715c01a3f7'
down_revision: Union[str, None] = '71ecdb7d359c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('jobs', 'extracted_keywords', new_column_name='matched_keywords')
    op.drop_index(op.f('ix_jobs_extracted_keywords'), table_name='jobs', postgresql_using='gin')
    op.create_index('ix_jobs_matched_keywords', 'jobs', ['matched_keywords'], unique=False, postgresql_using='gin')


def downgrade() -> None:
    op.drop_index('ix_jobs_matched_keywords', table_name='jobs', postgresql_using='gin')
    op.create_index(op.f('ix_jobs_extracted_keywords'), 'jobs', ['extracted_keywords'], unique=False, postgresql_using='gin')
    op.alter_column('jobs', 'matched_keywords', new_column_name='extracted_keywords')
