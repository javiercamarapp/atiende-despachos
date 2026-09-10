# -*- coding: utf-8 -*-
"""RLS (Row-Level Security) en PostgreSQL: invoices, audit_log,
audit_entries, client_users — H-18

Revision ID: 0017_rls_tenant_isolation
Revises: 0016_pipeline_jobs
Create Date: 2026-09-09

CONTEXTO (H-18 de la auditoría): hoy el aislamiento multi-tenant depende
POR COMPLETO de que cada consulta en b2b_ai/db/db.py y b2b_ai/audit/trail.py
recuerde escribir "WHERE tenant_id = ?" — confirmado en la ronda db-core. No
hay ninguna barrera en la base de datos: una consulta nueva (o una editada)
que por bug omita ese filtro devuelve/modifica filas de CUALQUIER tenant sin
que nada lo impida. Esta migración añade Row-Level Security como defensa en
profundidad ADICIONAL — el filtro explícito de db.py/trail.py NO se retira
en ningún método; ver los cambios en esas dos rutas en el mismo commit
(Database._rls_tenant / Database._rls_admin_bypass).

TABLAS CUBIERTAS (dinero y PII, las que pidió H-18):
  - invoices        : montos fiscales (subtotal/iva/total) por tenant.
  - audit_log       : bitácora de tool-calls internas (payload puede llevar
                       datos del CFDI procesado).
  - audit_entries   : audit trail enterprise (user_id, resource, details,
                       ip — el más rico en PII de los dos audit*).
  - client_users    : cuentas del portal del cliente (email, password_hash).

`leads` se DEJA FUERA deliberadamente pese a tener tenant_id (añadido en
0008_privacy_consent): en el código actual (b2b_ai/db/db.py::add_lead/
list_leads) es el buzón de leads comerciales DE Atiende Despachos (landing pública),
nunca se escribe con un tenant_id real (siempre NULL) y se lee sin scope de
tenant (panel interno de Likide, no dato de un despacho cliente). Meterle
una política tenant_id=current_setting(...) no protegería nada real hoy (no
hay ninguna ruta de lectura por-tenant que RLS pudiera reforzar) y sí podría
romper ese panel interno si algún día se le pasa tenant_id por error. Si
`leads` empieza a usarse como dato real de un tenant (asignar leads a un
despacho), esta migración debe extenderse — no antes.

DISEÑO
------
1. GUC de sesión (transaction-local, `set_config(name, value, is_local=true)`):
     app.current_tenant_id — id del tenant autenticado para ESTA operación.
     app.rls_bypass        — 'on' SOLO en los pocos call sites legítimamente
                              cross-tenant (dashboards/CLI de admin global,
                              bootstrap de login por email, resolución de
                              sesión/JWT por id) — ver Database._rls_admin_bypass
                              y sus usos, todos documentados en el código.
   Ambos se fijan en Database/AuditTrail, NUNCA en SQL de negocio suelto.

2. Política (misma USING y WITH CHECK en las 4 tablas):
     rls_bypass = 'on'
     OR (tenant_id IS NOT NULL
         AND tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::bigint)
   Sin bypass y sin GUC de tenant fijado, el default es DENEGAR (fail
   closed) — no "ver todo" como pasaría hoy si una query olvida su WHERE.
   (El `NULLIF(..., '')` no es cosmético: ver la nota junto a `_POLICY_SQL`
   más abajo sobre el orden de evaluación de AND/OR en PostgreSQL, que
   reventaba un cast a bigint aun en la rama que "no debía" ejecutarse.)

3. FORCE ROW LEVEL SECURITY (no solo ENABLE): sin esto, PostgreSQL exime
   por defecto al ROLE DUEÑO de la tabla de sus propias políticas de RLS.
   Este repo migra y conecta con el MISMO rol (B2B_DB_URL / DATABASE_URL
   único, ver migrations/env.py) — sin FORCE, el rol de la app sería
   inmune a las políticas que esta misma migración crea, dando una falsa
   sensación de seguridad. Con FORCE, hasta el dueño respeta la política
   (solo un superusuario real, o un rol con BYPASSRLS explícito, la
   saltaría — ninguno de los dos es el rol de conexión normal).

4. Rol de aplicación de mínimo privilegio (`despachos_app_rls`): además de
   FORCE (que ya protege al rol actual sea cual sea), se crea un rol
   LOGIN sin BYPASSRLS y sin ser dueño de nada, con exactamente los
   privilegios que la app necesita sobre estas tablas. Es defensa en
   profundidad adicional para el día en que se separe la conexión de
   runtime de la de migraciones (hoy son la misma, ver limitación abajo);
   no reemplaza el FORCE, que es lo que protege la conexión ACTUAL.
   La contraseña se fija vía variable de entorno (DESPACHOS_APP_RLS_PASSWORD)
   con un fallback aleatorio si no se define, para que `alembic upgrade`
   nunca falle en un entorno donde no se planea usar este rol todavía;
   rotar la contraseña real es un paso operativo posterior (no se hace
   aquí porque este script no toca secretos de despliegue).

LIMITACIÓN ARQUITECTÓNICA REAL (documentada, no un half-fix silencioso):
El GUC es transaction-local, y `b2b_ai.db.db.Database` reutiliza UNA
conexión por hilo entre requests (pool compartido, `_pg_conn`), con la
mayoría de los métodos de escritura haciendo su propio commit() individual
— no hay una única transacción por-request. Por eso el GUC se fija en cada
método de Database/AuditTrail justo antes de su propia consulta (con el
MISMO tenant_id que ese método ya recibe como argumento), en vez de una vez
al principio del request. Esto protege bien el escenario adversarial que
pide H-18: una consulta que por bug OMITE "AND tenant_id=?" en su SQL,
aunque el tenant_id correcto sí haya llegado como argumento. NO protege
contra un caller que calcula/pasa un tenant_id INCORRECTO (confusión de
autorización aguas arriba) — eso requeriría fijar el GUC desde el tenant
autenticado en el límite del request, de forma independiente de lo que cada
método de Database reciba, lo cual exige una conexión (o transacción)
dedicada por request en vez de la conexión compartida por hilo que existe
hoy en b2b_ai/db/db.py. Ese es un refactor de arquitectura de conexión más
grande (afecta a los ~80 métodos de escritura y a los 4 pools de conexión
distintos documentados en el docstring de módulo de db.py) y NO se hace en
esta migración.
"""
from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op

