"""Allow SHA-256-only ingestion before normalized hashing is implemented.

Revision ID: 20260926_0002
Revises: 20260925_0001
"""
from typing import Sequence, Union

from alembic import op


revision: str = "20260926_0002"
down_revision: Union[str, Sequence[str], None] = "20260925_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("document_versions") as batch_op:
        batch_op.alter_column("normalized_hash", nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("document_versions") as batch_op:
        batch_op.alter_column("normalized_hash", nullable=False)