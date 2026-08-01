"""outstanding_invoices: add unique constraint for ON CONFLICT upsert

Adds a UNIQUE constraint on (tenant_id, factura_id) so that
upsert_outstanding_invoice()'s ON CONFLICT (tenant_id, factura_id) DO UPDATE SET
works on PostgreSQL.

Revision ID: 0005_outstanding_unique
Revises: 0004_audit_feature_flags
Create Date: 2026-07-31
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_outstanding_unique"
down_revision = "0004_audit_feature_flags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_outstanding_invoices_tenant_factura",
        "outstanding_invoices",
        ["tenant_id", "factura_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_outstanding_invoices_tenant_factura",
        "outstanding_invoices",
        type_="unique",
    )