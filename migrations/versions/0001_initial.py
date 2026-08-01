"""initial schema: todas las tablas del MVP (PostgreSQL)

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-31
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- Multi-tenant (núcleo) ----
    op.create_table(
        "tenants",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("rfc", sa.Text(), nullable=True),
        sa.Column("blocked", sa.BigInteger(), server_default="0", nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), server_default="contador", nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )

    op.create_table(
        "invoices",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("folio_fiscal", sa.Text(), nullable=True),
        sa.Column("archivo", sa.Text(), nullable=False),
        sa.Column("fecha", sa.Text(), nullable=True),
        sa.Column("tipo", sa.Text(), nullable=True),
        sa.Column("serie", sa.Text(), nullable=True),
        sa.Column("folio", sa.Text(), nullable=True),
        sa.Column("emisor_rfc", sa.Text(), nullable=True),
        sa.Column("emisor_nombre", sa.Text(), nullable=True),
        sa.Column("receptor_rfc", sa.Text(), nullable=True),
        sa.Column("subtotal", sa.Text(), nullable=True),
        sa.Column("iva", sa.Text(), nullable=True),
        sa.Column("total", sa.Text(), nullable=True),
        sa.Column("moneda", sa.Text(), server_default="MXN", nullable=True),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("categoria", sa.Text(), nullable=True),
        sa.Column("confianza", sa.Float(), nullable=True),
        sa.Column("razon_clasificacion", sa.Text(), nullable=True),
        sa.Column("valido", sa.BigInteger(), server_default="0", nullable=True),
        sa.Column("requires_human_review", sa.BigInteger(),
                  server_default="1", nullable=True),
        sa.Column("issues", sa.Text(), nullable=True),
        sa.Column("erp_poliza", sa.Text(), nullable=True),
        sa.Column("erp_status", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="procesado", nullable=True),
        sa.Column("procesado_en", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
        sa.UniqueConstraint("tenant_id", "folio_fiscal",
                            name="uq_invoices_tenant_folio"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )

    op.create_table(
        "classifications",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("invoice_id", sa.BigInteger(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("categoria", sa.Text(), nullable=True),
        sa.Column("confianza", sa.Float(), nullable=True),
        sa.Column("razon", sa.Text(), nullable=True),
        sa.Column("method", sa.Text(), server_default="rules", nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=True),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=True),
        sa.Column("entity", sa.Text(), nullable=True),
        sa.Column("entity_id", sa.Text(), nullable=True),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=True),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("recipient", sa.Text(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="queued", nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
    )

    op.create_table(
        "schema_version",
        sa.Column("version", sa.BigInteger(), primary_key=True),
        sa.Column("applied_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
    )

    # ---- API keys + leads ----
    op.create_table(
        "api_keys",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column("active", sa.BigInteger(), server_default="1", nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
        sa.UniqueConstraint("key_hash", name="uq_api_keys_hash"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )

    op.create_table(
        "leads",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("nombre", sa.Text(), nullable=False),
        sa.Column("despacho", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("facturas", sa.Text(), nullable=True),
        sa.Column("mensaje", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="nuevo", nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
    )

    # ---- Config por tenant + revisión humana + webhooks ----
    op.create_table(
        "tenant_config",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("config_key", sa.Text(), nullable=False),
        sa.Column("config_value", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
        sa.UniqueConstraint("tenant_id", "config_key",
                            name="uq_tenant_config"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )

    op.create_table(
        "reviews",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("invoice_id", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("decision", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="pending", nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"]),
    )

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=True),
        sa.Column("event", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("attempts", sa.BigInteger(), server_default="0", nullable=True),
        sa.Column("max_attempts", sa.BigInteger(), server_default="3",
                  nullable=True),
        sa.Column("last_status", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_retry_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )

    # ---- Cobranza (FASE 3) ----
    op.create_table(
        "collection_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=True),
        sa.Column("factura_id", sa.Text(), nullable=False),
        sa.Column("tipo_recordatorio", sa.Text(), nullable=False),
        sa.Column("canal", sa.Text(), server_default="email", nullable=True),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
        sa.Column("respuesta", sa.Text(), nullable=True),
    )

    op.create_table(
        "outstanding_invoices",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=True),
        sa.Column("factura_id", sa.Text(), nullable=False),
        sa.Column("monto", sa.Float(), nullable=False),
        sa.Column("fecha_vencimiento", sa.Text(), nullable=False),
        sa.Column("dias_vencido", sa.BigInteger(), server_default="0",
                  nullable=True),
        sa.Column("score", sa.Float(), server_default="0.0", nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
        sa.UniqueConstraint("tenant_id", "factura_id",
                            name="uq_outstanding_unique"),
    )
    op.create_index("idx_outstanding_unique", "outstanding_invoices",
                    ["tenant_id", "factura_id"], unique=True)

    # ---- Enterprise multi-tenant (FASE 4) ----
    op.create_table(
        "tenant_usage",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("api_calls", sa.BigInteger(), server_default="0", nullable=True),
        sa.Column("invoices_processed", sa.BigInteger(), server_default="0",
                  nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
        sa.UniqueConstraint("tenant_id", name="uq_tenant_usage"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )

    op.create_table(
        "webhook_subscriptions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("event", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("active", sa.BigInteger(), server_default="1", nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
        sa.UniqueConstraint("tenant_id", "event", "url",
                            name="uq_wh_subscription"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )

    # ---- Contabilidad electrónica (FASE 3) ----
    op.create_table(
        "cuentas_contables",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("codigo", sa.Text(), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=False),
        sa.Column("nivel", sa.BigInteger(), server_default="3", nullable=True),
        sa.Column("naturaleza", sa.Text(), server_default="D", nullable=True),
        sa.Column("grupo", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
        sa.UniqueConstraint("tenant_id", "codigo", name="uq_cuenta_tenant"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )

    op.create_table(
        "asientos_contables",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("fecha", sa.Text(), nullable=False),
        sa.Column("cuenta_debito", sa.Text(), nullable=False),
        sa.Column("cuenta_credito", sa.Text(), nullable=False),
        sa.Column("monto", sa.Text(), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("factura_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )

    op.create_table(
        "balanzas_mensuales",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("periodo", sa.Text(), nullable=False),
        sa.Column("cuenta_id", sa.BigInteger(), nullable=True),
        sa.Column("saldo_inicial", sa.Text(), server_default="0.00", nullable=True),
        sa.Column("debe", sa.Text(), server_default="0.00", nullable=True),
        sa.Column("haber", sa.Text(), server_default="0.00", nullable=True),
        sa.Column("saldo_final", sa.Text(), server_default="0.00", nullable=True),
        sa.UniqueConstraint("tenant_id", "periodo", "cuenta_id",
                            name="uq_balanza"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["cuenta_id"], ["cuentas_contables.id"]),
    )

    op.create_table(
        "paquetes_contabilidad",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("periodo", sa.Text(), nullable=False),
        sa.Column("rfc", sa.Text(), nullable=True),
        sa.Column("estado", sa.Text(), server_default="borrador", nullable=True),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )

    # ---- Portal del cliente (FASE 5) ----
    op.create_table(
        "client_users",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), server_default="cliente", nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
        sa.UniqueConstraint("tenant_id", "email", name="uq_client_user"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )

    op.create_table(
        "portal_sessions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_portal_token"),
        sa.ForeignKeyConstraint(["user_id"], ["client_users.id"]),
    )


def downgrade() -> None:
    for t in ("portal_sessions", "client_users", "paquetes_contabilidad",
              "balanzas_mensuales", "asientos_contables", "cuentas_contables",
              "webhook_subscriptions", "tenant_usage", "outstanding_invoices",
              "collection_events", "webhook_deliveries", "reviews",
              "tenant_config", "leads", "api_keys", "schema_version",
              "notifications", "audit_log", "classifications", "invoices",
              "users", "tenants"):
        op.drop_table(t)
