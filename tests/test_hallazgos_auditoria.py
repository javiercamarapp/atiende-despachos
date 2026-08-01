# -*- coding: utf-8 -*-
"""
Pruebas de regresión de los hallazgos de docs/auditoria-2026-08.md.

Cada prueba de aquí falla si alguien deshace una de las correcciones. Están
juntas a propósito: el valor de una auditoría no es el informe, es que sus
conclusiones queden ancladas en la suite.
"""
import importlib
import os

import pytest
from fastapi.testclient import TestClient

from b2b_ai.api.app import RateLimiter, create_app
from b2b_ai.audit.trail import AuditTrail, Actions
from b2b_ai.db.db import Database

KEY = "clave-de-servicio-para-las-pruebas"


@pytest.fixture
def app_db(tmp_path, monkeypatch):
    monkeypatch.setenv("B2B_API_KEY", KEY)
    monkeypatch.setenv("B2B_RATE_LIMIT", "off")
    db = Database(str(tmp_path / "hallazgos.db"))
    return TestClient(create_app(db=db)), db


def _h():
    return {"X-API-Key": KEY}


# --------------------------------------------------------------------------- #
# Hallazgo 1 (CRÍTICO) — el secreto JWT no puede caer a un literal del código
# --------------------------------------------------------------------------- #
def test_jwt_sin_secreto_falla_fuera_de_desarrollo(monkeypatch):
    from b2b_ai.auth import middleware

    monkeypatch.delenv("B2B_JWT_SECRET", raising=False)
    monkeypatch.setenv("B2B_ENV", "production")
    monkeypatch.setattr(middleware, "_ephemeral_secret", None)
    with pytest.raises(RuntimeError) as exc:
        middleware.jwt_secret()
    assert "B2B_JWT_SECRET" in str(exc.value)


def test_jwt_rechaza_secreto_corto(monkeypatch):
    from b2b_ai.auth import middleware

    monkeypatch.setenv("B2B_JWT_SECRET", "corto")
    with pytest.raises(RuntimeError):
        middleware.jwt_secret()


def test_jwt_en_desarrollo_genera_secreto_aleatorio(monkeypatch):
    """En dev NO se lanza, pero el secreto tampoco es predecible."""
    from b2b_ai.auth import middleware

    monkeypatch.delenv("B2B_JWT_SECRET", raising=False)
    monkeypatch.setenv("B2B_ENV", "dev")
    monkeypatch.setattr(middleware, "_ephemeral_secret", None)
    uno = middleware.jwt_secret()
    assert len(uno) >= middleware.MIN_SECRET_LEN
    # Estable dentro del proceso (los tokens sirven durante la corrida)...
    assert middleware.jwt_secret() == uno
    # ...pero distinto en otro proceso.
    monkeypatch.setattr(middleware, "_ephemeral_secret", None)
    assert middleware.jwt_secret() != uno


def test_no_queda_ningun_secreto_de_desarrollo_en_el_codigo():
    """El literal que se eliminó no puede volver por la puerta de atrás."""
    ruta = importlib.util.find_spec("b2b_ai.auth.middleware").origin
    with open(ruta, encoding="utf-8") as fh:
        src = fh.read()
    assert "_DEV_SECRET =" not in src
    assert "no-usable-en-produccion" not in src


# --------------------------------------------------------------------------- #
# Hallazgo 2 (ALTO) — `xml_path` no puede salirse de los directorios permitidos
# --------------------------------------------------------------------------- #
def test_xml_path_fuera_de_los_roots_no_lee_el_archivo(app_db, tmp_path,
                                                       monkeypatch):
    """El caso que se verificó explotable: leer un XML ajeno e importarlo."""
    c, db = app_db
    permitido = tmp_path / "permitido"
    permitido.mkdir()
    ajeno = tmp_path / "de_otro_tenant.xml"
    ajeno.write_text(
        '<?xml version="1.0"?><cfdi:Comprobante '
        'xmlns:cfdi="http://www.sat.gob.mx/cfd/4" Version="4.0" Total="1"/>')
    monkeypatch.setenv("B2B_LOCAL_XML_DIRS", str(permitido))

    r = c.post("/api/v1/invoices/process", headers=_h(),
               json={"xml_path": str(ajeno)})
    assert r.status_code == 403
    # Y no se filtra la ruta en el mensaje (no sirve de oráculo).
    assert str(ajeno) not in r.text
    # Nada se importó al tenant.
    assert c.get("/api/v1/invoices", headers=_h()).json()["count"] == 0


