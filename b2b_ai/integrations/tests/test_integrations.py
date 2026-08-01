# -*- coding: utf-8 -*-
"""
test_integrations.py — Tests comprehensivos para el módulo de integraciones.

Cubre: SAT (Ecodex, Finkok, Portal), ERP (CONTPAQi, Aspel, QuickBooks, Xero),
Bancos (BBVA, Banorte, Santander, OFX, CSV), Nómina, Pagos (Stripe, Conekta,
PayPal), Comunicación (SendGrid, Twilio, WhatsApp), Almacenamiento (Drive,
OneDrive, S3), Firmas (DocuSign, FIEL), CRM (HubSpot, Pipedrive),
Monitoreo (Sentry, Console), e IntegrationHub.
"""
from __future__ import annotations

import pytest
from datetime import datetime
from typing import Any, Dict
# ---------------------------------------------------------------------------
# SAT Integration Tests
# ---------------------------------------------------------------------------

class TestSATAdapter:
    """Tests para adaptadores SAT."""

    def test_ecodex_connect_and_timbrar(self):
        from b2b_ai.integrations.sat import EcodexAdapter, CFDIRequest, CFDIStatus

        adapter = EcodexAdapter()
        assert not adapter.is_connected

        result = adapter.connect()
        assert result is True
        assert adapter.is_connected

        request = CFDIRequest(
            rfc_emisor="XAXX010101000",
            rfc_receptor="AAA010101AAA",
            subtotal=10000.00,
            iva=1600.00,
            total=11600.00,
        )

        response = adapter.timbrar_cfdi(request)
        assert response.exito is True
        assert response.uuid != ""
        assert response.fecha_timbrado != ""

    def test_ecodex_cancelar_cfdi(self):
        from b2b_ai.integrations.sat import EcodexAdapter, CFDIRequest, CancelacionRequest, TipoCancelacion

        adapter = EcodexAdapter()
        adapter.connect()

        # First timbre
        request = CFDIRequest(
            rfc_emisor="XAXX010101000",
            rfc_receptor="AAA010101AAA",
            subtotal=5000.00,
            total=5800.00,
        )
        timbrado = adapter.timbrar_cfdi(request)

        # Then cancel
        cancel = CancelacionRequest(
            uuid=timbrado.uuid,
            motivo=TipoCancelacion.FACTURA_CANCELACION,
            rfc="XAXX010101000",
        )
        result = adapter.cancelar_cfdi(cancel)
        assert result["exito"] is True
        assert result["uuid"] == timbrado.uuid

    def test_ecodex_consultar_cfdi(self):
        from b2b_ai.integrations.sat import EcodexAdapter

        adapter = EcodexAdapter()
        adapter.connect()

        cfdi = adapter.consultar_cfdi("test-uuid-123")
        assert cfdi.uuid == "test-uuid-123"

    def test_ecodex_consultar_rfc(self):
        from b2b_ai.integrations.sat import EcodexAdapter

        adapter = EcodexAdapter()
        adapter.connect()

        rfc = adapter.consultar_rfc("AAA010101AAA")
        assert rfc.rfc == "AAA010101AAA"
        assert rfc.estatus == "activo"

    def test_ecodex_contabilidad_electronica(self):
        from b2b_ai.integrations.sat import EcodexAdapter, ContabilidadElectronica

        adapter = EcodexAdapter()
        adapter.connect()

        datos = ContabilidadElectronica(
            ejercicio=2026,
            mes=1,
            rfc="AAA010101AAA",
            balanza={"cuentas": []},
            catalogo={"cuentas": []},
        )
        result = adapter.contabilidad_electronica(datos)
        assert result["exito"] is True

    def test_ecodex_not_connected_raises(self):
        from b2b_ai.integrations.sat import EcodexAdapter, CFDIRequest, SATAdapterError

        adapter = EcodexAdapter()
        request = CFDIRequest(
            rfc_emisor="XAXX010101000",
            rfc_receptor="AAA010101AAA",
            subtotal=1000.00,
            total=1160.00,
        )

        with pytest.raises(SATAdapterError, match="no está conectado"):
            adapter.timbrar_cfdi(request)

    def test_finkok_connect_and_timbrar(self):
        from b2b_ai.integrations.sat import FinkokAdapter, CFDIRequest

        adapter = FinkokAdapter()
        adapter.connect()

        request = CFDIRequest(
            rfc_emisor="XAXX010101000",
            rfc_receptor="BBB020202BBB",
            subtotal=8000.00,
            iva=1280.00,
            total=9280.00,
        )

        response = adapter.timbrar_cfdi(request)
        assert response.exito is True
        assert response.uuid != ""

    def test_finkok_cancelar(self):
        from b2b_ai.integrations.sat import FinkokAdapter, CFDIRequest, CancelacionRequest, TipoCancelacion

        adapter = FinkokAdapter()
        adapter.connect()

        request = CFDIRequest(
            rfc_emisor="XAXX010101000",
            rfc_receptor="BBB020202BBB",
            subtotal=3000.00,
            total=3480.00,
        )
        timbrado = adapter.timbrar_cfdi(request)

        cancel = CancelacionRequest(
            uuid=timbrado.uuid,
            motivo=TipoCancelacion.FACTURA_ERRORES,
            rfc="XAXX010101000",
        )
        result = adapter.cancelar_cfdi(cancel)
        assert result["exito"] is True

    def test_sat_portal_no_timbrar(self):
        from b2b_ai.integrations.sat import SATPortalAdapter, CFDIRequest, SATAdapterError

        adapter = SATPortalAdapter()
        adapter.connect()

        request = CFDIRequest(
            rfc_emisor="XAXX010101000",
            rfc_receptor="AAA010101AAA",
            subtotal=1000.00,
            total=1160.00,
        )

        with pytest.raises(SATAdapterError, match="no permite timbrar"):
            adapter.timbrar_cfdi(request)

    def test_sat_portal_consultar_rfc(self):
        from b2b_ai.integrations.sat import SATPortalAdapter

        adapter = SATPortalAdapter()
        adapter.connect()

        rfc = adapter.consultar_rfc("AAA010101AAA")
        assert rfc.rfc == "AAA010101AAA"
        assert rfc.estatus == "activo"

    def test_sat_portal_no_contabilidad(self):
        from b2b_ai.integrations.sat import SATPortalAdapter, ContabilidadElectronica, SATAdapterError

        adapter = SATPortalAdapter()
        adapter.connect()

        datos = ContabilidadElectronica(ejercicio=2026, mes=1, rfc="AAA010101AAA")
        with pytest.raises(SATAdapterError, match="no acepta contabilidad"):
            adapter.contabilidad_electronica(datos)

    def test_sat_test_connection(self):
        from b2b_ai.integrations.sat import EcodexAdapter

        adapter = EcodexAdapter()
        # Before connect
        result = adapter.test_connection()
        assert result["status"] == "error"

        # After connect
        adapter.connect()
        result = adapter.test_connection()
        assert result["status"] == "connected"


# ---------------------------------------------------------------------------
# ERP Integration Tests
# ---------------------------------------------------------------------------

