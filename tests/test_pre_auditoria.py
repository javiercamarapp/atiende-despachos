# -*- coding: utf-8 -*-
"""
test_pre_auditoria.py — Tests del módulo de Pre-Auditoría Contable.

Cobertura:
  Deducibilidad: gasto deducible, no deducible, monto excesivo, lista vacía.
  Consistencia:  partida doble ok, partida doble rota, fecha futura,
                  cuenta vacía, sin descripción.
  CFF:           RFC inválido, sin CFDI, sin CE, sin periodos, todo ok.
  Reporte:       Sin hallazgos, con hallazgos, score, resumen.
  Routes:        POST /run, POST /deductibility, POST /consistency,
                  POST /cff-compliance, GET /report, GET /history.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.pre_auditoria.models import (
    AuditFinding,
    AuditReport,
    DeductibilityCheck,
    Severity,
)
from b2b_ai.features.pre_auditoria.service import (
    check_cff_compliance,
    check_consistency,
    check_deductibility,
    generate_audit_report,
    run_pre_audit,
)
from b2b_ai.features.pre_auditoria.routes import build_pre_auditoria_router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(build_pre_auditoria_router())
    return app


def _client() -> TestClient:
    return TestClient(_app())


def _asiento_ok(**overrides) -> dict:
    base = {"id": "1", "fecha": "2026-07-15",
            "cuenta_debito": "1000", "cuenta_credito": "4100",
            "debe": "5000.00", "haber": "5000.00",
            "descripcion": "Venta de servicios"}
    base.update(overrides)
    return base


# ===========================================================================
# Tests: Deducibilidad
# ===========================================================================
class TestDeductibility:
    def test_gasto_deducible(self):
        checks = check_deductibility([
            {"invoice_id": "1", "concepto": "Renta de oficina", "monto": 15000},
        ])
        assert len(checks) == 1
        assert checks[0].es_deducible is True

    def test_gasto_no_deducible(self):
        checks = check_deductibility([
            {"invoice_id": "2", "concepto": "Multas SAT por incumplimiento", "monto": 5000},
        ])
        assert len(checks) == 1
        assert checks[0].es_deducible is False
        assert checks[0].articulo_cff == "Art. 28 LISR"

    def test_gasto_monto_excesivo(self):
        checks = check_deductibility([
            {"invoice_id": "3", "concepto": "Equipo de cómputo", "monto": 75000},
        ])
        assert len(checks) == 1
        assert checks[0].es_deducible is True
        assert "soporte adicional" in checks[0].razon

    def test_lista_vacia(self):
        checks = check_deductibility([])
        assert checks == []

    def test_propinas_no_deducible(self):
        checks = check_deductibility([
            {"invoice_id": "4", "concepto": "Propinas del restaurante", "monto": 500},
        ])
        assert checks[0].es_deducible is False


# ===========================================================================
# Tests: Consistencia
# ===========================================================================
class TestConsistency:
    def test_partida_doble_ok(self):
        findings = check_consistency([_asiento_ok()])
        # Should have no critical/high findings
        assert all(f.severity not in (Severity.CRITICAL, Severity.HIGH)
                   for f in findings)

    def test_partida_doble_rota(self):
        asiento = _asiento_ok(debe="5000", haber="3000")
        findings = check_consistency([asiento])
        assert any(f.category == "partida_doble" for f in findings)
        assert any(f.severity == Severity.CRITICAL for f in findings)

    def test_fecha_futura(self):
        asiento = _asiento_ok(fecha="2099-12-31")
        findings = check_consistency([asiento])
        assert any(f.category == "fecha_futura" for f in findings)

    def test_cuenta_vacia(self):
        asiento = _asiento_ok(cuenta_debito="")
        findings = check_consistency([asiento])
        assert any(f.category == "cuenta_incompleta" for f in findings)

    def test_sin_descripcion(self):
        asiento = _asiento_ok(descripcion="")
        findings = check_consistency([asiento])
        assert any(f.category == "sin_descripcion" for f in findings)

    def test_lista_vacia(self):
        findings = check_consistency([])
        assert findings == []


# ===========================================================================
# Tests: CFF Compliance
# ===========================================================================
class TestCFFCompliance:
    def test_rfc_invalido(self):
        findings = check_cff_compliance({"rfc": "ABC"})
        assert any(f.category == "rfc_invalido" for f in findings)

    def test_sin_cfdi(self):
        findings = check_cff_compliance({"rfc": "DESP820101AAA", "cfdi_count": 0})
        assert any(f.category == "sin_cfdi" for f in findings)

    def test_sin_ce(self):
        findings = check_cff_compliance({
            "rfc": "DESP820101AB1",
            "cfdi_count": 50,
            "tiene_contabilidad_electronica": False,
        })
        assert any(f.category == "sin_ce" for f in findings)

    def test_todo_ok(self):
        findings = check_cff_compliance({
            "rfc": "DESP820101AB1",
            "cfdi_count": 100,
            "tiene_contabilidad_electronica": True,
            "periodos_cerrados": ["2026-01", "2026-02"],
        })
        assert findings == []


# ===========================================================================
# Tests: Reporte
# ===========================================================================
class TestAuditReport:
    def test_sin_hallazgos(self):
        report = generate_audit_report([], period="2026-07", tenant_id=1)
        assert report.score == 100.0
        assert "Sin hallazgos" in report.summary

    def test_con_hallazgos(self):
        findings = [
            AuditFinding(category="test", severity=Severity.CRITICAL,
                         description="Error grave"),
            AuditFinding(category="test", severity=Severity.MEDIUM,
                         description="Error menor"),
        ]
        report = generate_audit_report(findings, period="2026-07")
        assert report.score < 100.0
        assert "2 hallazgo(s)" in report.summary

    def test_to_dict(self):
        report = generate_audit_report([], period="2026-07", tenant_id=1)
        d = report.to_dict()
        assert "findings" in d
        assert d["score"] == 100.0

    def test_run_pre_audit_completo(self):
        report = run_pre_audit(
            tenant_id=1,
            period="2026-07",
            invoices=[{"invoice_id": "1", "concepto": "Multas", "monto": 500}],
            ledger=[_asiento_ok()],
            cff_data={"rfc": "DESP820101AB1", "cfdi_count": 10,
                       "tiene_contabilidad_electronica": True,
                       "periodos_cerrados": ["2026-06"]},
        )
        assert isinstance(report, AuditReport)
        assert report.period == "2026-07"
        # Multa = no deducible → at least 1 finding
        assert len(report.findings) >= 1


# ===========================================================================
# Tests: Routes
# ===========================================================================
class TestPreAuditoriaRoutes:
    def test_run_pre_audit(self):
        resp = _client().post("/pre-auditoria/run", json={
            "tenant_id": 1,
            "period": "2026-07",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "report" in data

    def test_deductibility(self):
        resp = _client().post("/pre-auditoria/deductibility", json={
            "invoices": [{"invoice_id": "1", "concepto": "Multas SAT", "monto": 1000}],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["no_deducibles"] >= 1

    def test_consistency(self):
        resp = _client().post("/pre-auditoria/consistency", json={
            "ledger": [_asiento_ok()],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "findings" in data

    def test_cff_compliance(self):
        resp = _client().post("/pre-auditoria/cff-compliance", json={
            "rfc": "DESP820101AB1",
            "cfdi_count": 50,
            "tiene_contabilidad_electronica": True,
            "periodos_cerrados": ["2026-01"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    def test_get_report(self):
        client = _client()
        # First generate a report
        client.post("/pre-auditoria/run", json={
            "tenant_id": 5,
            "period": "2026-08",
        })
        # Then retrieve it
        resp = client.get("/pre-auditoria/report/5-2026-08")
        assert resp.status_code == 200
        assert resp.json()["report"]["period"] == "2026-08"

    def test_get_report_not_found(self):
        resp = _client().get("/pre-auditoria/report/999-2099-01")
        assert resp.status_code == 404

    def test_history(self):
        client = _client()
        client.post("/pre-auditoria/run", json={
            "tenant_id": 3, "period": "2026-06",
        })
        resp = client.get("/pre-auditoria/history", params={"tenant_id": 3})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
