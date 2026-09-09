# -*- coding: utf-8 -*-
"""H-18 — Row-Level Security (PostgreSQL) como defensa en profundidad.

Prueba adversarial REAL pedida en H-18: con RLS activo (migración
0016_rls_tenant_isolation), un intento de leer/escribir la fila de OTRO
tenant SIN el filtro explícito "AND tenant_id=?" debe fallar/devolver vacío,
incluso si el código de aplicación tuviera ese bug -- simulado aquí
ejecutando SQL crudo sin el filtro (lo que un método de `Database` con un
bug de "olvidé el WHERE" produciría), y confirmando que PostgreSQL igual
lo bloquea gracias a la política `tenant_isolation`.

Requiere:
  - `B2B_DB_URL` apuntando a un PostgreSQL con las migraciones de Alembic
    aplicadas (mismo patrón que tests/test_db_pg_integration.py) y con un
    rol de conexión con privilegio para hacer `ALTER ROLE ... PASSWORD` del
    rol `despachos_app_rls` creado por 0016 (típicamente el rol admin de
    migraciones). Sin esto, el módulo entero se salta (no falla) --
    consistente con el resto de tests de integración PG del repo.

La prueba conecta DOS veces a la misma base: una vez con el rol admin
(fixtures: crear tenants/filas) y otra con `despachos_app_rls` -- el rol de
mínimo privilegio (NOSUPERUSER NOBYPASSRLS) que crea la migración -- porque
un superusuario (incluido el owner por defecto de este repo en dev,
ver docker-compose.yml) SIEMPRE bypasea RLS sin importar FORCE ROW LEVEL
SECURITY. Probar contra el rol admin daría un falso "RLS no protege nada"
que en realidad es "este rol nunca iba a estar sujeto a RLS" -- ver el
hallazgo documentado en el commit sobre esta limitación real de
docker-compose.yml.
"""
from __future__ import annotations

import os

import psycopg
import pytest

from b2b_ai.audit.trail import AuditTrail
from b2b_ai.db.db import Database

ADMIN_DSN = os.environ.get("B2B_DB_URL", "")
_TEST_APP_ROLE = "despachos_app_rls"
_TEST_APP_ROLE_PASSWORD = "h18-adversarial-test-only"


def _admin_available():
    if not ADMIN_DSN:
        return False
    try:
        with psycopg.connect(ADMIN_DSN, connect_timeout=3) as c:
            # La migración 0016 debe haber corrido (rol + políticas).
            row = c.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s", (_TEST_APP_ROLE,)
            ).fetchone()
            return row is not None
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _admin_available(),
    reason="B2B_DB_URL no disponible o migración 0016 (rol despachos_app_rls) no aplicada",
)


def _app_role_dsn() -> str:
    """DSN al mismo host/db que ADMIN_DSN pero autenticando como el rol de
    mínimo privilegio que crea 0016_rls_tenant_isolation."""
    # ADMIN_DSN: postgresql://user:pass@host:port/db
    prefix, rest = ADMIN_DSN.split("://", 1)
    _, hostpart = rest.split("@", 1)
    return f"{prefix}://{_TEST_APP_ROLE}:{_TEST_APP_ROLE_PASSWORD}@{hostpart}"