class TestERPAdapter:
    """Tests para adaptadores ERP."""

    def test_contpaqi_web_connect(self):
        from b2b_ai.integrations.erp import CONTPAQiWebAdapter

        adapter = CONTPAQiWebAdapter()
        assert not adapter.is_connected

        result = adapter.connect()
        assert result is True
        assert adapter.is_connected

    def test_contpaqi_web_get_invoices(self):
        from b2b_ai.integrations.erp import CONTPAQiWebAdapter

        adapter = CONTPAQiWebAdapter()
        adapter.connect()

        invoices = adapter.get_invoices()
        assert len(invoices) > 0
        assert invoices[0].monto > 0

    def test_contpaqi_web_get_polizas(self):
        from b2b_ai.integrations.erp import CONTPAQiWebAdapter

        adapter = CONTPAQiWebAdapter()
        adapter.connect()

        polizas = adapter.get_polizas()
        assert len(polizas) > 0
        assert polizas[0].esta_cuadrada()

    def test_contpaqi_web_upload_poliza_balanced(self):
        from b2b_ai.integrations.erp import CONTPAQiWebAdapter, Poliza, CuentaPoliza

        adapter = CONTPAQiWebAdapter()
        adapter.connect()

        poliza = Poliza(
            id="TEST-001",
            fecha="2026-01-15",
            concepto="Test póliza",
            cuentas=[
                CuentaPoliza(cuenta="1101", debe=5000, haber=0),
                CuentaPoliza(cuenta="4101", debe=0, haber=5000),
            ],
        )

        result = adapter.upload_poliza(poliza)
        assert result["exito"] is True

    def test_contpaqi_web_upload_poliza_unbalanced(self):
        from b2b_ai.integrations.erp import CONTPAQiWebAdapter, Poliza, CuentaPoliza

        adapter = CONTPAQiWebAdapter()
        adapter.connect()

        poliza = Poliza(
            id="TEST-002",
            fecha="2026-01-15",
            concepto="Test póliza descuadrada",
            cuentas=[
                CuentaPoliza(cuenta="1101", debe=5000, haber=0),
                CuentaPoliza(cuenta="4101", debe=0, haber=3000),
            ],
        )

        result = adapter.upload_poliza(poliza)
        assert result["exito"] is False

    def test_contpaqi_web_chart_of_accounts(self):
        from b2b_ai.integrations.erp import CONTPAQiWebAdapter

        adapter = CONTPAQiWebAdapter()
        adapter.connect()

        coa = adapter.get_chart_of_accounts()
        assert len(coa.cuentas) > 0

    def test_contpaqi_web_balanza(self):
        from b2b_ai.integrations.erp import CONTPAQiWebAdapter

        adapter = CONTPAQiWebAdapter()
        adapter.connect()

        balanza = adapter.get_balanza(2026, 1)
        assert balanza.ejercicio == 2026
        assert balanza.mes == 1
        assert balanza.total_deudor > 0

    def test_contpaqi_desktop_connect(self):
        from b2b_ai.integrations.erp import CONTPAQiDesktopAdapter

        adapter = CONTPAQiDesktopAdapter()
        result = adapter.connect()
        assert result is True

    def test_aspel_cloud_connect(self):
        from b2b_ai.integrations.erp import AspelCloudAdapter

        adapter = AspelCloudAdapter()
        result = adapter.connect()
        assert result is True

        invoices = adapter.get_invoices()
        assert len(invoices) > 0

    def test_quickbooks_connect(self):
        from b2b_ai.integrations.erp import QuickBooksOnlineAdapter

        adapter = QuickBooksOnlineAdapter()
        result = adapter.connect()
        assert result is True

        invoices = adapter.get_invoices()
        assert len(invoices) > 0

    def test_xero_connect(self):
        from b2b_ai.integrations.erp import XeroAdapter

        adapter = XeroAdapter()
        result = adapter.connect()
        assert result is True

        invoices = adapter.get_invoices()
        assert len(invoices) > 0

    def test_erp_not_connected_raises(self):
        from b2b_ai.integrations.erp import CONTPAQiWebAdapter, ERPAdapterError

        adapter = CONTPAQiWebAdapter()
        with pytest.raises(ERPAdapterError, match="no está conectado"):
            adapter.get_invoices()

    def test_erp_poliza_cuadrada(self):
        from b2b_ai.integrations.erp import Poliza, CuentaPoliza

        # Cuadrada
        p1 = Poliza(
            cuentas=[
                CuentaPoliza(cuenta="1", debe=100, haber=0),
                CuentaPoliza(cuenta="2", debe=0, haber=100),
            ]
        )
        assert p1.esta_cuadrada() is True

        # Descuadrada
        p2 = Poliza(
            cuentas=[
                CuentaPoliza(cuenta="1", debe=100, haber=0),
                CuentaPoliza(cuenta="2", debe=0, haber=50),
            ]
        )
        assert p2.esta_cuadrada() is False


# ---------------------------------------------------------------------------
# Bank Integration Tests
# ---------------------------------------------------------------------------

class TestBankAdapter:
    """Tests para adaptadores bancarios."""

    def test_bbva_connect(self):
        from b2b_ai.integrations.bancos import BBVAAdapter

        adapter = BBVAAdapter()
        result = adapter.connect()
        assert result is True
        assert adapter.is_connected

    def test_bbva_get_statement(self):
        from b2b_ai.integrations.bancos import BBVAAdapter

        adapter = BBVAAdapter()
        adapter.connect()

        statement = adapter.get_statement()
        assert statement.bank.value == "bbva"
        assert len(statement.transactions) > 0
        assert statement.saldo_inicial > 0

    def test_bbva_get_transactions(self):
        from b2b_ai.integrations.bancos import BBVAAdapter

        adapter = BBVAAdapter()
        adapter.connect()

        txs = adapter.get_transactions()
        assert len(txs) > 0

    def test_bbva_download_statement(self):
        from b2b_ai.integrations.bancos import BBVAAdapter, FormatoEstado

        adapter = BBVAAdapter()
        adapter.connect()

        content = adapter.download_statement(FormatoEstado.OFX)
        assert len(content) > 0

    def test_banorte_connect(self):
        from b2b_ai.integrations.bancos import BanorteAdapter

        adapter = BanorteAdapter()
        adapter.connect()

        statement = adapter.get_statement()
        assert statement.bank.value == "banorte"
        assert len(statement.transactions) > 0

    def test_santander_connect(self):
        from b2b_ai.integrations.bancos import SantanderAdapter

        adapter = SantanderAdapter()
        adapter.connect()

        statement = adapter.get_statement()
        assert statement.bank.value == "santander"
        assert len(statement.transactions) > 0

    def test_bank_statement_calcular_totales(self):
        from b2b_ai.integrations.bancos import BankStatement, BankTransaction, Banco, TipoTransaccion

        statement = BankStatement(
            saldo_inicial=100000.0,
            transactions=[
                BankTransaction(
                    fecha="2026-01-01", monto=50000.0,
                    descripcion="Deposito", tipo=TipoTransaccion.DEPOSITO,
                ),
                BankTransaction(
                    fecha="2026-01-02", monto=-30000.0,
                    descripcion="Retiro", tipo=TipoTransaccion.RETIRO,
                ),
            ],
        )
        statement.calcular_totales()

        assert statement.total_abonos == 50000.0
        assert statement.total_cargos == -30000.0
        assert statement.saldo_final == 120000.0
        assert statement.num_transacciones == 2

    def test_bank_not_connected_raises(self):
        from b2b_ai.integrations.bancos import BBVAAdapter, BankAdapterError

        adapter = BBVAAdapter()
        with pytest.raises(BankAdapterError, match="no está conectado"):
            adapter.get_statement()

    def test_ofx_parser_parse_content(self):
        from b2b_ai.integrations.bancos import OFXParser

        parser = OFXParser()
        parser.connect()

        ofx_content = """OFXHEADER:100
DATA:OFXSGML
VERSION:102
<OFX>
<BANKTRANLIST>
<STMTTRN>
<TRNTYPE>OTHER
<DTPOSTED>20260115
<TRNAMT>-5000.00
<FITID>REF001
<NAME>TRANSFERENCIA
</STMTTRN>
<STMTTRN>
<TRNTYPE>OTHER
<DTPOSTED>20260120
<TRNAMT>10000.00
<FITID>REF002
<NAME>DEPOSITO
</STMTTRN>
</BANKTRANLIST>
<BALANCE>
<BALAMT>95000.00
</BALANCE>
</OFX>"""

        statement = parser.parse_ofx_content(ofx_content)
        assert len(statement.transactions) == 2
        assert statement.saldo_inicial == 95000.0
        assert statement.transactions[0].monto == -5000.0
        assert statement.transactions[1].monto == 10000.0

    def test_csv_parser_parse_content(self):
        from b2b_ai.integrations.bancos import CSVParser

        parser = CSVParser()
        parser.connect()

        csv_content = """Fecha,Monto,Descripcion,Referencia
2026-01-01,50000.00,DEPOSITO CLIENTE,REF-001
2026-01-02,-3000.00,COMISION MENSUAL,REF-002
2026-01-05,15000.00,TRANSFERENCIA SPEI,REF-003"""

        statement = parser.parse_csv_content(csv_content)
        assert len(statement.transactions) == 3
        assert statement.total_abonos == 65000.0
        assert statement.total_cargos == -3000.0


# ---------------------------------------------------------------------------
# Nómina Integration Tests
# ---------------------------------------------------------------------------

class TestNominaAdapter:
    """Tests para integración de nómina."""

    def test_nomina_service_calcular_isr(self):
        from b2b_ai.integrations.nomina import NominaService

        service = NominaService()
        # ISR should be 0 for low salary
        isr = service.calcular_isr(5000)
        assert isr == 0.0
        # ISR should be positive for high salary
        isr = service.calcular_isr(100000)
        assert isr > 0

    def test_nomina_service_calcular_imss(self):
        from b2b_ai.integrations.nomina import NominaService

        service = NominaService()
        imss = service.calcular_imss(500)
        assert imss.total_obrero > 0
        assert imss.total_patron > 0
        assert imss.total_patron > imss.total_obrero

    def test_nomina_service_calcular_infonavit(self):
        from b2b_ai.integrations.nomina import NominaService

        service = NominaService()
        infonavit = service.calcular_infonavit(500)
        assert infonavit == 750.0

    def test_nomina_service_calcular_impuestos(self):
        from b2b_ai.integrations.nomina import NominaService

        service = NominaService()
        calculo = service.calcular_impuestos_empleado(
            salario_bruto=30000,
            salario_diario=1000,
        )
        assert calculo.isr >= 0
        assert calculo.imss_obrero > 0
        assert calculo.imss_patronal > 0
        assert calculo.infonavit > 0
        assert calculo.salario_neto < 30000
        assert calculo.salario_neto > 0

    def test_nomina_service_calcular_nomina(self):
        from b2b_ai.integrations.nomina import NominaService, Empleado

        service = NominaService()
        empleados = [
            Empleado(
                id="EMP-001", nombre="Juan Pérez", rfc="PEPJ800101AAA",
                salario_diario=500, salario_bruto=15000,
            ),
            Empleado(
                id="EMP-002", nombre="María López", rfc="LOPM900202BBB",
                salario_diario=800, salario_bruto=24000,
            ),
        ]
        periodo = {"mes": 1, "anio": 2026, "dias_pagados": 30}
        nomina = service.calcular_nomina(empleados, periodo)

        assert nomina.mes == 1
        assert nomina.anio == 2026
        assert len(nomina.empleados) == 2
        assert nomina.total_percepciones == 39000
        assert nomina.total_neto < 39000
        assert nomina.total_isr >= 0
        assert nomina.total_imss_obrero > 0

    def test_nomina_service_generar_cfdi(self):
        from b2b_ai.integrations.nomina import NominaService

        service = NominaService()
        cfdi = service.generar_cfdi_nomina({
            "emisor": {"rfc": "EMP010101AAA", "nombre": "Empresa Mock"},
            "receptor": {"rfc": "REC020202BBB", "nombre": "Empleado Mock"},
            "period": {"mes": 1, "anio": 2026, "dias_pagados": 30},
            "taxes": {"isr": 2500, "imss_obrero": 500},
            "subtotal": 15000,
            "total": 12000,
        })
        assert cfdi.uuid != ""
        assert cfdi.version == "4.0"
        assert cfdi.serie == "NOM"
        assert cfdi.status == "timbrado"
        assert cfdi.complemento_nomina is not None


