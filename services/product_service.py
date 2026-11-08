import logging
from uuid import uuid4
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.models.document import Document
from db.models.product import Product
from schemas.product import GetProductsResponse, ProductCreate, ProductResponse

logger = logging.getLogger(__name__)


class ProductService:
    """
    Manage lifecycle operations for Product entities.

    Attributes:
        db: SQLAlchemy session for product metadata.
    """

    def __init__(self, db: Session | None = None) -> None:
        self.db = db

    def create_product(self, data: ProductCreate) -> ProductResponse:
        """Create a new product in the database. Generates a UUID if product_id is not provided."""
        if self.db is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database session is not available",
            )

        # Generate a UUID if product_id was omitted or empty
        target_product_id = data.product_id.strip() if data.product_id and data.product_id.strip() else str(uuid4())

        existing = self.db.scalar(
            select(Product).where(Product.product_id == target_product_id)
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Product with ID '{target_product_id}' already exists",
            )

        product = Product(
            product_id=target_product_id,
            name=data.name.strip(),
            description=data.description.strip() if data.description else None,
        )
        self.db.add(product)
        self.db.commit()
        self.db.refresh(product)
        logger.info("Created product | product_id=%s | name=%s", product.product_id, product.name)

        return ProductResponse(
            product_id=product.product_id,
            name=product.name,
            description=product.description,
            document_count=0,
            created_at=product.created_at,
        )

    def list_products(self) -> GetProductsResponse:
        """List all products with associated document counts."""
        if self.db is None:
            return GetProductsResponse(total_count=0, products=[])

        products = self.db.scalars(
            select(Product).order_by(Product.created_at.desc())
        ).all()

        # Count documents per product
        doc_counts_query = (
            select(Document.product_id, func.count(Document.document_id))
            .group_by(Document.product_id)
        )
        doc_counts = dict(self.db.execute(doc_counts_query).all())

        items = [
            ProductResponse(
                product_id=p.product_id,
                name=p.name,
                description=p.description,
                document_count=doc_counts.get(p.product_id, 0),
                created_at=p.created_at,
            )
            for p in products
        ]
        return GetProductsResponse(total_count=len(items), products=items)

    def get_product(self, product_id: str) -> ProductResponse:
        """Fetch a single product by ID with document count."""
        if self.db is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database session is not available",
            )

        product = self.db.scalar(
            select(Product).where(Product.product_id == product_id)
        )
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product with ID '{product_id}' not found",
            )

        count = self.db.scalar(
            select(func.count(Document.document_id)).where(Document.product_id == product_id)
        ) or 0

        return ProductResponse(
            product_id=product.product_id,
            name=product.name,
            description=product.description,
            document_count=count,
            created_at=product.created_at,
        )
