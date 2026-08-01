# -*- coding: utf-8 -*-
"""
test_full_pipeline.py — Integration tests for the full pipeline.

Covers:
  - 5 different CFDI types → correct classification
  - Corrupt CFDI → graceful error handling
  - Unusual amount → anomaly detection
  - Duplicate invoice → dedup verification
  - Output integrity: all expected fields present
"""
import pytest
import os

from b2b_ai.db.db import Database
from b2b_ai.services.pipeline import process_file, process_batch, summarize
from b2b_ai.tools.logger import logger as global_logger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
EXPECTED_PIPELINE_KEYS = {
    "archivo", "datos", "validacion", "clasificacion",
    "anomalias", "aprobacion", "erp", "invoice_id",
    "insertado", "tenant_id", "notificacion", "pii",
}

EXPECTED_VALIDACION_KEYS = {"ok", "issues", "requires_human_review"}

EXPECTED_CLASIF_KEYS = {"categoria", "confianza", "razon", "requires_human_review"}


@pytest.fixture
def db_pipeline(tmp_path):
    """Returns a clean Database in a temp file, with logger wired."""
    db = Database(str(tmp_path / "pipeline_integ.db"))
    global_logger.set_db(db)
    return db


@pytest.fixture
def all_fixtures(fixture_dir):
    """Returns list of (name, path) for all 7 fixture CFDI files."""
    files = sorted(os.listdir(fixture_dir))
    return [(f, os.path.join(fixture_dir, f)) for f in files if f.endswith(".xml")]


# ---------------------------------------------------------------------------
# 1. 5 DIFFERENT CFDI TYPES → CORRECT CLASSIFICATION
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("fixture_name,expected_cat", [
    ("01_gasto_operativo_papeleria.xml", "gasto_operativo"),
    ("02_inversion_consultoria.xml",      "inversion"),
    ("03_activo_fijo_computadora.xml",    "activo_fijo"),
    ("04_nomina_pago.xml",                "nomina"),
    ("06_honorarios_retenciones.xml",     "inversion"),
])
def test_pipeline_clasifica_correctamente(db_pipeline, fixture_dir,
                                           fixture_name, expected_cat):
    db = db_pipeline
    path = os.path.join(fixture_dir, fixture_name)
    res = process_file(path, db=db)
    assert res["validacion"]["ok"] is True
    assert res["clasificacion"]["categoria"] == expected_cat
    assert res["insertado"] is True
    assert res["invoice_id"] is not None


# ---------------------------------------------------------------------------
# 2. CORRUPT CFDI → GRACEFUL ERROR HANDLING
# ---------------------------------------------------------------------------
def test_pipeline_cfdi_corrupto_manejo_graceful(db_pipeline, tmp_path):
    db = db_pipeline
    bad_xml = tmp_path / "corrupto.xml"
    bad_xml.write_text("<?xml version='1.0'?><not-a-cfdi><data/></not-a-cfdi>")

    with pytest.raises(Exception):
        process_file(str(bad_xml), db=db)


# ---------------------------------------------------------------------------
# 3. ANOMALY DETECTION — unusual amount vs historical
# ---------------------------------------------------------------------------
def test_pipeline_anomalia_monto_atipico(db_pipeline, fixture_dir):
    """Insert 3+ invoices from same emisor, then an extreme one → monto_atipico."""
    db = db_pipeline
    tid = db.create_tenant("Anomaly Test")

    # Insert 3 invoices from the SAME emisor to build history for monto_atipico
    same_emisor = "AAA010101AAA"
    for i in range(3):
        db.insert_invoice(
            tid,
            {"folio_fiscal": f"hist-{i}", "archivo": f"hist_{i}.xml",
             "fecha": "2026-07-01", "tipo": "I",
             "emisor_rfc": same_emisor, "emisor_nombre": "Proveedor X",
             "receptor_rfc": "REC999", "subtotal": "100.00",
             "iva": "16.00", "total": "116.00", "moneda": "MXN"},
            {"categoria": "gasto_operativo", "confianza": 0.9, "razon": "r"},
            {"ok": True, "issues": [], "requires_human_review": False},
        )

    # Now an extreme amount from the same emisor
    anomalo = {
        "folio_fiscal": "anomaly-uuid-999", "archivo": "anomalo.xml",
        "fecha": "2026-07-31", "tipo": "I",
        "emisor_rfc": same_emisor, "emisor_nombre": "Proveedor X",
        "receptor_rfc": "REC999",
        "subtotal": "999999999.00", "iva": "159999999.84",
        "total": "1159999998.84", "moneda": "MXN",
    }

    from b2b_ai.services.anomaly import detect_anomalies
    historical = db.list_invoices(tenant_id=tid, limit=200)
    anomalies = detect_anomalies(anomalo, historical=historical)
    anomaly_types = {a["tipo"] for a in anomalies}
    assert "monto_atipico" in anomaly_types, \
        f"Expected monto_atipico anomaly, got: {anomaly_types}"


# ---------------------------------------------------------------------------
# 4. DUPLICATE → DEDUP
# ---------------------------------------------------------------------------
def test_pipeline_dedup_no_reinserta(db_pipeline, fixture_dir):
    """Process same CFDI twice → second is rejected as duplicate."""
    db = db_pipeline
    path = os.path.join(fixture_dir, "05_gasto_operativo_internet.xml")
    r1 = process_file(path, db=db)
    r2 = process_file(path, db=db)
    assert r1["insertado"] is True
    assert r2["insertado"] is False
    assert db.count_invoices() == 1


# ---------------------------------------------------------------------------
# 5. OUTPUT FIELD INTEGRITY
# ---------------------------------------------------------------------------
def test_pipeline_output_tiene_todos_los_campos(db_pipeline, fixture_dir):
    """Every pipeline result dict has all expected keys and valid sub-fields."""
    db = db_pipeline
    path = os.path.join(fixture_dir, "02_inversion_consultoria.xml")
    res = process_file(path, db=db)

    # Top-level keys
    assert EXPECTED_PIPELINE_KEYS.issubset(res.keys()), \
        f"Missing top-level keys: {EXPECTED_PIPELINE_KEYS - res.keys()}"

    # validacion sub-keys
    assert EXPECTED_VALIDACION_KEYS.issubset(res["validacion"].keys())
    assert isinstance(res["validacion"]["ok"], bool)
    assert isinstance(res["validacion"]["issues"], list)

    # clasificacion sub-keys
    assert EXPECTED_CLASIF_KEYS.issubset(res["clasificacion"].keys())
    assert 0 <= res["clasificacion"]["confianza"] <= 1
    assert isinstance(res["clasificacion"]["categoria"], str)

    # anomalias — via tool anomaly output (anomalies list + summary)
    assert isinstance(res["anomalias"], dict)
    assert "anomalies" in res["anomalias"] or "nivel" in res["anomalias"]

    # erp
    assert "ok" in res["erp"]
    assert "poliza" in res["erp"]

    # invoice_id must be a positive int
    assert isinstance(res["invoice_id"], int) and res["invoice_id"] > 0

    # tenant_id must be an int
    assert isinstance(res["tenant_id"], int)