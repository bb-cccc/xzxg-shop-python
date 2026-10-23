from __future__ import annotations

# 数据访问模块：把业务查询封装为异步 Repository 操作。

from app.repositories.sql_support import *  # noqa: F401,F403


# 能力混入类，把这一领域的操作组合到主类中。
class CatalogRepositoryMixin:
    def _visible_product_filter(self):
        return (Product.status == 'active', Merchant.status == 'active')

    def _keyword_filter(self, keyword: str):
        raw = keyword.strip()
        terms: list[str] = []
        seen: set[str] = set()
        for item in [raw, *raw.split()]:
            item = item.strip()
            normalized = item.lower()
            if item and normalized not in seen:
                terms.append(item)
                seen.add(normalized)
            if len(terms) >= 10:
                break
        if not terms:
            return None
        clauses = []
        for term in terms:
            pattern = f'%{term}%'
            clauses.append(or_(Product.name.ilike(pattern), Product.brand.ilike(pattern), Category.name.ilike(pattern), cast(Product.tags_json, String).ilike(pattern), cast(Product.selling_points_json, String).ilike(pattern)))
        return or_(*clauses)

    def _product_record_query(self):
        return select(Product, Merchant, ProductSKU).join(Merchant, Merchant.merchant_id == Product.merchant_id).join(Category, Category.category_id == Product.category_id, isouter=True).join(ProductSKU, and_(ProductSKU.product_id == Product.product_id, ProductSKU.is_default.is_(True)), isouter=True)

    async def list_product_records(self, keyword: str, category_id: str, page: int, page_size: int) -> tuple[list[tuple[Product, Merchant, ProductSKU | None]], int]:
        visible_product, visible_merchant = self._visible_product_filter()
        filters = [visible_product, visible_merchant]
        if category_id:
            filters.append(or_(Product.category_id == category_id, Category.parent_id == category_id))
        keyword_filter = self._keyword_filter(keyword)
        if keyword_filter is not None:
            filters.append(keyword_filter)
        count_stmt = select(func.count(Product.product_id)).select_from(Product).join(Merchant, Merchant.merchant_id == Product.merchant_id).join(Category, Category.category_id == Product.category_id, isouter=True).where(*filters)
        total = int((await self.session.execute(count_stmt)).scalar_one() or 0)
        stmt = self._product_record_query().where(*filters).order_by(Product.sort_order, Product.product_id).offset((page - 1) * page_size).limit(page_size)
        rows = (await self.session.execute(stmt)).all()
        return ([(product, merchant, sku) for product, merchant, sku in rows], total)

    async def get_product_record(self, product_id: str) -> tuple[Product, Merchant, ProductSKU | None] | None:
        stmt = self._product_record_query().where(Product.product_id == product_id)
        row = (await self.session.execute(stmt)).first()
        if row is None:
            return None
        product, merchant, sku = row
        return (product, merchant, sku)

    async def list_product_skus(self, product_id: str) -> Sequence[ProductSKU]:
        stmt = select(ProductSKU).where(ProductSKU.product_id == product_id).order_by(ProductSKU.sku_id)
        return (await self.session.execute(stmt)).scalars().all()

    async def list_categories(self) -> Sequence[Category]:
        stmt = select(Category).order_by(Category.sort_order, Category.category_id)
        return (await self.session.execute(stmt)).scalars().all()

    async def list_merchants(self, page: int, page_size: int) -> tuple[list[Merchant], int]:
        filters = [Merchant.status == 'active']
        count_stmt = select(func.count(Merchant.merchant_id)).where(*filters)
        total = int((await self.session.execute(count_stmt)).scalar_one() or 0)
        stmt = select(Merchant).where(*filters).order_by(Merchant.merchant_id).offset((page - 1) * page_size).limit(page_size)
        return (list((await self.session.execute(stmt)).scalars().all()), total)
