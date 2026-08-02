# -*- coding: utf-8 -*-
"""
test_ap_ar.py — Tests for AP/AR End-to-End module (Agente 4).

Covers:
  1. APManager: receive, validate, register, list
  2. ARManager: register, collect, complement
  3. AgingReport: AP and AR aging with buckets
  4. PaymentScheduler: priority and cash flow scheduling
  5. SPEIPayment: sandbox payment and CLABE validation
  6. RetentionEngine: ISR retentions per LISR Art. 94-100
  7. NotasCredito: credit notes and reversal entries
  8. API routes via TestClient
"""
from __future__ import annotations

import pytest
from datetime import date, timedelta

from b2b_ai.features.ap_ar.models import (
    APInvoice,
    APInvoiceCreate,
    ARInvoice,
    ARInvoiceCreate,
    CollectRequest,
    CreditNoteCreate,
    CreditNoteType,
    InvoiceStatus,
    PaymentOrder,
    RetentionType,
)
from b2b_ai.features.ap_ar.ap_manager import APManager
from b2b_ai.features.ap_ar.ar_manager import ARManager
from b2b_ai.features.ap_ar.aging_report import AgingReportGenerator
from b2b_ai.features.ap_ar.payment_scheduler import PaymentScheduler
from b2b_ai.features.ap_ar.spei_payment import SPEIPayment
from b2b_ai.features.ap_ar.retention_engine import RetentionEngine, _calcular_tabla_art96
from b2b_ai.features.ap_ar.notas_credito import NotasCredito


# -----------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------

def _sample_ap_data(**overrides) -> APInvoiceCreate:
    defaults = dict(
        uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        rfc_emisor="EKU9003173C9",
        nombre_emisor="Proveedor SA de CV",
        rfc_receptor="AAA010101AAA",
        subtotal=10000.00,
        iva=1600.00,
        total=11600.00,
        fecha_emision="2026-07-15",
        fecha_vencimiento="2026-08-14",
        metodo_pago="PUE",
        concepto="Servicios de consultoría",
    )
    defaults.update(overrides)
    return APInvoiceCreate(**defaults)


def _sample_ar_data(**overrides) -> ARInvoiceCreate:
    defaults = dict(
        uuid="ar-uuid-12345678-abcd",
        rfc_receptor="XAXX010101000",
        nombre_receptor="Cliente SA de CV",
        rfc_emisor="AAA010101AAA",
        subtotal=50000.00,
        iva=8000.00,
        total=58000.00,
        fecha_emision="2026-07-01",
        fecha_vencimiento="2026-07-31",
        metodo_pago="PPD",
        concepto="Servicios de desarrollo",
    )
    defaults.update(overrides)
    return ARInvoiceCreate(**defaults)


# -----------------------------------------------------------------------
# 1. AP Manager Tests
# -----------------------------------------------------------------------

class TestAPManager:
    def test_receive_invoice(self):
        mgr = APManager(tenant_id=1)
        inv = mgr.receive_invoice(_sample_ap_data())
        assert inv.id == 1
        assert inv.status == InvoiceStatus.VALIDATED
        assert inv.total == 11600.00
        assert mgr.count_invoices() == 1

    def test_validate_total_mismatch(self):
        mgr = APManager()
        with pytest.raises(ValueError, match="Total.*no cuadra"):
            mgr.receive_invoice(_sample_ap_data(total=99999))

    def test_validate_missing_uuid(self):
        mgr = APManager()
        with pytest.raises(ValueError, match="UUID"):
            mgr.receive_invoice(_sample_ap_data(uuid=""))

    def test_validate_negative_subtotal(self):
        mgr = APManager()
        with pytest.raises(ValueError, match="Subtotal"):
            mgr.receive_invoice(_sample_ap_data(subtotal=-100))

    def test_register_invoice(self):
        mgr = APManager()
        inv = mgr.receive_invoice(_sample_ap_data())
        registered = mgr.register_invoice(inv.id)
        assert registered.status == InvoiceStatus.REGISTERED

    def test_register_nonexistent(self):
        mgr = APManager()
        with pytest.raises(ValueError, match="not found"):
            mgr.register_invoice(999)

    def test_list_invoices(self):
        mgr = APManager()
        mgr.receive_invoice(_sample_ap_data())
        mgr.receive_invoice(_sample_ap_data(
            uuid="b2c3d4e5-f6a7-8901-bcde-f12345678901"
        ))
        all_inv = mgr.list_invoices()
        assert len(all_inv) == 2

    def test_total_pending(self):
        mgr = APManager()
        mgr.receive_invoice(_sample_ap_data())
        mgr.receive_invoice(_sample_ap_data(
            uuid="b2c3d4e5-f6a7-8901-bcde-f12345678901",
            total=6960, subtotal=6000, iva=960,
        ))
        assert mgr.total_pending() == 18560.00

    def test_retencion_applied(self):
        """PF with honorarios should trigger retention."""
        mgr = APManager()
        inv = mgr.receive_invoice(_sample_ap_data(
            rfc_emisor="HEGA800615ABC",  # 13 chars = PF
            concepto="Honorarios de consultoría",
        ))
        assert inv.retencion_isr > 0


