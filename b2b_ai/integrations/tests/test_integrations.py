# -*- coding: utf-8 -*-
"""
test_integrations.py — Tests comprehensivos para el módulo de integraciones.

Cubre: SAT (Ecodex, Finkok, Portal), ERP (CONTPAQi, Aspel, QuickBooks, Xero),
Bancos (BBVA, Banorte, Santander, OFX, CSV), Nómina, e IntegrationHub.
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
        imss = service.calcular_imss(500)  # salario diario

        assert imss.total_obrero > 0
        assert imss.total_patron > 0
        assert imss.total_patron > imss.total_obrero

    def test_nomina_service_calcular_infonavit(self):
        from b2b_ai.integrations.nomina import NominaService

        service = NominaService()
        infonavit = service.calcular_infonavit(500)  # salario diario

        # 5% of (500 * 30) = 5% of 15000 = 750
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
                id="EMP-001",
                nombre="Juan Pérez",
                rfc="PEPJ800101AAA",
                salario_diario=500,
                salario_bruto=15000,
            ),
            Empleado(
                id="EMP-002",
                nombre="María López",
                rfc="LOPM900202BBB",
                salario_diario=800,
                salario_bruto=24000,
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
