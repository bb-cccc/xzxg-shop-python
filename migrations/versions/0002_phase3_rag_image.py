
# 本模块说明：Python 辅助模块：支持后端运行、测试或评测。
"""Add knowledge document, file and image vector metadata for phase 3."""

from alembic import op
import sqlalchemy as sa


revision = "0002_phase3_rag_image"
down_revision = "0001_phase1_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("knowledge_chunks")}
    additions = {
        "document_id": sa.Column("document_id", sa.String(64), nullable=False, server_default=""),
        "content": sa.Column("content", sa.Text(), nullable=False, server_default=""),
        "doc_type": sa.Column("doc_type", sa.String(64), nullable=False, server_default=""),
        "merchant_id": sa.Column("merchant_id", sa.String(64), nullable=False, server_default=""),
        "product_id": sa.Column("product_id", sa.String(64), nullable=False, server_default=""),
        "category_id": sa.Column("category_id", sa.String(64), nullable=False, server_default=""),
        "quality_score": sa.Column("quality_score", sa.Numeric(5, 4), nullable=False, server_default="0"),
        "metadata_json": sa.Column("metadata_json", sa.JSON(), nullable=True),
    }
    for name, column in additions.items():
        if name not in columns:
            op.add_column("knowledge_chunks", column)
    op.create_table(
        "knowledge_documents",
        sa.Column("document_id", sa.String(64), primary_key=True),
        sa.Column("merchant_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("title", sa.String(256), nullable=False, server_default=""),
        sa.Column("doc_type", sa.String(64), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="indexed"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_url", sa.String(1024), nullable=False, server_default=""),
        sa.Column("content_hash", sa.String(128), nullable=False, server_default=""),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    ) if "knowledge_documents" not in inspector.get_table_names() else None
    op.create_table(
        "stored_files",
        sa.Column("file_id", sa.String(64), primary_key=True),
        sa.Column("account_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("object_key", sa.String(512), nullable=False),
        sa.Column("url", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("storage_provider", sa.String(32), nullable=False, server_default="local"),
        sa.Column("source_url", sa.String(1024), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("object_key", name="uk_stored_files_object_key"),
    ) if "stored_files" not in inspector.get_table_names() else None
    op.create_table(
        "product_image_vectors",
        sa.Column("vector_id", sa.String(64), primary_key=True),
        sa.Column("product_id", sa.String(64), nullable=False),
        sa.Column("image_url", sa.String(512), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False, server_default="dashscope"),
        sa.Column("dimension", sa.Integer(), nullable=False, server_default="1536"),
        sa.Column("embedding_json", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False, server_default=""),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("product_id", "image_url", name="uk_product_image_vector_source"),
    ) if "product_image_vectors" not in inspector.get_table_names() else None


def downgrade() -> None:
    op.drop_table("product_image_vectors")
    op.drop_table("stored_files")
    op.drop_table("knowledge_documents")

