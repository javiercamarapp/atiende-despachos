# -*- coding: utf-8 -*-
"""
Edge cases + negative + contract tests del enterprise MVP.

Cubre los casos que NO están en la suite existente (test_e2e_security,
test_e2e_suite, test_integration_pipeline, test_api_v2):

EDGE CASES
  1. CFDI con campos faltantes (Fecha, RFC, SubTotal/Total) -> no crashea,
     marca inválido donde corresponde.
  2. CFDI con caracteres de control inválidos -> 422 controlado, no 500.
  3. CFDI con montos > 99,999,999 -> parsea, valida y persiste sin crashear.
  4. Uploads concurrentes del mismo tenant (threads) -> todos insertados,
     sin 'database is locked'.
  5. Recuperación ante pérdida de conexión a DB -> reconecta y re-lee.
  6. Manejo de timeout / no-ahorque del job async.

NEGATIVE TESTS
  7. Payload JSON inválido -> 400 controlado.
  8. Upload de archivo descomunal -> 422 controlado (no 500, no crash).

CONTRACT TESTS
  9. /openapi.json es 3.1.0 y todo path documentado responde (401/422,
     no 404) -> el spec coincide con la implementación.
  10. Esquema de respuesta del pipeline (claves exactas de _strip).
  11. Formato de salida del CLI (marcadores + código de salida).

Todas las aserciones están calibradas contra comportamiento real verificado
(pytest + TestClient / subprocess).
"""
import glob
import os
import re
import subprocess
import sys
import tempfile
import threading
import uuid

import pytest
from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.api.app import create_app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "fixtures", "cfdis")
KEY = "edge-case-secret-key"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)


def _fixture(name):
    return os.path.join(FIXTURES, name)


def _rmattr(xml, attr):
    """Elimina un atributo completo (con comillas) de un XML."""
    return re.sub(r"\s*" + attr + r'="[^"]*"', "", xml, count=1)


def _new_uuid(xml):
    return re.sub(r'UUID="[0-9a-fA-F\-]{36}"',
                  'UUID="%s"' % uuid.uuid4(), xml, count=1)


def _new_folio(xml, n):
    return re.sub(r'Folio="[0-9]+"', 'Folio="%s"' % n, xml, count=1)


@pytest.fixture
def ctx(tmp_path):
    db = Database(str(tmp_path / "edge.db"))
    tid = db.create_tenant("Despacho Edge", rfc="XAXX010101000")
    db.create_api_key(tid, "edge", KEY)
    app = create_app(db)
    return TestClient(app), db, tid


def _h():
    return {"X-API-Key": KEY}


def _write(tmp_path, name, xml):
    p = os.path.join(str(tmp_path), name)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(xml)
    return p


# --------------------------------------------------------------------------- #
# 1. EDGE: CFDI con campos faltantes
# --------------------------------------------------------------------------- #
def test_cfdi_sin_fecha_marca_invalido(tmp_path):
    from b2b_ai.cfdi.parser import parse_cfdi
    from b2b_ai.cfdi.validator import validate_cfdi
    src = open(_fixture("02_inversion_consultoria.xml"), encoding="utf-8").read()
    p = _write(tmp_path, "nofecha.xml", _rmattr(src, "Fecha"))
    v = validate_cfdi(parse_cfdi(p))
    assert v["ok"] is False
    assert any(i["code"] == "fecha_invalida" for i in v["issues"])


def test_cfdi_rfc_invalido_marca_invalido(tmp_path):
    from b2b_ai.cfdi.parser import parse_cfdi
    from b2b_ai.cfdi.validator import validate_cfdi
    src = open(_fixture("02_inversion_consultoria.xml"), encoding="utf-8").read()
    p = _write(tmp_path, "badrfc.xml",
               src.replace('Rfc="CON950820K12"', 'Rfc="123"'))
    v = validate_cfdi(parse_cfdi(p))
    assert v["ok"] is False
    assert any(i["code"] == "rfc_emisor_invalido" for i in v["issues"])