# ---------------------------------------------------------------------------
# Payment Integration Tests
# ---------------------------------------------------------------------------

class TestPaymentAdapter:
    """Tests para adaptadores de pagos."""

    def test_stripe_connect(self):
        from b2b_ai.integrations.pagos import StripeAdapter

        adapter = StripeAdapter()
        assert not adapter.is_connected

        result = adapter.connect()
        assert result is True
        assert adapter.is_connected

    def test_stripe_create_payment(self):
        from b2b_ai.integrations.pagos import StripeAdapter, PaymentRequest, Currency, PaymentMethod

        adapter = StripeAdapter()
        adapter.connect()

        request = PaymentRequest(
            amount=15000.00,
            currency=Currency.MXN,
            method=PaymentMethod.CARD,
            description="Pago de servicio mensual",
            customer_id="cus_mock_123",
        )
        payment = adapter.create_payment(request)
        assert payment.id != ""
        assert payment.amount == 15000.00
        assert payment.currency == Currency.MXN
        assert payment.status.value == "succeeded"

    def test_stripe_verify_payment(self):
        from b2b_ai.integrations.pagos import StripeAdapter

        adapter = StripeAdapter()
        adapter.connect()

        payment = adapter.verify_payment("pi_test_123")
        assert payment.id == "pi_test_123"
        assert payment.status.value == "succeeded"

    def test_stripe_refund(self):
        from b2b_ai.integrations.pagos import StripeAdapter, RefundRequest

        adapter = StripeAdapter()
        adapter.connect()

        request = RefundRequest(payment_id="pi_test_123", amount=5000.00, reason="Producto defectuoso")
        refund = adapter.refund(request)
        assert refund.id != ""
        assert refund.payment_id == "pi_test_123"
        assert refund.amount == 5000.00
        assert refund.status == "succeeded"

    def test_stripe_get_transactions(self):
        from b2b_ai.integrations.pagos import StripeAdapter

        adapter = StripeAdapter()
        adapter.connect()

        transactions = adapter.get_transactions()
        assert len(transactions) > 0
        assert transactions[0].amount > 0

    def test_stripe_not_connected_raises(self):
        from b2b_ai.integrations.pagos import StripeAdapter, PaymentRequest, PaymentAdapterError

        adapter = StripeAdapter()
        request = PaymentRequest(amount=1000.00)
        with pytest.raises(PaymentAdapterError, match="no está conectado"):
            adapter.create_payment(request)

    def test_stripe_test_connection(self):
        from b2b_ai.integrations.pagos import StripeAdapter

        adapter = StripeAdapter()
        result = adapter.test_connection()
        assert result["status"] == "error"

        adapter.connect()
        result = adapter.test_connection()
        assert result["status"] == "connected"

    def test_conekta_connect(self):
        from b2b_ai.integrations.pagos import ConektaAdapter

        adapter = ConektaAdapter()
        result = adapter.connect()
        assert result is True

    def test_conekta_create_payment(self):
        from b2b_ai.integrations.pagos import ConektaAdapter, PaymentRequest, PaymentMethod

        adapter = ConektaAdapter()
        adapter.connect()

        request = PaymentRequest(
            amount=3200.00,
            method=PaymentMethod.OXXO,
            description="Pago OXXO",
        )
        payment = adapter.create_payment(request)
        assert payment.id != ""
        assert payment.amount == 3200.00

    def test_conekta_get_transactions(self):
        from b2b_ai.integrations.pagos import ConektaAdapter

        adapter = ConektaAdapter()
        adapter.connect()

        transactions = adapter.get_transactions()
        assert len(transactions) > 0

    def test_paypal_connect(self):
        from b2b_ai.integrations.pagos import PayPalAdapter

        adapter = PayPalAdapter()
        result = adapter.connect()
        assert result is True

    def test_paypal_create_payment(self):
        from b2b_ai.integrations.pagos import PayPalAdapter, PaymentRequest, PaymentMethod

        adapter = PayPalAdapter()
        adapter.connect()

        request = PaymentRequest(
            amount=750.00,
            method=PaymentMethod.PAYPAL,
            description="PayPal payment",
        )
        payment = adapter.create_payment(request)
        assert payment.id != ""
        assert payment.amount == 750.00
        assert payment.method == PaymentMethod.PAYPAL

    def test_paypal_refund(self):
        from b2b_ai.integrations.pagos import PayPalAdapter, RefundRequest

        adapter = PayPalAdapter()
        adapter.connect()

        request = RefundRequest(payment_id="PAYID_TEST123", reason="Customer request")
        refund = adapter.refund(request)
        assert refund.id != ""
        assert refund.payment_id == "PAYID_TEST123"


# ---------------------------------------------------------------------------
# Communication Integration Tests
# ---------------------------------------------------------------------------

class TestCommunicationAdapter:
    """Tests para adaptadores de comunicación."""

    def test_sendgrid_connect(self):
        from b2b_ai.integrations.comunicacion import SendGridAdapter

        adapter = SendGridAdapter()
        result = adapter.connect()
        assert result is True

    def test_sendgrid_send_email(self):
        from b2b_ai.integrations.comunicacion import SendGridAdapter, EmailRequest

        adapter = SendGridAdapter()
        adapter.connect()

        request = EmailRequest(
            to="cliente@empresa.com",
            subject="Factura pendiente",
            body="<h1>Su factura está pendiente</h1>",
        )
        message = adapter.send_email(request)
        assert message.id != ""
        assert message.to == "cliente@empresa.com"
        assert message.subject == "Factura pendiente"
        assert message.channel.value == "email"

    def test_sendgrid_send_notification(self):
        from b2b_ai.integrations.comunicacion import SendGridAdapter, NotificationRequest

        adapter = SendGridAdapter()
        adapter.connect()

        request = NotificationRequest(
            user_id="user_001",
            title="Nuevo documento",
            body="Se ha subido un nuevo documento",
        )
        message = adapter.send_notification(request)
        assert message.id != ""
        assert message.channel.value == "email"

    def test_sendgrid_no_sms(self):
        from b2b_ai.integrations.comunicacion import SendGridAdapter, SMSRequest

        adapter = SendGridAdapter()
        adapter.connect()

        request = SMSRequest(to="+525512345678", message="Test")
        with pytest.raises(NotImplementedError, match="no soporta SMS"):
            adapter.send_sms(request)

    def test_sendgrid_not_connected_raises(self):
        from b2b_ai.integrations.comunicacion import SendGridAdapter, EmailRequest, CommunicationAdapterError

        adapter = SendGridAdapter()
        request = EmailRequest(to="test@test.com", subject="Test", body="Test")
        with pytest.raises(CommunicationAdapterError, match="no está conectado"):
            adapter.send_email(request)

    def test_twilio_connect(self):
        from b2b_ai.integrations.comunicacion import TwilioAdapter

        adapter = TwilioAdapter()
        result = adapter.connect()
        assert result is True

    def test_twilio_send_sms(self):
        from b2b_ai.integrations.comunicacion import TwilioAdapter, SMSRequest

        adapter = TwilioAdapter()
        adapter.connect()

        request = SMSRequest(to="+525512345678", message="Su código es 123456")
        message = adapter.send_sms(request)
        assert message.id != ""
        assert message.to == "+525512345678"
        assert message.body == "Su código es 123456"
        assert message.channel.value == "sms"

    def test_twilio_send_whatsapp(self):
        from b2b_ai.integrations.comunicacion import TwilioAdapter, WhatsAppRequest

        adapter = TwilioAdapter()
        adapter.connect()

        request = WhatsAppRequest(to="+525512345678", message="Hola, su factura está lista")
        message = adapter.send_whatsapp(request)
        assert message.id != ""
        assert message.channel.value == "whatsapp"

    def test_twilio_no_email(self):
        from b2b_ai.integrations.comunicacion import TwilioAdapter, EmailRequest

        adapter = TwilioAdapter()
        adapter.connect()

        request = EmailRequest(to="test@test.com", subject="Test", body="Test")
        with pytest.raises(NotImplementedError, match="no soporta email"):
            adapter.send_email(request)

    def test_whatsapp_business_connect(self):
        from b2b_ai.integrations.comunicacion import WhatsAppBusinessAdapter

        adapter = WhatsAppBusinessAdapter()
        result = adapter.connect()
        assert result is True

    def test_whatsapp_business_send(self):
        from b2b_ai.integrations.comunicacion import WhatsAppBusinessAdapter, WhatsAppRequest

        adapter = WhatsAppBusinessAdapter()
        adapter.connect()

        request = WhatsAppRequest(to="+525512345678", message="Notificación importante")
        message = adapter.send_whatsapp(request)
        assert message.id != ""
        assert message.to == "+525512345678"
        assert message.channel.value == "whatsapp"

    def test_whatsapp_business_send_notification(self):
        from b2b_ai.integrations.comunicacion import WhatsAppBusinessAdapter, NotificationRequest

        adapter = WhatsAppBusinessAdapter()
        adapter.connect()

        request = NotificationRequest(
            user_id="+525512345678",
            title="Alerta",
            body="Vencimiento próximo",
        )
        message = adapter.send_notification(request)
        assert message.id != ""
        assert message.channel.value == "whatsapp"

    def test_whatsapp_business_no_email(self):
        from b2b_ai.integrations.comunicacion import WhatsAppBusinessAdapter, EmailRequest

        adapter = WhatsAppBusinessAdapter()
        adapter.connect()

        request = EmailRequest(to="test@test.com", subject="Test", body="Test")
        with pytest.raises(NotImplementedError, match="no soporta email"):
            adapter.send_email(request)


