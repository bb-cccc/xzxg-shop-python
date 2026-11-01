
# 本模块说明：Python 辅助模块：支持后端运行、测试或评测。
"""Keep internal prompt publication metadata compatible with Go's schema."""

from alembic import op
import sqlalchemy as sa


revision = "0004_go_schema_compat"
down_revision = "0003_phase4_commerce_admin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "agent_prompt_publish_records" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("agent_prompt_publish_records")}
        if "nacos_data_id" not in columns:
            op.add_column("agent_prompt_publish_records", sa.Column("nacos_data_id", sa.String(128), nullable=False, server_default=""))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "agent_prompt_publish_records" in inspector.get_table_names() and "nacos_data_id" in {column["name"] for column in inspector.get_columns("agent_prompt_publish_records")}:
        op.drop_column("agent_prompt_publish_records", "nacos_data_id")