@pytest.fixture
def two_tenants_two_rows():
    """Crea, vía el rol admin, dos tenants con una fila propia en cada
    tabla protegida por RLS, y fija una contraseña conocida (solo para
    este test) al rol despachos_app_rls. Limpia todo al terminar."""
    admin = Database(ADMIN_DSN)
    with psycopg.connect(ADMIN_DSN) as raw:
        # ALTER ROLE ... PASSWORD no admite parámetro ligado en esa
        # posición (igual que CREATE ROLE en la migración 0016); el valor
        # es una constante fija del propio test, no input externo.
        raw.execute(
            f"ALTER ROLE {_TEST_APP_ROLE} PASSWORD '{_TEST_APP_ROLE_PASSWORD}'"
        )
        raw.commit()

    tenant_a = admin.create_tenant("H18-A", "AAA010101AA1")
    tenant_b = admin.create_tenant("H18-B", "BBB010101BB1")

    inv_a, _ = admin.insert_invoice(
        tenant_a,
        {"folio_fiscal": "h18-a-1", "archivo": "a.xml", "subtotal": "100",
         "iva": "16", "total": "116"},
        {"categoria": "gasto_operativo", "confianza": 0.9, "razon": "r"},
        {"ok": True, "issues": []},
    )
    inv_b, _ = admin.insert_invoice(
        tenant_b,
        {"folio_fiscal": "h18-b-1", "archivo": "b.xml", "subtotal": "200",
         "iva": "32", "total": "232"},
        {"categoria": "gasto_operativo", "confianza": 0.9, "razon": "r"},
        {"ok": True, "issues": []},
    )

    # Emails únicos por corrida (no solo por tenant): una corrida previa
    # interrumpida (p.ej. Ctrl-C a mitad del test) puede haber dejado
    # basura sin limpiar en esta base persistente -- un email fijo
    # colisionaría con esa basura y `get_client_user_by_email` (que barre
    # TODOS los tenants cuando no se le da uno) podría devolver la fila
    # vieja en vez de la de este test, dando un falso resultado.
    suffix = os.urandom(4).hex()
    email_a = f"h18-a-{suffix}@example.com"
    email_b = f"h18-b-{suffix}@example.com"
    cu_a = admin.create_client_user(tenant_a, email_a, "hash-a")
    cu_b = admin.create_client_user(tenant_b, email_b, "hash-b")

    trail = AuditTrail(admin)
    trail.log_action(None, tenant_a, "login", "session", details={"x": "a"})
    trail.log_action(None, tenant_b, "login", "session", details={"x": "b"})

    yield {
        "tenant_a": tenant_a, "tenant_b": tenant_b,
        "inv_a": inv_a, "inv_b": inv_b,
        "cu_a": cu_a, "cu_b": cu_b,
        "email_a": email_a, "email_b": email_b,
    }

    with psycopg.connect(ADMIN_DSN) as raw:
        # Orden importa: classifications tiene FK a invoices -- borrar
        # invoices primero revienta con ForeignKeyViolation.
        for t in ("audit_entries", "client_users", "classifications", "invoices"):
            raw.execute(f"DELETE FROM {t} WHERE tenant_id IN (%s,%s)",
                        (tenant_a, tenant_b))
        raw.execute("DELETE FROM tenants WHERE id IN (%s,%s)",
                    (tenant_a, tenant_b))
        raw.commit()
    admin.close()


@pytest.fixture
def app_role_db():
    """`Database` conectada como el rol de mínimo privilegio (SUJETO a
    RLS) -- lo que un despliegue real debería usar en producción para que
    esta defensa sea efectiva (ver hallazgo sobre docker-compose.yml en el
    commit: el rol usado hoy por el stack de este repo es superusuario y
    por eso NO está sujeto a RLS -- probar con ese rol daría un falso
    negativo)."""
    db = Database(_app_role_dsn(), migrate=False)
    yield db
    db.close()


