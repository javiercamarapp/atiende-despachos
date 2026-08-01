"""collections: tabla de log de pagos y configuración de cobranza

Revision ID: 0007_collections_module
Revises: 0006_outreach
Create Date: 2026-08-01

Agrega tablas para el módulo de cobranza automatizada:
  - collection_payments: log detallado de pagos recibidos vía webhook
  - collection_config: configuración por tenant (días de gracia, canales,
    thresholds de escalamiento, etc.)
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_collections_module"
down_revision = "0006_outreach"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- Log de pagos recibidos ----
    # Cada webhook de pago se registra aquí para trazabilidad completa.
    # Se separa de collection_events porque el contrato es distinto:
    # amount, reference, provider, paid_at son campos específicos de pagos.
    op.create_table(
        "collection_payments",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("factura_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        # payment_received | payment_partial | payment_rejected | ...
        sa.Column("amount", sa.Float(), server_default="0.0", nullable=True),
        sa.Column("currency", sa.Text(), server_default="MXN", nullable=True),
        sa.Column("reference", sa.Text(), nullable=True),
        # SPEI ref, CLABE, etc.
        sa.Column("provider", sa.Text(), server_default="manual", nullable=True),
        # spei | stripe | conekta | manual
        sa.Column("paid_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        # Datos adicionales del webhook
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
    )
    op.create_index(
        "idx_collection_payments_tenant",
        "collection_payments", ["tenant_id"],
    )
    op.create_index(
        "idx_collection_payments_factura",
        "collection_payments", ["factura_id"],
    )
    op.create_index(
        "idx_collection_payments_tenant_factura",
        "collection_payments", ["tenant_id", "factura_id"],
    )

    # ---- Configuración de cobranza por tenant ----
    # Parámetros de comportamiento del módulo de cobranza: días de gracia,
    # canales habilitados, umbrales de escalamiento, recordatorios máximos.
    op.create_table(
        "collection_config",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("config_key", sa.Text(), nullable=False),
        sa.Column("config_value", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
        sa.UniqueConstraint("tenant_id", "config_key",
                            name="uq_collection_config_tenant_key"),
    )
    op.create_index(
        "idx_collection_config_tenant",
        "collection_config", ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_collection_config_tenant",
                   table_name="collection_config")
    op.drop_table("collection_config")
    op.drop_index("idx_collection_payments_tenant_factura",
                   table_name="collection_payments")
    op.drop_index("idx_collection_payments_factura",
                   table_name="collection_payments")
    op.drop_index("idx_collection_payments_tenant",
                   table_name="collection_payments")
    op.drop_table("collection_payments")
