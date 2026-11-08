from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ProductCreate(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Human-readable product name",
    )
    product_id: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Optional custom product identifier. If omitted, a UUID will be generated automatically.",
    )
    description: Optional[str] = Field(
        default=None,
        max_length=1024,
        description="Optional detailed product description",
    )


class ProductResponse(BaseModel):
    product_id: str = Field(..., description="Unique product identifier (UUID or custom string)")
    name: str = Field(..., description="Human-readable product name")
    description: Optional[str] = Field(default=None, description="Product description")
    document_count: int = Field(default=0, description="Total documents associated with this product")
    created_at: datetime = Field(..., description="Timestamp when product was created")


class GetProductsResponse(BaseModel):
    total_count: int = Field(..., description="Total products registered")
    products: list[ProductResponse] = Field(..., description="List of registered products")