class TestInvoicesRLS:
    def test_select_sin_where_no_ve_otro_tenant(self, two_tenants_two_rows,
                                                 app_role_db):
        """Simula el bug adversarial exacto de H-18: una consulta que
        OMITE por completo "AND tenant_id=?". Con el filtro de la app
        ausente, solo RLS decide qué se ve."""
        ids = two_tenants_two_rows
        app_role_db._rls_tenant(ids["tenant_a"])
        rows = app_role_db.conn.execute(
            "SELECT id, tenant_id FROM invoices"  # SIN WHERE -- bug simulado
        ).fetchall()
        seen_tenants = {r["tenant_id"] for r in rows}
        assert ids["tenant_a"] in seen_tenants
        assert ids["tenant_b"] not in seen_tenants

    def test_lectura_directa_por_id_de_otro_tenant_no_ve_nada(
            self, two_tenants_two_rows, app_role_db):
        ids = two_tenants_two_rows
        app_role_db._rls_tenant(ids["tenant_a"])
        row = app_role_db.conn.execute(
            "SELECT id FROM invoices WHERE id = ?", (ids["inv_b"],)
        ).fetchone()
        assert row is None

    def test_get_invoice_metodo_real_de_la_app(self, two_tenants_two_rows,
                                                app_role_db):
        """El método real de la app SÍ trae el WHERE -- confirma que la
        doble defensa (filtro + RLS) no rompe el camino correcto."""
        ids = two_tenants_two_rows
        assert app_role_db.get_invoice(
            ids["inv_b"], tenant_id=ids["tenant_a"]) is None
        got = app_role_db.get_invoice(ids["inv_a"], tenant_id=ids["tenant_a"])
        assert got is not None and got["id"] == ids["inv_a"]

    def test_update_de_otro_tenant_afecta_cero_filas(self, two_tenants_two_rows,
                                                      app_role_db):
        ids = two_tenants_two_rows
        app_role_db._rls_tenant(ids["tenant_a"])
        cur = app_role_db.conn.execute(
            "UPDATE invoices SET total = 999999 WHERE id = ?",
            (ids["inv_b"],))
        app_role_db.conn.commit()
        assert cur.rowcount == 0
        app_role_db._rls_tenant(ids["tenant_b"])
        row = app_role_db.conn.execute(
            "SELECT total FROM invoices WHERE id = ?", (ids["inv_b"],)
        ).fetchone()
        assert float(row["total"]) != 999999.0

    def test_insert_falsificando_tenant_id_de_otro_falla(
            self, two_tenants_two_rows, app_role_db):
        """INSERT ... VALUES (tenant_id=B) mientras el GUC dice A: la
        cláusula WITH CHECK de la política debe rechazarlo -- ni siquiera
        deja crear el registro fantasma."""
        ids = two_tenants_two_rows
        app_role_db._rls_tenant(ids["tenant_a"])
        with pytest.raises(Exception, match="row-level security"):
            app_role_db.conn.execute(
                "INSERT INTO invoices (tenant_id, folio_fiscal, archivo) "
                "VALUES (?, ?, ?)",
                (ids["tenant_b"], "h18-forjado", "x.xml"))
            app_role_db.conn.commit()
        app_role_db.conn.rollback()

    def test_sin_contexto_de_tenant_fijado_no_ve_nada(
            self, two_tenants_two_rows, app_role_db):
        """Ningún GUC fijado (conexión "fría", como la primera consulta de
        un hilo reciclado que aún no llamó a `_rls_tenant`): debe fallar
        cerrado (0 filas), NUNCA "ver todo por default"."""
        rows = app_role_db.conn.execute(
            "SELECT id FROM invoices WHERE id IN (?, ?)",
            (two_tenants_two_rows["inv_a"], two_tenants_two_rows["inv_b"]),
        ).fetchall()
        assert rows == []


class TestClientUsersRLS:
    def test_select_sin_where_no_ve_otro_tenant(self, two_tenants_two_rows,
                                                 app_role_db):
        ids = two_tenants_two_rows
        app_role_db._rls_tenant(ids["tenant_a"])
        rows = app_role_db.conn.execute(
            "SELECT id, tenant_id, email FROM client_users"
        ).fetchall()
        emails = {r["email"] for r in rows}
        assert ids["email_a"] in emails
        assert ids["email_b"] not in emails

    def test_bootstrap_login_por_email_usa_bypass_explicito(
            self, two_tenants_two_rows, app_role_db):
        """`get_client_user_by_email(email)` sin tenant_id es el único
        camino legítimo cross-tenant (login antes de saber el tenant) --
        debe seguir funcionando (bypass explícito), no romperse por RLS."""
        ids = two_tenants_two_rows
        user = app_role_db.get_client_user_by_email(ids["email_b"])
        assert user is not None
        assert user["tenant_id"] == ids["tenant_b"]

    def test_delete_client_user_de_otro_tenant_no_borra_nada(
            self, two_tenants_two_rows, app_role_db):
        ids = two_tenants_two_rows
        app_role_db.delete_client_user(ids["cu_b"], tenant_id=ids["tenant_a"])
        # sigue existiendo (bypass admin para verificar)
        still_there = app_role_db.get_client_user(ids["cu_b"])
        assert still_there is not None


class TestAuditEntriesRLS:
    def test_get_audit_log_no_ve_otro_tenant_aunque_el_sql_no_filtre(
            self, two_tenants_two_rows, app_role_db):
        ids = two_tenants_two_rows
        app_role_db._rls_tenant(ids["tenant_a"])
        rows = app_role_db.conn.execute(
            "SELECT tenant_id, details FROM audit_entries"  # SIN WHERE
        ).fetchall()
        seen = {r["tenant_id"] for r in rows}
        assert ids["tenant_a"] in seen
        assert ids["tenant_b"] not in seen

    def test_metodo_real_get_audit_log(self, two_tenants_two_rows, app_role_db):
        trail = AuditTrail(app_role_db)
        entries = trail.get_audit_log(two_tenants_two_rows["tenant_a"])
        assert all(e.tenant_id == two_tenants_two_rows["tenant_a"] for e in entries)
