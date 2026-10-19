"""数据库基础设施层：创建异步引擎、会话、表结构并初始化演示数据。

数据库连接方言、历史表兼容和开发环境种子数据都集中在本模块，
业务服务只需要依赖统一的异步会话即可。
"""

from __future__ import annotations

# 数据库基础设施：创建异步连接、会话，并集中处理事务与初始化。

import hashlib
from datetime import datetime
from decimal import Decimal

from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.domain.models import Account, AgentPrompt, AppConfig, Base, Category, Coupon, KnowledgeChunk, Merchant, Product, ProductSKU, PromotionRule


def normalize_database_url(url: str) -> str:
    """将常见同步数据库 URL 转换为当前异步驱动可使用的 URL。"""
    if url.startswith("sqlite:///") and not url.startswith("sqlite+aiosqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    if url.startswith("mysql://"):
        return url.replace("mysql://", "mysql+aiomysql://", 1)
    return url


def create_engine(settings: Settings) -> AsyncEngine:
    """根据配置创建异步 SQLAlchemy 引擎，并设置连接池健康检查。"""
    url = normalize_database_url(settings.database_url)
    kwargs: dict[str, object] = {"echo": False, "pool_pre_ping": True}
    if url.startswith("sqlite+"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_async_engine(url, **kwargs)


async def initialize_database(engine: AsyncEngine, settings: Settings) -> None:
    """按配置创建表、补齐旧数据库字段，并在非生产环境写入演示数据。"""
    if not settings.run_migrations:
        return
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(_ensure_phase3_compat_columns)
    if settings.seed_demo_data and settings.app_env != "production":
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await seed_demo_data(session)


def legacy_sha256(password: str) -> str:
    """生成兼容旧演示账号的 SHA-256 密码摘要。"""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


async def seed_demo_data(session: AsyncSession) -> None:
    """向空数据库写入商家、商品、账号、优惠和知识库示例数据。"""
    if await session.scalar(select(Account.account_id).limit(1)) is not None:
        return

    session.add_all(
        [
            Merchant(
                merchant_id="m_001",
                name="小猪数码旗舰店",
                logo_url="/placeholder-merchant.svg",
                description="主营手机、耳机、智能设备和办公外设。",
                service_phone="400-000-0000",
                status="active",
            ),
            Category(category_id="c_phone", parent_id="", name="手机", sort_order=10),
            Category(category_id="c_mouse", parent_id="", name="鼠标", sort_order=20),
            KnowledgeChunk(chunk_id="ck_phone_001", title="X Phone 12 商品详情", snippet="X Phone 12 支持高速对焦、儿童抓拍模式，官方零售价 2999 元。", source="mysql_seed", sort_order=10),
            KnowledgeChunk(chunk_id="ck_mouse_001", title="Quiet Mouse S 商品详情", snippet="Quiet Mouse S 主打静音按键、无线连接和人体工学握持。", source="mysql_seed", sort_order=20),
            Account(
                account_id="acct_user_001",
                username="user",
                password_hash=legacy_sha256("user123456"),
                display_name="演示用户",
                role="user",
                status="active",
            ),
            Account(
                account_id="acct_merchant_001",
                username="merchant",
                password_hash=legacy_sha256("merchant123456"),
                display_name="小猪数码运营",
                role="merchant",
                merchant_id="m_001",
                status="active",
            ),
            Account(
                account_id="acct_admin_001",
                username="admin",
                password_hash=legacy_sha256("admin123456"),
                display_name="平台管理员",
                role="admin",
                status="active",
            ),
            AppConfig(config_key="retrieval.vector.enabled", config_value="false", value_type="bool", description="启用向量召回", domain="retrieval", is_secret=False),
            AppConfig(config_key="files.max_upload_bytes", config_value="10485760", value_type="int", description="文件上传最大字节数", domain="infra", is_secret=False),
            AgentPrompt(prompt_id="prm_default_main", prompt_key="agent.prompt.main_template", title="主 Agent 模板 Prompt", content="你是受控电商导购，只基于工具结果回答。", status="active", version=1, description="阶段 4 演示 Prompt", created_by="system", published_at=datetime.utcnow()),
            PromotionRule(promotion_id="promo_platform_001", name="平台满 300 减 30", scope="platform", type="full_reduction", threshold_amount=Decimal("300.00"), discount_amount=Decimal("30.00"), start_at=datetime(2026, 1, 1), end_at=datetime(2026, 12, 31, 23, 59, 59), status="active"),
            PromotionRule(promotion_id="promo_m_001_001", name="小猪数码满 1000 减 80", scope="merchant", merchant_id="m_001", type="full_reduction", threshold_amount=Decimal("1000.00"), discount_amount=Decimal("80.00"), start_at=datetime(2026, 1, 1), end_at=datetime(2026, 12, 31, 23, 59, 59), status="active"),
            Coupon(coupon_id="coupon_platform_001", name="平台新人满 200 减 20", scope="platform", type="fixed_amount", threshold_amount=Decimal("200.00"), discount_amount=Decimal("20.00"), total_count=10000, per_user_limit=1, start_at=datetime(2026, 1, 1), end_at=datetime(2026, 12, 31, 23, 59, 59), status="active"),
            Coupon(coupon_id="coupon_m_001_001", name="小猪数码满 500 减 50", scope="merchant", merchant_id="m_001", type="fixed_amount", threshold_amount=Decimal("500.00"), discount_amount=Decimal("50.00"), total_count=10000, per_user_limit=1, start_at=datetime(2026, 1, 1), end_at=datetime(2026, 12, 31, 23, 59, 59), status="active"),
        ]
    )
    session.add_all(
        [
            Product(
                product_id="p_001",
                merchant_id="m_001",
                name="X Phone 12",
                brand="X",
                category_id="c_phone",
                image_url="https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?auto=format&fit=crop&w=640&q=80",
                image_urls_json=["https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?auto=format&fit=crop&w=640&q=80"],
                price=Decimal("2999.00"),
                market_price=Decimal("3299.00"),
                stock_quantity=84,
                stock_status="in_stock",
                tags_json=["拍照", "预算内", "抓拍"],
                selling_points_json=["高速对焦", "儿童抓拍模式", "256GB 存储"],
                recommend_reason="抓拍和对焦能力适合日常拍照，价格为 2999 元。",
                risk_notes_json=[],
                attributes_json=[{"key": "存储", "value": "256GB"}],
                suitable_for_json=["拍娃", "日常拍照", "预算敏感"],
                not_suitable_for_json=[],
                description="适合预算内拍照和日常使用的手机。",
                status="active",
                sort_order=10,
            ),
            Product(
                product_id="p_002",
                merchant_id="m_001",
                name="Y Camera Max",
                brand="Y",
                category_id="c_phone",
                image_url="https://images.unsplash.com/photo-1598327105666-5b89351aff97?auto=format&fit=crop&w=640&q=80",
                image_urls_json=["https://images.unsplash.com/photo-1598327105666-5b89351aff97?auto=format&fit=crop&w=640&q=80"],
                price=Decimal("3499.00"),
                market_price=Decimal("3899.00"),
                stock_quantity=32,
                stock_status="in_stock",
                tags_json=["影像旗舰", "长焦", "续航"],
                selling_points_json=["长焦表现好", "夜景稳定", "续航更强"],
                recommend_reason="影像和续航配置更高，价格为 3499 元。",
                risk_notes_json=[],
                attributes_json=[{"key": "存储", "value": "256GB"}],
                suitable_for_json=["旅行拍照", "重视续航"],
                not_suitable_for_json=[],
                description="影像能力更强，但价格超过 3000。",
                status="active",
                sort_order=20,
            ),
            Product(
                product_id="p_mouse_001",
                merchant_id="m_001",
                name="Quiet Mouse S",
                brand="Q",
                category_id="c_mouse",
                image_url="https://images.unsplash.com/photo-1527814050087-3793815479db?auto=format&fit=crop&w=640&q=80",
                image_urls_json=["https://images.unsplash.com/photo-1527814050087-3793815479db?auto=format&fit=crop&w=640&q=80"],
                price=Decimal("129.00"),
                market_price=Decimal("159.00"),
                stock_quantity=120,
                stock_status="in_stock",
                tags_json=["静音", "办公", "无线"],
                selling_points_json=["静音微动", "人体工学", "长续航"],
                recommend_reason="静音、无线、握持舒适，更适合办公和宿舍。",
                risk_notes_json=["不适合高强度电竞"],
                attributes_json=[{"key": "连接", "value": "2.4G 无线 + 蓝牙"}],
                suitable_for_json=["办公", "宿舍", "图书馆"],
                not_suitable_for_json=["高强度电竞"],
                description="适合安静办公环境的无线鼠标。",
                status="active",
                sort_order=30,
            ),
        ]
    )
    session.add_all(
        [
            ProductSKU(sku_id="sku_001", product_id="p_001", sku_name="X Phone 12 标准版", price=Decimal("2999.00"), stock_quantity=84, stock_status="in_stock", specs_json={"版本": "标准版"}, is_default=True),
            ProductSKU(sku_id="sku_002", product_id="p_002", sku_name="Y Camera Max 标准版", price=Decimal("3499.00"), stock_quantity=32, stock_status="in_stock", specs_json={"版本": "标准版"}, is_default=True),
            ProductSKU(sku_id="sku_mouse_001", product_id="p_mouse_001", sku_name="Quiet Mouse S 标准版", price=Decimal("129.00"), stock_quantity=120, stock_status="in_stock", specs_json={"版本": "标准版"}, is_default=True),
        ]
    )
    await session.commit()


def _ensure_phase3_compat_columns(connection) -> None:
    """为复用旧版 SQLite 数据库的开发环境补充新增字段。"""
    inspector = inspect(connection)
    if "knowledge_chunks" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("knowledge_chunks")}
    additions = {
        "document_id": "VARCHAR(64) NOT NULL DEFAULT ''",
        "content": "TEXT NOT NULL DEFAULT ''",
        "doc_type": "VARCHAR(64) NOT NULL DEFAULT ''",
        "merchant_id": "VARCHAR(64) NOT NULL DEFAULT ''",
        "product_id": "VARCHAR(64) NOT NULL DEFAULT ''",
        "category_id": "VARCHAR(64) NOT NULL DEFAULT ''",
        "quality_score": "NUMERIC(5, 4) NOT NULL DEFAULT 0",
        "metadata_json": "JSON NULL",
    }
    for name, definition in additions.items():
        if name not in existing:
            connection.execute(text(f"ALTER TABLE knowledge_chunks ADD COLUMN {name} {definition}"))