# ---------------------------------------------------------------------------
# Storage Integration Tests
# ---------------------------------------------------------------------------

class TestStorageAdapter:
    """Tests para adaptadores de almacenamiento."""

    def test_google_drive_connect(self):
        from b2b_ai.integrations.storage import GoogleDriveAdapter

        adapter = GoogleDriveAdapter()
        result = adapter.connect()
        assert result is True

    def test_google_drive_upload(self):
        from b2b_ai.integrations.storage import GoogleDriveAdapter

        adapter = GoogleDriveAdapter()
        adapter.connect()

        result = adapter.upload("/tmp/test.pdf", "/Facturas")
        assert result.success is True
        assert result.file.id != ""
        assert result.file.name == "test.pdf"

    def test_google_drive_download(self):
        from b2b_ai.integrations.storage import GoogleDriveAdapter

        adapter = GoogleDriveAdapter()
        adapter.connect()

        content = adapter.download("gd_test_001")
        assert len(content) > 0

    def test_google_drive_list_files(self):
        from b2b_ai.integrations.storage import GoogleDriveAdapter

        adapter = GoogleDriveAdapter()
        adapter.connect()

        files = adapter.list_files("/Documentos")
        assert len(files) > 0
        assert files[0].id != ""

    def test_google_drive_delete(self):
        from b2b_ai.integrations.storage import GoogleDriveAdapter

        adapter = GoogleDriveAdapter()
        adapter.connect()

        result = adapter.delete("gd_test_001")
        assert result is True

    def test_google_drive_share(self):
        from b2b_ai.integrations.storage import GoogleDriveAdapter, SharePermission, PermissionRole

        adapter = GoogleDriveAdapter()
        adapter.connect()

        permissions = [SharePermission(user_id="user_001", role=PermissionRole.READ)]
        result = adapter.share("gd_test_001", permissions)
        assert result.success is True
        assert result.share_url is not None

    def test_google_drive_not_connected_raises(self):
        from b2b_ai.integrations.storage import GoogleDriveAdapter, StorageAdapterError

        adapter = GoogleDriveAdapter()
        with pytest.raises(StorageAdapterError, match="no está conectado"):
            adapter.upload("/tmp/test.pdf")

    def test_onedrive_connect(self):
        from b2b_ai.integrations.storage import OneDriveAdapter

        adapter = OneDriveAdapter()
        result = adapter.connect()
        assert result is True

    def test_onedrive_upload(self):
        from b2b_ai.integrations.storage import OneDriveAdapter

        adapter = OneDriveAdapter()
        adapter.connect()

        result = adapter.upload("/tmp/reporte.xlsx", "/Reportes")
        assert result.success is True
        assert result.file.name == "reporte.xlsx"

    def test_onedrive_list_files(self):
        from b2b_ai.integrations.storage import OneDriveAdapter

        adapter = OneDriveAdapter()
        adapter.connect()

        files = adapter.list_files("/Reportes")
        assert len(files) > 0

    def test_s3_connect(self):
        from b2b_ai.integrations.storage import S3Adapter

        adapter = S3Adapter()
        result = adapter.connect()
        assert result is True

    def test_s3_upload(self):
        from b2b_ai.integrations.storage import S3Adapter

        adapter = S3Adapter()
        adapter.connect()

        result = adapter.upload("/tmp/backup.zip", "/backups")
        assert result.success is True
        assert "s3://" in result.file.path

    def test_s3_download(self):
        from b2b_ai.integrations.storage import S3Adapter

        adapter = S3Adapter()
        adapter.connect()

        content = adapter.download("s3_obj_0001")
        assert len(content) > 0

    def test_s3_list_files(self):
        from b2b_ai.integrations.storage import S3Adapter

        adapter = S3Adapter()
        adapter.connect()

        files = adapter.list_files("/backups")
        assert len(files) > 0
        assert files[0].mime_type == "application/zip"

    def test_s3_share(self):
        from b2b_ai.integrations.storage import S3Adapter, SharePermission, PermissionRole

        adapter = S3Adapter()
        adapter.connect()

        permissions = [SharePermission(user_id="user_002", role=PermissionRole.READ)]
        result = adapter.share("s3_obj_0001", permissions)
        assert result.success is True


# ---------------------------------------------------------------------------
# Signatures Integration Tests
# ---------------------------------------------------------------------------

class TestSignatureAdapter:
    """Tests para adaptadores de firmas electrónicas."""

    def test_docusign_connect(self):
        from b2b_ai.integrations.firmas import DocuSignAdapter

        adapter = DocuSignAdapter()
        result = adapter.connect()
        assert result is True

    def test_docusign_create_envelope(self):
        from b2b_ai.integrations.firmas import DocuSignAdapter, SigningRequest, Signer

        adapter = DocuSignAdapter()
        adapter.connect()

        request = SigningRequest(
            document_id="DOC-001",
            document_name="contrato.pdf",
            subject="Firma de contrato",
            signers=[
                Signer(name="Juan Pérez", email="juan@empresa.com", order=1),
                Signer(name="María López", email="maria@empresa.com", order=2),
            ],
        )
        envelope = adapter.create_envelope(request)
        assert envelope.id != ""
        assert envelope.status.value == "sent"
        assert len(envelope.signers) == 2

    def test_docusign_get_status(self):
        from b2b_ai.integrations.firmas import DocuSignAdapter

        adapter = DocuSignAdapter()
        adapter.connect()

        status = adapter.get_status("env_test_123")
        assert status.envelope_id == "env_test_123"
        assert status.percent_complete == 50

    def test_docusign_download_signed(self):
        from b2b_ai.integrations.firmas import DocuSignAdapter

        adapter = DocuSignAdapter()
        adapter.connect()

        content = adapter.download_signed("env_test_123")
        assert len(content) > 0

    def test_docusign_cancel(self):
        from b2b_ai.integrations.firmas import DocuSignAdapter

        adapter = DocuSignAdapter()
        adapter.connect()

        result = adapter.cancel("env_test_123")
        assert result is True

    def test_docusign_not_connected_raises(self):
        from b2b_ai.integrations.firmas import DocuSignAdapter, SigningRequest, SignatureAdapterError

        adapter = DocuSignAdapter()
        request = SigningRequest(document_id="DOC-001", signers=[])
        with pytest.raises(SignatureAdapterError, match="no está conectado"):
            adapter.create_envelope(request)

    def test_fiel_connect(self):
        from b2b_ai.integrations.firmas import FIELAdapter

        adapter = FIELAdapter()
        result = adapter.connect()
        assert result is True

    def test_fiel_create_envelope(self):
        from b2b_ai.integrations.firmas import FIELAdapter, SigningRequest, Signer

        adapter = FIELAdapter()
        adapter.connect()

        request = SigningRequest(
            document_id="CFDI-001",
            document_name="factura.xml",
            signers=[Signer(name="Titular", email="rfc@sat.gob.mx")],
        )
        envelope = adapter.create_envelope(request)
        assert envelope.id != ""
        assert envelope.status.value == "completed"
        assert envelope.completed_at is not None

    def test_fiel_get_status(self):
        from b2b_ai.integrations.firmas import FIELAdapter

        adapter = FIELAdapter()
        adapter.connect()

        status = adapter.get_status("fiel_test_123")
        assert status.status.value == "completed"
        assert status.percent_complete == 100

    def test_docusign_test_connection(self):
        from b2b_ai.integrations.firmas import DocuSignAdapter

        adapter = DocuSignAdapter()
        result = adapter.test_connection()
        assert result["status"] == "error"

        adapter.connect()
        result = adapter.test_connection()
        assert result["status"] == "connected"


# ---------------------------------------------------------------------------
# CRM Integration Tests
# ---------------------------------------------------------------------------

