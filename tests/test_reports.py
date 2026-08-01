# -*- coding: utf-8 -*-
"""Tests FASE 3 — Reportes gerenciales (GerentialReports) con datos mock."""
import pytest

from b2b_ai.services.reports import GerentialReports


def inv(i, rfc, nombre, total, fecha="2026-07-15", tipo="E", valido=1,
        requiere=0, folio=None, erp="confirmado", status="procesado",
        created="2026-07-15T10:00:00", procesado="2026-07-15T10:00:05"):
    """Fábrica de factura mock con la forma de db.list_invoices."""
    return {
        "id": i, "tenant_id": 1, "folio_fiscal": folio or f"F-{i:03d}",
        "archivo": f"cfdi-{i}.xml", "fecha": fecha, "tipo": tipo,
        "serie": "A", "folio": str(i),
        "emisor_rfc": rfc, "emisor_nombre": nombre,
        "receptor_rfc": "DESP820101AB1",
        "subtotal": str(round(float(total) / 1.16, 2)),
        "iva": str(round(float(total) * 0.16 / 1.16, 2)),
        "total": str(total), "moneda": "MXN", "descripcion": "",
        "categoria": "gasto_operativo", "confianza": 0.9,
        "razon_clasificacion": "test", "valido": valido,
        "requires_human_review": requiere, "issues": "",
        "erp_poliza": "P-1", "erp_status": erp, "status": status,
        "procesado_en": procesado, "created_at": created,
    }


@pytest.fixture
def invoices():
    # Proveedor A: 3 facturas (no flags de proveedor nuevo).
    # Proveedor B: 1 factura (señal low de proveedor nuevo).
    a = [
        inv(1, "AAA010101AA1", "Papelería A", 1000.00, fecha="2026-07-02"),
        inv(2, "AAA010101AA1", "Papelería A", 1200.00, fecha="2026-07-10"),
        inv(3, "AAA010101AA1", "Papelería A", 900.00, fecha="2026-07-18"),
    ]
    b = [
        inv(4, "BBB020202BB2", "Consultora B", 50000.00, fecha="2026-07-05",
            tipo="I"),
    ]
    # Ingreso del proveedor C (flujo de caja).
    c = [inv(5, "CCC030303CC3", "Cliente C", 8000.00, fecha="2026-06-20",
             tipo="I")]
    return a + b + c


def test_resumen_ejecutivo(invoices):
    rep = GerentialReports(invoices)
    r = rep.resumen_ejecutivo()
    assert r["facturas"] == 5
    assert r["validas"] == 5
    assert r["invalidas"] == 0
    assert r["monto_total"] > 0
    assert r["tasa_error"] == 0.0
    assert set(r["anomalias"]) == {"total", "por_severidad"}
    # Proveedor B (1 sola factura) genera señal low de proveedor nuevo.
    assert r["anomalias"]["total"] >= 1


def test_resumen_filtrado_por_periodo(invoices):
    rep = GerentialReports(invoices)
    r = rep.resumen_ejecutivo(period="2026-07")
    assert r["facturas"] == 4  # excluye la de 2026-06
    r2 = rep.resumen_ejecutivo(period="2026-06")
    assert r2["facturas"] == 1


def test_analisis_proveedores_orden_y_limite(invoices):
    rep = GerentialReports(invoices)
    r = rep.analisis_proveedores(limit=2)
    assert r["total_proveedores"] == 3
    provs = r["proveedores"]
    assert len(provs) == 2
    # Ordenados por monto desc: Consultora B (50000) primero.
    assert provs[0]["rfc"] == "BBB020202BB2"
    # Cada proveedor agrega frecuencia, monto y anomalías.
    a = next(p for p in r["proveedores"] if p["rfc"] == "BBB020202BB2")
    assert a["count"] == 1
    assert a["monto"] == 50000.0


def test_flujo_caja_ingresos_vs_egresos(invoices):
    rep = GerentialReports(invoices)
    r = rep.flujo_caja()
    flujo = r["flujo"]
    assert flujo, "debe haber al menos un mes"
    june = next(f for f in flujo if f["mes"] == "2026-06")
    assert june["ingresos"] == 8000.0  # tipo I
    assert june["egresos"] == 0.0
    july = next(f for f in flujo if f["mes"] == "2026-07")
    assert july["ingresos"] == 50000.0
    assert july["egresos"] > 0
    assert r["proyeccion"] is not None
    assert r["proyeccion"]["mes"] == "2026-08"


def test_alertas_detecta_pendientes_y_conciliacion(invoices):
    pend = invoices + [inv(6, "DDD040404DD4", "Pendiente S.A.",
                          100.00, requiere=1, erp="pendiente")]
    # Conciliación con partidas sin pareja -> alerta de conciliación.
    conc = {"pendientes_banco": 2, "pendientes_facturas": 1,
            "tasa_conciliacion": 40.0}
    rep = GerentialReports(pend, reconciliation=conc)
    r = rep.alertas()
    tipos = {a["tipo"] for a in r["alertas"]}
    assert "facturas_pendientes" in tipos
    assert "conciliacion_incompleta" in tipos
    assert r["total"] == len(r["alertas"])


def test_alertas_criticas_por_duplicado():
    # Duplicado: mismo RFC + monto + fecha (<=3 días) → anomalía high.
    # Folio fiscal igual en las dos primeras: mismo documento expedido dos veces.
    dups = [
        inv(1, "AAA010101AA1", "Papelería A", 1000.00, fecha="2026-07-10", folio="DUP-001"),
        inv(2, "AAA010101AA1", "Papelería A", 1000.00, fecha="2026-07-11", folio="DUP-001"),
        inv(3, "AAA010101AA1", "Papelería A", 500.00, fecha="2026-07-15"),
    ]
    rep = GerentialReports(dups)
    r = rep.alertas()
    tipos = {a["tipo"] for a in r["alertas"]}
    assert "anomalias_criticas" in tipos


def test_export_csv_genera_tabla(invoices):
    rep = GerentialReports(invoices)
    csv_text = rep.export_csv(rep.analisis_proveedores(limit=5))
    assert isinstance(csv_text, str)
    assert "rfc" in csv_text
    assert "monto" in csv_text
    assert "BBB020202BB2" in csv_text


def test_export_pdf_genera_html(tmp_path):
    rep = GerentialReports([])
    html = rep.export_pdf({"facturas": 10, "monto_total": 999.0},
                          title="Mi reporte")
    assert html.startswith("<!DOCTYPE html>")
    assert "Mi reporte" in html
    assert "999" in html
    # Escribe a archivo cuando se pasa filename.
    out = tmp_path / "rep.html"
    returned = rep.export_pdf({"facturas": 1}, title="X", filename=str(out))
    assert returned == str(out)
    assert out.exists()


def test_reconciliation_derivada(invoices):
    rep = GerentialReports(invoices)
    conc = rep.reconciliation()
    assert "tasa_conciliacion" in conc
    assert conc.get("es_muestra") is True
