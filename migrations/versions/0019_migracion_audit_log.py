# -*- coding: utf-8 -*-
"""log de auditoría append-only para migracion_catalogo (REQ-MIG-016)

Revision ID: 0019_migracion_audit_log
Revises: 0018_mapeos_migracion_catalogo
Create Date: 2026-09-11

Contexto (docs/BLUEPRINT-AGENTES-FISCALES.md, REQ-MIG-016 -- "pendiente"
antes de esta migración, a no confundir con el docstring de
`0018_mapeos_migracion_catalogo.py`, que cita REQ-MIG-016 por error: esa
migración resuelve la persistencia de `mapeos_migracion_catalogo`, un
requisito propio sin ID asignado en la matriz; el texto real de
REQ-MIG-016 en el blueprint es el log de auditoría append-only que esta
migración sí implementa):

  "Log de auditoría append-only: cada aprobación/rechazo/edición de un
  MapeoMigracionCuenta debe insertar una fila inmutable en
  migracion_catalogo_audit_log (quién, cuándo, mapeo, decisión, nota);
  el log nunca acepta UPDATE ni DELETE (verificable con permisos de BD
  o trigger que los rechace)."

`MigracionCatalogoService.aprobar/rechazar/editar`
(`b2b_ai/features/migracion_catalogo/service.py`) son las ÚNICAS tres
operaciones que mueven un `MapeoMigracionCuenta` fuera de
`estado=PENDIENTE` (ver docstring de módulo de `service.py` y de
`routes.py`) -- son los puntos de "modificación del catálogo" que este
log debe cubrir. `registrar()` (alta inicial de un mapeo por el motor de
matching, sin decisión humana todavía) queda fuera a propósito: no es
una decisión de revisión, y el propio texto de REQ-MIG-016 habla
explícitamente de "aprobación/rechazo/edición".

DISEÑO: trigger de Postgres, no permisos de rol
-------------------------------------------------
El blueprint ofrece dos caminos ("permisos de BD o trigger"). Se elige
trigger por una razón concreta de este repo, no por preferencia
estética: `migrations/versions/0017_rls_tenant_isolation.py` (mismo
autor, mismo repo) ya documenta que la conexión de runtime de la app y
la de migraciones son -- hoy -- LA MISMA (`B2B_DB_URL`/`DATABASE_URL`
único, ver `migrations/env.py`), y que por eso creó `despachos_app_rls`
como rol de mínimo privilegio que la app NO usa todavía en producción.
Un `REVOKE UPDATE, DELETE` sobre el rol que efectivamente conecta hoy
(el dueño de la tabla, quien la crea vía `alembic upgrade`) no protegería
nada: el dueño de una tabla en PostgreSQL tiene privilegios implícitos
sobre ella que un `REVOKE` normal no puede quitarle (eso es precisamente
lo que fuerza a RLS a usar `FORCE ROW LEVEL SECURITY` en 0017 en vez de
confiar en las políticas por sí solas). Un trigger `BEFORE UPDATE OR
DELETE` que hace `RAISE EXCEPTION`, en cambio, se dispara SIEMPRE --
incluido el dueño de la tabla -- sin más excepción que un superusuario
real desactivando triggers a mano (`session_replication_role`, que
requiere superusuario, no el rol de conexión normal de la app). Es la
única de las dos opciones que de verdad protege la conexión actual de
este repo tal como está configurada hoy.

Columnas (quién/qué cambió/cuándo/antes/después, como pide REQ-MIG-016):
  - id                : PK, texto (mismo estilo que
                        `mapeos_migracion_catalogo.id` -- UUID generado
                        en Python, sin depender de extensiones de PG).
  - migracion_id      : agrupa las filas de una migración cross-database
                        concreta, igual que en `mapeos_migracion_catalogo`
                        (0018) -- mismo criterio de aislamiento.
  - mapeo_id          : qué `MapeoMigracionCuenta` cambió.
  - accion            : 'aprobar' | 'rechazar' | 'editar'.
  - decidido_por      : quién tomó la decisión (nunca vacío -- ya lo
                        exige `service.py::_exigir_pendiente_y_responsable`
                        antes de llegar aquí).
  - nota              : justificación humana de la decisión (puede ser
                        NULL solo para 'aprobar' sin nota explícita).
  - valores_antes     : snapshot JSONB del `MapeoMigracionCuenta` ANTES
                        de la decisión.
  - valores_despues   : snapshot JSONB del `MapeoMigracionCuenta`
                        DESPUÉS de la decisión.
  - creado_en         : TIMESTAMPTZ real de Postgres (no calculado en
                        Python) -- no hay `actualizado_en`: la fila
                        nunca se actualiza, por diseño.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0019_migracion_audit_log"
down_revision = "0018_mapeos_migracion_catalogo"
branch_labels = None
depends_on = None

_TABLE = "migracion_catalogo_audit_log"
_TRIGGER_FN = "migracion_catalogo_audit_log_bloquear_update_delete"
_TRIGGER = "migracion_catalogo_audit_log_append_only"


def upgrade() -> None:
    conn = op.get_bind()

    op.create_table(
        _TABLE,
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("migracion_id", sa.Text(), nullable=False),
        sa.Column("mapeo_id", sa.Text(), nullable=False),
        sa.Column("accion", sa.Text(), nullable=False),
        sa.Column("decidido_por", sa.Text(), nullable=False),
        sa.Column("nota", sa.Text(), nullable=True),
        sa.Column("valores_antes", postgresql.JSONB(), nullable=True),
        sa.Column("valores_despues", postgresql.JSONB(), nullable=False),
        sa.Column(
            "creado_en",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "accion IN ('aprobar', 'rechazar', 'editar')",
            name="ck_migracion_catalogo_audit_log_accion",
        ),
    )
    op.create_index(
        "idx_migracion_catalogo_audit_log_migracion",
        _TABLE,
        ["migracion_id"],
    )
    op.create_index(
        "idx_migracion_catalogo_audit_log_mapeo",
        _TABLE,
        ["mapeo_id"],
    )

    # Trigger fail-closed: rechaza CUALQUIER UPDATE o DELETE sobre la
    # tabla, sin excepción de rol (ver docstring del módulo arriba sobre
    # por qué esto y no GRANT/REVOKE). El mensaje de error queda en
    # español, igual que el resto de mensajes orientados a humanos de
    # este repo (ver EXCEPTION_MESSAGES en otras migraciones/servicios).
    conn.execute(sa.text(f"""
        CREATE OR REPLACE FUNCTION {_TRIGGER_FN}()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                '% no está permitido sobre %: es un log de auditoría '
                'append-only (REQ-MIG-016) -- las filas nunca se '
                'modifican ni se borran una vez escritas.',
                TG_OP, TG_TABLE_NAME
                USING ERRCODE = 'restrict_violation';
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
    """))
    conn.execute(sa.text(f"""
        CREATE TRIGGER {_TRIGGER}
        BEFORE UPDATE OR DELETE ON {_TABLE}
        FOR EACH ROW EXECUTE FUNCTION {_TRIGGER_FN}();
    """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text(f"DROP TRIGGER IF EXISTS {_TRIGGER} ON {_TABLE}"))
    conn.execute(sa.text(f"DROP FUNCTION IF EXISTS {_TRIGGER_FN}()"))
    op.drop_index("idx_migracion_catalogo_audit_log_mapeo", table_name=_TABLE)
    op.drop_index("idx_migracion_catalogo_audit_log_migracion", table_name=_TABLE)
    op.drop_table(_TABLE)
