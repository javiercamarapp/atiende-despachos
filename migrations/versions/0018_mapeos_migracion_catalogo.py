# -*- coding: utf-8 -*-
"""persistencia real de mapeos de migración de catálogo (REQ-MIG-016)

Revision ID: 0018_mapeos_migracion_catalogo
Revises: 0017_rls_tenant_isolation
Create Date: 2026-09-09

Contexto (auditoría de producción, cluster de migración cross-database):
`MigracionCatalogoService` (`b2b_ai/features/migracion_catalogo/service.py`)
solo tenía un repositorio en memoria (`dict` de proceso) para los
`MapeoMigracionCuenta` -- ninguna aprobación/edición/rechazo humano
(REQ-MIG-007) sobrevivía a un reinicio del proceso. Para una migración
larga (cientos de pólizas, entre dos bases de datos físicamente
distintas) eso significa perder todo el trabajo de revisión humano si el
proceso se interrumpe a medias.

Esta migración agrega la tabla que
`b2b_ai/features/migracion_catalogo/repositorio_postgres.py::RepositorioMapeosPostgres`
necesita para dar persistencia real, sin cambiar en absoluto
`service.py` (que ya recibía un repositorio inyectable con interfaz de
`dict` -- este repositorio simplemente implementa esa misma interfaz
respaldada por SQL en vez de memoria).

Diseño de columnas: un mapeo (10 campos de
`models.py::MapeoMigracionCuenta`) más `migracion_id` (agrupa todos los
mapeos de una migración cross-database concreta -- p.ej.
"empresa-x:2024-2026->2020-2023" -- para que dos migraciones distintas
nunca se mezclen aunque compartan esta misma tabla física) y
`creado_en`/`actualizado_en` (auditoría real de Postgres, no calculada
en Python).

Sin RLS (a diferencia de `0017_rls_tenant_isolation.py`): esta tabla no
tiene un único `tenant_id` dueño de cada fila -- un mapeo cross-database
involucra un tenant de origen y uno de destino, potencialmente en dos
bases físicas distintas -- así que la política de aislamiento por
tenant_id de H-18 no aplica aquí de forma directa. El aislamiento real
de esta tabla es por `migracion_id`, aplicado en cada consulta de
`RepositorioMapeosPostgres` (nunca se lee/escribe sin ese filtro).
"""
from alembic import op
import sqlalchemy as sa

revision = "0018_mapeos_migracion_catalogo"
down_revision = "0017_rls_tenant_isolation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mapeos_migracion_catalogo",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("migracion_id", sa.Text(), nullable=False),
        sa.Column("origen_cuenta_id", sa.Text(), nullable=False),
        sa.Column("destino_cuenta_id", sa.Text(), nullable=True),
        sa.Column("tipo_match", sa.Text(), nullable=False),
        sa.Column("score", sa.Numeric(6, 2), nullable=False, server_default="0"),
        sa.Column(
            "estado", sa.Text(), nullable=False, server_default="pendiente"
        ),
        sa.Column("aprobado_por", sa.Text(), nullable=True),
        sa.Column("aprobado_en", sa.Text(), nullable=True),
        sa.Column("nota", sa.Text(), nullable=True),
        sa.Column("estrategia_conciliacion_saldos", sa.Text(), nullable=True),
        sa.Column(
            "creado_en",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "actualizado_en",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_mapeos_migracion_catalogo_migracion",
        "mapeos_migracion_catalogo",
        ["migracion_id"],
    )
    op.create_index(
        "idx_mapeos_migracion_catalogo_origen",
        "mapeos_migracion_catalogo",
        ["migracion_id", "origen_cuenta_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_mapeos_migracion_catalogo_origen",
        table_name="mapeos_migracion_catalogo",
    )
    op.drop_index(
        "idx_mapeos_migracion_catalogo_migracion",
        table_name="mapeos_migracion_catalogo",
    )
    op.drop_table("mapeos_migracion_catalogo")
