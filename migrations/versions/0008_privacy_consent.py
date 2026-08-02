"""privacy_consent + leads_tenant_id + missing_indexes

Revision ID: 0008_privacy_consent
Revises: 0007_collections_module

Adds accepted_privacy_at to client_users (LFPDPPP Art. 8),
tenant_id to leads table (multi-tenant isolation),
and missing indexes for performance.
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_privacy_consent"
down_revision = "0007_collections_module"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- LFPDPPP Art. 8: Privacy consent timestamp ----
    op.add_column(
        "client_users",
        sa.Column("accepted_privacy_at", sa.TIMESTAMP(timezone=True),
                  nullable=True),
    )

    # ---- Multi-tenant isolation: add tenant_id to leads ----
    op.add_column(
        "leads",
        sa.Column("tenant_id", sa.BigInteger(), nullable=True),
    )
    op.create_index("idx_leads_tenant", "leads", ["tenant_id"])

    # ---- Missing indexes for frequently filtered columns ----
    op.create_index("idx_invoices_status", "invoices", ["status"])
    op.create_index("idx_invoices_valido", "invoices", ["valido"])
    op.create_index("idx_invoices_emisor_rfc", "invoices", ["emisor_rfc"])
    op.create_index(
        "idx_invoices_tenant_status", "invoices", ["tenant_id", "status"])
    op.create_index(
        "idx_outreach_leads_next_send",
        "outreach_campaign_leads",
        ["next_send_at"],
        postgresql_where=sa.text("next_send_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_outreach_leads_next_send",
                  table_name="outreach_campaign_leads")
    op.drop_index("idx_invoices_tenant_status", table_name="invoices")
    op.drop_index("idx_invoices_emisor_rfc", table_name="invoices")
    op.drop_index("idx_invoices_valido", table_name="invoices")
    op.drop_index("idx_invoices_status", table_name="invoices")
    op.drop_index("idx_leads_tenant", table_name="leads")
    op.drop_column("leads", "tenant_id")
    op.drop_column("client_users", "accepted_privacy_at")