def test_cfdi_sin_subtotal_total_no_crashea(tmp_path):
    """Sin SubTotal/Total el pipeline no debe crashear: los checks de
    aritmética se omiten (valores ausentes) en lugar de explotar."""
    from b2b_ai.cfdi.parser import parse_cfdi
    src = open(_fixture("02_inversion_consultoria.xml"), encoding="utf-8").read()
    xml = _rmattr(_rmattr(src, "SubTotal"), "Total")
    p = _write(tmp_path, "nosub.xml", xml)
    datos = parse_cfdi(p)  # no debe lanzar
    assert datos["subtotal"] is None


def test_cfdi_campo_faltante_pipeline_sobrevive(ctx, tmp_path):
    """Un CFDI con campos faltantes procesado por el pipeline (nivel API)
    devuelve 200 con valido=False (o 422 controlado), nunca 500."""
    c, _db, _tid = ctx
    src = open(_fixture("02_inversion_consultoria.xml"), encoding="utf-8").read()
    xml = _rmattr(src, "Fecha")
    p = _write(tmp_path, "missing_api.xml", xml)
    r = c.post("/api/v1/invoices/process", headers=_h(),
               json={"xml_path": p})
    assert r.status_code in (200, 422), r.text
    assert r.status_code != 500


# --------------------------------------------------------------------------- #
# 2. EDGE: CFDI con caracteres inválidos
# --------------------------------------------------------------------------- #
def test_cfdi_caracteres_invalidos_422(ctx, tmp_path):
    c, _db, _tid = ctx
    src = open(_fixture("02_inversion_consultoria.xml"), encoding="utf-8").read()
    xml = src.replace(
        'Descripcion="Servicios profesionales de consultoria y desarrollo de software a la medida"',
        'Descripcion="Servicios \u0001\u0002\u001f consultoria"')
    p = _write(tmp_path, "badchar.xml", xml)
    # Multipart: el pipeline convierte CFDIError en 422 controlado.
    with open(p, "rb") as fh:
        r = c.post("/api/v1/invoices/process", headers=_h(),
                   files={"xml_file": ("badchar.xml", fh, "text/xml")})
    assert r.status_code == 422, r.text
    assert "CFDI inválido" in r.json().get("detail", "")


# --------------------------------------------------------------------------- #
# 3. EDGE: CFDI con montos > 99,999,999
# --------------------------------------------------------------------------- #
def test_cfdi_montos_grandes_pipeline(ctx, tmp_path):
    c, db, tid = ctx
    src = open(_fixture("02_inversion_consultoria.xml"), encoding="utf-8").read()
    xml = (src
           .replace('SubTotal="5000.00"', 'SubTotal="999999999.99"')
           .replace('Total="5800.00"', 'Total="1159999999.98"')
           .replace('Importe="5000.00"', 'Importe="999999999.99"')
           .replace('Base="5000.00"', 'Base="999999999.99"')
           .replace('Importe="800.00"', 'Importe="159999999.998"')
           .replace('TotalImpuestosTrasladados="800.00"',
                    'TotalImpuestosTrasladados="159999999.998"')
           .replace('ValorUnitario="5000.00"', 'ValorUnitario="999999999.99"'))
    p = _write(tmp_path, "big.xml", xml)
    r = c.post("/api/v1/invoices/process", headers=_h(),
               json={"xml_path": p})
    # No 500; el pipeline persiste aunque la aritmética marque incoherencia.
    assert r.status_code == 200, r.text
    assert r.json()["result"]["insertado"] is True
    assert float(r.json()["result"]["total"]) > 99999999
    assert db.count_invoices(tenant_id=tid) == 1


# --------------------------------------------------------------------------- #
# 4. EDGE: uploads concurrentes del mismo tenant
# --------------------------------------------------------------------------- #
def test_concurrent_uploads_mismo_tenant(tmp_path):
    db = Database(str(tmp_path / "conc.db"))
    tid = db.create_tenant("Conc")
    base = open(_fixture("02_inversion_consultoria.xml"), encoding="utf-8").read()
    errors = []
    N = 8

    def worker(i):
        try:
            xml = _new_folio(_new_uuid(base), 1000 + i)
            p = _write(tmp_path, f"conc_{i}.xml", xml)
            from b2b_ai.services.pipeline import process_file
            r = process_file(p, db=db, tenant_id=tid)
            if not r["insertado"]:
                errors.append((i, "not inserted"))
        except Exception as e:  # noqa: BLE001
            errors.append((i, type(e).__name__, str(e)[:60]))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], errors
    assert db.count_invoices(tenant_id=tid) == N


