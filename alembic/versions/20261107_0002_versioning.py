"""Add versioning columns to documents table and create products table.

Revision:   20261107_0002
Parent:     20260925_0001 (initial)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20261107_0002"
down_revision: Union[str, Sequence[str], None] = "20260925_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create products table
    op.create_table(
        "products",
        sa.Column("product_id", sa.String(255), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # 2. Add versioning columns to documents using batch mode for SQLite compatibility
    with op.batch_alter_table("documents") as batch_op:
        batch_op.add_column(sa.Column("doc_family_id", sa.String(255), nullable=False, server_default="default"))
        batch_op.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(
            sa.Column(
                "parent_id",
                sa.String(255),
                sa.ForeignKey("documents.document_id", ondelete="SET NULL"),
                nullable=True,
            )
        )
        batch_op.add_column(sa.Column("is_latest", sa.Boolean(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("storage_path", sa.String(1024), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("minhash_sketch", sa.JSON(), nullable=True))

        batch_op.create_index("ix_documents_doc_family_id", ["doc_family_id"])
        batch_op.create_index("ix_documents_parent_id", ["parent_id"])
        batch_op.create_index("ix_documents_is_latest", ["is_latest"])


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_index("ix_documents_is_latest")
        batch_op.drop_index("ix_documents_parent_id")
        batch_op.drop_index("ix_documents_doc_family_id")
        batch_op.drop_column("minhash_sketch")
        batch_op.drop_column("storage_path")
        batch_op.drop_column("is_latest")
        batch_op.drop_column("parent_id")
        batch_op.drop_column("version")
        batch_op.drop_column("doc_family_id")

    op.drop_table("products")
