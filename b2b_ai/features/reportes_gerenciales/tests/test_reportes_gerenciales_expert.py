# -*- coding: utf-8 -*-
"""test_reportes_gerenciales_expert.py — Expert-level tests for Reportes Gerenciales module."""
from __future__ import annotations
import threading
import pytest
from b2b_ai.features.reportes_gerenciales.service import ReportesService
from b2b_ai.features.reportes_gerenciales.models import (
    MonthlyReport, CashFlow, ProfitLoss, KPI, ExportFormat, TrendDirection,
)
from b2b_ai.features.reportes_gerenciales.validators import (
    validate_period, validate_amount_range, validate_kpi_threshold, validate_monthly_report_data,
)
from b2b_ai.features.compliance import sanitize_string, mask_rfc, check_sql_injection, encode_output


class TestIdempotency:
    def test_service_init_idempotent(self):
        s1 = ReportesService("t1")
        s2 = ReportesService("t1")
        assert len(s1._reports) == len(s2._reports) == 0

    def test_generate_report_different_ids(self):
        svc = ReportesService("t1")
        r1 = svc.generate_monthly_report("t1", 1, 2024, {"revenue": 100000})
        r2 = svc.generate_monthly_report("t1", 1, 2024, {"revenue": 100000})
        assert r1.id != r2.id


class TestAuditTrail:
    def test_log_audit(self):
        svc = ReportesService("t1")
        entry = svc.log_audit(user="u1", action="generate", module="reportes", result="ok")
        assert entry.action == "generate"


class TestInputSanitization:
    def test_encode_output(self):
        assert "&lt;" in encode_output("<script>test</script>")

    def test_check_sql_injection(self):
        safe, _ = check_sql_injection("normal report")
        assert safe
        safe, _ = check_sql_injection("'; DROP TABLE--")
        assert not safe


class TestErrorHandling:
    def test_generate_invalid_month(self):
        svc = ReportesService("t1")
        with pytest.raises(ValueError):
            svc.generate_monthly_report("t1", 13, 2024)

    def test_validate_period_invalid(self):
        ok, _ = validate_period("bad")
        assert not ok

    def test_validate_amount_negative(self):
        ok, _ = validate_amount_range(-100)
        assert not ok

    def test_validate_amount_exceeds_max(self):
        ok, _ = validate_amount_range(2_000_000_000)
        assert not ok


class TestTenantIsolation:
    def test_report_tenant(self):
        svc = ReportesService("t1")
        report = svc.generate_monthly_report("t1", 1, 2024, {"revenue": 100000})
        assert report.tenant_id == "t1"

    def test_mask_rfc(self):
        masked = mask_rfc("EMP850101AB1")
        assert "***" in masked


class TestEdgeCases:
    def test_kpi_dashboard_empty_data(self):
        svc = ReportesService("t1")
        result = svc.generate_kpi_dashboard("t1", "2024-01")
        assert result["ok"] is True
        assert len(result["kpis"]) >= 6

    def test_cash_flow_zero(self):
        svc = ReportesService("t1")
        cf = svc.generate_cash_flow("t1", "2024-01")
        assert cf.inflows == 0.0
        assert cf.outflows == 0.0

    def test_profit_loss_zero(self):
        svc = ReportesService("t1")
        pl = svc.generate_profit_loss("t1", "2024-01")
        assert pl.income == 0.0
        assert pl.taxes == 0.0

    def test_validate_kpi_no_target(self):
        ok, _ = validate_kpi_threshold(95.0, target=None)
        assert ok

    def test_validate_kpi_within_threshold(self):
        ok, _ = validate_kpi_threshold(95.0, target=100.0, threshold_pct=0.20)
        assert ok

    def test_validate_kpi_exceeds_threshold(self):
        ok, _ = validate_kpi_threshold(50.0, target=100.0, threshold_pct=0.20)
        assert not ok

    def test_validate_monthly_report_data_invalid(self):
        ok, _ = validate_monthly_report_data({"period": "bad"})
        assert not ok


class TestConcurrentAccess:
    def test_concurrent_generate(self):
        svc = ReportesService("t1")
        results = []
        def run():
            results.append(svc.generate_monthly_report("t1", 1, 2024, {"revenue": 100000}))
        threads = [threading.Thread(target=run) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(results) == 5


class TestDataValidation:
    def test_export_json(self):
        svc = ReportesService("t1")
        report = svc.generate_monthly_report("t1", 1, 2024, {"revenue": 100000})
        exported = svc.export_report(report, ExportFormat.JSON)
        import json
        data = json.loads(exported)
        assert data["period"] == "2024-01"

    def test_export_csv(self):
        svc = ReportesService("t1")
        report = svc.generate_monthly_report("t1", 1, 2024, {"revenue": 100000})
        exported = svc.export_report(report, ExportFormat.CSV)
        assert "Campo,Valor" in exported

    def test_export_pdf(self):
        svc = ReportesService("t1")
        report = svc.generate_monthly_report("t1", 1, 2024, {"revenue": 100000})
        exported = svc.export_report(report, ExportFormat.PDF)
        assert "Reporte" in exported


class TestOutputVerification:
    def test_monthly_report_structure(self):
        svc = ReportesService("t1")
        report = svc.generate_monthly_report("t1", 1, 2024, {"revenue": 500000, "expenses": 300000, "taxes_paid": 50000})
        assert report.period == "2024-01"
        assert report.revenue == 500000
        assert report.profit == 150000
        assert len(report.kpis) >= 4
        assert report.referencia_legal == "CFF Art. 89"

    def test_cash_flow_with_projection(self):
        svc = ReportesService("t1")
        cf = svc.generate_cash_flow("t1", "2024-01", {
            "opening_balance": 100000, "inflows": 300000, "outflows": 250000,
            "project_forward": True, "monthly_growth_rate": 0.05, "projection_months": 3,
        })
        assert cf.projection is not None
        assert cf.projection["months"] == 3

    def test_profit_loss_computed(self):
        svc = ReportesService("t1")
        pl = svc.generate_profit_loss("t1", "2024-01", {
            "income": 500000, "cost_of_goods_sold": 200000,
            "operating_expenses": 150000, "other_income": 10000, "other_expenses": 5000,
        })
        assert pl.gross_profit == 300000
        assert pl.operating_profit == 150000
        assert pl.pre_tax_profit == 155000
        assert pl.taxes > 0


class TestRetryLogic:
    def test_report_escalation(self):
        svc = ReportesService("t1")
        report = svc.generate_monthly_report("t1", 1, 2024, {"revenue": 100000})
        assert report.escalation_path == "review_by_contador"