revision = "0017_rls_tenant_isolation"
down_revision = "0016_pipeline_jobs"
branch_labels = None
depends_on = None

# Tablas protegidas por H-18 (dinero + PII multi-tenant). `leads` queda
# fuera deliberadamente -- ver docstring del módulo.
_RLS_TABLES = ("invoices", "audit_log", "audit_entries", "client_users")

_APP_ROLE = "despachos_app_rls"

#
# NOTA sobre orden de evaluación (gotcha real, encontrado al probar esto
# contra PostgreSQL de verdad, no solo leído en la doc): "the inputs of an
# AND or OR operator are not necessarily evaluated left-to-right" (docs de
# PostgreSQL). Una primera versión de esta política ponía
# "current_setting(...) <> '' AND tenant_id = current_setting(...)::bigint"
# asumiendo que el cast a bigint nunca se intentaría si el GUC estaba en
# blanco -- PostgreSQL SÍ puede evaluar el cast igual, y `''::bigint`
# lanza `invalid input syntax for type bigint` incluso cuando ese AND
# nunca podía ser TRUE. La prueba adversarial
# (tests/adversarial/test_rls_tenant_isolation_pg.py) lo reprodujo en la
# primera corrida real. Arreglo: `NULLIF(..., '')::bigint` nunca falla por
# cast de cadena vacía (da NULL, y `tenant_id = NULL` es NULL/false de
# forma segura) sin depender de en qué orden se evalúen los operandos.
_POLICY_SQL = """
    current_setting('app.rls_bypass', true) = 'on'
    OR (
        tenant_id IS NOT NULL
        AND tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::bigint
    )
"""


