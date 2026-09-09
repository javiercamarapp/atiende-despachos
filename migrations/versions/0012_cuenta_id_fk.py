"""cuentas_contables/asientos_contables: cuenta_id UUID + FK activa

Revision ID: 0012_cuenta_id_fk
Revises: 0011_devolucion_iva_seguimiento
Create Date: 2026-09-08

REQ-MIG-001 (docs/BLUEPRINT-AGENTES-FISCALES.md, matriz REQ-MIG):
Base estructural para la migración/fusión de catálogo de cuentas
(`b2b_ai/features/migracion_catalogo/`, aún por construir en REQ-MIG-002+).

Qué hace esta migración (solo esquema, ningún dato se reclasifica):

  - `cuentas_contables` gana una columna `cuenta_id UUID NOT NULL DEFAULT
    gen_random_uuid()` que pasa a ser el PRIMARY KEY de la tabla.
  - La columna `id` (bigint identity) NO se elimina ni cambia de tipo: se
    conserva como UNIQUE NOT NULL. Es la referenciada por
    `balanzas_mensuales.cuenta_id` (bigint) y por el resto del código de
    aplicación (`b2b_ai/db/db.py`, `lastrowid`, etc.), que sigue tratando
    los ids como enteros — ver la nota en `b2b_ai/db/models.py` líneas
    909-932 ("no se cambia a UUID para no romper la capa de datos"). Esta
    migración respeta esa decisión: agrega un PK UUID nuevo para el motor
    de migración de catálogo sin tocar el id entero que ya usan las demás
    tablas y el código existente.
  - `asientos_contables` gana una columna `cuenta_id UUID` NULLABLE con
    FK activa a `cuentas_contables(cuenta_id)`. Es nullable y no se
    hace ningún backfill: `cuenta_debito`/`cuenta_credito` (TEXT) se
    conservan intactas. Poblar `cuenta_id` a partir de esos textos
    requeriría decidir a qué cuenta del catálogo corresponde cada
    valor — una reclasificación de cuenta que, por ADR-3 del blueprint,
    NUNCA se aplica sola: solo vía aprobación humana explícita en el
    flujo de `migracion_catalogo` (REQ-MIG-003 a REQ-MIG-009). Esta
    migración deja lista la columna y la FK; no reemplaza todavía
    `cuenta_debito`/`cuenta_credito` en el código de la aplicación.

Verificación: `\\d asientos_contables` debe mostrar
`cuenta_id_fkey FOREIGN KEY (cuenta_id) REFERENCES cuentas_contables(cuenta_id)`
activa.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0012_cuenta_id_fk"
down_revision = "0011_devolucion_iva_seguimiento"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Nueva columna UUID en cuentas_contables, poblada por default para
    #    las filas existentes (server_default para que el ADD COLUMN no
    #    falle sobre una tabla con datos).
    op.add_column(
        "cuentas_contables",
        sa.Column(
            "cuenta_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
    )

    # 2) Conservar `id` como UNIQUE NOT NULL antes de tocar su PK, para que
    #    la FK de balanzas_mensuales(cuenta_id) -> cuentas_contables(id)
    #    nunca quede sin una restricción única que la respalde.
    op.create_unique_constraint(
        "uq_cuentas_contables_id", "cuentas_contables", ["id"]
    )

    # 3) balanzas_mensuales_cuenta_id_fkey está atada al índice concreto de
    #    cuentas_contables_pkey (no a "cualquier" unique sobre id), así que
    #    hay que soltarla antes de poder tocar el PK y volver a crearla
    #    después contra la unique constraint nueva.
    op.drop_constraint(
        "balanzas_mensuales_cuenta_id_fkey",
        "balanzas_mensuales",
        type_="foreignkey",
    )

    # 4) Promover cuenta_id a PRIMARY KEY (y degradar `id` de PK a UNIQUE).
    op.drop_constraint(
        "cuentas_contables_pkey", "cuentas_contables", type_="primary"
    )
    op.create_primary_key(
        "cuentas_contables_pkey", "cuentas_contables", ["cuenta_id"]
    )

    op.create_foreign_key(
        "balanzas_mensuales_cuenta_id_fkey",
        "balanzas_mensuales",
        "cuentas_contables",
        ["cuenta_id"],
        ["id"],
    )

    # 5) asientos_contables: columna UUID nullable + FK activa. Sin
    #    backfill ni drop de cuenta_debito/cuenta_credito (ver docstring).
    op.add_column(
        "asientos_contables",
        sa.Column("cuenta_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "asientos_contables_cuenta_id_fkey",
        "asientos_contables",
        "cuentas_contables",
        ["cuenta_id"],
        ["cuenta_id"],
    )
    op.create_index(
        "idx_asientos_cuenta_id", "asientos_contables", ["cuenta_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_asientos_cuenta_id", table_name="asientos_contables")
    op.drop_constraint(
        "asientos_contables_cuenta_id_fkey",
        "asientos_contables",
        type_="foreignkey",
    )
    op.drop_column("asientos_contables", "cuenta_id")

    op.drop_constraint(
        "balanzas_mensuales_cuenta_id_fkey",
        "balanzas_mensuales",
        type_="foreignkey",
    )
    op.drop_constraint(
        "cuentas_contables_pkey", "cuentas_contables", type_="primary"
    )
    op.create_primary_key("cuentas_contables_pkey", "cuentas_contables", ["id"])
    # Soltar la unique constraint auxiliar ANTES de recrear la FK de
    # balanzas_mensuales: si ambas (pkey y uq_cuentas_contables_id) existen
    # a la vez sobre `id`, Postgres puede atar la FK nueva a la unique en
    # vez de al pkey, y entonces el DROP de la unique fallaría después por
    # dependencia — igual que pasó al subir esta migración.
    op.drop_constraint(
        "uq_cuentas_contables_id", "cuentas_contables", type_="unique"
    )
    op.create_foreign_key(
        "balanzas_mensuales_cuenta_id_fkey",
        "balanzas_mensuales",
        "cuentas_contables",
        ["cuenta_id"],
        ["id"],
    )
    op.drop_column("cuentas_contables", "cuenta_id")
