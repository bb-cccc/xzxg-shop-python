
# 本模块说明：Python 辅助模块：支持后端运行、测试或评测。
"""Create the complete SQL baseline used by a fresh Python deployment.

The original revision was an empty marker because local development used
``Base.metadata.create_all``.  That made a production ``alembic upgrade``
leave a new database without the phase 1 tables.  The baseline now creates a
schema snapshot for every table known at this revision.  Later revisions are
idempotent, so databases that already contain only the old phase 1 tables can
still be upgraded in place.
"""

revision = "0001_phase1_baseline"
down_revision = None
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

from app.domain.models import Base


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    # Copy the metadata into a private snapshot so the migration does not
    # mutate the application's declarative metadata while Alembic runs.
    snapshot = sa.MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(snapshot)
    for table in snapshot.sorted_tables:
        if table.name in existing:
            continue
        # Do not reuse Column.copy() here: it carries ``index=True`` metadata,
        # while the explicit index operations below would then create every
        # index twice on SQLite and MySQL.
        columns = [
            sa.Column(
                column.name,
                column.type,
                primary_key=column.primary_key,
                nullable=column.nullable,
                unique=column.unique,
                index=False,
            )
            for column in table.columns
        ]
        constraints = [constraint.copy() for constraint in list(table.constraints) if isinstance(constraint, sa.UniqueConstraint)]
        op.create_table(table.name, *columns, *constraints)
        for index in table.indexes:
            op.create_index(index.name, table.name, [column.name for column in index.columns], unique=index.unique)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    snapshot = sa.MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(snapshot)
    for table in reversed(snapshot.sorted_tables):
        if table.name in inspector.get_table_names():
            for index in table.indexes:
                op.drop_index(index.name, table_name=table.name)
            op.drop_table(table.name)