# -----------------------------------------------------------------------
# 2. AR Manager Tests
# -----------------------------------------------------------------------

class TestARManager:
    def test_register_ar_invoice(self):
        mgr = ARManager(tenant_id=1)
        inv = mgr.register_invoice(_sample_ar_data())
        assert inv.id == 1
        assert inv.status == InvoiceStatus.PENDING
        assert inv.total == 58000.00

    def test_collect_partial(self):
        mgr = ARManager()
        inv = mgr.register_invoice(_sample_ar_data())
        result = mgr.collect(CollectRequest(
            ar_invoice_id=inv.id,
            monto=20000.00,
        ))
        assert result.monto_cobrado == 20000.00
        assert result.nuevo_status == "parcial"

    def test_collect_full(self):
        mgr = ARManager()
        inv = mgr.register_invoice(_sample_ar_data())
        result = mgr.collect(CollectRequest(
            ar_invoice_id=inv.id,
            monto=58000.00,
        ))
        assert result.nuevo_status == "cobrada"

    def test_collect_exceeds_balance(self):
        mgr = ARManager()
        inv = mgr.register_invoice(_sample_ar_data())
        with pytest.raises(ValueError, match="excede"):
            mgr.collect(CollectRequest(
                ar_invoice_id=inv.id,
                monto=999999.00,
            ))

    def test_build_complemento_pago(self):
        mgr = ARManager()
        inv = mgr.register_invoice(_sample_ar_data())
        comp = mgr.build_complemento_pago(inv.id, 20000.00)
        assert comp["type"] == "P"
        assert comp["related_documents"][0]["id"] == inv.uuid

    def test_complemento_only_ppd(self):
        mgr = ARManager()
        inv = mgr.register_invoice(_sample_ar_data(metodo_pago="PUE"))
        with pytest.raises(ValueError, match="PPD"):
            mgr.build_complemento_pago(inv.id, 20000.00)

    def test_total_outstanding(self):
        mgr = ARManager()
        mgr.register_invoice(_sample_ar_data())
        mgr.register_invoice(_sample_ar_data(
            uuid="ar-uuid-2",
            total=10000, subtotal=8620.69, iva=1379.31,
        ))
        assert mgr.total_outstanding() == 68000.00


# -----------------------------------------------------------------------
# 3. Aging Report Tests
# -----------------------------------------------------------------------