def test_xml_path_desactivado_por_defecto(app_db, monkeypatch):
    """Sin B2B_LOCAL_XML_DIRS la ingesta local no existe."""
    c, _ = app_db
    monkeypatch.delenv("B2B_LOCAL_XML_DIRS", raising=False)
    r = c.post("/api/v1/invoices/process", headers=_h(),
               json={"xml_path": "/etc/passwd"})
    assert r.status_code == 400


def test_xml_path_no_escapa_con_dot_dot(app_db, tmp_path, monkeypatch):
    """`..` se resuelve ANTES de comparar contra los roots."""
    c, _ = app_db
    permitido = tmp_path / "permitido"
    permitido.mkdir()
    (tmp_path / "fuera.xml").write_text("<a/>")
    monkeypatch.setenv("B2B_LOCAL_XML_DIRS", str(permitido))
    r = c.post("/api/v1/invoices/process", headers=_h(),
               json={"xml_path": str(permitido / ".." / "fuera.xml")})
    assert r.status_code == 403


def test_folder_confinado_igual_que_xml_path(app_db, monkeypatch):
    c, _ = app_db
    monkeypatch.delenv("B2B_LOCAL_XML_DIRS", raising=False)
    r = c.post("/process", headers=_h(), json={"folder": "/"})
    assert r.status_code == 400


def test_xml_malformado_devuelve_422_y_no_500(app_db, tmp_path, monkeypatch):
    """Hallazgo 6: la rama JSON no capturaba CFDIError."""
    c, _ = app_db
    monkeypatch.setenv("B2B_LOCAL_XML_DIRS", str(tmp_path))
    roto = tmp_path / "truncado.xml"
    roto.write_text('<?xml version="1.0"?><cfdi:Comprobante')
    r = c.post("/api/v1/invoices/process", headers=_h(),
               json={"xml_path": str(roto)})
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# Hallazgo 3 (ALTO) — la búsqueda del audit log no cruza tenants
# --------------------------------------------------------------------------- #
def test_search_audit_log_no_filtra_entre_tenants(tmp_path):
    """El `AND` sin paréntesis dejaba pasar filas de otros tenants."""
    db = Database(str(tmp_path / "audit.db"))
    t = AuditTrail(db)
    t.log_action("user_a", 1, Actions.CREATE, "invoice", "11", ip="1.1.1.1")
    t.log_action("user_b", 2, Actions.CREATE, "invoice", "22", ip="2.2.2.2")
    t.log_action("user_c", 3, Actions.CREATE, "invoice", "33", ip="3.3.3.3")

    todos = t.search_audit_log("invoice")
    assert len(todos) == 3

    for tenant in (1, 2, 3):
        acotado = t.search_audit_log("invoice", tenant_id=tenant)
        assert len(acotado) == 1, "la búsqueda devolvió filas de otro tenant"
        assert acotado[0].tenant_id == tenant

    # La rama que SÍ funcionaba antes (ip, la última del OR) sigue funcionando.
    assert len(t.search_audit_log("1.1.1.1", tenant_id=1)) == 1
    assert len(t.search_audit_log("1.1.1.1", tenant_id=2)) == 0


# --------------------------------------------------------------------------- #
# Hallazgo 4 (ALTO) — el estado de conciliación es persistente, no de proceso
# --------------------------------------------------------------------------- #
CSV = ("Fecha;Descripcion;Abono;Referencia\n"
       "2026-08-01;Pago A;100.00;R1\n"
       "2026-08-02;Pago B;200.00;R2\n")


def _sube_estado(c, csv=CSV):
    return c.post("/api/v1/reconciliation/upload", headers=_h(),
                  files={"file": ("edo.csv", csv.encode(), "text/csv")},
                  data={"bank": "generico"})


def test_conciliacion_sobrevive_a_una_instancia_nueva(tmp_path, monkeypatch):
    """Simula el caso multi-worker: subir en un proceso, leer en otro.

    Dos aplicaciones distintas sobre la MISMA base. Antes el estado vivía en un
    dict de módulo, así que la segunda no veía nada de la primera (y, peor, en
    las pruebas veía el estado de la anterior).
    """
    monkeypatch.setenv("B2B_API_KEY", KEY)
    monkeypatch.setenv("B2B_RATE_LIMIT", "off")
    ruta = str(tmp_path / "conc.db")

    subida = TestClient(create_app(db=Database(ruta)))
    assert _sube_estado(subida).status_code == 200

    # "Otro worker": aplicación y objeto Database nuevos, misma base.
    lectura = TestClient(create_app(db=Database(ruta)))
    rep = lectura.get("/api/v1/reconciliation/report", headers=_h()).json()
    assert rep["ok"] is True
    assert rep["movimientos_banco"] == 2