class TestCRMAdapter:
    """Tests para adaptadores de CRM."""

    def test_hubspot_connect(self):
        from b2b_ai.integrations.crm import HubSpotAdapter

        adapter = HubSpotAdapter()
        result = adapter.connect()
        assert result is True

    def test_hubspot_create_contact(self):
        from b2b_ai.integrations.crm import HubSpotAdapter, ContactCreateRequest

        adapter = HubSpotAdapter()
        adapter.connect()

        request = ContactCreateRequest(
            name="Juan Pérez García",
            email="juan@empresa.com",
            phone="+525512345678",
            company="Empresa Ejemplo S.A.",
            tags=["lead", "enterprise"],
        )
        contact = adapter.create_contact(request)
        assert contact.id != ""
        assert contact.name == "Juan Pérez García"
        assert contact.email == "juan@empresa.com"
        assert "lead" in contact.tags

    def test_hubspot_get_contact(self):
        from b2b_ai.integrations.crm import HubSpotAdapter

        adapter = HubSpotAdapter()
        adapter.connect()

        contact = adapter.get_contact("hs_contact_001")
        assert contact.id == "hs_contact_001"
        assert contact.name != ""

    def test_hubspot_update_contact(self):
        from b2b_ai.integrations.crm import HubSpotAdapter

        adapter = HubSpotAdapter()
        adapter.connect()

        contact = adapter.update_contact("hs_contact_001", {"name": "Nombre Actualizado"})
        assert contact.id == "hs_contact_001"
        assert contact.name == "Nombre Actualizado"

    def test_hubspot_list_contacts(self):
        from b2b_ai.integrations.crm import HubSpotAdapter

        adapter = HubSpotAdapter()
        adapter.connect()

        contacts = adapter.list_contacts()
        assert len(contacts) > 0

    def test_hubspot_create_deal(self):
        from b2b_ai.integrations.crm import HubSpotAdapter, DealCreateRequest, DealStage

        adapter = HubSpotAdapter()
        adapter.connect()

        request = DealCreateRequest(
            title="Proyecto ERP Cloud",
            value=250000.00,
            stage=DealStage.PROPOSAL,
        )
        deal = adapter.create_deal("hs_contact_001", request)
        assert deal.id != ""
        assert deal.title == "Proyecto ERP Cloud"
        assert deal.value == 250000.00
        assert deal.contact_id == "hs_contact_001"

    def test_hubspot_not_connected_raises(self):
        from b2b_ai.integrations.crm import HubSpotAdapter, ContactCreateRequest, CRMAdapterError

        adapter = HubSpotAdapter()
        request = ContactCreateRequest(name="Test")
        with pytest.raises(CRMAdapterError, match="no está conectado"):
            adapter.create_contact(request)

    def test_pipedrive_connect(self):
        from b2b_ai.integrations.crm import PipedriveAdapter

        adapter = PipedriveAdapter()
        result = adapter.connect()
        assert result is True

    def test_pipedrive_create_contact(self):
        from b2b_ai.integrations.crm import PipedriveAdapter, ContactCreateRequest

        adapter = PipedriveAdapter()
        adapter.connect()

        request = ContactCreateRequest(
            name="María López Hernández",
            email="maria@corporativo.com",
            company="Corporativo Demo",
        )
        contact = adapter.create_contact(request)
        assert contact.id != ""
        assert contact.name == "María López Hernández"

    def test_pipedrive_create_deal(self):
        from b2b_ai.integrations.crm import PipedriveAdapter, DealCreateRequest, DealStage

        adapter = PipedriveAdapter()
        adapter.connect()

        request = DealCreateRequest(
            title="Consultoría Fiscal",
            value=180000.00,
            stage=DealStage.NEGOTIATION,
        )
        deal = adapter.create_deal("pd_contact_001", request)
        assert deal.id != ""
        assert deal.value == 180000.00

    def test_pipedrive_list_contacts(self):
        from b2b_ai.integrations.crm import PipedriveAdapter

        adapter = PipedriveAdapter()
        adapter.connect()

        contacts = adapter.list_contacts()
        assert len(contacts) > 0


# ---------------------------------------------------------------------------
# Monitoring Integration Tests
# ---------------------------------------------------------------------------

class TestMonitoringAdapter:
    """Tests para adaptadores de monitoreo."""

    def test_sentry_connect(self):
        from b2b_ai.integrations.monitoreo import SentryAdapter

        adapter = SentryAdapter()
        result = adapter.connect()
        assert result is True

    def test_sentry_capture_exception(self):
        from b2b_ai.integrations.monitoreo import SentryAdapter, ErrorLevel

        adapter = SentryAdapter()
        adapter.connect()

        try:
            raise ValueError("Test error")
        except ValueError as e:
            report = adapter.capture_exception(e, context={"feature": "billing"})
            assert report.id != ""
            assert "ValueError" in report.message
            assert report.level == ErrorLevel.ERROR
            assert report.stacktrace is not None

    def test_sentry_capture_message(self):
        from b2b_ai.integrations.monitoreo import SentryAdapter, ErrorLevel

        adapter = SentryAdapter()
        adapter.connect()

        report = adapter.capture_message("Pago procesado exitosamente", level=ErrorLevel.INFO)
        assert report.id != ""
        assert report.message == "Pago procesado exitosamente"
        assert report.level == ErrorLevel.INFO

    def test_sentry_add_breadcrumb(self):
        from b2b_ai.integrations.monitoreo import SentryAdapter

        adapter = SentryAdapter()
        adapter.connect()

        breadcrumb = adapter.add_breadcrumb("Inicio de proceso", category="workflow")
        assert breadcrumb.message == "Inicio de proceso"
        assert breadcrumb.category == "workflow"
        assert len(adapter.breadcrumbs) == 1

    def test_sentry_set_user(self):
        from b2b_ai.integrations.monitoreo import SentryAdapter

        adapter = SentryAdapter()
        adapter.connect()

        user = adapter.set_user("user_001", email="user@empresa.com")
        assert user.user_id == "user_001"
        assert user.email == "user@empresa.com"
        assert adapter.user_context is not None

    def test_sentry_clear_user(self):
        from b2b_ai.integrations.monitoreo import SentryAdapter

        adapter = SentryAdapter()
        adapter.connect()

        adapter.set_user("user_001")
        assert adapter.user_context is not None

        adapter.clear_user()
        assert adapter.user_context is None

    def test_sentry_not_connected_raises(self):
        from b2b_ai.integrations.monitoreo import SentryAdapter, MonitoringAdapterError

        adapter = SentryAdapter()
        with pytest.raises(MonitoringAdapterError, match="no está conectado"):
            adapter.capture_exception(Exception("test"))

    def test_console_connect(self):
        from b2b_ai.integrations.monitoreo import ConsoleAdapter

        adapter = ConsoleAdapter()
        result = adapter.connect()
        assert result is True

    def test_console_capture_exception(self):
        from b2b_ai.integrations.monitoreo import ConsoleAdapter, ErrorLevel

        adapter = ConsoleAdapter()
        adapter.connect()

        try:
            raise RuntimeError("Console test error")
        except RuntimeError as e:
            report = adapter.capture_exception(e)
            assert report.id != ""
            assert "RuntimeError" in report.message
            assert report.level == ErrorLevel.ERROR

    def test_console_capture_message(self):
        from b2b_ai.integrations.monitoreo import ConsoleAdapter, ErrorLevel

        adapter = ConsoleAdapter()
        adapter.connect()

        report = adapter.capture_message("Debug message", level=ErrorLevel.DEBUG)
        assert report.id != ""
        assert report.level == ErrorLevel.DEBUG

    def test_monitoring_test_connection(self):
        from b2b_ai.integrations.monitoreo import SentryAdapter

        adapter = SentryAdapter()
        result = adapter.test_connection()
        assert result["status"] == "error"

        adapter.connect()
        result = adapter.test_connection()
        assert result["status"] == "connected"
        assert result["environment"] == "development"


# ---------------------------------------------------------------------------
# IntegrationHub Tests
# ---------------------------------------------------------------------------