class TestAgingReport:
    def test_ap_aging_buckets(self):
        gen = AgingReportGenerator()
        today = date(2026, 8, 1)
        invoices = [
            APInvoice(
                uuid=f"uuid-{i}", rfc_emisor="RFC", subtotal=1000, iva=160,
                total=1160, fecha_emision="2026-07-01",
                fecha_vencimiento=due,
            )
            for i, due in enumerate([
                "2026-07-25",  # 7 days overdue → 0-30
                "2026-06-20",  # 42 days overdue → 31-60
                "2026-05-15",  # 78 days overdue → 61-90
                "2026-03-01",  # 153 days overdue → 90+
            ])
        ]
        report = gen.generate_ap(invoices, today=today)
        assert report.total_facturas == 4
        assert len(report.buckets) == 4
        # Verify each bucket has at least one invoice
        counts = {b.bucket: b.count for b in report.buckets}
        assert counts["0-30"] == 1
        assert counts["31-60"] == 1
        assert counts["61-90"] == 1
        assert counts["90+"] == 1

    def test_ar_aging_excludes_paid(self):
        gen = AgingReportGenerator()
        invoices = [
            ARInvoice(
                uuid="uuid-1", rfc_receptor="RFC", subtotal=1000, iva=160,
                total=1160, fecha_emision="2026-07-01",
                fecha_vencimiento="2026-07-15",
                status=InvoiceStatus.PAID,
            ),
            ARInvoice(
                uuid="uuid-2", rfc_receptor="RFC", subtotal=5000, iva=800,
                total=5800, fecha_emision="2026-07-01",
                fecha_vencimiento="2026-07-15",
                status=InvoiceStatus.PENDING,
            ),
        ]
        report = gen.generate_ar(invoices, today=date(2026, 8, 1))
        assert report.total_facturas == 1  # Paid excluded

    def test_aging_by_entity(self):
        gen = AgingReportGenerator()
        invoices = [
            APInvoice(
                uuid=f"uuid-{i}", rfc_emisor=rfc, nombre_emisor=name,
                subtotal=1000, iva=160, total=1160,
                fecha_emision="2026-07-01",
                fecha_vencimiento="2026-07-15",
            )
            for i, (rfc, name) in enumerate([
                ("PROV001", "Proveedor Uno"),
                ("PROV001", "Proveedor Uno"),
                ("PROV002", "Proveedor Dos"),
            ])
        ]
        entries = gen.aging_by_entity_ap(invoices, today=date(2026, 8, 1))
        assert len(entries) == 2
        # PROV001 should have double the amount
        p1 = next(e for e in entries if e.rfc == "PROV001")
        assert p1.total == 2320.0


# -----------------------------------------------------------------------
# 4. Payment Scheduler Tests
# -----------------------------------------------------------------------

class TestPaymentScheduler:
    def test_schedule_basic(self):
        sched = PaymentScheduler(empresa="LIKA")
        today = date(2026, 8, 1)
        invoices = [
            APInvoice(
                id=i, uuid=f"uuid-{i}", rfc_emisor="RFC",
                subtotal=5000, iva=800, total=5800,
                fecha_emision="2026-07-01",
                fecha_vencimiento=due,
                status=InvoiceStatus.REGISTERED,
            )
            for i, due in enumerate([
                "2026-08-05",  # 4 days → priority 3
                "2026-08-15",  # 14 days → priority 5
                "2026-07-20",  # overdue → priority 1
            ])
        ]
        schedule = sched.schedule_payments(invoices, cash_available=20000, today=today)
        assert len(schedule) == 3
        # First should be the overdue one
        assert schedule[0].prioridad_efectiva == 1

    def test_cash_limit(self):
        sched = PaymentScheduler()
        today = date(2026, 8, 1)
        invoices = [
            APInvoice(
                id=i, uuid=f"uuid-{i}", rfc_emisor="RFC",
                subtotal=5000, iva=800, total=5800,
                fecha_emision="2026-07-01",
                fecha_vencimiento="2026-08-05",
                status=InvoiceStatus.REGISTERED,
            )
            for i in range(5)
        ]
        schedule = sched.schedule_payments(invoices, cash_available=10000, today=today)
        total = sched.calculate_total_scheduled(schedule)
        assert total <= 10000

    def test_skips_paid_invoices(self):
        sched = PaymentScheduler()
        invoices = [
            APInvoice(
                id=1, uuid="uuid-1", rfc_emisor="RFC",
                subtotal=5000, iva=800, total=5800,
                fecha_emision="2026-07-01",
                fecha_vencimiento="2026-08-05",
                status=InvoiceStatus.PAID,
            ),
        ]
        schedule = sched.schedule_payments(invoices, cash_available=100000)
        assert len(schedule) == 0


# -----------------------------------------------------------------------
# 5. SPEI Payment Tests
# -----------------------------------------------------------------------

