"""Add monitor, archive, and read receipt persistence"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20250114_api_integration"
down_revision = None
branch_labels = None
depends_on = None


def _ensure_column(inspector, table_name: str, column_name: str) -> bool:
    columns = {col["name"] for col in inspector.get_columns(table_name)}
    return column_name in columns


def _ensure_index(inspector, table_name: str, index_name: str) -> bool:
    indexes = {index["name"] for index in inspector.get_indexes(table_name)}
    return index_name in indexes


def _ensure_fk(inspector, table_name: str, fk_name: str) -> bool:
    fks = {fk["name"] for fk in inspector.get_foreign_keys(table_name)}
    return fk_name in fks


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "monitors" not in tables:
        op.create_table(
            "monitors",
            sa.Column("id", sa.String(length=255), primary_key=True),
            sa.Column("user_id", sa.String(length=255), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("tenant_id", sa.String(length=255), sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("url", sa.String(length=1024), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("last_run_at", sa.DateTime(), nullable=True),
            sa.Column("archived_at", sa.DateTime(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("latest_task_id", sa.String(length=255), sa.ForeignKey("analysis_tasks.id", ondelete="SET NULL"), nullable=True),
        )
        op.create_unique_constraint("uq_monitor_user_url", "monitors", ["user_id", "url"])
        op.create_index("idx_monitor_user", "monitors", ["user_id"])
        op.create_index("idx_monitor_tenant", "monitors", ["tenant_id"])
        tables.add("monitors")

    if "monitor_competitors" not in tables:
        op.create_table(
            "monitor_competitors",
            sa.Column("id", sa.String(length=255), primary_key=True),
            sa.Column("monitor_id", sa.String(length=255), sa.ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False),
            sa.Column("competitor_id", sa.String(length=255), sa.ForeignKey("competitors.id", ondelete="CASCADE"), nullable=False),
            sa.Column("tracked", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("monitor_id", "competitor_id", name="uq_monitor_competitor"),
        )
        op.create_index("idx_monitor_competitor_monitor", "monitor_competitors", ["monitor_id"])
        op.create_index("idx_monitor_competitor_competitor", "monitor_competitors", ["competitor_id"])
        tables.add("monitor_competitors")

    if "change_read_receipts" not in tables:
        op.create_table(
            "change_read_receipts",
            sa.Column("id", sa.String(length=255), primary_key=True),
            sa.Column("user_id", sa.String(length=255), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("change_id", sa.String(length=255), sa.ForeignKey("change_detections.id", ondelete="CASCADE"), nullable=False),
            sa.Column("read_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("user_id", "change_id", name="uq_user_change_read"),
        )
        tables.add("change_read_receipts")

    if "analysis_archives" not in tables:
        op.create_table(
            "analysis_archives",
            sa.Column("id", sa.String(length=255), primary_key=True),
            sa.Column("user_id", sa.String(length=255), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("monitor_id", sa.String(length=255), sa.ForeignKey("monitors.id", ondelete="SET NULL"), nullable=True),
            sa.Column("task_id", sa.String(length=255), sa.ForeignKey("analysis_tasks.id", ondelete="SET NULL"), nullable=True),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("tenant_snapshot", sa.JSON(), nullable=True),
            sa.Column("competitor_snapshot", sa.JSON(), nullable=True),
            sa.Column("change_snapshot", sa.JSON(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("search_text", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        tables.add("analysis_archives")

    if "analysis_tasks" in tables:
        if not _ensure_column(inspector, "analysis_tasks", "user_id"):
            op.add_column("analysis_tasks", sa.Column("user_id", sa.String(length=255), nullable=True))
        if not _ensure_column(inspector, "analysis_tasks", "monitor_id"):
            op.add_column("analysis_tasks", sa.Column("monitor_id", sa.String(length=255), nullable=True))
        if not _ensure_column(inspector, "analysis_tasks", "latest_stage"):
            op.add_column("analysis_tasks", sa.Column("latest_stage", sa.String(length=255), nullable=True))

        inspector = sa.inspect(bind)  # refresh schema cache

        if not _ensure_index(inspector, "analysis_tasks", "ix_analysis_tasks_user_id"):
            op.create_index("ix_analysis_tasks_user_id", "analysis_tasks", ["user_id"])
        if not _ensure_index(inspector, "analysis_tasks", "ix_analysis_tasks_monitor_id"):
            op.create_index("ix_analysis_tasks_monitor_id", "analysis_tasks", ["monitor_id"])

        inspector = sa.inspect(bind)
        if "monitors" in tables and not _ensure_fk(inspector, "analysis_tasks", "fk_analysis_tasks_monitor_id"):
            op.create_foreign_key(
                "fk_analysis_tasks_monitor_id",
                "analysis_tasks",
                "monitors",
                ["monitor_id"],
                ["id"],
                ondelete="SET NULL",
            )
        inspector = sa.inspect(bind)
        if "users" in tables and not _ensure_fk(inspector, "analysis_tasks", "fk_analysis_tasks_user_id"):
            op.create_foreign_key(
                "fk_analysis_tasks_user_id",
                "analysis_tasks",
                "users",
                ["user_id"],
                ["id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "analysis_tasks" in tables:
        if _ensure_fk(inspector, "analysis_tasks", "fk_analysis_tasks_monitor_id"):
            op.drop_constraint("fk_analysis_tasks_monitor_id", "analysis_tasks", type_="foreignkey")
        if _ensure_fk(inspector, "analysis_tasks", "fk_analysis_tasks_user_id"):
            op.drop_constraint("fk_analysis_tasks_user_id", "analysis_tasks", type_="foreignkey")

        inspector = sa.inspect(bind)
        if _ensure_index(inspector, "analysis_tasks", "ix_analysis_tasks_monitor_id"):
            op.drop_index("ix_analysis_tasks_monitor_id", table_name="analysis_tasks")
        inspector = sa.inspect(bind)
        if _ensure_index(inspector, "analysis_tasks", "ix_analysis_tasks_user_id"):
            op.drop_index("ix_analysis_tasks_user_id", table_name="analysis_tasks")

        inspector = sa.inspect(bind)
        for column_name in ("latest_stage", "monitor_id", "user_id"):
            if _ensure_column(inspector, "analysis_tasks", column_name):
                op.drop_column("analysis_tasks", column_name)
                inspector = sa.inspect(bind)

    for table_name in (
        "analysis_archives",
        "change_read_receipts",
        "monitor_competitors",
        "monitors",
    ):
        inspector = sa.inspect(bind)
        if table_name in inspector.get_table_names():
            op.drop_table(table_name)