class TestIntegrationHub:
    """Tests para el IntegrationHub central."""

    def test_register_adapter(self):
        from b2b_ai.integrations import IntegrationHub, EcodexAdapter

        hub = IntegrationHub()
        adapter = EcodexAdapter()

        hub.register_adapter("sat_ecodex", adapter)
        assert hub.count == 1

    def test_register_duplicate_raises(self):
        from b2b_ai.integrations import IntegrationHub, EcodexAdapter, IntegrationHubError

        hub = IntegrationHub()
        hub.register_adapter("sat_ecodex", EcodexAdapter())

        with pytest.raises(IntegrationHubError, match="ya está registrado"):
            hub.register_adapter("sat_ecodex", EcodexAdapter())

    def test_get_adapter(self):
        from b2b_ai.integrations import IntegrationHub, EcodexAdapter, FinkokAdapter

        hub = IntegrationHub()
        hub.register_adapter("ecodex", EcodexAdapter())
        hub.register_adapter("finkok", FinkokAdapter())

        adapter = hub.get_adapter("ecodex")
        assert adapter.name == "ecodex"

        adapter = hub.get_adapter("finkok")
        assert adapter.name == "finkok"

    def test_get_adapter_not_found(self):
        from b2b_ai.integrations import IntegrationHub, IntegrationHubError

        hub = IntegrationHub()
        with pytest.raises(IntegrationHubError, match="no encontrado"):
            hub.get_adapter("nonexistent")

    def test_unregister_adapter(self):
        from b2b_ai.integrations import IntegrationHub, EcodexAdapter

        hub = IntegrationHub()
        hub.register_adapter("ecodex", EcodexAdapter())
        assert hub.count == 1

        result = hub.unregister_adapter("ecodex")
        assert result is True
        assert hub.count == 0

        # Unregister non-existent
        result = hub.unregister_adapter("ecodex")
        assert result is False

    def test_list_adapters(self):
        from b2b_ai.integrations import IntegrationHub, EcodexAdapter, CONTPAQiWebAdapter, BBVAAdapter

        hub = IntegrationHub()
        hub.register_adapter("sat_ecodex", EcodexAdapter())
        hub.register_adapter("erp_contpaqi", CONTPAQiWebAdapter())
        hub.register_adapter("banco_bbva", BBVAAdapter())

        adapters = hub.list_adapters()
        assert len(adapters) == 3
        assert adapters["sat_ecodex"]["category"] == "sat"
        assert adapters["erp_contpaqi"]["category"] == "erp"
        assert adapters["banco_bbva"]["category"] == "banco"

    def test_test_connection(self):
        from b2b_ai.integrations import IntegrationHub, EcodexAdapter

        hub = IntegrationHub()
        hub.register_adapter("ecodex", EcodexAdapter())

        # Before connect
        result = hub.test_connection("ecodex")
        assert result["status"] == "error"

        # After connect
        hub.get_adapter("ecodex").connect()
        result = hub.test_connection("ecodex")
        assert result["status"] == "connected"

    def test_get_status(self):
        from b2b_ai.integrations import IntegrationHub, EcodexAdapter, CONTPAQiWebAdapter

        hub = IntegrationHub()
        hub.register_adapter("sat_ecodex", EcodexAdapter())
        hub.register_adapter("erp_contpaqi", CONTPAQiWebAdapter())

        status = hub.get_status()
        assert status["total_adapters"] == 2
        assert "adapters" in status

    def test_connect_all(self):
        from b2b_ai.integrations import IntegrationHub, EcodexAdapter, CONTPAQiWebAdapter

        hub = IntegrationHub()
        hub.register_adapter("sat_ecodex", EcodexAdapter())
        hub.register_adapter("erp_contpaqi", CONTPAQiWebAdapter())

        results = hub.connect_all()
        assert results["sat_ecodex"] is True
        assert results["erp_contpaqi"] is True

    def test_get_adapters_by_category(self):
        from b2b_ai.integrations import (
            IntegrationHub, EcodexAdapter, FinkokAdapter,
            CONTPAQiWebAdapter, BBVAAdapter,
        )

        hub = IntegrationHub()
        hub.register_adapter("sat_ecodex", EcodexAdapter())
        hub.register_adapter("sat_finkok", FinkokAdapter())
        hub.register_adapter("erp_contpaqi", CONTPAQiWebAdapter())
        hub.register_adapter("banco_bbva", BBVAAdapter())

        sat_adapters = hub.get_adapters_by_category("sat")
        assert len(sat_adapters) == 2

        erp_adapters = hub.get_adapters_by_category("erp")
        assert len(erp_adapters) == 1

        banco_adapters = hub.get_adapters_by_category("banco")
        assert len(banco_adapters) == 1

    def test_full_workflow(self):
        """Test completo: registrar todos los adaptadores, conectar y verificar."""
        from b2b_ai.integrations import (
            IntegrationHub,
            EcodexAdapter,
            FinkokAdapter,
            CONTPAQiWebAdapter,
            QuickBooksOnlineAdapter,
            BBVAAdapter,
            BanorteAdapter,
            NominaService,
        )

        hub = IntegrationHub()

        # Register all adapters
        hub.register_adapter("sat_ecodex", EcodexAdapter())
        hub.register_adapter("sat_finkok", FinkokAdapter())
        hub.register_adapter("erp_contpaqi", CONTPAQiWebAdapter())
        hub.register_adapter("erp_quickbooks", QuickBooksOnlineAdapter())
        hub.register_adapter("banco_bbva", BBVAAdapter())
        hub.register_adapter("banco_banorte", BanorteAdapter())
        hub.register_adapter("nomina_service", NominaService())

        assert hub.count == 7

        # Connect all
        results = hub.connect_all()
        assert all(results.values())

        # Get status
        status = hub.get_status()
        assert status["total_adapters"] == 7
        assert status["connected"] == 7

        # Get by category
        sat = hub.get_adapters_by_category("sat")
        assert len(sat) == 2

        erp = hub.get_adapters_by_category("erp")
        assert len(erp) == 2

        banco = hub.get_adapters_by_category("banco")
        assert len(banco) == 2

        nomina = hub.get_adapters_by_category("nomina")
        assert len(nomina) == 1

    def test_hub_with_all_new_adapters(self):
        """Test completo con todos los nuevos adaptadores de integración."""
        from b2b_ai.integrations import (
            IntegrationHub,
            StripeAdapter,
            ConektaAdapter,
            PayPalAdapter,
            SendGridAdapter,
            TwilioAdapter,
            WhatsAppBusinessAdapter,
            GoogleDriveAdapter,
            OneDriveAdapter,
            S3Adapter,
            DocuSignAdapter,
            FIELAdapter,
            HubSpotAdapter,
            PipedriveAdapter,
            SentryAdapter,
            ConsoleAdapter,
        )

        hub = IntegrationHub()

        # Pagos
        hub.register_adapter("pago_stripe", StripeAdapter())
        hub.register_adapter("pago_conekta", ConektaAdapter())
        hub.register_adapter("pago_paypal", PayPalAdapter())

        # Comunicación
        hub.register_adapter("com_sendgrid", SendGridAdapter())
        hub.register_adapter("com_twilio", TwilioAdapter())
        hub.register_adapter("com_whatsapp", WhatsAppBusinessAdapter())

        # Almacenamiento
        hub.register_adapter("store_drive", GoogleDriveAdapter())
        hub.register_adapter("store_onedrive", OneDriveAdapter())
        hub.register_adapter("store_s3", S3Adapter())

        # Firmas
        hub.register_adapter("firma_docusign", DocuSignAdapter())
        hub.register_adapter("firma_fiel", FIELAdapter())

        # CRM
        hub.register_adapter("crm_hubspot", HubSpotAdapter())
        hub.register_adapter("crm_pipedrive", PipedriveAdapter())

        # Monitoreo
        hub.register_adapter("mon_sentry", SentryAdapter())
        hub.register_adapter("mon_console", ConsoleAdapter())

        assert hub.count == 15

        # Connect all
        results = hub.connect_all()
        assert all(results.values())

        # Verify categories
        assert len(hub.get_adapters_by_category("pago")) == 3
        assert len(hub.get_adapters_by_category("comunicacion")) == 3
        assert len(hub.get_adapters_by_category("almacenamiento")) == 3
        assert len(hub.get_adapters_by_category("firma")) == 2
        assert len(hub.get_adapters_by_category("crm")) == 2
        assert len(hub.get_adapters_by_category("monitoreo")) == 2

        # Get full status
        status = hub.get_status()
        assert status["total_adapters"] == 15
        assert status["connected"] == 15

    def test_hub_category_filtering(self):
        """Test de filtrado por categoría con nuevos adaptadores."""
        from b2b_ai.integrations import (
            IntegrationHub,
            StripeAdapter,
            SendGridAdapter,
            GoogleDriveAdapter,
            DocuSignAdapter,
            HubSpotAdapter,
            SentryAdapter,
        )

        hub = IntegrationHub()
        hub.register_adapter("pago_stripe", StripeAdapter())
        hub.register_adapter("com_sendgrid", SendGridAdapter())
        hub.register_adapter("store_drive", GoogleDriveAdapter())
        hub.register_adapter("firma_docusign", DocuSignAdapter())
        hub.register_adapter("crm_hubspot", HubSpotAdapter())
        hub.register_adapter("mon_sentry", SentryAdapter())

        assert hub.count == 6

        # Each adapter gets its own category
        assert len(hub.get_adapters_by_category("pago")) == 1
        assert len(hub.get_adapters_by_category("comunicacion")) == 1
        assert len(hub.get_adapters_by_category("almacenamiento")) == 1
        assert len(hub.get_adapters_by_category("firma")) == 1
        assert len(hub.get_adapters_by_category("crm")) == 1
        assert len(hub.get_adapters_by_category("monitoreo")) == 1

        # Empty category
        assert len(hub.get_adapters_by_category("nonexistent")) == 0


# ---------------------------------------------------------------------------
# SAT Direct Integration Tests
# ---------------------------------------------------------------------------