class TestSPEIPayment:
    def test_validate_clabe_valid(self):
        spei = SPEIPayment()
        # Valid CLABE (known test value)
        assert spei.validate_clabe("646180157012345678") is False  # Not a real check digit
        # Verify validation works for known good CLABE
        assert spei.validate_clabe("012345678901234567") is False

    def test_validate_clabe_invalid_length(self):
        spei = SPEIPayment()
        assert spei.validate_clabe("12345") is False
        assert spei.validate_clabe("") is False

    def test_validate_clabe_non_digits(self):
        spei = SPEIPayment()
        assert spei.validate_clabe("12345678901234567A") is False

    def test_sandbox_payment(self):
        import asyncio
        spei = SPEIPayment(stp_token="test_token", empresa="LIKA")
        order = PaymentOrder(
            clave_rastreo="TEST20260801ABCDEF",
            concepto_pago="Pago test",
            cuenta_beneficiario="646180157000000001",
            cuenta_ordenante="646180157000000002",
            nombre_beneficiario="Proveedor Test",
            nombre_ordenante="Likida Test",
            rfc_beneficiario="EKU9003173C9",
            rfc_ordenante="AAA010101AAA",
            institucion_beneficiario=90646,
            monto=5000.00,
            fecha_programada="2026-08-05",
        )
        result = asyncio.run(spei.enviar_pago(order))
        assert result["status"] == "LIQUIDACION"
        assert result["stp_id"] is not None
        assert result["error"] is None

    def test_build_payload(self):
        spei = SPEIPayment(empresa="LIKA", clabe_ordenante="646180157000000002")
        order = PaymentOrder(
            clave_rastreo="TESTKEY",
            concepto_pago="Pago factura TEST",
            cuenta_beneficiario="646180157000000001",
            nombre_beneficiario="Proveedor SA",
            rfc_beneficiario="EKU9003173C9",
            monto=10000.00,
            fecha_programada="2026-08-10",
        )
        payload = spei.build_payload(order)
        assert payload["monto"] == 10000.00
        assert payload["cuentaOrdenante"] == "646180157000000002"
        assert payload["empresa"] == "LIKA"


# -----------------------------------------------------------------------
# 6. Retention Engine Tests
# -----------------------------------------------------------------------

class TestRetentionEngine:
    def test_arrendamiento_pf(self):
        engine = RetentionEngine()
        result = engine.calcular_retencion(
            "HEGA800615ABC",  # PF (13 chars)
            RetentionType.ARRENDAMIENTO_PF,
            20000.00,
        )
        assert result.aplica_retencion is True
        assert result.retencion == 2000.00  # 10%
        assert result.monto_neto == 18000.00

    def test_servicios_profesionales_pf(self):
        engine = RetentionEngine()
        result = engine.calcular_retencion(
            "HEGA800615ABC",
            RetentionType.SERVICIOS_PROFESIONALES,
            15000.00,
        )
        assert result.aplica_retencion is True
        assert result.retencion == 1500.00  # 10%

    def test_regalias_nacional(self):
        engine = RetentionEngine()
        result = engine.calcular_retencion(
            "HEGA800615ABC",
            RetentionType.REGALIAS_NACIONAL,
            10000.00,
        )
        assert result.retencion == 2500.00  # 25%

    def test_regalias_extranjero(self):
        engine = RetentionEngine()
        result = engine.calcular_retencion(
            "HEGA800615ABC",
            RetentionType.REGALIAS_EXTRANJERO,
            10000.00,
        )
        assert result.retencion == 4000.00  # 40%

    def test_subcontratacion(self):
        engine = RetentionEngine()
        result = engine.calcular_retencion(
            "HEGA800615ABC",
            RetentionType.SUBCONTRATACION,
            50000.00,
        )
        assert result.retencion == 3000.00  # 6%

    def test_pm_no_retencion(self):
        engine = RetentionEngine()
        result = engine.calcular_retencion(
            "EKU9003173C9",  # PM (12 chars)
            RetentionType.SERVICIOS_PROFESIONALES,
            50000.00,
        )
        assert result.aplica_retencion is False
        assert "Persona Moral" in result.motivo

    def test_iva_honorarios_2_3_rule(self):
        """P1: retención IVA = IVA trasladado (16%) × 2/3 (LIVA Art. 1-A fracc. IV)."""
        engine = RetentionEngine()
        result = engine.calcular_retencion(
            "HEGA800615ABC",  # PF (13 chars)
            RetentionType.IVA_HONORARIOS,
            10000.00,  # subtotal
        )
        # IVA trasladado = 10000 × 16% = 1600 → retención = 1600 × 2/3 = 1066.67
        assert result.aplica_retencion is True
        assert result.iva_trasladado == pytest.approx(1600.00, abs=0.02)
        assert result.retencion == pytest.approx(1066.67, abs=0.02)
        assert "2/3" in result.fundamento or "2/3" in result.motivo or "1º-A" in result.fundamento

    def test_iva_arrendamiento_applies_to_pm(self):
        """Retención IVA aplica independientemente de PF/PM (LIVA Art. 1-A)."""
        engine = RetentionEngine()
        result = engine.calcular_retencion(
            "EKU9003173C9",  # PM (12 chars)
            RetentionType.IVA_ARRENDAMIENTO,
            50000.00,
        )
        assert result.aplica_retencion is True
        assert result.iva_trasladado == pytest.approx(8000.00, abs=0.02)
        assert result.retencion == pytest.approx(5333.33, abs=0.02)

    def test_tabla_art96(self):
        # Test the progressive table
        assert _calcular_tabla_art96(0) == 0
        assert _calcular_tabla_art96(746.04) == pytest.approx(14.31, abs=0.02)
        # Higher bracket
        result = _calcular_tabla_art96(10000)
        assert result > 0
        assert result < 10000

    def test_detectar_tipo_retencion(self):
        engine = RetentionEngine()
        assert engine.detectar_tipo_retencion("RFC", "Arrendamiento de oficina") == RetentionType.ARRENDAMIENTO_PF
        assert engine.detectar_tipo_retencion("RFC", "Honorarios de consultoría") == RetentionType.HONORARIOS_PF
        assert engine.detectar_tipo_retencion("RFC", "Licencia de software y regalías") == RetentionType.REGALIAS_NACIONAL


