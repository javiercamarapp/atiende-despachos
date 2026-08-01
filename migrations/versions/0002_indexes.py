"""optimized indexes

Revision ID: 0002_indexes
Revises: 0001_initial
Create Date: 2026-07-31
"""
from alembic import op

revision = "0002_indexes"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Facturas: lectura por tenant + orden por id, por fecha, por categoría.
    op.create_index("idx_invoices_tenant", "invoices", ["tenant_id"])
    op.create_index("idx_invoices_fecha", "invoices", ["fecha"])
    op.create_index("idx_invoices_tenant_categoria", "invoices",
                    ["tenant_id", "categoria"])
    op.create_index("idx_invoices_tenant_fecha", "invoices",
                    ["tenant_id", "fecha"])

    # Audit log: filtro por tool y por tenant.
    op.create_index("idx_audit_tool", "audit_log", ["tool_name"])
    op.create_index("idx_audit_tenant", "audit_log", ["tenant_id"])

    # API keys y config por tenant.
    op.create_index("idx_api_keys_tenant", "api_keys", ["tenant_id"])
    op.create_index("idx_tenant_config_tenant", "tenant_config", ["tenant_id"])

    # Revisión humana.
    op.create_index("idx_reviews_tenant", "reviews", ["tenant_id"])
    op.create_index("idx_reviews_status", "reviews", ["status"])

    # Webhooks.
    op.create_index("idx_webhook_tenant", "webhook_deliveries", ["tenant_id"])
    op.create_index("idx_wh_sub_tenant", "webhook_subscriptions", ["tenant_id"])
    op.create_index("idx_wh_sub_event", "webhook_subscriptions", ["event"])

    # Uso por tenant.
    op.create_index("idx_usage_tenant", "tenant_usage", ["tenant_id"])

    # Cobranza.
    op.create_index("idx_collection_events_factura", "collection_events",
                    ["factura_id"])
    op.create_index("idx_collection_events_tenant", "collection_events",
                    ["tenant_id"])
    op.create_index("idx_outstanding_invoices_tenant", "outstanding_invoices",
                    ["tenant_id"])
    op.create_index("idx_outstanding_invoices_due", "outstanding_invoices",
                    ["fecha_vencimiento"])

    # Contabilidad electrónica.
    op.create_index("idx_cuentas_tenant", "cuentas_contables", ["tenant_id"])
    op.create_index("idx_asientos_tenant", "asientos_contables", ["tenant_id"])
    op.create_index("idx_asientos_fecha", "asientos_contables", ["fecha"])
    op.create_index("idx_balanzas_tenant", "balanzas_mensuales", ["tenant_id"])
    op.create_index("idx_balanzas_periodo", "balanzas_mensuales", ["periodo"])
    op.create_index("idx_paquetes_tenant", "paquetes_contabilidad", ["tenant_id"])
    op.create_index("idx_paquetes_periodo", "paquetes_contabilidad", ["periodo"])

    # Portal del cliente.
    op.create_index("idx_client_users_tenant", "client_users", ["tenant_id"])
    op.create_index("idx_client_users_email", "client_users", ["email"])
    op.create_index("idx_portal_sessions_user", "portal_sessions", ["user_id"])


def downgrade() -> None:
    for idx, tbl, cols in [
        ("idx_invoices_tenant", "invoices", ["tenant_id"]),
        ("idx_invoices_fecha", "invoices", ["fecha"]),
        ("idx_invoices_tenant_categoria", "invoices", ["tenant_id", "categoria"]),
        ("idx_invoices_tenant_fecha", "invoices", ["tenant_id", "fecha"]),
        ("idx_audit_tool", "audit_log", ["tool_name"]),
        ("idx_audit_tenant", "audit_log", ["tenant_id"]),
        ("idx_api_keys_tenant", "api_keys", ["tenant_id"]),
        ("idx_tenant_config_tenant", "tenant_config", ["tenant_id"]),
        ("idx_reviews_tenant", "reviews", ["tenant_id"]),
        ("idx_reviews_status", "reviews", ["status"]),
        ("idx_webhook_tenant", "webhook_deliveries", ["tenant_id"]),
        ("idx_wh_sub_tenant", "webhook_subscriptions", ["tenant_id"]),
        ("idx_wh_sub_event", "webhook_subscriptions", ["event"]),
        ("idx_usage_tenant", "tenant_usage", ["tenant_id"]),
        ("idx_collection_events_factura", "collection_events", ["factura_id"]),
        ("idx_collection_events_tenant", "collection_events", ["tenant_id"]),
        ("idx_outstanding_invoices_tenant", "outstanding_invoices", ["tenant_id"]),
        ("idx_outstanding_invoices_due", "outstanding_invoices", ["fecha_vencimiento"]),
        ("idx_cuentas_tenant", "cuentas_contables", ["tenant_id"]),
        ("idx_asientos_tenant", "asientos_contables", ["tenant_id"]),
        ("idx_asientos_fecha", "asientos_contables", ["fecha"]),
        ("idx_balanzas_tenant", "balanzas_mensuales", ["tenant_id"]),
        ("idx_balanzas_periodo", "balanzas_mensuales", ["periodo"]),
        ("idx_paquetes_tenant", "paquetes_contabilidad", ["tenant_id"]),
        ("idx_paquetes_periodo", "paquetes_contabilidad", ["periodo"]),
        ("idx_client_users_tenant", "client_users", ["tenant_id"]),
        ("idx_client_users_email", "client_users", ["email"]),
        ("idx_portal_sessions_user", "portal_sessions", ["user_id"]),
    ]:
        op.drop_index(idx, table_name=tbl)
