from __future__ import annotations

# 核心基础设施模块：集中管理配置、日志、限流和运行时状态。

import hashlib
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.domain.models import Account, AgentPrompt, AppConfig, Base, Category, Coupon, KnowledgeChunk, Merchant, Product, ProductSKU, PromotionRule


# 规范化 normalize_database_url 
def normalize_database_url(url: str) -> str:
    if url.startswith("sqlite:///") and not url.startswith("sqlite+aiosqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    if url.startswith("mysql://"):
        return url.replace("mysql://", "mysql+aiomysql://", 1)
    return url


# 创建 create_engine 
def create_engine(settings: Settings) -> AsyncEngine:
    url = normalize_database_url(settings.database_url)
    kwargs: dict[str, object] = {"echo": False, "pool_pre_ping": True}
    if url.startswith("sqlite+"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_async_engine(url, **kwargs)


async def initialize_database(engine: AsyncEngine, settings: Settings) -> None:
    if settings.app_env.strip().lower() == "production" and settings.seed_demo_data:
        raise RuntimeError("SEED_DEMO_DATA must be false in production")
    schema_mode = str(getattr(settings, "database_schema_mode", "auto")).strip().lower()
    app_env = settings.app_env.strip().lower()
    if schema_mode == "auto" and app_env not in {"development", "dev", "test", "local"}:
        raise RuntimeError("DATABASE_SCHEMA_MODE=auto is only allowed in development or test")
    if schema_mode == "auto" and settings.run_migrations:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.run_sync(_ensure_phase3_compat_columns)
    elif schema_mode == "alembic" and settings.run_migrations:
        raise RuntimeError("DATABASE_SCHEMA_MODE=alembic requires running python -m scripts.migrate before startup")
    elif schema_mode not in {"auto", "alembic"}:
        raise ValueError("DATABASE_SCHEMA_MODE must be auto or alembic")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    if settings.seed_demo_data and settings.app_env != "production":
        async with factory() as session:
            await seed_demo_data(session)
    else:
        async with factory() as session:
            await _ensure_runtime_defaults(session)
            await session.commit()


def legacy_sha256(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


async def seed_demo_data(session: AsyncSession) -> None:
    if await session.scalar(select(Account.account_id).limit(1)) is not None:
        await _ensure_runtime_defaults(session)
        await session.commit()
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
            AgentPrompt(prompt_id="prm_default_main", prompt_key="agent.prompt.main_template", title="主 Agent 模板 Prompt", content="你是受控电商导购，只基于工具结果回答。", status="active", version=1, description="阶段 4 演示 Prompt", created_by="system", published_at=datetime.now(timezone.utc)),
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
    await _ensure_runtime_defaults(session)
    await session.commit()


async def _ensure_runtime_defaults(session: AsyncSession) -> None:
    """Fill the configuration/prompt catalog when opening a Go-created database."""
    defaults = [
        ("ai.enabled", "false", "bool", "是否启用真实模型调用", "app", False),
        ("ai.active_provider", "qwen", "string", "当前生效模型供应商", "app", False),
        ("ai.qwen.base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1", "string", "千问 OpenAI 兼容模型服务 Base URL", "app", False),
        ("ai.qwen.small_model", "qwen3.5-flash", "string", "千问低成本小模型", "app", False),
        ("ai.qwen.large_model", "qwen3.7-plus", "string", "千问复杂导购决策模型", "app", False),
        ("http.cors.allowed_origins", "*", "string", "允许跨域访问的 Origin", "infra", False),
        ("files.max_upload_bytes", "10485760", "int", "文件上传最大字节数", "infra", False),
        ("tts.provider", "xunfei", "string", "TTS 供应商：xunfei 或 doubao", "infra", False),
        ("xunfei.tts.enabled", "false", "bool", "是否启用讯飞在线语音合成", "infra", False),
        ("xunfei.tts.max_runes", "800", "int", "TTS 单次合成最大字符数", "infra", False),
        ("doubao.tts.enabled", "false", "bool", "是否启用豆包语音合成", "infra", False),
        ("vector.enabled", "false", "bool", "是否启用向量召回", "infra", False),
        ("milvus.address", "http://127.0.0.1:19530", "string", "Milvus REST 地址", "infra", False),
        ("image_embedding.provider", "dashscope", "string", "图片 Embedding 提供方", "infra", False),
        ("image_embedding.dimension", "1536", "int", "图片 Embedding 维度", "infra", False),
        ("retrieval.product.rerank.enabled", "true", "bool", "是否启用商品候选重排", "rag", False),
        ("retrieval.product.rerank.model_enabled", "true", "bool", "是否调用商品重排模型", "rag", False),
        ("retrieval.product.rerank.fallback_rule_enabled", "true", "bool", "重排模型失败时回退规则", "rag", False),
        ("retrieval.product.rerank.max_candidates", "80", "int", "商品重排候选数", "rag", False),
        ("retrieval.product.rerank.model_min_score", "0.50", "float", "商品重排最低分", "rag", False),
        ("retrieval.product.rerank.model_max_score_delta", "0.12", "float", "商品重排最高分差", "rag", False),
        ("retrieval.product.ok.max_results", "10", "int", "商品检索相关结果最多数量", "rag", False),
        ("agent.followups_enabled", "true", "bool", "是否生成追问", "app", False),
        ("risk.enabled", "true", "bool", "是否启用输入和账号风控", "app", False),
        ("memory.enabled", "true", "bool", "是否启用短期多轮记忆", "app", False),
    ]
    for key, value, value_type, description, domain, is_secret in defaults:
        if await session.get(AppConfig, key) is None:
            session.add(AppConfig(config_key=key, config_value=value, value_type=value_type, description=description, domain=domain, is_secret=is_secret, updated_at=datetime.now(timezone.utc)))
    prompt_defaults = [
        ("agent.prompt.route", "一级路由 Prompt", "guide/non_guide 路由"),
        ("agent.prompt.guide_intent", "导购细分 Prompt", "P1-P6 导购意图识别"),
        ("agent.prompt.non_guide_intent", "非导购细分 Prompt", "非导购服务域识别"),
        ("agent.prompt.main_template", "主 Agent 模板 Prompt", "受控电商导购回答"),
        ("agent.prompt.tool_call_protocol", "工具调用协议 Prompt", "ReAct 工具协议"),
        ("agent.prompt.final_output_rules", "最终回答规范 Prompt", "最终回答规范"),
        ("agent.prompt.followups", "追问生成 Prompt", "导购追问生成"),
        ("agent.prompt.guide_suggestions", "小猪浮窗建议 Prompt", "页面导购建议"),
        ("agent.prompt.memory_retrieval", "短期记忆检索 Prompt", "短期记忆检索"),
        ("agent.prompt.session_summary", "会话摘要 Prompt", "会话滚动摘要"),
    ]
    for key, title, description in prompt_defaults:
        exists = await session.scalar(select(AgentPrompt.prompt_id).where(AgentPrompt.prompt_key == key).limit(1))
        if exists is None:
            now = datetime.now(timezone.utc)
            session.add(AgentPrompt(prompt_id=f"prm_default_{hashlib.sha1(key.encode()).hexdigest()[:12]}", prompt_key=key, title=title, content="你是受控电商导购，只基于真实工具结果回答。", status="active", version=1, description=description, created_by="system", published_at=now, created_at=now, updated_at=now))


def _ensure_phase3_compat_columns(connection) -> None:
    """Add Stage 3 columns when a developer reuses a Stage 2 SQLite database."""
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if "agent_prompt_publish_records" in tables:
        prompt_columns = {column["name"] for column in inspector.get_columns("agent_prompt_publish_records")}
        if "nacos_data_id" not in prompt_columns:
            connection.execute(text("ALTER TABLE agent_prompt_publish_records ADD COLUMN nacos_data_id VARCHAR(128) NOT NULL DEFAULT ''"))
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
