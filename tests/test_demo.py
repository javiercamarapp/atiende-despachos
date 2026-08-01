# -*- coding: utf-8 -*-
"""Tests para el comando `demo` del CLI (modo demo interactivo)."""
from __future__ import annotations

import os
import pytest

from b2b_ai.services.demo import (
    CFDI_TEMPLATES,
    generate_sample_xmls,
    generate_demo_report,
    _get_total,
)

DEMO_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "demo-data")


@pytest.fixture
def tmp_db(tmp_path):
    """Temporary database for tests (file-backed, not :memory:)."""
    from b2b_ai.db.db import Database
    return Database(str(tmp_path / "test.db"))


def test_demo_data_dir_exists():
    """The demo-data directory must exist and contain XML files."""
    assert os.path.isdir(DEMO_DATA_DIR), f"demo-data directory missing at {DEMO_DATA_DIR}"
    xmls = sorted(f for f in os.listdir(DEMO_DATA_DIR) if f.endswith(".xml"))
    assert len(xmls) >= 10, f"Expected >=10 XML files, found {len(xmls)}"
    names = " ".join(xmls).lower()
    assert "papeleria" in names
    assert "hosting" in names
    assert "servicios_profesionales" in names
    assert "nomina" in names
    assert "nota_credito" in names
    assert "activo_fijo" in names
    assert "cancelada" in names
    assert "monto_inusual" in names


def test_demo_xmls_parseable():
    """All demo XMLs must be parseable by the CFDI parser."""
    from b2b_ai.cfdi.parser import parse_cfdi
    xmls = sorted(
        os.path.join(DEMO_DATA_DIR, f)
        for f in os.listdir(DEMO_DATA_DIR)
        if f.endswith(".xml")
    )
    for x in xmls:
        datos = parse_cfdi(x)
        assert datos["emisor_rfc"], f"Missing emisor_rfc in {x}"
        assert datos["folio_fiscal"], f"Missing folio_fiscal in {x}"
        assert datos["version"] in ("4.0", "3.3")


def test_generate_demo_output_dir(tmp_path):
    """generate_demo_output_dir creates the output directory if missing."""
    from b2b_ai.services.demo import ensure_output_dir
    out_dir = str(tmp_path / "demo-output")
    path = ensure_output_dir(out_dir)
    assert os.path.isdir(path)


def test_generate_sample_xmls(tmp_path):
    """generate_sample_xmls creates valid XMLs from templates."""
    out = str(tmp_path / "demo-data")
    generate_sample_xmls(out)
    xmls = [f for f in os.listdir(out) if f.endswith(".xml")]
    assert len(xmls) >= 10
    assert "gasto_papeleria.xml" in xmls
    assert "gasto_hosting.xml" in xmls
    assert "gasto_servicios_profesionales.xml" in xmls
    assert "nomina_empleado1.xml" in xmls
    assert "nomina_empleado2.xml" in xmls
    assert "nota_credito1.xml" in xmls
    assert "nota_credito2.xml" in xmls
    assert "activo_fijo_computo.xml" in xmls
    assert "factura_cancelada.xml" in xmls
    assert "monto_inusual.xml" in xmls


def test_generate_demo_report_smoke(tmp_path):
    """generate_demo_report returns valid HTML with correct structure."""
    results = [{
        "archivo": "test.xml",
        "datos": {"emisor_rfc": "XAXX010101000", "emisor_nombre": "Test S.A.",
                  "fecha": "2026-07-01T12:00:00", "total": 1160.0, "subtotal": 1000.0,
                  "iva": 160.0, "folio_fiscal": "uuid-test", "moneda": "MXN"},
        "validacion": {"ok": True, "checks": {"pass": 5, "fail": 0}, "issues": [], "warnings": []},
        "clasificacion": {"categoria": "gasto_operativo", "confianza": 0.9, "razon": "Test"},
        "anomalias": {"anomalies": []},
        "erp": {"poliza": "P-001", "status": "ok"},
        "aprobacion": {"decision": "auto_approved", "razon": "Auto"},
        "notificacion": {"status": "skipped"},
    }] * 3
    out_dir = str(tmp_path / "demo-output")
    elapsed = 1.5
    report_path = generate_demo_report(results, out_dir, elapsed)
    assert os.path.exists(report_path)
    with open(report_path, "r") as f:
        html = f.read()
    assert "<!DOCTYPE html>" in html
    assert "1,160.00" in html  # formatted with commas
    assert "B&B AI" in html


