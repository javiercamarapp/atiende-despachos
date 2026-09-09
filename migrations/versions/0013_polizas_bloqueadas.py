"""migración de pólizas: destino atómico + cola de bloqueadas

Revision ID: 0013_polizas_bloqueadas
Revises: 0012_cuenta_id_fk
Create Date: 2026-09-08

REQ-MIG-009 (docs/BLUEPRINT-AGENTES-FISCALES.md, matriz REQ-MIG):
"El motor de migración de pólizas debe ser transaccional por póliza
completa: si alguna línea de una póliza no tiene mapeo aprobado, la
póliza ENTERA se aborta (0 líneas migradas de esa póliza) y se manda a
una cola `polizas_bloqueadas`; nunca debe migrar parcialmente una
póliza dejando débito≠crédito en destino."

Esta migración agrega las dos tablas que ese motor
(`b2b_ai/features/migracion_catalogo/migrador.py::migrar_poliza`)
necesita para poder demostrar la garantía transaccional con Postgres
real (no con mocks):

  - `lineas_poliza_migradas`: destino de cada línea YA migrada. Solo se
    escribe dentro de una única transacción de Postgres por póliza
    (todas sus líneas o ninguna) — la atomicidad la da la transacción
    de la base de datos, no un chequeo posterior en Python.
    `cuenta_destino_id` tiene FK activa a `cuentas_contables(cuenta_id)`
    (REQ-MIG-001): un `destino_cuenta_id` inválido en un mapeo hace que
    Postgres rechace el INSERT y, por tanto, toda la transacción de esa
    póliza se revierta sola.
  - `polizas_bloqueadas`: cola de revisión para toda póliza abortada
    (por falta de mapeo aprobado en alguna línea, o por cualquier error
    durante el intento de escritura en destino). Guarda qué cuentas
    origen no tenían mapeo aprobado/editado, para que un humano corrija
    el mapeo (REQ-MIG-007) y la póliza se pueda reintentar después
    (reintento real = REQ-MIG-010, fuera de alcance de este requisito).

No se toca `asientos_contables`/`cuentas_contables` (ADR-3: ningún dato
existente se reclasifica por este cambio de esquema).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0013_polizas_bloqueadas"
down_revision = "0012_cuenta_id_fk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lineas_poliza_migradas",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("poliza_origen_id", sa.Text(), nullable=False),
        sa.Column("mapeo_id", sa.Text(), nullable=False),
        sa.Column("cuenta_origen_id", sa.Text(), nullable=False),
        sa.Column(
            "cuenta_destino_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("debe", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("haber", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column(
            "migrada_en",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(
            ["cuenta_destino_id"], ["cuentas_contables.cuenta_id"]
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "poliza_origen_id",
            "cuenta_origen_id",
            name="uq_linea_poliza_migrada_origen",
        ),
    )
    op.create_index(
        "idx_lineas_poliza_migradas_tenant",
        "lineas_poliza_migradas",
        ["tenant_id"],
    )
    op.create_index(
        "idx_lineas_poliza_migradas_poliza",
        "lineas_poliza_migradas",
        ["tenant_id", "poliza_origen_id"],
    )

    op.create_table(
        "polizas_bloqueadas",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("poliza_origen_id", sa.Text(), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column(
            "cuentas_sin_mapeo", sa.Text(), nullable=False, server_default="[]"
        ),
        sa.Column(
            "bloqueada_en",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    op.create_index(
        "idx_polizas_bloqueadas_tenant", "polizas_bloqueadas", ["tenant_id"]
    )
    op.create_index(
        "idx_polizas_bloqueadas_poliza",
        "polizas_bloqueadas",
        ["tenant_id", "poliza_origen_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_polizas_bloqueadas_poliza", table_name="polizas_bloqueadas"
    )
    op.drop_index(
        "idx_polizas_bloqueadas_tenant", table_name="polizas_bloqueadas"
    )
    op.drop_table("polizas_bloqueadas")

    op.drop_index(
        "idx_lineas_poliza_migradas_poliza", table_name="lineas_poliza_migradas"
    )
    op.drop_index(
        "idx_lineas_poliza_migradas_tenant", table_name="lineas_poliza_migradas"
    )
    op.drop_table("lineas_poliza_migradas")
