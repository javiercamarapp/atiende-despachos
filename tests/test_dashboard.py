# -*- coding: utf-8 -*-
"""Tests FASE 3 — Dashboard API interactivo: todos los endpoints JSON."""
import pytest
from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.api.app import create_app

API_KEY = "test-secret-key-123"


def _insert(db, tenant, fecha, rfc, nombre, total, tipo="E",
            valido=True, requiere=False):
    """Inserta una factura directamente en la DB para controlar los datos."""
    datos = {
        "folio_fiscal": f"T{len(db.list_invoices(tenant_id=tenant))+1:03d}",
        "archivo": "f.xml", "fecha": fecha, "tipo": tipo, "serie": "A",
        "emisor_rfc": rfc, "emisor_nombre": nombre,
        "receptor_rfc": "DESP820101AB1",
        "subtotal": str(round(total / 1.16, 2)),
        "iva": str(round(total * 0.16 / 1.16, 2)),
        "total": str(total), "moneda": "MXN", "descripcion": "",
    }
    clasif = {"categoria": "gasto_operativo", "confianza": 0.9, "razon": "test"}
    validacion = {"ok": valido, "issues": [],
                  "requires_human_review": requiere}
    erp = {"poliza": "P-1", "status": "confirmado"}
    db.insert_invoice(tenant, datos, clasif, validacion, erp=erp)


@pytest.fixture
def client(tmp_path):
    db = Database(str(tmp_path / "api.db"))
    db.create_tenant("Despacho A", rfc="XAXX010101000")
    db.create_api_key(1, "test-key", API_KEY)
    # Proveedor A (3 facturas, 2 meses) y proveedor B (1 factura).
    _insert(db, 1, "2026-06-10", "AAA010101AA1", "Papelería A", 1000.0)
    _insert(db, 1, "2026-07-02", "AAA010101AA1", "Papelería A", 1200.0)
    _insert(db, 1, "2026-07-15", "AAA010101AA1", "Papelería A", 900.0)
    _insert(db, 1, "2026-07-05", "BBB020202BB2", "Consultora B", 50000.0)
    app = create_app(db)
    return TestClient(app), db


def _h():
    return {"X-API-Key": API_KEY}


def test_summary_endpoint(client):
    c, db = client
    r = c.get("/api/v1/dashboard/summary", headers=_h())
    assert r.status_code == 200
    body = r.json()
    assert body["total_facturas"] == 4
    assert body["monto_total"] == pytest.approx(53100.0)
    assert body["validas"] == 4
    assert body["invalidas"] == 0
    assert body["por_estado"] == {"procesado": 4}


def test_monthly_endpoint_agrupa_por_mes(client):
    c, db = client
    r = c.get("/api/v1/dashboard/monthly", headers=_h())
    assert r.status_code == 200
    meses = r.json()["meses"]
    assert [m["mes"] for m in meses] == ["2026-06", "2026-07"]
    junio = next(m for m in meses if m["mes"] == "2026-06")
    julio = next(m for m in meses if m["mes"] == "2026-07")
    assert junio["facturas"] == 1
    assert junio["monto"] == pytest.approx(1000.0)
    assert julio["facturas"] == 3
    assert julio["monto"] == pytest.approx(52100.0)
    assert "anomalias" in junio


def test_monthly_filtro_rango_fechas(client):
    c, db = client
    r = c.get("/api/v1/dashboard/monthly", headers=_h(),
              params={"fecha_desde": "2026-07-01", "fecha_hasta": "2026-07-31"})
    assert r.status_code == 200
    meses = r.json()["meses"]
    assert [m["mes"] for m in meses] == ["2026-07"]


def test_by_provider_endpoint(client):
    c, db = client
    r = c.get("/api/v1/dashboard/by-provider", headers=_h())
    assert r.status_code == 200
    provs = r.json()["proveedores"]
    # Top por monto: Consultora B primero.
    assert provs[0]["rfc"] == "BBB020202BB2"
    assert provs[0]["monto"] == pytest.approx(50000.0)
    assert provs[0]["count"] == 1
    a = next(p for p in provs if p["rfc"] == "AAA010101AA1")
    assert a["count"] == 3
    assert a["monto"] == pytest.approx(3100.0)


def test_anomalies_endpoint(client):
    c, db = client
    r = c.get("/api/v1/dashboard/anomalies", headers=_h())
    assert r.status_code == 200
    body = r.json()
    assert "total" in body
    assert "por_severidad" in body
    assert "por_tipo" in body
    # Consultora B (1 sola factura) genera una señal low (proveedor nuevo).
    assert body["por_severidad"].get("low", 0) >= 1
    assert body["por_tipo"].get("proveedor_nuevo", 0) >= 1


def test_reconciliation_endpoint(client):
    c, db = client
    r = c.get("/api/v1/dashboard/reconciliation", headers=_h())
    assert r.status_code == 200
    conc = r.json()["reconciliacion"]
    assert "tasa_conciliacion" in conc
    assert "matched" in conc
    assert conc["es_muestra"] is True


def test_kpi_endpoint(client):
    c, db = client
    r = c.get("/api/v1/dashboard/kpi", headers=_h())
    assert r.status_code == 200
    kpi = r.json()["kpi"]
    assert kpi["total_facturas"] == 4
    assert kpi["tasa_error_pct"] == 0.0
    assert kpi["porcentaje_automatico_pct"] == 100.0
    assert kpi["tiempo_promedio_procesamiento_seg"] == 0.0
    assert kpi["anomalias_total"] >= 1


def test_endpoints_requieren_auth(client):
    c, db = client
    for path in ("/summary", "/monthly", "/by-provider", "/anomalies",
                 "/reconciliation", "/kpi"):
        assert c.get("/api/v1/dashboard" + path).status_code == 401, path


def test_tenant_aislamiento(client):
    """La key de un tenant no ve los datos de otro."""
    c, db = client
    db.create_tenant("Despacho B")
    db.create_api_key(2, "key-b", "key-B-otro")
    _insert(db, 2, "2026-07-01", "ZZZ999999ZZ9", "Otro", 777.0)
    r = c.get("/api/v1/dashboard/summary", headers={"X-API-Key": "key-B-otro"})
    assert r.status_code == 200
    body = r.json()
    assert body["total_facturas"] == 1
    assert body["monto_total"] == pytest.approx(777.0)


def test_spa_dashboard_served(client):
    c, db = client
    r = c.get("/dashboard/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Chart.js" in r.text or "chart.umd" in r.text
    assert "Top proveedores" in r.text
