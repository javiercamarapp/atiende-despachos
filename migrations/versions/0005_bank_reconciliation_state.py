"""estado de conciliación bancaria persistido por tenant

Revision ID: 0005_bank_reconciliation_state
Revises: 0004_audit_feature_flags
Create Date: 2026-08-01

Equivalente en PostgreSQL de la migración SQLite 13 (`b2b_ai/db/models.py`).

El estado de conciliación vivía en un diccionario a nivel de módulo dentro de
`b2b_ai/api/reconciliation.py`. Con más de un worker eso no funciona: la subida
del estado de cuenta aterriza en un proceso y el reporte se pide a otro. Aquí se
persiste lo único que no es derivable —los movimientos subidos y las
confirmaciones manuales—; las facturas salen de `invoices` y los cruces se
recalculan en cada petición.
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_bank_reconciliation_state"
down_revision = "0005_outstanding_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bank_transactions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=True),
        sa.Column("tx_id", sa.Text(), nullable=False),
        sa.Column("banco", sa.Text(), nullable=True),
        sa.Column("filename", sa.Text(), nullable=True),
        # Movimiento normalizado. TEXT y no JSONB: db.py lo serializa y
        # deserializa con json.dumps/loads igual en los dos backends, y no se
        # consulta por dentro.
        sa.Column("data", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
    )
    # COALESCE porque dos NULL no colisionan en un índice único y el tenant
    # nulo (key de servicio) es un caso real. Debe coincidir EXACTAMENTE con el
    # índice de SQLite para que `ON CONFLICT DO NOTHING` lo infiera igual.
    op.execute(
        "CREATE UNIQUE INDEX idx_bank_tx_unico ON bank_transactions "
        "(COALESCE(tenant_id, -1), tx_id)")
    op.create_index("idx_bank_tx_tenant", "bank_transactions", ["tenant_id"])

    op.create_table(
        "bank_confirmations",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=True),
        sa.Column("tx_id", sa.Text(), nullable=False),
        sa.Column("invoice_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
    )
    op.execute(
        "CREATE UNIQUE INDEX idx_bank_conf_unico ON bank_confirmations "
        "(COALESCE(tenant_id, -1), tx_id)")
    op.create_index("idx_bank_conf_tenant", "bank_confirmations",
                    ["tenant_id"])


def downgrade() -> None:
    op.drop_index("idx_bank_conf_tenant", table_name="bank_confirmations")
    op.execute("DROP INDEX IF EXISTS idx_bank_conf_unico")
    op.drop_table("bank_confirmations")
    op.drop_index("idx_bank_tx_tenant", table_name="bank_transactions")
    op.execute("DROP INDEX IF EXISTS idx_bank_tx_unico")
    op.drop_table("bank_transactions")
