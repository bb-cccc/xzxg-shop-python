from __future__ import annotations

# 数据访问模块：把业务查询封装为异步 Repository 操作。

from app.repositories.sql_support import *  # noqa: F401,F403


# 能力混入类，把这一领域的操作组合到主类中。
class CommerceRepositoryMixin:

    async def _cart_rows(self, account_id: str, *, lock: bool=False):
        stmt = select(CartItem, Product, Merchant, ProductSKU).join(Product, Product.product_id == CartItem.product_id).join(Merchant, Merchant.merchant_id == Product.merchant_id).join(ProductSKU, ProductSKU.sku_id == CartItem.sku_id, isouter=True).where(CartItem.account_id == account_id).order_by(CartItem.created_at, CartItem.cart_item_id)
        if lock:
            stmt = stmt.with_for_update()
        return list((await self.session.execute(stmt)).all())

    async def get_cart_rows(self, account_id: str):
        return await self._cart_rows(account_id)

    async def add_cart_item(self, account_id: str, product_id: str, sku_id: str, quantity: int) -> bool:
        quantity = max(1, quantity)
        await self._prepare_write()
        try:
            async with self.session.begin():
                product = await self.session.scalar(select(Product).where(Product.product_id == product_id).with_for_update())
                if product is None or product.status != 'active' or product.stock_quantity <= 0:
                    return False
                if not sku_id:
                    sku_id = str(await self.session.scalar(select(ProductSKU.sku_id).where(ProductSKU.product_id == product_id).order_by(ProductSKU.sku_id).limit(1)) or '')
                sku = None
                if sku_id:
                    sku = await self.session.scalar(select(ProductSKU).where(ProductSKU.product_id == product_id, ProductSKU.sku_id == sku_id).with_for_update())
                    if sku is None or sku.stock_status == 'out_of_stock' or sku.stock_quantity <= 0:
                        return False
                existing = await self.session.scalar(select(CartItem).where(CartItem.account_id == account_id, CartItem.product_id == product_id, CartItem.sku_id == sku_id).with_for_update())
                available = sku.stock_quantity if sku is not None else product.stock_quantity
                if existing is not None and existing.quantity + quantity > available:
                    return False
                if existing is None:
                    self.session.add(CartItem(cart_item_id=self._new_id('cart'), account_id=account_id, product_id=product_id, sku_id=sku_id, quantity=quantity, selected=True))
                else:
                    existing.quantity += quantity
                    existing.selected = True
                    existing.updated_at = datetime.now(timezone.utc)
                return True
        except IntegrityError:
            await self.session.rollback()
            return False

    async def checkout(self, account_id: str) -> list[tuple[Order, list[OrderItem], str]]:
        await self._prepare_write()
        try:
            async with self.session.begin():
                rows = await self._cart_rows(account_id, lock=True)
                selected = [row for row in rows if row[0].selected]
                if not selected:
                    return []
                discount_data = await self._calculate_cart_discount(account_id, rows, lock=True)
                total_discount = Decimal(str(discount_data['discount_amount']))
                coupon_lines = [line for line in discount_data['lines'] if line.get('type') == 'coupon']
                grouped: dict[str, list[tuple[CartItem, Product, Merchant, ProductSKU | None]]] = {}
                for cart_item, product, merchant, sku in selected:
                    if product.stock_quantity < cart_item.quantity:
                        raise ValueError('库存不足')
                    if sku is not None and sku.stock_quantity < cart_item.quantity:
                        raise ValueError('库存不足')
                    grouped.setdefault(product.merchant_id, []).append((cart_item, product, merchant, sku))
                created: list[tuple[Order, list[OrderItem], str]] = []
                total_order_amount = sum((Decimal(str(sku.price if sku is not None else product.price)) * quantity.quantity for merchant_rows in grouped.values() for quantity, product, _merchant, sku in merchant_rows), Decimal('0.00'))
                allocated_discount = Decimal('0.00')
                created_order_count = 0
                merchant_ids = list(grouped)
                for merchant_id, merchant_rows in grouped.items():
                    total = sum((Decimal(str(sku.price if sku is not None else product.price)) * quantity.quantity for quantity, product, _merchant, sku in merchant_rows), Decimal('0.00'))
                    if merchant_id == merchant_ids[-1]:
                        order_discount = min(total, max(Decimal('0.00'), total_discount - allocated_discount))
                    else:
                        order_discount = (total_discount * total / total_order_amount).quantize(Decimal('0.01')) if total_order_amount else Decimal('0.00')
                        order_discount = min(total, order_discount)
                    allocated_discount += order_discount
                    now = datetime.now(timezone.utc)
                    order = Order(order_id=self._new_id('ord'), order_no=f"NO{now.strftime('%Y%m%d%H%M%S')}{secrets.token_hex(3)}", account_id=account_id, merchant_id=merchant_id, status='pending_payment', total_amount=total, discount_amount=order_discount, pay_amount=max(Decimal('0.00'), total - order_discount), payment_deadline_at=now + timedelta(minutes=30), created_at=now, updated_at=now)
                    self.session.add(order)
                    items: list[OrderItem] = []
                    for cart_item, product, merchant, sku in merchant_rows:
                        updated_product = await self.session.execute(update(Product).where(Product.product_id == product.product_id, Product.stock_quantity >= cart_item.quantity).values(stock_quantity=Product.stock_quantity - cart_item.quantity, stock_status=case((Product.stock_quantity - cart_item.quantity <= 0, 'out_of_stock'), else_=Product.stock_status), updated_at=datetime.now(timezone.utc)))
                        if updated_product.rowcount != 1:
                            raise ValueError('库存不足')
                        if sku is not None:
                            updated_sku = await self.session.execute(update(ProductSKU).where(ProductSKU.sku_id == sku.sku_id, ProductSKU.stock_quantity >= cart_item.quantity).values(stock_quantity=ProductSKU.stock_quantity - cart_item.quantity, stock_status=case((ProductSKU.stock_quantity - cart_item.quantity <= 0, 'out_of_stock'), else_=ProductSKU.stock_status), updated_at=datetime.now(timezone.utc)))
                            if updated_sku.rowcount != 1:
                                raise ValueError('库存不足')
                        item = OrderItem(order_item_id=self._new_id('oi'), order_id=order.order_id, product_id=product.product_id, sku_id=cart_item.sku_id, name=product.name, image_url=product.image_url, price=sku.price if sku is not None else product.price, quantity=cart_item.quantity, merchant_id=merchant.merchant_id, merchant_name=merchant.name)
                        items.append(item)
                        self.session.add(item)
                        self.session.add(cart_item)
                        await self.session.delete(cart_item)
                    self.session.add(Payment(payment_id=self._new_id('pay'), order_id=order.order_id, account_id=account_id, amount=order.pay_amount, status='pending', method='mock_balance', expires_at=order.payment_deadline_at, created_at=now, updated_at=now))
                    if created_order_count == 0:
                        for line in coupon_lines:
                            user_coupon = await self.session.scalar(select(UserCoupon).where(UserCoupon.user_coupon_id == line.get('id'), UserCoupon.account_id == account_id, UserCoupon.status == 'unused').with_for_update())
                            if user_coupon is not None:
                                user_coupon.status = 'used'
                                user_coupon.order_id = order.order_id
                                user_coupon.used_at = now
                    created_order_count += 1
                    created.append((order, items, merchant_rows[0][2].name))
                return created
        except ValueError:
            await self.session.rollback()
            raise

    async def update_cart_item(self, account_id: str, cart_item_id: str, quantity: int | None=None, selected: bool | None=None) -> bool:
        await self._prepare_write()
        try:
            async with self.session.begin():
                item = await self.session.scalar(select(CartItem).where(CartItem.account_id == account_id, CartItem.cart_item_id == cart_item_id).with_for_update())
                if item is None:
                    return False
                if quantity is not None:
                    if quantity <= 0:
                        return False
                    product = await self.session.scalar(select(Product).where(Product.product_id == item.product_id).with_for_update())
                    sku = await self.session.scalar(select(ProductSKU).where(ProductSKU.sku_id == item.sku_id, ProductSKU.product_id == item.product_id).with_for_update()) if item.sku_id else None
                    available = sku.stock_quantity if sku is not None else product.stock_quantity if product is not None else 0
                    if product is None or product.status != 'active' or quantity > available:
                        return False
                    item.quantity = quantity
                if selected is not None:
                    item.selected = selected
                item.updated_at = datetime.now(timezone.utc)
                return True
        except IntegrityError:
            await self.session.rollback()
            return False

    async def delete_cart_item(self, account_id: str, cart_item_id: str) -> bool:
        await self._prepare_write()
        async with self.session.begin():
            item = await self.session.scalar(select(CartItem).where(CartItem.account_id == account_id, CartItem.cart_item_id == cart_item_id).with_for_update())
            if item is None:
                return False
            await self.session.delete(item)
            return True

    async def _calculate_cart_discount(self, account_id: str, rows, *, lock: bool=False) -> dict[str, object]:
        total = Decimal('0.00')
        merchant_totals: dict[str, Decimal] = {}
        for cart_item, product, merchant, sku in rows:
            if not cart_item.selected:
                continue
            price = Decimal(str(sku.price if sku and sku.price is not None else product.price))
            line = price * cart_item.quantity
            total += line
            merchant_totals[merchant.merchant_id] = merchant_totals.get(merchant.merchant_id, Decimal('0.00')) + line
        now = datetime.now(timezone.utc)
        lines: list[dict[str, str]] = []
        discount = Decimal('0.00')
        promotions = list((await self.session.execute(select(PromotionRule).where(PromotionRule.status == 'active', PromotionRule.start_at <= now, PromotionRule.end_at >= now).order_by(PromotionRule.created_at.desc()))).scalars().all())
        for promotion in promotions:
            base = merchant_totals.get(promotion.merchant_id, Decimal('0.00')) if promotion.scope == 'merchant' else total
            value = self._discount_amount(base, promotion.type, Decimal(str(promotion.threshold_amount)), Decimal(str(promotion.discount_amount)), Decimal(str(promotion.discount_rate)))
            if value > 0:
                discount += value
                lines.append({'type': 'promotion', 'id': promotion.promotion_id, 'name': promotion.name, 'amount': f'{value:.2f}'})
        coupon_stmt = select(UserCoupon, Coupon).join(Coupon, Coupon.coupon_id == UserCoupon.coupon_id).where(UserCoupon.account_id == account_id, UserCoupon.status == 'unused')
        if lock:
            coupon_stmt = coupon_stmt.with_for_update()
        user_coupons = list((await self.session.execute(coupon_stmt)).all())
        for user_coupon, coupon in user_coupons:
            if coupon.status != 'active' or (self._aware(coupon.start_at) and self._aware(coupon.start_at) > now) or (self._aware(coupon.end_at) and self._aware(coupon.end_at) < now):
                continue
            base = merchant_totals.get(coupon.merchant_id, Decimal('0.00')) if coupon.scope == 'merchant' else total
            value = self._discount_amount(base, coupon.type, Decimal(str(coupon.threshold_amount)), Decimal(str(coupon.discount_amount)))
            if value > 0:
                discount += value
                lines.append({'type': 'coupon', 'id': user_coupon.user_coupon_id, 'name': coupon.name, 'amount': f'{value:.2f}'})
        discount = min(total, discount)
        return {'total_amount': f'{total:.2f}', 'discount_amount': f'{discount:.2f}', 'pay_amount': f'{total - discount:.2f}', 'lines': lines}

    async def preview_cart_discount(self, account_id: str) -> dict[str, object]:
        return await self._calculate_cart_discount(account_id, await self._cart_rows(account_id))

    async def list_orders(self, *, account_id: str='', merchant_id: str='', page: int=1, page_size: int=10) -> tuple[list[tuple[Order, Merchant, list[OrderItem]]], int]:
        filters = []
        if account_id:
            filters.append(Order.account_id == account_id)
        if merchant_id:
            filters.append(Order.merchant_id == merchant_id)
        total = int((await self.session.execute(select(func.count(Order.order_id)).where(*filters))).scalar_one() or 0)
        rows = list((await self.session.execute(select(Order, Merchant).join(Merchant, Merchant.merchant_id == Order.merchant_id).where(*filters).order_by(Order.created_at.desc(), Order.order_id.desc()).offset((page - 1) * page_size).limit(page_size))).all())
        result: list[tuple[Order, Merchant, list[OrderItem]]] = []
        for order, merchant in rows:
            items = list((await self.session.execute(select(OrderItem).where(OrderItem.order_id == order.order_id).order_by(OrderItem.order_item_id))).scalars().all())
            result.append((order, merchant, items))
        return (result, total)

    async def get_order_detail(self, account_id: str, order_id: str, *, is_admin: bool=False) -> tuple[Order, Merchant, list[OrderItem], Payment | None] | None:
        filters = [Order.order_id == order_id]
        if not is_admin:
            filters.append(Order.account_id == account_id)
        row = (await self.session.execute(select(Order, Merchant).join(Merchant, Merchant.merchant_id == Order.merchant_id).where(*filters))).first()
        if row is None:
            return None
        order, merchant = row
        items = list((await self.session.execute(select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.order_item_id))).scalars().all())
        payment = await self.session.scalar(select(Payment).where(Payment.order_id == order_id).order_by(Payment.created_at.desc()))
        return (order, merchant, items, payment)

    async def pay_order(self, account_id: str, order_id: str, method: str='mock_balance') -> tuple[Order, Payment] | None:
        await self._prepare_write()
        async with self.session.begin():
            order = await self.session.scalar(select(Order).where(Order.order_id == order_id, Order.account_id == account_id).with_for_update())
            if order is None:
                return None
            payment = await self.session.scalar(select(Payment).where(Payment.order_id == order_id).order_by(Payment.created_at.desc()).with_for_update())
            now = datetime.now(timezone.utc)
            deadline = self._aware(order.payment_deadline_at)
            if not can_transition(order.status, 'pending_ship') or (deadline and now > deadline) or payment is None or (payment.status != 'pending'):
                return None
            order.status = 'pending_ship'
            order.paid_at = now
            order.updated_at = now
            payment.status = 'success'
            payment.method = method.strip() or 'mock_balance'
            payment.transaction_no = self._new_id('txn')
            payment.paid_at = now
            payment.updated_at = now
            return (order, payment)

    # 取消
    async def cancel_order(self, account_id: str, order_id: str, reason: str='') -> Order | None:
        await self._prepare_write()
        async with self.session.begin():
            order = await self.session.scalar(select(Order).where(Order.order_id == order_id, Order.account_id == account_id).with_for_update())
            if order is None or not can_transition(order.status, 'canceled'):
                return None
            payment = await self.session.scalar(select(Payment).where(Payment.order_id == order_id, Payment.status == 'pending').order_by(Payment.created_at.desc()).with_for_update())
            now = datetime.now(timezone.utc)
            order.status = 'canceled'
            order.closed_at = now
            order.cancel_reason = reason.strip()[:256] or '用户取消'
            order.updated_at = now
            if payment is not None:
                payment.status = 'failed'
                payment.updated_at = now
            return order

    async def confirm_receipt(self, account_id: str, order_id: str) -> Order | None:
        await self._prepare_write()
        async with self.session.begin():
            order = await self.session.scalar(select(Order).where(Order.order_id == order_id, Order.account_id == account_id).with_for_update())
            if order is None or not can_transition(order.status, 'completed'):
                return None
            now = datetime.now(timezone.utc)
            order.status = 'completed'
            order.completed_at = now
            order.updated_at = now
            return order

    async def update_order_status(self, order_id: str, status: str, merchant_id: str='') -> tuple[Order, Merchant, list[OrderItem]] | None:
        await self._prepare_write()
        async with self.session.begin():
            order = await self.session.scalar(select(Order).where(Order.order_id == order_id).with_for_update())
            if order is None:
                return None
            merchant = await self.session.get(Merchant, order.merchant_id)
            if merchant is None or (merchant_id and order.merchant_id != merchant_id) or (not can_transition(order.status, status)):
                return None
            items = list((await self.session.execute(select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.order_item_id))).scalars().all())
            order.status = status
            now = datetime.now(timezone.utc)
            order.updated_at = now
            if status == 'completed':
                order.completed_at = now
            if status in {'canceled', 'closed_timeout'}:
                order.closed_at = now
            return (order, merchant, items)

    async def expire_pending_orders(self) -> int:
        now = datetime.now(timezone.utc)
        rows = list((await self.session.execute(select(Order).where(Order.status == 'pending_payment', Order.payment_deadline_at.is_not(None), Order.payment_deadline_at < now))).scalars().all())
        for order in rows:
            order.status = 'closed_timeout'
            order.closed_at = now
            order.cancel_reason = '支付超时自动关闭'
            order.updated_at = now
            payments = list((await self.session.execute(select(Payment).where(Payment.order_id == order.order_id, Payment.status == 'pending'))).scalars().all())
            for payment in payments:
                payment.status = 'expired'
                payment.updated_at = now
        if rows:
            await self.session.commit()
        return len(rows)

    async def list_promotions(self, merchant_id: str='', page: int=1, page_size: int=10) -> tuple[list[PromotionRule], int]:
        filters = [PromotionRule.merchant_id == merchant_id] if merchant_id else []
        total = int((await self.session.execute(select(func.count(PromotionRule.promotion_id)).where(*filters))).scalar_one() or 0)
        stmt = select(PromotionRule).where(*filters).order_by(PromotionRule.created_at.desc(), PromotionRule.promotion_id.desc()).offset((page - 1) * page_size).limit(page_size)
        return (list((await self.session.execute(stmt)).scalars().all()), total)

    # 创建 create_promotion 
    async def create_promotion(self, item: PromotionRule) -> PromotionRule:
        self.session.add(item)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    # 更新 update_promotion_status 
    async def update_promotion_status(self, promotion_id: str, status: str, merchant_id: str='') -> PromotionRule | None:
        stmt = select(PromotionRule).where(PromotionRule.promotion_id == promotion_id)
        if merchant_id:
            stmt = stmt.where(PromotionRule.merchant_id == merchant_id)
        item = await self.session.scalar(stmt)
        if item is None:
            return None
        item.status = status
        item.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(item)
        return item

    # 列出 list_available_coupons 
    async def list_available_coupons(self, page: int=1, page_size: int=10) -> tuple[list[Coupon], int]:
        now = datetime.now(timezone.utc)
        filters = [Coupon.status == 'active', Coupon.start_at <= now, Coupon.end_at >= now, or_(Coupon.total_count == 0, Coupon.claimed_count < Coupon.total_count)]
        total = int((await self.session.execute(select(func.count(Coupon.coupon_id)).where(*filters))).scalar_one() or 0)
        stmt = select(Coupon).where(*filters).order_by(Coupon.created_at.desc(), Coupon.coupon_id.desc()).offset((page - 1) * page_size).limit(page_size)
        return (list((await self.session.execute(stmt)).scalars().all()), total)

    # 列出 list_user_coupons 
    async def list_user_coupons(self, account_id: str, page: int=1, page_size: int=10) -> tuple[list[tuple[UserCoupon, Coupon]], int]:
        filters = [UserCoupon.account_id == account_id]
        total = int((await self.session.execute(select(func.count(UserCoupon.user_coupon_id)).where(*filters))).scalar_one() or 0)
        stmt = select(UserCoupon, Coupon).join(Coupon, Coupon.coupon_id == UserCoupon.coupon_id).where(*filters).order_by(UserCoupon.claimed_at.desc(), UserCoupon.user_coupon_id.desc()).offset((page - 1) * page_size).limit(page_size)
        return (list((await self.session.execute(stmt)).all()), total)

    async def claim_coupon(self, account_id: str, coupon_id: str) -> tuple[UserCoupon, Coupon] | None:
        now = datetime.now(timezone.utc)
        await self._prepare_write()
        try:
            async with self.session.begin():
                coupon = await self.session.scalar(select(Coupon).where(Coupon.coupon_id == coupon_id).with_for_update())
                if coupon is None or coupon.status != 'active' or (coupon and self._aware(coupon.start_at) and (self._aware(coupon.start_at) > now)) or (coupon and self._aware(coupon.end_at) and (self._aware(coupon.end_at) < now)):
                    return None
                if coupon.total_count > 0 and coupon.claimed_count >= coupon.total_count:
                    return None
                owned = int((await self.session.execute(select(func.count(UserCoupon.user_coupon_id)).where(UserCoupon.account_id == account_id, UserCoupon.coupon_id == coupon_id))).scalar_one() or 0)
                if owned >= max(1, coupon.per_user_limit):
                    return None
                item = UserCoupon(user_coupon_id=self._new_id('uc'), coupon_id=coupon_id, account_id=account_id, status='unused', claimed_at=now)
                coupon.claimed_count += 1
                self.session.add(item)
                await self.session.flush()
                return (item, coupon)
        except IntegrityError:
            await self.session.rollback()
            return None

    async def create_product_review(self, account_id: str, order_id: str, order_item_id: str, rating: int, content: str, tags: list[str]) -> ProductReview | None:
        if rating < 1 or rating > 5 or (not content.strip()):
            return None
        row = (await self.session.execute(select(OrderItem, Order).join(Order, Order.order_id == OrderItem.order_id).where(OrderItem.order_item_id == order_item_id, OrderItem.order_id == order_id, Order.account_id == account_id))).first()
        if row is None or row[1].status != 'completed':
            return None
        item, _order = row
        review = ProductReview(review_id=self._new_id('rev'), order_id=order_id, order_item_id=order_item_id, product_id=item.product_id, sku_id=item.sku_id, account_id=account_id, rating=rating, content=content.strip(), tags_json=[str(tag).strip() for tag in tags if str(tag).strip()][:20], status='visible')
        self.session.add(review)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            return None
        await self.session.refresh(review)
        return review

    async def list_product_reviews(self, product_id: str, page: int=1, page_size: int=10, *, merchant_id: str='', all_status: bool=False) -> tuple[list[ProductReview], int]:
        filters = [ProductReview.product_id == product_id] if product_id else []
        if merchant_id:
            filters.append(Product.merchant_id == merchant_id)
        if not all_status:
            filters.append(ProductReview.status == 'visible')
        stmt_base = select(ProductReview).join(Product, Product.product_id == ProductReview.product_id, isouter=bool(merchant_id)).where(*filters)
        total = len(list((await self.session.execute(stmt_base)).scalars().all()))
        stmt = stmt_base.order_by(ProductReview.created_at.desc(), ProductReview.review_id.desc()).offset((page - 1) * page_size).limit(page_size)
        return (list((await self.session.execute(stmt)).scalars().all()), total)

    async def reply_review(self, merchant_id: str, review_id: str, reply: str) -> ProductReview | None:
        if not reply.strip():
            return None
        row = (await self.session.execute(select(ProductReview, Product).join(Product, Product.product_id == ProductReview.product_id).where(ProductReview.review_id == review_id, Product.merchant_id == merchant_id))).first()
        if row is None:
            return None
        review = row[0]
        review.merchant_reply = reply.strip()[:1000]
        review.merchant_replied_at = datetime.now(timezone.utc)
        review.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(review)
        return review

    async def update_review_status(self, review_id: str, status: str) -> ProductReview | None:
        item = await self.session.get(ProductReview, review_id)
        if item is None:
            return None
        item.status = status
        item.updated_at = datetime.now(timezone.utc)
        await self.session.commit()
        await self.session.refresh(item)
        return item
