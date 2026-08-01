"""audit trail + feature flags

Revision ID: 0004_audit_feature_flags
Revises: 0003_seed
Create Date: 2026-07-31
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_audit_feature_flags"
down_revision = "0003_seed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- Audit trail enterprise ----
    # Bitácora de acciones con contexto de usuario y request. Separada de
    # audit_log (tools internas) por su contrato distinto: user_id, resource,
    # resource_id, details (JSON serializado), ip. Aislada por tenant_id.
    op.create_table(
        "audit_entries",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("resource_id", sa.Text(), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("ip", sa.Text(), nullable=True),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
    )
    op.create_index("idx_audit_entries_tenant", "audit_entries", ["tenant_id"])
    op.create_index("idx_audit_entries_tenant_ts", "audit_entries",
                    ["tenant_id", "timestamp"])
    op.create_index("idx_audit_entries_resource", "audit_entries", ["resource"])

    # ---- Feature flags por tenant ----
    # tenant_id NULL = flag global. rollout_percentage (0-100) permite rollout
    # gradual cuando enabled=1. Defaults de tenants nuevos en el código
    # (b2b_ai.features.flags), no en la DB.
    op.create_table(
        "feature_flags",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=True),
        sa.Column("enabled", sa.BigInteger(), server_default="0", nullable=True),
        sa.Column("rollout_percentage", sa.BigInteger(), server_default="100",
                  nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
        sa.UniqueConstraint("tenant_id", "name", name="uq_feature_flag"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    op.create_index("idx_feature_flags_tenant", "feature_flags", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("idx_feature_flags_tenant", table_name="feature_flags")
    op.drop_table("feature_flags")
    op.drop_index("idx_audit_entries_resource", table_name="audit_entries")
    op.drop_index("idx_audit_entries_tenant_ts", table_name="audit_entries")
    op.drop_index("idx_audit_entries_tenant", table_name="audit_entries")
    op.drop_table("audit_entries")