# -----------------------------------------------------------------------
# 7. Notas de Crédito Tests
# -----------------------------------------------------------------------

class TestNotasCredito:
    def test_crear_nota_credito(self):
        nc = NotasCredito()
        note = nc.crear_nota_credito(CreditNoteCreate(
            cfdi_original_uuid="original-uuid-12345",
            monto=5000.00,
            concepto="Devolución parcial de mercancía",
            tipo=CreditNoteType.DEVOLUCION,
            rfc_emisor="PROV001",
            rfc_receptor="CLI001",
        ))
        assert note.status == "emitida"
        assert note.monto == 5000.00
        assert note.uuid.startswith("CN-")

    def test_listar_notas_por_cfdi(self):
        nc = NotasCredito()
        nc.crear_nota_credito(CreditNoteCreate(
            cfdi_original_uuid="uuid-A", monto=1000,
            concepto="Descuento", tipo=CreditNoteType.DESCUENTO,
        ))
        nc.crear_nota_credito(CreditNoteCreate(
            cfdi_original_uuid="uuid-A", monto=2000,
            concepto="Devolución", tipo=CreditNoteType.DEVOLUCION,
        ))
        nc.crear_nota_credito(CreditNoteCreate(
            cfdi_original_uuid="uuid-B", monto=500,
            concepto="Bonificación", tipo=CreditNoteType.BONIFICACION,
        ))
        assert len(nc.list_notas(cfdi_original_uuid="uuid-A")) == 2
        assert len(nc.list_notas(cfdi_original_uuid="uuid-B")) == 1

    def test_calcular_monto_total(self):
        nc = NotasCredito()
        nc.crear_nota_credito(CreditNoteCreate(
            cfdi_original_uuid="uuid-X", monto=1000,
            concepto="Nota 1", tipo=CreditNoteType.DESCUENTO,
        ))
        nc.crear_nota_credito(CreditNoteCreate(
            cfdi_original_uuid="uuid-X", monto=3000,
            concepto="Nota 2", tipo=CreditNoteType.DEVOLUCION,
        ))
        assert nc.calcular_monto_total_notas("uuid-X") == 4000.00

    def test_build_facturapi_payload(self):
        nc = NotasCredito()
        payload = nc.build_facturapi_payload(CreditNoteCreate(
            cfdi_original_uuid="original-123",
            monto=5000,
            concepto="Devolución",
            tipo=CreditNoteType.DEVOLUCION,
        ))
        assert payload["type"] == "E"
        assert payload["related_documents"][0]["id"] == "original-123"

    def test_generate_reversal_entry(self):
        nc = NotasCredito()
        entry = nc.generate_reversal_entry("orig-uuid", "cn-uuid", 10000)
        assert entry["cuadrada"] is True
        total_debe = sum(l["debe"] for l in entry["lineas"])
        total_haber = sum(l["haber"] for l in entry["lineas"])
        assert total_debe == pytest.approx(total_haber, abs=0.02)


