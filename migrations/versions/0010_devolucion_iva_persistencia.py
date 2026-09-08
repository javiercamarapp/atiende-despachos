"""devolucion_iva persistencia (PostgreSQL) — REQ-IVA-005

Revision ID: 0010_devolucion_iva_persistencia
Revises: 0009_document_management
Create Date: 2026-09-08

Agrega las 4 tablas persistentes que reemplazan los dicts en memoria de
`devolucion_iva/service.py` (ver ADR-5, BLUEPRINT-AGENTES-FISCALES.md):

  - devolucion_iva_solicitudes         (SolicitudDevolucion)
  - devolucion_iva_papeles_trabajo     (PapelTrabajo)
  - diot_entries                       (DiotEntry / DIOTEntry persistidos)
  - depositos_bancarios_clasificados   (ClasificacionDepositoResult + su
                                         DepositoBancario, de
                                         reconciliacion_ingresos_egresos)

Las 4 tienen `tenant_id NOT NULL` y un índice compuesto (tenant_id, periodo)
— requisito duro de REQ-IVA-005 para poder acotar por despacho+periodo sin
escanear toda la tabla, y para blindar el aislamiento multi-tenant a nivel de
esquema (no solo de código, ver REQ-IVA-007).

Los campos de colección (documentos, facturas, diot_entries, declaraciones,
uuids) se guardan como TEXT con JSON serializado, igual que `documents.tags`
en 0009_document_management: no se consultan por dentro, y así el mismo
código de (de)serialización sirve para SQLite (dev/test) y PostgreSQL
(producción).
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_devolucion_iva_persistencia"
down_revision = "0009_document_management"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- devolucion_iva_solicitudes ----------------------------------------
    op.create_table(
        "devolucion_iva_solicitudes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("periodo", sa.String(), nullable=False),
        sa.Column("monto_solicitado", sa.Float(), nullable=False,
                  server_default="0"),
        sa.Column("cuenta_banco", sa.String(), nullable=True),
        sa.Column("clabe", sa.String(), nullable=True),
        sa.Column("documentos", sa.Text(), nullable=False,
                  server_default="[]"),
        sa.Column("status", sa.String(), nullable=False,
                  server_default="pendiente"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=True),
    )
    op.create_index("idx_deviva_solicitudes_tenant",
                    "devolucion_iva_solicitudes", ["tenant_id"])
    op.create_index("idx_deviva_solicitudes_tenant_periodo",
                    "devolucion_iva_solicitudes", ["tenant_id", "periodo"])

    # -- devolucion_iva_papeles_trabajo -------------------------------------
    op.create_table(
        "devolucion_iva_papeles_trabajo",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("periodo", sa.String(), nullable=False),
        sa.Column("facturas", sa.Text(), nullable=False,
                  server_default="[]"),
        sa.Column("diot_entries", sa.Text(), nullable=False,
                  server_default="[]"),
        sa.Column("declaraciones", sa.Text(), nullable=False,
                  server_default="[]"),
        sa.Column("saldo_a_favor", sa.Float(), nullable=False,
                  server_default="0"),
        sa.Column("monto_solicitado", sa.Float(), nullable=False,
                  server_default="0"),
        sa.Column("status", sa.String(), nullable=False,
                  server_default="pendiente"),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("idx_deviva_papeles_tenant",
                    "devolucion_iva_papeles_trabajo", ["tenant_id"])
    op.create_index("idx_deviva_papeles_tenant_periodo",
                    "devolucion_iva_papeles_trabajo", ["tenant_id", "periodo"])

    # -- diot_entries ---------------------------------------------------
    op.create_table(
        "diot_entries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("periodo", sa.String(), nullable=False),
        sa.Column("report_id", sa.String(), nullable=True),
        sa.Column("rfc_tercero", sa.String(), nullable=False),
        sa.Column("nombre", sa.String(), nullable=False, server_default=""),
        sa.Column("tipo_operacion", sa.String(), nullable=False),
        sa.Column("tipo_iva", sa.String(), nullable=False,
                  server_default="16"),
        sa.Column("monto_neto", sa.Float(), nullable=False,
                  server_default="0"),
        sa.Column("iva_trasladado", sa.Float(), nullable=False,
                  server_default="0"),
        sa.Column("iva_acreditable", sa.Float(), nullable=False,
                  server_default="0"),
        sa.Column("numero_facturas", sa.Integer(), nullable=False,
                  server_default="1"),
        sa.Column("uuids", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("fecha", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("idx_diot_entries_tenant", "diot_entries", ["tenant_id"])
    op.create_index("idx_diot_entries_tenant_periodo", "diot_entries",
                    ["tenant_id", "periodo"])
    op.create_index("idx_diot_entries_report", "diot_entries", ["report_id"])

    # -- depositos_bancarios_clasificados ------------------------------------
    op.create_table(
        "depositos_bancarios_clasificados",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("periodo", sa.String(), nullable=False),
        sa.Column("deposito_id", sa.String(), nullable=False),
        sa.Column("fecha", sa.String(), nullable=True),
        sa.Column("monto", sa.Float(), nullable=False, server_default="0"),
        sa.Column("descripcion", sa.Text(), nullable=False,
                  server_default=""),
        sa.Column("referencia", sa.String(), nullable=False,
                  server_default=""),
        sa.Column("banco", sa.String(), nullable=False, server_default=""),
        sa.Column("cuenta", sa.String(), nullable=False, server_default=""),
        sa.Column("es_credito", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("clasificacion", sa.String(), nullable=False),
        sa.Column("confianza", sa.Float(), nullable=False,
                  server_default="0"),
        sa.Column("razon", sa.Text(), nullable=False, server_default=""),
        sa.Column("articulo_cff", sa.String(), nullable=True),
        sa.Column("requires_human_review", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("idx_depbancarios_tenant",
                    "depositos_bancarios_clasificados", ["tenant_id"])
    op.create_index("idx_depbancarios_tenant_periodo",
                    "depositos_bancarios_clasificados",
                    ["tenant_id", "periodo"])
    op.create_index("idx_depbancarios_deposito",
                    "depositos_bancarios_clasificados", ["deposito_id"])


def downgrade() -> None:
    op.drop_index("idx_depbancarios_deposito",
                  table_name="depositos_bancarios_clasificados")
    op.drop_index("idx_depbancarios_tenant_periodo",
                  table_name="depositos_bancarios_clasificados")
    op.drop_index("idx_depbancarios_tenant",
                  table_name="depositos_bancarios_clasificados")
    op.drop_table("depositos_bancarios_clasificados")

    op.drop_index("idx_diot_entries_report", table_name="diot_entries")
    op.drop_index("idx_diot_entries_tenant_periodo",
                  table_name="diot_entries")
    op.drop_index("idx_diot_entries_tenant", table_name="diot_entries")
    op.drop_table("diot_entries")

    op.drop_index("idx_deviva_papeles_tenant_periodo",
                  table_name="devolucion_iva_papeles_trabajo")
    op.drop_index("idx_deviva_papeles_tenant",
                  table_name="devolucion_iva_papeles_trabajo")
    op.drop_table("devolucion_iva_papeles_trabajo")

    op.drop_index("idx_deviva_solicitudes_tenant_periodo",
                  table_name="devolucion_iva_solicitudes")
    op.drop_index("idx_deviva_solicitudes_tenant",
                  table_name="devolucion_iva_solicitudes")
    op.drop_table("devolucion_iva_solicitudes")