def test_generate_report_with_anomalies(tmp_path):
    """HTML report must highlight anomalies with the anomaly-card class."""
    results = [{
        "archivo": "anomaly.xml",
        "datos": {"emisor_rfc": "XAXX010101000", "emisor_nombre": "Anomaly S.A.",
                  "fecha": "2026-07-01T12:00:00", "total": 999999.0,
                  "subtotal": 862068.0, "iva": 137931.0, "folio_fiscal": "uuid-anom",
                  "moneda": "MXN"},
        "validacion": {"ok": True, "checks": {"pass": 5, "fail": 0}, "issues": [], "warnings": []},
        "clasificacion": {"categoria": "gasto_operativo", "confianza": 0.5,
                          "razon": "Monto inusual", "requires_human_review": True},
        "anomalias": {"anomalies": [{"tipo": "monto_atipico", "severity": "high",
                                     "descripcion": "Monto fuera de rango",
                                     "supuestos": [], "referencia_legal": "CFF",
                                     "detalle": {"monto": 999999}}]},
        "erp": {"poliza": None, "status": "pending_approval"},
        "aprobacion": {"decision": "requires_review", "razon": "Monto inusual"},
        "notificacion": {"status": "alert"},
    }]
    out_dir = str(tmp_path / "demo-output")
    report_path = generate_demo_report(results, out_dir, 2.3)
    with open(report_path, "r") as f:
        html = f.read()
    assert "anomaly-card" in html
    assert "Anomalías Detectadas" in html or "anomalias detectadas" in html.lower()
    assert "monto_atipico" in html


def test_cfdi_templates_completeness():
    """CFDI_TEMPLATES must have all 10 required entries."""
    assert len(CFDI_TEMPLATES) >= 10
    keys = {t["id"] for t in CFDI_TEMPLATES}
    required = {"papeleria", "hosting", "servicios_profesionales",
                "nomina1", "nomina2", "nota_credito1", "nota_credito2",
                "activo_fijo", "cancelada", "monto_inusual"}
    missing = required - keys
    assert not missing, f"Missing CFDI template ids: {missing}"


def test_cfdi_templates_xml_syntax(tmp_path):
    """Each CFDI_TEMPLATE produces valid XML parseable by the CFDI parser."""
    from b2b_ai.cfdi.parser import parse_cfdi
    for t in CFDI_TEMPLATES:
        xml_path = str(tmp_path / f"{t['id']}.xml")
        with open(xml_path, "w") as f:
            f.write(t["xml"])
        datos = parse_cfdi(xml_path)
        assert datos["folio_fiscal"], f"Template {t['id']} has no UUID"
        assert datos["version"] in ("4.0", "3.3"), f"Template {t['id']} has wrong version"
        # Notes de crédito (E) pueden tener total=0.00
        if t["id"] not in ("nota_credito1", "nota_credito2"):
            assert datos["total"] is not None and datos["total"] > 0, \
                f"Template {t['id']} has total={datos['total']}"


def test_demo_pipeline_integration(tmp_path, tmp_db):
    """End-to-end: generate XMLs -> process through pipeline -> report."""
    data_dir = str(tmp_path / "demo-data")
    generate_sample_xmls(data_dir)
    xmls = sorted(f for f in os.listdir(data_dir) if f.endswith(".xml"))
    assert len(xmls) >= 10

    from b2b_ai.services.pipeline import process_file
    results = []
    for fname in xmls:
        path = os.path.join(data_dir, fname)
        res = process_file(path, db=tmp_db, tenant_id=None)
        results.append(res)
        assert "datos" in res

    out_dir = str(tmp_path / "demo-output")
    report_path = generate_demo_report(results, out_dir, 3.0)
    assert os.path.exists(report_path)
    with open(report_path, "r") as f:
        html = f.read()
    assert "B&B AI" in html
    assert "Procesadas" in html or "procesadas" in html or "Facturas" in html


def test_demo_output_dir_permissions(tmp_path):
    """Test that demo-output directory creation works with existing dir."""
    out_dir = str(tmp_path / "demo-output")
    os.makedirs(out_dir, exist_ok=True)
    from b2b_ai.services.demo import ensure_output_dir
    path = ensure_output_dir(out_dir)
    assert path == out_dir


def test_get_total_helper():
    """_get_total correctly extracts and formats totals."""
    entry = {"datos": {"total": 1234.56}}
    assert _get_total(entry) == 1234.56
    entry = {"datos": {"total": "0.00"}}
    assert _get_total(entry) == 0.0
    entry = {"datos": {}}
    assert _get_total(entry) == 0.0