class TestSATDirect:
    """Tests para integración SAT Direct."""

    def test_sat_direct_connect(self):
        from b2b_ai.integrations.sat_direct import SATDirectConnection

        adapter = SATDirectConnection()
        assert not adapter.is_connected
        result = adapter.connect()
        assert result is True
        assert adapter.is_connected

    def test_sat_direct_timbrar(self):
        from b2b_ai.integrations.sat_direct import SATDirectConnection

        adapter = SATDirectConnection()
        adapter.connect()
        response = adapter.timbrar_cfdi({"rfc_emisor": "XAXX010101000", "rfc_receptor": "AAA010101AAA", "total": 11600})
        assert response.exito is True
        assert response.uuid != ""

    def test_sat_direct_cancelar(self):
        from b2b_ai.integrations.sat_direct import SATDirectConnection

        adapter = SATDirectConnection()
        adapter.connect()
        result = adapter.cancelar_cfdi("test-uuid", "02", "XAXX010101000")
        assert result["exito"] is True

    def test_sat_direct_consultar_rfc(self):
        from b2b_ai.integrations.sat_direct import SATDirectConnection

        adapter = SATDirectConnection()
        adapter.connect()
        result = adapter.consultar_rfc("AAA010101AAA")
        assert result["rfc"] == "AAA010101AAA"

    def test_sat_direct_contabilidad(self):
        from b2b_ai.integrations.sat_direct import SATDirectConnection, ContabilidadElectronicaDirect

        adapter = SATDirectConnection()
        adapter.connect()
        datos = ContabilidadElectronicaDirect(ejercicio=2026, mes=1, rfc="AAA010101AAA")
        result = adapter.contabilidad_electronica(datos)
        assert result["exito"] is True

    def test_sat_direct_diot(self):
        from b2b_ai.integrations.sat_direct import SATDirectConnection, DIOTSubmission, DIOTRecord

        adapter = SATDirectConnection()
        adapter.connect()
        diot = DIOTSubmission(ejercicio=2026, mes=1, rfc="AAA010101AAA",
                             registros=[DIOTRecord(rfc_tercero="BBB020202BBB", valor_acumulado=50000, mes=1, ejercicio=2026)])
        result = adapter.enviar_diot(diot)
        assert result["exito"] is True

    def test_sat_direct_not_connected(self):
        from b2b_ai.integrations.sat_direct import SATDirectConnection, SATDirectAdapterError

        adapter = SATDirectConnection()
        with pytest.raises(SATDirectAdapterError, match="no está conectado"):
            adapter.timbrar_cfdi({})


# ---------------------------------------------------------------------------
# Additional ERP Tests
# ---------------------------------------------------------------------------

class TestAdditionalERP:
    """Tests para adaptadores ERP adicionales."""

    def test_contpaqi_one(self):
        from b2b_ai.integrations.erp import CONTPAQiOneAdapter

        adapter = CONTPAQiOneAdapter()
        result = adapter.connect()
        assert result is True
        invoices = adapter.get_invoices()
        assert len(invoices) > 0

    def test_quickbooks_desktop(self):
        from b2b_ai.integrations.erp import QuickBooksDesktopAdapter

        adapter = QuickBooksDesktopAdapter()
        result = adapter.connect()
        assert result is True
        invoices = adapter.get_invoices()
        assert len(invoices) > 0

    def test_peak(self):
        from b2b_ai.integrations.erp import PeakAdapter

        adapter = PeakAdapter()
        result = adapter.connect()
        assert result is True
        invoices = adapter.get_invoices()
        assert len(invoices) > 0

    def test_multileg(self):
        from b2b_ai.integrations.erp import MultilegAdapter

        adapter = MultilegAdapter()
        result = adapter.connect()
        assert result is True

    def test_euroweb(self):
        from b2b_ai.integrations.erp import EurowebAdapter

        adapter = EurowebAdapter()
        result = adapter.connect()
        assert result is True

    def test_absis(self):
        from b2b_ai.integrations.erp import AbsisAdapter

        adapter = AbsisAdapter()
        result = adapter.connect()
        assert result is True

    def test_factor_d(self):
        from b2b_ai.integrations.erp import FactorDAdapter

        adapter = FactorDAdapter()
        result = adapter.connect()
        assert result is True

    def test_taxko(self):
        from b2b_ai.integrations.erp import TaxkoAdapter

        adapter = TaxkoAdapter()
        result = adapter.connect()
        assert result is True

    def test_facturadirecta(self):
        from b2b_ai.integrations.erp import FacturaDirectaAdapter

        adapter = FacturaDirectaAdapter()
        result = adapter.connect()
        assert result is True


# ---------------------------------------------------------------------------
# Additional Bank Tests
# ---------------------------------------------------------------------------

class TestAdditionalBanks:
    """Tests para adaptadores bancarios adicionales."""

    def test_hsbc(self):
        from b2b_ai.integrations.bancos import HSBCAdapter

        adapter = HSBCAdapter()
        result = adapter.connect()
        assert result is True
        statement = adapter.get_statement()
        assert len(statement.transactions) > 0

    def test_banamex(self):
        from b2b_ai.integrations.bancos import BanamexAdapter

        adapter = BanamexAdapter()
        result = adapter.connect()
        assert result is True
        statement = adapter.get_statement()
        assert len(statement.transactions) > 0

    def test_scotiabank(self):
        from b2b_ai.integrations.bancos import ScotiabankAdapter

        adapter = ScotiabankAdapter()
        result = adapter.connect()
        assert result is True
        statement = adapter.get_statement()
        assert len(statement.transactions) > 0

    def test_inbursa(self):
        from b2b_ai.integrations.bancos import InbursaAdapter

        adapter = InbursaAdapter()
        result = adapter.connect()
        assert result is True
        statement = adapter.get_statement()
        assert len(statement.transactions) > 0

    def test_afirme(self):
        from b2b_ai.integrations.bancos import AfirmeAdapter

        adapter = AfirmeAdapter()
        result = adapter.connect()
        assert result is True
        statement = adapter.get_statement()
        assert len(statement.transactions) > 0


# ---------------------------------------------------------------------------
# Additional Payment Tests
# ---------------------------------------------------------------------------

class TestAdditionalPayments:
    """Tests para adaptadores de pago adicionales."""

    def test_kushki(self):
        from b2b_ai.integrations.pagos import KushkiAdapter, PaymentRequest, Currency

        adapter = KushkiAdapter()
        result = adapter.connect()
        assert result is True
        payment = adapter.create_payment(PaymentRequest(amount=5000, currency=Currency.MXN))
        assert payment.status.value == "succeeded"

    def test_mercadopago(self):
        from b2b_ai.integrations.pagos import MercadoPagoAdapter, PaymentRequest, Currency

        adapter = MercadoPagoAdapter()
        result = adapter.connect()
        assert result is True
        payment = adapter.create_payment(PaymentRequest(amount=8000, currency=Currency.MXN))
        assert payment.status.value == "succeeded"

    def test_paypal_mexico(self):
        from b2b_ai.integrations.pagos import PayPalMexicoAdapter, PaymentRequest, Currency

        adapter = PayPalMexicoAdapter()
        result = adapter.connect()
        assert result is True
        payment = adapter.create_payment(PaymentRequest(amount=6000, currency=Currency.MXN))
        assert payment.status.value == "succeeded"


# ---------------------------------------------------------------------------
# Additional Communication Tests
# ---------------------------------------------------------------------------

class TestAdditionalCommunication:
    """Tests para adaptadores de comunicación adicionales."""

    def test_mailgun(self):
        from b2b_ai.integrations.comunicacion import MailgunAdapter, EmailRequest

        adapter = MailgunAdapter()
        result = adapter.connect()
        assert result is True
        msg = adapter.send_email(EmailRequest(to="test@likida.ai", subject="Test", body="Hello"))
        assert msg.status.value == "sent"

    def test_aws_ses(self):
        from b2b_ai.integrations.comunicacion import AWSSesAdapter, EmailRequest

        adapter = AWSSesAdapter()
        result = adapter.connect()
        assert result is True
        msg = adapter.send_email(EmailRequest(to="test@likida.ai", subject="SES Test", body="SES Hello"))
        assert msg.status.value == "sent"

    def test_vonage(self):
        from b2b_ai.integrations.comunicacion import VonageAdapter, SMSRequest

        adapter = VonageAdapter()
        result = adapter.connect()
        assert result is True
        msg = adapter.send_sms(SMSRequest(to="+525512345678", message="Test SMS"))
        assert msg.status.value == "sent"

    def test_messagebird(self):
        from b2b_ai.integrations.comunicacion import MessageBirdAdapter, WhatsAppRequest

        adapter = MessageBirdAdapter()
        result = adapter.connect()
        assert result is True
        msg = adapter.send_whatsapp(WhatsAppRequest(to="+525512345678", message="Test WA"))
        assert msg.status.value == "sent"


# ---------------------------------------------------------------------------
# Additional Storage Tests
# ---------------------------------------------------------------------------

class TestAdditionalStorage:
    """Tests para adaptadores de almacenamiento adicionales."""

    def test_dropbox(self):
        from b2b_ai.integrations.storage import DropboxAdapter

        adapter = DropboxAdapter()
        result = adapter.connect()
        assert result is True
        upload = adapter.upload("/tmp/test.pdf", "/docs")
        assert upload.success is True
        files = adapter.list_files()
        assert len(files) > 0

    def test_box(self):
        from b2b_ai.integrations.storage import BoxAdapter

        adapter = BoxAdapter()
        result = adapter.connect()
        assert result is True
        upload = adapter.upload("/tmp/test.xlsx", "/reports")
        assert upload.success is True

    def test_gcs(self):
        from b2b_ai.integrations.storage import GCSAdapter

        adapter = GCSAdapter()
        result = adapter.connect()
        assert result is True
        upload = adapter.upload("/tmp/data.parquet", "/data")
        assert upload.success is True


