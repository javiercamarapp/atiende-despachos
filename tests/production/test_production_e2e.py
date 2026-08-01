# -*- coding: utf-8 -*-
"""
test_production_e2e.py — Camino crítico de producción.

Verifica el flujo que un cliente real recorre en producción:

  GET  /health                          -> liveness + backend
  POST /api/v1/invoices/process         -> upload -> parse -> validate
                                           -> classify -> store
  GET  /api/v1/stats, /api/v1/invoices  -> report (lo que se entrega)
  Auth (401 / key inválida / service-key scope)
  Rate limiting (429) y exención del healthcheck
  Aislamiento multi-tenant (IDOR bloqueado)
  Robustez ante payloads inválidos (400/404/422, nunca 500)
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# --------------------------------------------------------------------------- #
# 1. Liveness / health
# --------------------------------------------------------------------------- #
def test_health_ok(clean_client):
    r = clean_client["client"].get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["backend"] == "sqlite"          # capa de datos actual
    assert body["schema_version"] >= 1
    assert "version" in body


# --------------------------------------------------------------------------- #
# 2. Pipeline completo: upload -> parse -> validate -> classify -> store -> report
# --------------------------------------------------------------------------- #
def test_pipeline_completo_upload_a_report(clean_client, sample_consultoria):
    c, h = clean_client["client"], {"X-API-Key": clean_client["key"]}

    with open(sample_consultoria, "rb") as fh:
        r = c.post("/api/v1/invoices/process", headers=h,
                   files={"xml_file": ("02_inversion_consultoria.xml", fh, "text/xml")})
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    # parse + validate (el fixture 02 genera requires_human_review por regla
    # de negocio del pipeline — no es un error del sistema)
    assert res["valido"] is True
    # classify
    assert res["categoria"] == "inversion"
    assert res["confianza"] >= 0.5
    # store
    assert res["insertado"] is True
    assert float(res["total"]) == 5800.0

    # report (lo que ve el despacho)
    st = c.get("/api/v1/stats", headers=h).json()
    assert st["total_facturas"] == 1
    assert st["report"]["total"] == "5800.00"
    assert st["report"]["por_categoria"]["inversion"]["count"] == 1

    # listado
    lst = c.get("/api/v1/invoices", headers=h).json()
    assert lst["count"] == 1
    inv_id = lst["invoices"][0]["id"]
    det = c.get(f"/api/v1/invoices/{inv_id}", headers=h)
    assert det.status_code == 200
    assert det.json()["invoice"]["emisor_rfc"] == "CON950820K12"


# --------------------------------------------------------------------------- #
# 3. Auth flow
# --------------------------------------------------------------------------- #
def test_auth_flow(clean_client, sample_consultoria):
    c = clean_client["client"]

    # sin key -> 401
    assert c.get("/api/v1/stats").status_code == 401
    assert c.post("/api/v1/invoices/process").status_code == 401

    # key inválida -> 401
    assert c.get("/api/v1/stats", headers={"X-API-Key": "clave-incorrecta"}).status_code == 401

    # key válida -> 200
    assert c.get("/api/v1/stats", headers={"X-API-Key": clean_client["key"]}).status_code == 200

    # el lead público NO requiere key
    r = c.post("/api/v1/leads", json={"nombre": "Ana", "email": "ana@x.com"})
    assert r.status_code == 200


# --------------------------------------------------------------------------- #
# 4. Rate limiting
# --------------------------------------------------------------------------- #
def test_rate_limiting_devuelve_429(rate_limited_client):
    c = rate_limited_client["client"]
    # límite bajo (10/min). Sin key: primeros 10 -> 401, siguientes -> 429.
    codes = [c.get("/api/v1/stats").status_code for _ in range(14)]
    assert codes[:10] == [401] * 10
    assert all(x == 429 for x in codes[10:])

    # el healthcheck está exento de rate-limit
    assert c.get("/health").status_code == 200
    # respuesta 429 trae Retry-After
    assert c.get("/api/v1/stats").headers.get("retry-after")


# --------------------------------------------------------------------------- #
# 5. Multi-tenant isolation (IDOR bloqueado)
# --------------------------------------------------------------------------- #
def test_multi_tenant_aislamiento(rate_limited_client, sample_consultoria, sample_nomina):
    c, db = rate_limited_client["client"], rate_limited_client["db"]
    ha = {"X-API-Key": rate_limited_client["key_a"]}
    hb = {"X-API-Key": rate_limited_client["key_b"]}
    ta, tb = rate_limited_client["tenant_a"], rate_limited_client["tenant_b"]

    # A sube una consultoría, B una nómina
    for hdr, f in ((ha, sample_consultoria), (hb, sample_nomina)):
        r = c.post("/api/v1/invoices/process", headers=hdr, json={"xml_path": f})
        assert r.status_code == 200
        assert r.json()["result"]["insertado"] is True

    assert db.count_invoices() == 2
    assert c.get("/api/v1/invoices", headers=ha).json()["count"] == 1
    assert c.get("/api/v1/invoices", headers=hb).json()["count"] == 1

    # IDOR: A no puede leer la factura de B
    id_b = c.get("/api/v1/invoices", headers=hb).json()["invoices"][0]["id"]
    assert c.get(f"/api/v1/invoices/{id_b}", headers=ha).status_code == 404

    # B no puede forzar el tenant de A vía query param
    forced = c.get("/api/v1/invoices", headers=hb, params={"tenant_id": ta}).json()
    assert forced["tenant_id"] == tb
    assert forced["count"] == 1


# --------------------------------------------------------------------------- #
# 6. Robustez ante payloads inválidos
# --------------------------------------------------------------------------- #
def test_payloads_invalidos_never_500(clean_client, tmp_path):
    c, h = clean_client["client"], {"X-API-Key": clean_client["key"]}

    # body no-JSON
    r = c.post("/api/v1/invoices/process", headers=h, content=b"not json", )
    assert r.status_code in (400, 422)

    # JSON sin xml_path
    r = c.post("/api/v1/invoices/process", headers=h, json={})
    assert r.status_code in (400, 422)

    # xml_path fuera de los directorios permitidos -> 403 (nunca 500)
    r = c.post("/api/v1/invoices/process", headers=h,
               json={"xml_path": "/no/existe.xml"})
    assert r.status_code == 403

    # archivo vacío -> 400
    empty = tmp_path / "empty.xml"
    empty.write_text("")
    with open(empty, "rb") as fh:
        r = c.post("/api/v1/invoices/process", headers=h,
                   files={"xml_file": ("empty.xml", fh, "text/xml")})
    assert r.status_code in (400, 422)

    # extensión no permitida -> 422
    evil = tmp_path / "malware.sh"
    evil.write_text("#!/bin/sh\necho pwned")
    with open(evil, "rb") as fh:
        r = c.post("/api/v1/invoices/process", headers=h,
                   files={"xml_file": ("malware.sh", fh, "text/plain")})
    assert r.status_code == 422

    # CFDI corrupto -> 422, no 500
    bad = tmp_path / "corrupto.xml"
    bad.write_text("<?xml version='1.0'?><root><oops/></root>")
    with open(bad, "rb") as fh:
        r = c.post("/api/v1/invoices/process", headers=h,
                   files={"xml_file": ("corrupto.xml", fh, "text/xml")})
    assert r.status_code == 422

    # el sistema sigue sano
    assert c.get("/health").status_code == 200


# --------------------------------------------------------------------------- #
# 7. Dedup (mismo UUID no se re-inserta)
# --------------------------------------------------------------------------- #
def test_dedup_no_duplica(clean_client, sample_papeleria):
    c, h = clean_client["client"], {"X-API-Key": clean_client["key"]}
    db = clean_client["db"]
    r1 = c.post("/api/v1/invoices/process", headers=h, json={"xml_path": sample_papeleria})
    r2 = c.post("/api/v1/invoices/process", headers=h, json={"xml_path": sample_papeleria})
    assert r1.json()["result"]["insertado"] is True
    assert r2.json()["result"]["insertado"] is False
    assert db.count_invoices() == 1
