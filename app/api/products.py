from __future__ import annotations



from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_repository
from app.core.errors import APIError
from app.domain.models import Category, Merchant, Product, ProductSKU
from app.domain.schemas import (
    CategoryOut,
    MerchantOut,
    PageResponse,
    ProductAttributeOut,
    ProductCardOut,
    ProductDetailOut,
    ProductSKUOut,
    amount_string,
)
from app.repositories.sql import SQLRepository

router = APIRouter(tags=["catalog"])


def product_card(product: Product, merchant: Merchant, sku: ProductSKU | None) -> ProductCardOut:
    return ProductCardOut(
        productId=product.product_id,
        skuId=sku.sku_id if sku and sku.sku_id else None,
        merchantId=merchant.merchant_id,
        merchantName=merchant.name,
        name=product.name,
        brand=product.brand,
        categoryId=product.category_id,
        imageUrl=product.image_url,
        price=amount_string(product.price),
        marketPrice=amount_string(product.market_price),
        stockStatus=product.stock_status,
        status=product.status,
        tags=list(product.tags_json or []),
        sellingPoints=list(product.selling_points_json or []),
        recommendReason=product.recommend_reason,
        riskNotes=list(product.risk_notes_json or []),
    )


def product_detail(product: Product, merchant: Merchant, sku: ProductSKU | None) -> ProductDetailOut:
    card = product_card(product, merchant, sku)
    return ProductDetailOut(
        **card.model_dump(),
        imageUrls=list(product.image_urls_json or []),
        stockQuantity=product.stock_quantity,
        attributes=[ProductAttributeOut(**item) for item in (product.attributes_json or [])],
        suitableFor=list(product.suitable_for_json or []),
        notSuitableFor=list(product.not_suitable_for_json or []),
        description=product.description,
    )


@router.get("/categories/tree")
async def categories(repository: SQLRepository = Depends(get_repository)) -> dict[str, list[CategoryOut]]:
    rows = await repository.list_categories()
    by_id: dict[str, CategoryOut] = {
        row.category_id: CategoryOut(categoryId=row.category_id, parentId=row.parent_id, name=row.name)
        for row in rows
    }
    roots: list[CategoryOut] = []
    for row in rows:
        item = by_id[row.category_id]
        if row.parent_id and row.parent_id in by_id:
            parent = by_id[row.parent_id]
            if parent.children is None:
                parent.children = []
            parent.children.append(item)
        else:
            roots.append(item)
    return {"items": roots}


@router.get("/merchants", response_model_exclude_none=True)
async def merchants(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    repository: SQLRepository = Depends(get_repository),
) -> PageResponse[MerchantOut]:
    items, total = await repository.list_merchants(page, page_size)
    return PageResponse(items=[MerchantOut(
        merchantId=item.merchant_id,
        name=item.name,
        logoUrl=item.logo_url,
        description=item.description,
        servicePhone=item.service_phone or None,
        status=item.status,
    ) for item in items], page=page, page_size=page_size, total=total)


@router.get("/products", response_model_exclude_none=True)
async def products(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    keyword: str = "",
    category_id: str = "",
    repository: SQLRepository = Depends(get_repository),
) -> PageResponse[ProductCardOut]:
    items, total = await repository.list_product_records(keyword, category_id, page, page_size)
    return PageResponse(items=[product_card(product, merchant, sku) for product, merchant, sku in items], page=page, page_size=page_size, total=total)


@router.get("/products/{product_id}/skus", response_model_exclude_none=True)
async def product_skus(
    product_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    repository: SQLRepository = Depends(get_repository),
) -> PageResponse[ProductSKUOut]:
    all_items = list(await repository.list_product_skus(product_id))
    total = len(all_items)
    items = all_items[(page - 1) * page_size : page * page_size]
    return PageResponse(items=[ProductSKUOut(
        skuId=item.sku_id,
        productId=item.product_id,
        skuName=item.sku_name,
        price=amount_string(item.price),
        stockQuantity=item.stock_quantity,
        stockStatus=item.stock_status,
        specs=dict(item.specs_json or {}),
    ) for item in items], page=page, page_size=page_size, total=total)


@router.get("/products/{product_id}", response_model=ProductDetailOut, response_model_exclude_none=True)
async def product(product_id: str, repository: SQLRepository = Depends(get_repository)) -> ProductDetailOut:
    row = await repository.get_product_record(product_id)
    if row is None:
        raise APIError(404, "product_not_found", "商品不存在")
    return product_detail(*row)