def test_conciliacion_no_se_filtra_entre_instancias_sin_datos(tmp_path,
                                                              monkeypatch):
    """Una base recién creada no ve movimientos de ninguna corrida previa."""
    monkeypatch.setenv("B2B_API_KEY", KEY)
    monkeypatch.setenv("B2B_RATE_LIMIT", "off")

    primera = TestClient(create_app(db=Database(str(tmp_path / "a.db"))))
    assert _sube_estado(primera).status_code == 200

    segunda = TestClient(create_app(db=Database(str(tmp_path / "b.db"))))
    rep = segunda.get("/api/v1/reconciliation/report", headers=_h()).json()
    assert rep["ok"] is False, "el estado se filtró entre bases distintas"


def test_conciliacion_resubir_no_duplica(app_db):
    c, _ = app_db
    assert _sube_estado(c).status_code == 200
    assert _sube_estado(c).status_code == 200
    rep = c.get("/api/v1/reconciliation/report", headers=_h()).json()
    assert rep["movimientos_banco"] == 2


def test_conciliacion_aislada_por_tenant(tmp_path, monkeypatch):
    """Los movimientos de un despacho no aparecen en el reporte de otro."""
    monkeypatch.setenv("B2B_RATE_LIMIT", "off")
    monkeypatch.delenv("B2B_API_KEY", raising=False)
    db = Database(str(tmp_path / "multi.db"))
    t1 = db.create_tenant("Despacho A", "AAA010101AAA")
    t2 = db.create_tenant("Despacho B", "BBB010101BBB")
    db.create_api_key(t1, "a", "clave-del-despacho-a")
    db.create_api_key(t2, "b", "clave-del-despacho-b")
    c = TestClient(create_app(db=db))

    ha = {"X-API-Key": "clave-del-despacho-a"}
    hb = {"X-API-Key": "clave-del-despacho-b"}
    assert c.post("/api/v1/reconciliation/upload", headers=ha,
                  files={"file": ("a.csv", CSV.encode(), "text/csv")},
                  data={"bank": "generico"}).status_code == 200

    assert c.get("/api/v1/reconciliation/report",
                 headers=hb).json()["ok"] is False
    assert c.get("/api/v1/reconciliation/report",
                 headers=ha).json()["movimientos_banco"] == 2


# --------------------------------------------------------------------------- #
# Hallazgo 7 (MEDIO) — el limitador no crece sin techo
# --------------------------------------------------------------------------- #
def test_rate_limiter_no_acumula_claves_muertas():
    """Pedir rutas distintas no hace crecer el diccionario para siempre.

    Lo que se mide NO es que el diccionario quede vacío —las claves de la
    ventana actual tienen que seguir ahí, si no el límite no limitaría—, sino
    que su tamaño deje de depender de cuántas rutas distintas se pidieron. Antes
    la relación era 1:1 y no había techo: 20 000 rutas inventadas eran 20 000
    claves retenidas para siempre.
    """
    def retenidas(n):
        rl = RateLimiter(limit=10, window=0.001, sweep_every=50)
        for i in range(n):
            rl.allow(("1.2.3.4", f"/ruta-inventada-{i}"))
        return rl.tracked_keys

    pocas, muchas = retenidas(5_000), retenidas(20_000)
    # 4x las peticiones NO puede dar ~4x las claves retenidas.
    assert muchas < pocas * 2, (
        f"retención lineal en el nº de rutas ({pocas} → {muchas}): "
        f"la fuga de memoria sigue ahí")
    assert muchas < 20_000 * 0.25, (
        f"el limitador retiene {muchas} de 20 000 claves")


def test_rate_limiter_sigue_limitando_despues_del_barrido():
    """El barrido no puede debilitar el límite."""
    rl = RateLimiter(limit=3, window=60.0, sweep_every=1)
    key = ("9.9.9.9", "/api/v1/stats")
    assert [rl.allow(key) for _ in range(5)] == [True, True, True, False, False]