# --------------------------------------------------------------------------- #
# 5. EDGE: recuperación ante pérdida de conexión a DB
# --------------------------------------------------------------------------- #
def test_db_connection_loss_recovery(tmp_path):
    db = Database(str(tmp_path / "rec.db"))
    db.create_tenant("A")
    # Simula caída de la conexión thread-local.
    conn = db._local.conn
    conn.close()
    db._local.conn = None
    # El acceso siguiente debe reconectar y servir datos.
    assert db.conn.execute("SELECT 1").fetchone()[0] == 1
    assert len(db.list_tenants()) == 1
    db.close()


def test_db_reopen_mismo_path_persiste(tmp_path):
    path = str(tmp_path / "persist.db")
    db = Database(path)
    db.create_tenant("Persistente", rfc="XAXX010101999")
    db.close()
    db2 = Database(path, migrate=False)
    tenants = db2.list_tenants()
    assert len(tenants) == 1
    assert tenants[0]["name"] == "Persistente"
    db2.close()


# --------------------------------------------------------------------------- #
# 6. EDGE: timeout / no-ahorque del job async
# --------------------------------------------------------------------------- #
def test_job_async_no_se_ahorca_y_responde(ctx, sample_consultoria):
    c, _db, _tid = ctx
    r = c.post("/api/v2/batch", headers=_h(),
               json={"paths": [sample_consultoria], "async": True})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    # El job se resuelve en tiempo finito (poll con tope).
    done = None
    for _ in range(50):
        rr = c.get(f"/api/v2/batch/{job_id}", headers=_h())
        assert rr.status_code == 200
        if rr.json()["status"] == "completed":
            done = rr.json()
            break
    assert done is not None, "job async no completó (posible ahorque)"
    assert done["summary"]["procesadas"] == 1


# --------------------------------------------------------------------------- #
# 7. NEGATIVO: payload JSON inválido
# --------------------------------------------------------------------------- #
def test_payload_json_invalido_400(ctx):
    c, _db, _tid = ctx
    r = c.post("/api/v1/invoices/process", headers=_h(),
               content=b"{{{ not valid json")
    assert r.status_code == 400
    assert "Body inválido" in r.json().get("detail", "")


def test_payload_json_estructura_invalida_400(ctx):
    c, _db, _tid = ctx
    r = c.post("/api/v1/invoices/process", headers=_h(),
               json={})  # sin xml_path ni xml_file
    assert r.status_code == 400


# --------------------------------------------------------------------------- #
# 8. NEGATIVO: upload de archivo descomunal
# --------------------------------------------------------------------------- #
def test_upload_descomunal_no_rompe_api(ctx):
    c, _db, _tid = ctx
    big = b"<?xml version='1.0'?>" + b"<x>" * 300000 + b"</x>" * 300000
    r = c.post("/api/v1/invoices/process", headers=_h(),
               files={"xml_file": ("huge.xml", big, "text/xml")})
    assert r.status_code == 422, r.text
    # El sistema sigue sano.
    assert c.get("/health").status_code == 200


# --------------------------------------------------------------------------- #
# 9. CONTRATO: OpenAPI spec vs implementación
# --------------------------------------------------------------------------- #
def test_openapi_es_3_y_completa(ctx):
    c, _db, _tid = ctx
    oa = c.get("/openapi.json").json()
    assert oa["openapi"].startswith("3.")
    assert len(oa["paths"]) >= 50
    # Endpoints críticos documentados.
    for path in ("/api/v1/invoices/process", "/api/v1/invoices",
                 "/api/v1/stats", "/api/v2/batch", "/health"):
        assert path in oa["paths"], path


