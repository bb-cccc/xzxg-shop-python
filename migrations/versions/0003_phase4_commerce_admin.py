
# 本模块说明：Python 辅助模块：支持后端运行、测试或评测。
"""Add commerce, moderation and admin configuration tables for phase 4."""

from alembic import op
import sqlalchemy as sa


revision = "0003_phase4_commerce_admin"
down_revision = "0002_phase3_rag_image"
branch_labels = None
depends_on = None


def _create(name, *columns, constraints=()):
    inspector = sa.inspect(op.get_bind())
    if name not in inspector.get_table_names():
        op.create_table(name, *columns, *constraints)


def upgrade() -> None:
    _create(
        "promotion_rules",
        sa.Column("promotion_id", sa.String(64), primary_key=True), sa.Column("name", sa.String(128), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False, server_default="platform"), sa.Column("merchant_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("product_id", sa.String(64), nullable=False, server_default=""), sa.Column("category_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("type", sa.String(32), nullable=False, server_default="full_reduction"), sa.Column("threshold_amount", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("discount_amount", sa.Numeric(10, 2), nullable=False, server_default="0"), sa.Column("discount_rate", sa.Numeric(5, 4), nullable=False, server_default="0"),
        sa.Column("stackable", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("start_at", sa.DateTime(), nullable=False), sa.Column("end_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    _create(
        "coupons",
        sa.Column("coupon_id", sa.String(64), primary_key=True), sa.Column("name", sa.String(128), nullable=False), sa.Column("scope", sa.String(32), nullable=False, server_default="platform"),
        sa.Column("merchant_id", sa.String(64), nullable=False, server_default=""), sa.Column("type", sa.String(32), nullable=False, server_default="fixed_amount"),
        sa.Column("threshold_amount", sa.Numeric(10, 2), nullable=False, server_default="0"), sa.Column("discount_amount", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("claimed_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("per_user_limit", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("start_at", sa.DateTime(), nullable=False), sa.Column("end_at", sa.DateTime(), nullable=False), sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    _create(
        "user_coupons",
        sa.Column("user_coupon_id", sa.String(64), primary_key=True), sa.Column("coupon_id", sa.String(64), nullable=False), sa.Column("account_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="unused"), sa.Column("order_id", sa.String(64), nullable=False, server_default=""), sa.Column("claimed_at", sa.DateTime(), nullable=False), sa.Column("used_at", sa.DateTime(), nullable=True),
    )
    _create(
        "product_reviews",
        sa.Column("review_id", sa.String(64), primary_key=True), sa.Column("order_id", sa.String(64), nullable=False), sa.Column("order_item_id", sa.String(64), nullable=False),
        sa.Column("product_id", sa.String(64), nullable=False), sa.Column("sku_id", sa.String(64), nullable=False, server_default=""), sa.Column("account_id", sa.String(64), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False), sa.Column("content", sa.Text(), nullable=False), sa.Column("tags_json", sa.JSON(), nullable=False), sa.Column("status", sa.String(32), nullable=False, server_default="visible"),
        sa.Column("merchant_reply", sa.Text(), nullable=False, server_default=""), sa.Column("merchant_replied_at", sa.DateTime(), nullable=True), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False),
        constraints=(sa.UniqueConstraint("order_item_id", name="uk_product_reviews_order_item"),),
    )
    _create(
        "app_configs",
        sa.Column("config_key", sa.String(128), primary_key=True), sa.Column("config_value", sa.Text(), nullable=False, server_default=""), sa.Column("value_type", sa.String(32), nullable=False, server_default="string"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""), sa.Column("domain", sa.String(64), nullable=False, server_default=""), sa.Column("is_secret", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    _create(
        "agent_prompts",
        sa.Column("prompt_id", sa.String(64), primary_key=True), sa.Column("prompt_key", sa.String(128), nullable=False), sa.Column("title", sa.String(128), nullable=False), sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"), sa.Column("version", sa.Integer(), nullable=False, server_default="1"), sa.Column("description", sa.Text(), nullable=False, server_default=""), sa.Column("created_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("published_at", sa.DateTime(), nullable=True), sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False),
        constraints=(sa.UniqueConstraint("prompt_key", "version", name="uk_agent_prompts_key_version"),),
    )
    _create(
        "agent_prompt_publish_records",
        sa.Column("record_id", sa.String(64), primary_key=True), sa.Column("prompt_key", sa.String(128), nullable=False), sa.Column("prompt_id", sa.String(64), nullable=False), sa.Column("version", sa.Integer(), nullable=False), sa.Column("published_by", sa.String(64), nullable=False, server_default=""), sa.Column("publish_target", sa.String(128), nullable=False, server_default="database"), sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    for name in ("agent_prompt_publish_records", "agent_prompts", "app_configs", "product_reviews", "user_coupons", "coupons", "promotion_rules"):
        op.drop_table(name)