def upgrade() -> None:
    conn = op.get_bind()

    # 1) Rol de aplicación de mínimo privilegio. NOSUPERUSER/NOBYPASSRLS
    #    explícitos: aunque son el default de CREATE ROLE, se listan para
    #    que la intención quede en el propio SQL, no solo en el default de
    #    Postgres. La password sale de una env var (nunca hardcodeada); si
    #    no está definida se genera una aleatoria de un solo uso -- el rol
    #    queda creado pero inutilizable hasta que alguien fije una
    #    contraseña real (paso operativo, fuera del alcance de esta
    #    migración de esquema).
    # NOTA técnica: CREATE ROLE es DDL y su cláusula PASSWORD exige un
    # literal de cadena en esa posición gramatical -- ni un DO $$ ... $$
    # ni la cláusula PASSWORD aceptan un parámetro ligado ($1) ahí (falla
    # con "could not determine data type of parameter"). Por eso el check
    # de existencia se hace como un SELECT parametrizado normal (DML, sí
    # soporta bind params) y el password se interpola como literal SQL ya
    # escapado a mano (duplicando comillas simples) en vez de vía DO $$.
    app_role_password = os.environ.get("DESPACHOS_APP_RLS_PASSWORD") \
        or f"changeme-{os.urandom(9).hex()}"
    _pw_literal = app_role_password.replace("'", "''")
    role_exists = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role"),
        {"role": _APP_ROLE},
    ).fetchone()
    if not role_exists:
        conn.execute(sa.text(
            f"CREATE ROLE {_APP_ROLE} LOGIN NOSUPERUSER NOBYPASSRLS "
            f"NOCREATEDB NOCREATEROLE PASSWORD '{_pw_literal}'"
        ))

    conn.execute(sa.text(f"GRANT USAGE ON SCHEMA public TO {_APP_ROLE}"))
    conn.execute(sa.text(f"GRANT SELECT ON tenants TO {_APP_ROLE}"))
    # `classifications` NO está en _RLS_TABLES (no es la tabla de dinero/PII
    # que pide H-18, solo guarda categoria/confianza/razon de clasificación)
    # pero `Database.insert_invoice` escribe ahí en la MISMA operación que
    # escribe `invoices` (historial de clasificación) -- sin este GRANT el
    # rol de mínimo privilegio no podría ni siquiera completar un insert de
    # factura normal, lo cual lo haría inservible como rol de runtime real.
    # Se concede acceso por completitud funcional; NO se le activa RLS
    # (fuera del alcance que pidió H-18) -- queda como limitación menor
    # documentada, no un descuido.
    _EXTRA_GRANT_TABLES = ("classifications",)
    for t in _RLS_TABLES + _EXTRA_GRANT_TABLES:
        conn.execute(sa.text(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO {_APP_ROLE}"))
    # Secuencias de las PK `id` (SERIAL/BIGSERIAL) -- sin esto el rol no
    # podría insertar (nextval requiere USAGE explícito).
    for t in _RLS_TABLES + _EXTRA_GRANT_TABLES:
        conn.execute(sa.text(f"""
            DO $$
            DECLARE seq text;
            BEGIN
                SELECT pg_get_serial_sequence('{t}', 'id') INTO seq;
                IF seq IS NOT NULL THEN
                    EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %s TO {_APP_ROLE}', seq);
                END IF;
            END
            $$;
        """))

    # 2) RLS real: ENABLE + FORCE (ver docstring: FORCE es lo que hace que
    #    esto proteja también a la conexión actual, dueña de las tablas) +
    #    política única de aislamiento por tenant con bypass explícito.
    for t in _RLS_TABLES:
        conn.execute(sa.text(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY"))
        conn.execute(sa.text(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY"))
        conn.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation ON {t}"))
        conn.execute(sa.text(
            f"CREATE POLICY tenant_isolation ON {t} "
            f"USING ({_POLICY_SQL}) WITH CHECK ({_POLICY_SQL})"
        ))


def downgrade() -> None:
    for t in _RLS_TABLES:
        conn = op.get_bind()
        conn.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation ON {t}"))
        conn.execute(sa.text(f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY"))
        conn.execute(sa.text(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY"))
    # El rol despachos_app_rls NO se elimina en downgrade: podría tener
    # objetos/GRANTs dependientes hechos a mano fuera de esta migración
    # (p.ej. si ya se rotó DATABASE_URL para usarlo). Quitar privilegios es
    # seguro y suficiente para revertir el efecto de esta migración;
    # DROP ROLE queda como paso operativo manual si de verdad se quiere.
    op.get_bind().execute(sa.text(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_APP_ROLE}') THEN
                REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {_APP_ROLE};
                REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM {_APP_ROLE};
                REVOKE USAGE ON SCHEMA public FROM {_APP_ROLE};
            END IF;
        END
        $$;
    """))
