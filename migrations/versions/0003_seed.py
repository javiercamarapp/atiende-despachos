"""seed: datos de prueba

Revision ID: 0003_seed
Revises: 0002_indexes
Create Date: 2026-07-31
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_seed"
down_revision = "0002_indexes"
branch_labels = None
depends_on = None

# Marcador de entorno: solo se siembran datos de prueba si no está presente
# B2B_SEED_SKIP=1 (permite saltarse el seed en producción si se desea).
import os  # noqa: E402


def upgrade() -> None:
    if os.environ.get("B2B_SEED_SKIP"):
        return

    tenants = sa.table(
        "tenants",
        sa.column("id", sa.BigInteger()),
        sa.column("name", sa.Text()),
        sa.column("rfc", sa.Text()),
    )
    users = sa.table(
        "users",
        sa.column("id", sa.BigInteger()),
        sa.column("tenant_id", sa.BigInteger()),
        sa.column("name", sa.Text()),
        sa.column("email", sa.Text()),
        sa.column("role", sa.Text()),
    )
    conn = op.get_bind()

    t1_id = conn.execute(tenants.insert().returning(tenants.c.id).values(
        name="Despacho Demo", rfc="DEMO010101AAA")).scalar_one()
    t2_id = conn.execute(tenants.insert().returning(tenants.c.id).values(
        name="Despacho Beta", rfc="BETA010101BBB")).scalar_one()

    conn.execute(users.insert().values(tenant_id=t1_id, name="Contador Demo",
                                       email="contador@demo.com",
                                       role="contador"))
    conn.execute(users.insert().values(tenant_id=t2_id, name="Admin Beta",
                                       email="admin@beta.com", role="admin"))

    # Factura de ejemplo para el tenant Demo.
    invoices = sa.table(
        "invoices",
        sa.column("id", sa.BigInteger()),
        sa.column("tenant_id", sa.BigInteger()),
        sa.column("folio_fiscal", sa.Text()),
        sa.column("archivo", sa.Text()),
        sa.column("fecha", sa.Text()),
        sa.column("tipo", sa.Text()),
        sa.column("emisor_rfc", sa.Text()),
        sa.column("emisor_nombre", sa.Text()),
        sa.column("receptor_rfc", sa.Text()),
        sa.column("subtotal", sa.Text()),
        sa.column("iva", sa.Text()),
        sa.column("total", sa.Text()),
        sa.column("moneda", sa.Text()),
        sa.column("categoria", sa.Text()),
        sa.column("confianza", sa.Float()),
        sa.column("valido", sa.BigInteger()),
    )
    conn.execute(invoices.insert().values(
        tenant_id=t1_id,
        folio_fiscal="SEED-0001",
        archivo="seed.xml",
        fecha="2026-07-15",
        tipo="I",
        emisor_rfc="XAXX010101000",
        emisor_nombre="Proveedor Semilla",
        receptor_rfc="DEMO010101AAA",
        subtotal="1000.00",
        iva="160.00",
        total="1160.00",
        moneda="MXN",
        categoria="gasto_operativo",
        confianza=0.95,
        valido=1,
    ))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM invoices WHERE folio_fiscal='SEED-0001'"))
    conn.execute(sa.text("DELETE FROM users WHERE tenant_id IN "
                         "(SELECT id FROM tenants WHERE rfc IN "
                         "('DEMO010101AAA','BETA010101BBB'))"))
    conn.execute(sa.text("DELETE FROM tenants WHERE rfc IN "
                         "('DEMO010101AAA','BETA010101BBB')"))