# ---------------------------------------------------------------------------
# Additional Signature Tests
# ---------------------------------------------------------------------------

class TestAdditionalSignatures:
    """Tests para adaptadores de firma adicionales."""

    def test_adobe_sign(self):
        from b2b_ai.integrations.firmas import AdobeSignAdapter, SigningRequest, Signer

        adapter = AdobeSignAdapter()
        result = adapter.connect()
        assert result is True
        envelope = adapter.create_envelope(SigningRequest(
            document_id="doc_001", signers=[Signer(name="Test", email="test@likida.ai")]
        ))
        assert envelope.status.value == "sent"


# ---------------------------------------------------------------------------
# Additional CRM Tests
# ---------------------------------------------------------------------------

class TestAdditionalCRM:
    """Tests para adaptadores CRM adicionales."""

    def test_salesforce(self):
        from b2b_ai.integrations.crm import SalesforceAdapter, ContactCreateRequest

        adapter = SalesforceAdapter()
        result = adapter.connect()
        assert result is True
        contact = adapter.create_contact(ContactCreateRequest(name="SF Contact", email="sf@likida.ai"))
        assert contact.id != ""

    def test_zoho_crm(self):
        from b2b_ai.integrations.crm import ZohoCRMAdapter, ContactCreateRequest

        adapter = ZohoCRMAdapter()
        result = adapter.connect()
        assert result is True
        contact = adapter.create_contact(ContactCreateRequest(name="Zoho Contact", email="zoho@likida.ai"))
        assert contact.id != ""


# ---------------------------------------------------------------------------
# Additional Monitoring Tests
# ---------------------------------------------------------------------------

class TestAdditionalMonitoring:
    """Tests para adaptadores de monitoreo adicionales."""

    def test_datadog(self):
        from b2b_ai.integrations.monitoreo import DatadogAdapter, ErrorLevel

        adapter = DatadogAdapter()
        result = adapter.connect()
        assert result is True
        report = adapter.capture_exception(Exception("Test error"), level=ErrorLevel.ERROR)
        assert report.id != ""

    def test_new_relic(self):
        from b2b_ai.integrations.monitoreo import NewRelicAdapter, ErrorLevel

        adapter = NewRelicAdapter()
        result = adapter.connect()
        assert result is True
        report = adapter.capture_message("Test message", level=ErrorLevel.INFO)
        assert report.id != ""

    def test_logrocket(self):
        from b2b_ai.integrations.monitoreo import LogRocketAdapter, ErrorLevel

        adapter = LogRocketAdapter()
        result = adapter.connect()
        assert result is True
        report = adapter.capture_message("Frontend error", level=ErrorLevel.WARNING)
        assert report.id != ""


# ---------------------------------------------------------------------------
# AI/ML Integration Tests
# ---------------------------------------------------------------------------

class TestAIIntegration:
    """Tests para adaptadores AI/ML."""

    def test_openai(self):
        from b2b_ai.integrations.ai import OpenAIAdapter, AIRequest, AIMessage, AIMessageRole

        adapter = OpenAIAdapter()
        result = adapter.connect()
        assert result is True
        response = adapter.generate(AIRequest(messages=[AIMessage(role=AIMessageRole.USER, content="Hola")]))
        assert response.content != ""

    def test_anthropic(self):
        from b2b_ai.integrations.ai import AnthropicAdapter, AIRequest, AIMessage, AIMessageRole

        adapter = AnthropicAdapter()
        result = adapter.connect()
        assert result is True
        response = adapter.generate(AIRequest(messages=[AIMessage(role=AIMessageRole.USER, content="Hola")]))
        assert response.content != ""

    def test_vertex_ai(self):
        from b2b_ai.integrations.ai import VertexAIAdapter, AIRequest, AIMessage, AIMessageRole

        adapter = VertexAIAdapter()
        result = adapter.connect()
        assert result is True
        response = adapter.generate(AIRequest(messages=[AIMessage(role=AIMessageRole.USER, content="Hola")]))
        assert response.content != ""

    def test_openai_embed(self):
        from b2b_ai.integrations.ai import OpenAIAdapter, EmbeddingRequest

        adapter = OpenAIAdapter()
        adapter.connect()
        result = adapter.embed(EmbeddingRequest(input_text="Texto de prueba"))
        assert len(result.embedding) > 0

    def test_ai_not_connected(self):
        from b2b_ai.integrations.ai import OpenAIAdapter, AIRequest, AIMessage, AIMessageRole, AIAdapterError

        adapter = OpenAIAdapter()
        with pytest.raises(AIAdapterError, match="no está conectado"):
            adapter.generate(AIRequest(messages=[AIMessage(role=AIMessageRole.USER, content="Test")]))


# ---------------------------------------------------------------------------
# Document Processing Tests
# ---------------------------------------------------------------------------

class TestDocumentProcessing:
    """Tests para procesamiento de documentos."""

    def test_reportlab(self):
        from b2b_ai.integrations.documentos import ReportLabProcessor, PDFRequest

        proc = ReportLabProcessor()
        result = proc.generate_pdf(PDFRequest(template_name="factura", data={"total": 11600}))
        assert result.success is True
        assert result.content is not None

    def test_lxml(self):
        from b2b_ai.integrations.documentos import LXMLProcessor, XMLParseRequest

        proc = LXMLProcessor()
        result = proc.parse_xml(XMLParseRequest(xml_content="<root><data>test</data></root>"))
        assert result.success is True
        assert result.is_valid is True

    def test_tesseract(self):
        from b2b_ai.integrations.documentos import TesseractProcessor, OCRRequest

        proc = TesseractProcessor()
        result = proc.extract_text_ocr(OCRRequest(language="spa"))
        assert result.success is True
        assert result.text != ""

    def test_openpyxl(self):
        from b2b_ai.integrations.documentos import OpenPyxlProcessor, ExcelExportRequest

        proc = OpenPyxlProcessor()
        result = proc.export_excel(ExcelExportRequest(
            data=[{"name": "Test", "value": 100}, {"name": "Test2", "value": 200}]
        ))
        assert result.success is True
        assert result.num_rows == 2


# ---------------------------------------------------------------------------
# Analytics Integration Tests
# ---------------------------------------------------------------------------

class TestAnalyticsIntegration:
    """Tests para adaptadores de analytics."""

    def test_google_analytics(self):
        from b2b_ai.integrations.analytics import GoogleAnalyticsAdapter, AnalyticsEvent

        adapter = GoogleAnalyticsAdapter()
        result = adapter.connect()
        assert result is True
        event_result = adapter.track_event(AnalyticsEvent(event_name="page_view"))
        assert event_result.success is True

    def test_mixpanel(self):
        from b2b_ai.integrations.analytics import MixpanelAdapter, AnalyticsEvent

        adapter = MixpanelAdapter()
        result = adapter.connect()
        assert result is True
        event_result = adapter.track_event(AnalyticsEvent(event_name="button_click"))
        assert event_result.success is True

    def test_amplitude(self):
        from b2b_ai.integrations.analytics import AmplitudeAdapter, AnalyticsEvent

        adapter = AmplitudeAdapter()
        result = adapter.connect()
        assert result is True
        event_result = adapter.track_event(AnalyticsEvent(event_name="purchase"))
        assert event_result.success is True

    def test_analytics_query(self):
        from b2b_ai.integrations.analytics import GoogleAnalyticsAdapter, AnalyticsQuery

        adapter = GoogleAnalyticsAdapter()
        adapter.connect()
        result = adapter.query(AnalyticsQuery(metric="sessions", date_range={"start": "2026-01-01", "end": "2026-01-31"}))
        assert result.success is True
        assert len(result.data) > 0


# ---------------------------------------------------------------------------
# IntegrationHub with New Adapters Tests
# ---------------------------------------------------------------------------

class TestHubNewAdapters:
    """Tests para IntegrationHub con adaptadores nuevos."""

    def test_hub_sat_direct(self):
        from b2b_ai.integrations.hub import IntegrationHub
        from b2b_ai.integrations.sat_direct import SATDirectConnection

        hub = IntegrationHub()
        hub.register_adapter("sat_direct", SATDirectConnection())
        assert hub.count == 1
        assert "sat_direct" in hub.get_adapters_by_category("sat_direct")

    def test_hub_ai(self):
        from b2b_ai.integrations.hub import IntegrationHub
        from b2b_ai.integrations.ai import OpenAIAdapter

        hub = IntegrationHub()
        hub.register_adapter("ai_openai", OpenAIAdapter())
        assert hub.count == 1
        assert "ai_openai" in hub.get_adapters_by_category("ai_ml")

    def test_hub_documentos(self):
        from b2b_ai.integrations.hub import IntegrationHub
        from b2b_ai.integrations.documentos import ReportLabProcessor

        hub = IntegrationHub()
        hub.register_adapter("doc_pdf", ReportLabProcessor())
        assert hub.count == 1
        assert "doc_pdf" in hub.get_adapters_by_category("documentos")

    def test_hub_analytics(self):
        from b2b_ai.integrations.hub import IntegrationHub
        from b2b_ai.integrations.analytics import GoogleAnalyticsAdapter

        hub = IntegrationHub()
        hub.register_adapter("ga", GoogleAnalyticsAdapter())
        assert hub.count == 1
        assert "ga" in hub.get_adapters_by_category("analytics")

