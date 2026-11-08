from fastapi import APIRouter, Depends, status

from api.deps import get_product_service
from schemas.product import GetProductsResponse, ProductCreate, ProductResponse
from services.product_service import ProductService

router = APIRouter(prefix="/products", tags=["Products"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ProductResponse,
    summary="Create a product",
    description=(
        "Register a new product in the system with a unique product_id, "
        "human-readable name, and optional description. Use this product_id "
        "when uploading documents."
    ),
)
async def create_product(
    payload: ProductCreate,
    service: ProductService = Depends(get_product_service),
) -> ProductResponse:
    return service.create_product(payload)


@router.get(
    "",
    response_model=GetProductsResponse,
    summary="List products",
    description="Retrieve all registered products with associated document counts.",
)
async def list_products(
    service: ProductService = Depends(get_product_service),
) -> GetProductsResponse:
    return service.list_products()


@router.get(
    "/{product_id}",
    response_model=ProductResponse,
    summary="Get product details",
    description="Retrieve details and document count for a specific product ID.",
)
async def get_product(
    product_id: str,
    service: ProductService = Depends(get_product_service),
) -> ProductResponse:
    return service.get_product(product_id)