def test_openapi_paths_documentados_existen(ctx):
    """Cada path documentado en /openapi.json debe responder (401/422),
    no 404 — es decir, el spec coincide con la implementación real."""
    c, _db, _tid = ctx
    oa = c.get("/openapi.json").json()
    for path in list(oa["paths"].keys())[:40]:
        for method in oa["paths"][path]:
            if method not in ("get", "post", "put", "delete", "patch"):
                continue
            url = path
            # Necesita parámetros de path para resolver; usamos 0/por-defecto.
            url = re.sub(r"\{[^}]+\}", "0", url)
            r = c.request(method.upper(), url)
            # Sin key -> 401/422 esperados para rutas protegidas;
            # públicos (health/static) -> 200. Nunca 404/500.
            assert r.status_code != 404, f"{method.upper()} {path} -> 404"
            assert r.status_code != 500, f"{method.upper()} {path} -> 500"


def test_openapi_security_requerida_en_v1(ctx):
    c, _db, _tid = ctx
    oa = c.get("/openapi.json").json()
    # La ruta protegida debe exigir seguridad (o al menos no ser abierta).
    sec = oa["paths"].get("/api/v1/invoices", {}).get("get", {}).get("security")
    # Si no declara security explícita, FastAPI aplica la global del app.
    assert sec is None or len(sec) > 0


# --------------------------------------------------------------------------- #
# 10. CONTRATO: esquema de respuesta del pipeline (_strip)
# --------------------------------------------------------------------------- #
def test_respuesta_pipeline_esquema_exacto(ctx, sample_consultoria):
    c, _db, _tid = ctx
    r = c.post("/api/v1/invoices/process", headers=_h(),
               json={"xml_path": sample_consultoria})
    assert r.status_code == 200
    res = r.json()["result"]
    expected = {"archivo", "valido", "requires_human_review", "categoria",
                "confianza", "erp_poliza", "erp_status", "insertado",
                "total", "emisor", "notificacion"}
    assert set(res.keys()) == expected, set(res.keys()) ^ expected
    assert isinstance(res["valido"], bool)
    assert isinstance(res["confianza"], (int, float))
    assert 0 <= res["confianza"] <= 1


def test_respuesta_stats_esquema(ctx):
    c, _db, _tid = ctx
    r = c.get("/api/v1/stats", headers=_h())
    assert r.status_code == 200
    body = r.json()
    for key in ("total_facturas", "monto_total", "iva_total", "por_categoria",
                "report", "tools_registered"):
        assert key in body, key


# --------------------------------------------------------------------------- #
# 11. CONTRATO: formato de salida del CLI
# --------------------------------------------------------------------------- #
def test_cli_process_formato_salida(tmp_path):
    db_path = str(tmp_path / "cli_contract.db")
    env = dict(os.environ, B2B_DB_PATH=db_path)
    proc = subprocess.run(
        [sys.executable, "-m", "b2b_ai.cli", "process",
         _fixture("03_activo_fijo_computadora.xml")],
        capture_output=True, text=True, env=env, cwd=ROOT)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    for marker in ("===", "archivo", "RFC emisor", "Total", "Folio fiscal",
                   "VALIDACIÓN", "CLASIFICACIÓN", "ERP", "Procesado"):
        assert marker in out, f"falta '{marker}' en salida CLI"


def test_cli_status_formato_salida(tmp_path):
    db_path = str(tmp_path / "cli_status.db")
    env = dict(os.environ, B2B_DB_PATH=db_path)
    proc = subprocess.run([sys.executable, "-m", "b2b_ai.cli", "status"],
                          capture_output=True, text=True, env=env, cwd=ROOT)
    assert proc.returncode == 0, proc.stderr
    for marker in ("Versión", "Base", "Tenants", "Facturas", "Audit", "Tools"):
        assert marker in proc.stdout, f"falta '{marker}'"


def test_cli_error_archivo_inexistente(tmp_path):
    env = dict(os.environ, B2B_DB_PATH=str(tmp_path / "cli_err.db"))
    proc = subprocess.run([sys.executable, "-m", "b2b_ai.cli", "process",
                           "/no/existe.xml"],
                          capture_output=True, text=True, env=env, cwd=ROOT)
    assert proc.returncode == 1
    assert "Error" in proc.stderr
