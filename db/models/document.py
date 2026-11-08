from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base


class Document(Base):
    __tablename__ = "documents"

    document_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    product_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    # --- Versioning & document-family lineage ---
    doc_family_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    parent_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        ForeignKey("documents.document_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    is_latest: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    # --- MinIO hierarchical storage path ---
    # e.g.  products/{product_id}/{doc_family_id}/v{version}/{filename}
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False, default="")

    # --- MinHash sketch (84 ints stored as JSON array) ---
    minhash_sketch: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