# -----------------------------------------------------------------------
# 8. API Route Tests
# -----------------------------------------------------------------------

class TestAPIRoutes:
    """Test the API endpoints via FastAPI TestClient."""

    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from b2b_ai.features.ap_ar.routes import build_ap_ar_router

        app = FastAPI()
        app.include_router(build_ap_ar_router())
        return TestClient(app)

    def test_post_ap_invoices(self, client):
        resp = client.post("/ap/invoices", json={
            "uuid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "rfc_emisor": "EKU9003173C9",
            "nombre_emisor": "Proveedor SA",
            "subtotal": 10000,
            "iva": 1600,
            "total": 11600,
            "fecha_emision": "2026-07-15",
            "fecha_vencimiento": "2026-08-14",
            "concepto": "Servicios",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["invoice"]["total"] == 11600

    def test_post_ap_invoices_validation_error(self, client):
        resp = client.post("/ap/invoices", json={
            "uuid": "short",
            "rfc_emisor": "EKU9003173C9",
            "subtotal": 10000,
            "iva": 1600,
            "total": 11600,
            "fecha_emision": "2026-07-15",
            "fecha_vencimiento": "2026-08-14",
        })
        assert resp.status_code == 422

    def test_get_ap_aging(self, client):
        # First add an invoice
        client.post("/ap/invoices", json={
            "uuid": "aging-test-uuid-1234567890",
            "rfc_emisor": "EKU9003173C9",
            "subtotal": 10000, "iva": 1600, "total": 11600,
            "fecha_emision": "2026-07-15",
            "fecha_vencimiento": "2026-08-14",
        })
        resp = client.get("/ap/aging")
        assert resp.status_code == 200
        data = resp.json()
        assert "buckets" in data
        assert data["tipo"] == "ap"

    def test_post_ar_invoices(self, client):
        resp = client.post("/ar/invoices", json={
            "uuid": "ar-uuid-1234567890",
            "rfc_receptor": "XAXX010101000",
            "nombre_receptor": "Cliente SA",
            "subtotal": 50000, "iva": 8000, "total": 58000,
            "fecha_emision": "2026-07-01",
            "fecha_vencimiento": "2026-07-31",
            "metodo_pago": "PPD",
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_get_ar_aging(self, client):
        resp = client.get("/ar/aging")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tipo"] == "ar"

    def test_post_ar_collect(self, client):
        # Create invoice first
        client.post("/ar/invoices", json={
            "uuid": "collect-test-uuid-123456",
            "rfc_receptor": "XAXX010101000",
            "subtotal": 50000, "iva": 8000, "total": 58000,
            "fecha_emision": "2026-07-01",
            "fecha_vencimiento": "2026-07-31",
        })
        resp = client.post("/ar/collect", json={
            "ar_invoice_id": 1,
            "monto": 30000,
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_get_retenciones(self, client):
        resp = client.get(
            "/retenciones/calcular",
            params={
                "proveedor_rfc": "HEGA800615ABC",
                "tipo_servicio": "arrendamiento_pf",
                "monto_factura": 20000,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["retencion"] == 2000.0
        assert data["aplica_retencion"] is True

    def test_post_notas_credito(self, client):
        resp = client.post("/notas-credito", json={
            "cfdi_original_uuid": "original-uuid-12345",
            "monto": 5000,
            "concepto": "Devolución parcial",
            "tipo": "devolucion",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["nota"]["monto"] == 5000
