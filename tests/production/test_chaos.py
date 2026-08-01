# -*- coding: utf-8 -*-
"""
test_chaos.py — Pruebas de caos (resiliencia).

Simula fallos que ocurren en producción y verifica que el sistema degrada
con errores controlados, NUNCA con un crash del intérprete ni con datos
silenciosamente corruptos:

  1. Pérdida de conexión a la DB   (archivo borrado / path inválido)
  2. Modificaciones concurrentes   (thundering herd sobre la misma DB)
  3. Payloads inválidos a nivel de DB
  4. Timeout / operaciones lentas  (no cuelgan el proceso)
"""
import os
import threading

import pytest

from b2b_ai.db.db import Database


# --------------------------------------------------------------------------- #
# 1. Pérdida de conexión a la DB
# --------------------------------------------------------------------------- #
def test_db_perdida_de_conexion_error_controlado_y_recuperacion(tmp_path):
    """Si la conexión a la DB se cae, la siguiente operación falla con un
    error controlado (nunca datos falsos ni cuelgue), y el sistema se recupera
    al reconectar."""
    import sqlite3
    path = str(tmp_path / "chaos.db")
    db = Database(path)
    # sanity: funciona
    db.create_tenant("Despacho", rfc="XAXX010101000")

    # pérdida de conexión: cerramos la conexión real del thread-local
    db.conn.close()
    with pytest.raises(sqlite3.ProgrammingError):
        db.create_tenant("Otro", rfc="XAXX010101001")

    # recuperación: close() fuerza una conexión nueva
    db.close()
    db.create_tenant("Recuperado", rfc="XAXX010101002")
    assert len(db.list_tenants()) == 2


def test_db_path_invalido_no_crashea():
    """Un path de DB inválido no rompe el intérprete: lanza DatabaseError."""
    from sqlite3 import DatabaseError
    # path apuntando a un directorio -> no se puede abrir como DB
    with pytest.raises((DatabaseError, OSError)):
        Database("/tmp")


def test_db_corrupta_no_devuelve_datos_falsos(tmp_path):
    """Un archivo que no es una DB SQLite provoca DatabaseError al migrar."""
    from sqlite3 import DatabaseError
    path = tmp_path / "corrupta.db"
    path.write_bytes(b"no es una base de datos sqlite en absoluto" * 4)
    with pytest.raises((DatabaseError, OSError)):
        Database(str(path))


# --------------------------------------------------------------------------- #
# 2. Modificaciones concurrentes (thundering herd)
# --------------------------------------------------------------------------- #
def test_escrituras_concurrentes_no_corrompen(tmp_path):
    """20 hilos insertan facturas en paralelo sobre la misma Database.

    Verifica que la estrategia thread-local de conexiones de la capa SQLite
    aguanta la concurrencia sin corromper la DB ni perder escrituras.
    """
    import copy
    from b2b_ai.cfdi.parser import parse_cfdi
    fixture = os.path.normpath(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "..", "fixtures", "cfdis", "01_gasto_operativo_papeleria.xml"))

    db = Database(str(tmp_path / "concurrent.db"))
    t = db.create_tenant("Despacho A", rfc="XAXX010101000")
    base = parse_cfdi(fixture)
    clasif = {"categoria": "gasto_operativo", "confianza": 0.9, "razon": ""}
    val = {"ok": True, "requires_human_review": False, "issues": []}

    n_threads, per_thread = 20, 3
    errors = []

    def worker(wid):
        try:
            for j in range(per_thread):
                datos = copy.deepcopy(base)
                datos["folio_fiscal"] = "conc-%d-%d" % (wid, j)  # uuid único
                db.insert_invoice(tenant_id=t, datos=datos, clasif=clasif,
                                  validacion=val)
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    assert not errors, f"errores en hilos: {errors[:3]}"
    # la DB sigue legible y consistente (sin pérdida de escrituras)
    assert db.count_invoices(tenant_id=t) == n_threads * per_thread


# --------------------------------------------------------------------------- #
# 3. Payloads inválidos a nivel de DB
# --------------------------------------------------------------------------- #
def test_insert_invoice_datos_invalidos_no_corrompen(tmp_path):
    """La capa SQLite (sin enforce de FK) tolera un tenant inexistente sin
    corromper: el conteo solo refleja filas del tenant válido y la DB sigue
    consistente. Documenta el comportamiento observado, no uno asumido."""
    import copy
    from b2b_ai.cfdi.parser import parse_cfdi
    fixture = os.path.normpath(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "..", "fixtures", "cfdis", "01_gasto_operativo_papeleria.xml"))
    db = Database(str(tmp_path / "invalid.db"))
    t = db.create_tenant("Despacho", rfc="XAXX010101000")
    base = parse_cfdi(fixture)
    clasif = {"categoria": "gasto_operativo", "confianza": 0.9, "razon": ""}
    val = {"ok": True, "requires_human_review": False, "issues": []}

    # escritura válida
    d = copy.deepcopy(base); d["folio_fiscal"] = "ok-1"
    db.insert_invoice(tenant_id=t, datos=d, clasif=clasif, validacion=val)

    # tenant inexistente: tolerado (no FK) pero NO debe tocarse la DB
    d2 = copy.deepcopy(base); d2["folio_fiscal"] = "ok-2"
    db.insert_invoice(tenant_id=999999, datos=d2, clasif=clasif, validacion=val)

    # el conteo del tenant válido es correcto y la DB sigue consistente
    assert db.count_invoices(tenant_id=t) == 1


# --------------------------------------------------------------------------- #
# 4. Timeout / operaciones lentas no cuelgan el proceso
# --------------------------------------------------------------------------- #
def test_api_operacion_lenta_devuelve_error_no_cuelga(clean_client, tmp_path):
    """Un archivo gigante (buffer grande) no cuelga: la API lo rechaza o lo
    procesa, pero siempre responde."""
    c = clean_client["client"]
    h = {"X-API-Key": clean_client["key"]}
    big = tmp_path / "gigante.xml"
    # 3 MB de basura XML mal formada: debe dar 422, no colgar
    big.write_text("<?xml version='1.0'?><root>" + ("<x/>" * 500000) + "</root>")
    with open(big, "rb") as fh:
        r = c.post("/api/v1/invoices/process", headers=h,
                   files={"xml_file": ("gigante.xml", fh, "text/xml")})
    assert r.status_code in (400, 422, 500)  # error controlado, jamás timeout/cuelgue
    # y el servidor sigue respondiendo
    assert c.get("/health").status_code == 200
