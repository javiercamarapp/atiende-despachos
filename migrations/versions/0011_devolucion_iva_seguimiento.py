"""devolucion_iva_solicitudes: columnas de seguimiento y congruencia

Revision ID: 0011_devolucion_iva_seguimiento
Revises: 0010_devolucion_iva_persistencia
Create Date: 2026-09-08

REQ-IVA-006 (docs/BLUEPRINT-AGENTES-FISCALES.md, matriz REQ-IVA):
`DevolucionIVAService` debe leer/escribir `_solicitudes`, `_status` y
`_papeles_trabajo` desde tablas reales en vez de dicts de proceso.

`devolucion_iva_solicitudes` (0010_devolucion_iva_persistencia) ya cubre
`SolicitudDevolucion`, pero le faltaban las columnas de:

  - Seguimiento ante el SAT (antes solo en el dict `_status`,
    `StatusDevolucion`): `fecha_presentacion`, `fecha_respuesta`,
    `monto_aprobado`, `observaciones`.
  - Congruencia previa al envío (REQ-IVA-010, `EstadoEnvioSolicitud`):
    `estado`, `motivo_aclaracion`.

Todas nullable: son campos opcionales en los modelos Pydantic
correspondientes, y así no interfieren con el `tenant_id NOT NULL` que
`devolucion_iva_solicitudes` ya exige a nivel de esquema.
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_devolucion_iva_seguimiento"
down_revision = "0010_devolucion_iva_persistencia"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "devolucion_iva_solicitudes",
        sa.Column("estado", sa.String(), nullable=True),
    )
    op.add_column(
        "devolucion_iva_solicitudes",
        sa.Column("motivo_aclaracion", sa.Text(), nullable=True),
    )
    op.add_column(
        "devolucion_iva_solicitudes",
        sa.Column("fecha_presentacion", sa.String(), nullable=True),
    )
    op.add_column(
        "devolucion_iva_solicitudes",
        sa.Column("fecha_respuesta", sa.String(), nullable=True),
    )
    op.add_column(
        "devolucion_iva_solicitudes",
        sa.Column("monto_aprobado", sa.Float(), nullable=True),
    )
    op.add_column(
        "devolucion_iva_solicitudes",
        sa.Column("observaciones", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("devolucion_iva_solicitudes", "observaciones")
    op.drop_column("devolucion_iva_solicitudes", "monto_aprobado")
    op.drop_column("devolucion_iva_solicitudes", "fecha_respuesta")
    op.drop_column("devolucion_iva_solicitudes", "fecha_presentacion")
    op.drop_column("devolucion_iva_solicitudes", "motivo_aclaracion")
    op.drop_column("devolucion_iva_solicitudes", "estado")
