# -*- coding: utf-8 -*-
"""
test_erp_adapters.py — Production-ready tests for ALL ERP adapters.

Tests each adapter in mock mode (no real credentials needed).
Covers: connect, disconnect, get_invoices, get_polizas, upload_poliza,
get_chart_of_accounts, get_balanza, health_check, error handling.
"""
from __future__ import annotations

import pytest
from typing import Dict, Any

from b2b_ai.integrations.erp.adapter import ERPAdapter, ERPAdapterError
from b2b_ai.integrations.erp.http_client import ERPAPIError, ERPAuthError, ERPConnectionError
from b2b_ai.integrations.erp.models import (
    ERPConfig, ERPType, Invoice, Poliza, CuentaPoliza,
    ChartOfAccounts, BalanzaComprobacion, StatusPoliza,
)
from b2b_ai.integrations.erp.quickbooks import QuickBooksOnlineAdapter
from b2b_ai.integrations.erp.xero import XeroAdapter
from b2b_ai.integrations.erp.contpaqi_web import CONTPAQiWebAdapter
from b2b_ai.integrations.erp.contpaqi_desktop import CONTPAQiDesktopAdapter
from b2b_ai.integrations.erp.aspel_cloud import AspelCloudAdapter
from b2b_ai.integrations.erp.factor_d import FactorDAdapter
from b2b_ai.integrations.erp.taxko import TaxkoAdapter
from b2b_ai.integrations.erp.facturadirecta import FacturaDirectaAdapter
from b2b_ai.integrations.erp.peak import PeakAdapter
from b2b_ai.integrations.erp.multileg import MultilegAdapter
from b2b_ai.integrations.erp.euroweb import EurowebAdapter
from b2b_ai.integrations.erp.absis import AbsisAdapter


# =========================================================================
# Helpers
# =========================================================================
def _balanced_poliza() -> Poliza:
    """Create a balanced poliza for testing."""
    return Poliza(
        id="TEST-POL-001", fecha="2026-07-01",
        concepto="Poliza de prueba", tipo="Diario", numero=1,
        cuentas=[
            CuentaPoliza(cuenta="1101", descripcion="Caja", debe=10000, haber=0),
            CuentaPoliza(cuenta="4101", descripcion="Ingresos", debe=0, haber=10000),
        ],
        monto_total=10000, status=StatusPoliza.CONTABILIZADA,
    )


def _unbalanced_poliza() -> Poliza:
    """Create an unbalanced poliza for testing."""
    return Poliza(
        id="TEST-POL-002", fecha="2026-07-01",
        concepto="Poliza descuadrada", tipo="Diario", numero=2,
        cuentas=[
            CuentaPoliza(cuenta="1101", descripcion="Caja", debe=10000, harbor=0),
        ],
        monto_total=10000, status=StatusPoliza.REGISTRADA,
    )


# =========================================================================
# Cloud ERP Adapters — Mock Mode Tests
# =========================================================================
class TestCloudAdapters:
    """Test all cloud ERP adapters in mock mode."""

    ADAPTERS = [
        ("QuickBooksOnline", QuickBooksOnlineAdapter),
        ("Xero", XeroAdapter),
        ("CONTPAQiWeb", CONTPAQiWebAdapter),
        ("AspelCloud", AspelCloudAdapter),
        ("FactorD", FactorDAdapter),
        ("Taxko", TaxkoAdapter),
        ("FacturaDirecta", FacturaDirectaAdapter),
    ]

    @pytest.fixture(params=ADAPTERS, ids=[a[0] for a in ADAPTERS])
    def adapter(self, request):
        """Create adapter instance (no credentials = mock mode)."""
        cls = request.param[1]
        return cls()

    # -- Connect/Disconnect --
    def test_connect_returns_true(self, adapter):
        assert adapter.connect() is True
        assert adapter.is_connected

    def test_disconnect(self, adapter):
        adapter.connect()
        adapter.disconnect()
        assert not adapter.is_connected

    def test_connect_sets_empresa_info(self, adapter):
        adapter.connect()
        assert adapter._empresa_info.get("nombre")

    def test_health_check_mock(self, adapter):
        adapter.connect()
        health = adapter.health_check()
        assert health["status"] == "healthy_mock"
        assert health["mock"] is True
        assert health["connected"] is True

    def test_health_check_disconnected(self, adapter):
        health = adapter.health_check()
        assert health["status"] == "disconnected"
        assert health["connected"] is False

    # -- Invoices --
    def test_get_invoices_mock(self, adapter):
        adapter.connect()
        invoices = adapter.get_invoices()
        assert len(invoices) >= 1
        assert all(isinstance(inv, Invoice) for inv in invoices)
        assert all(inv.monto > 0 for inv in invoices)

    def test_get_invoices_requires_connection(self, adapter):
        with pytest.raises(ERPAdapterError):
            adapter.get_invoices()

    # -- Polizas --
    def test_get_polizas_mock(self, adapter):
        adapter.connect()
        polizas = adapter.get_polizas()
        assert len(polizas) >= 1
        assert all(isinstance(p, Poliza) for p in polizas)
        assert all(p.esta_cuadrada() for p in polizas)

    # -- Upload Poliza --
    def test_upload_balanced_poliza(self, adapter):
        adapter.connect()
        result = adapter.upload_poliza(_balanced_poliza())
        assert result["exito"] is True
        assert "id_erp" in result
        assert "fecha_registro" in result

    def test_upload_unbalanced_poliza_fails(self, adapter):
        adapter.connect()
        result = adapter.upload_poliza(_unbalanced_poliza())
        assert result["exito"] is False

    # -- Chart of Accounts --
    def test_get_chart_of_accounts_mock(self, adapter):
        adapter.connect()
        chart = adapter.get_chart_of_accounts()
        assert isinstance(chart, ChartOfAccounts)
        assert len(chart.cuentas) >= 1
        assert chart.ejercicio >= 2025

    # -- Balanza --
    def test_get_balanza_mock(self, adapter):
        adapter.connect()
        balanza = adapter.get_balanza(2026, 1)
        assert isinstance(balanza, BalanzaComprobacion)
        assert balanza.ejercicio == 2026
        assert balanza.mes == 1
        assert len(balanza.cuentas) >= 1
        assert balanza.total_deudor > 0
        assert balanza.total_acreedor > 0

    # -- Date range filtering --
    def test_get_invoices_with_date_range(self, adapter):
        adapter.connect()
        invoices = adapter.get_invoices({"from": "2026-01-01", "to": "2026-12-31"})
        assert len(invoices) >= 1

    # -- Mock fallback --
    def test_uses_mock_without_credentials(self, adapter):
        assert adapter._use_mock is True
        adapter.connect()
        assert adapter._use_mock is True


# =========================================================================
# Desktop ERP Adapters — Mock Mode Tests
# =========================================================================
class TestDesktopAdapters:
    """Test all desktop ERP adapters in mock mode."""

    ADAPTERS = [
        ("CONTPAQiDesktop", CONTPAQiDesktopAdapter),
        ("Peak", PeakAdapter),
        ("Multileg", MultilegAdapter),
        ("Euroweb", EurowebAdapter),
        ("Absis", AbsisAdapter),
    ]

    @pytest.fixture(params=ADAPTERS, ids=[a[0] for a in ADAPTERS])
    def adapter(self, request):
        """Create adapter instance (no DB credentials = mock mode)."""
        cls = request.param[1]
        return cls()

    def test_connect_returns_true(self, adapter):
        assert adapter.connect() is True
        assert adapter.is_connected

    def test_disconnect(self, adapter):
        adapter.connect()
        adapter.disconnect()
        assert not adapter.is_connected

    def test_health_check_mock(self, adapter):
        adapter.connect()
        health = adapter.health_check()
        assert health["status"] == "healthy_mock"
        assert health["mock"] is True

    def test_get_invoices_mock(self, adapter):
        adapter.connect()
        invoices = adapter.get_invoices()
        assert len(invoices) >= 1
        assert all(isinstance(inv, Invoice) for inv in invoices)

    def test_get_polizas_mock(self, adapter):
        adapter.connect()
        polizas = adapter.get_polizas()
        assert len(polizas) >= 1
        assert all(isinstance(p, Poliza) for p in polizas)
        assert all(p.esta_cuadrada() for p in polizas)

    def test_upload_balanced_poliza(self, adapter):
        adapter.connect()
        result = adapter.upload_poliza(_balanced_poliza())
        assert result["exito"] is True

    def test_upload_unbalanced_poliza_fails(self, adapter):
        adapter.connect()
        result = adapter.upload_poliza(_unbalanced_poliza())
        assert result["exito"] is False

    def test_get_chart_of_accounts_mock(self, adapter):
        adapter.connect()
        chart = adapter.get_chart_of_accounts()
        assert isinstance(chart, ChartOfAccounts)
        assert len(chart.cuentas) >= 1

    def test_get_balanza_mock(self, adapter):
        adapter.connect()
        balanza = adapter.get_balanza(2026, 1)
        assert isinstance(balanza, BalanzaComprobacion)
        assert balanza.ejercicio == 2026


# =========================================================================
# QuickBooks Online — Specific Tests
# =========================================================================
class TestQuickBooksOnline:
    def test_default_endpoint(self):
        adapter = QuickBooksOnlineAdapter()
        assert "quickbooks.api.intuit.com" in adapter.config.endpoint

    def test_mock_mode_has_realm_id(self):
        adapter = QuickBooksOnlineAdapter()
        adapter.connect()
        assert "realm_id" in adapter._empresa_info

    def test_upload_returns_id_erp(self):
        adapter = QuickBooksOnlineAdapter()
        adapter.connect()
        result = adapter.upload_poliza(_balanced_poliza())
        assert result["id_erp"].startswith("QB-JE-")


# =========================================================================
# Xero — Specific Tests
# =========================================================================
class TestXero:
    def test_default_endpoint(self):
        adapter = XeroAdapter()
        assert "xero.com" in adapter.config.endpoint

    def test_upload_returns_id_erp(self):
        adapter = XeroAdapter()
        adapter.connect()
        result = adapter.upload_poliza(_balanced_poliza())
        assert result["id_erp"].startswith("XERO-MJ-")


# =========================================================================
# CONTPAQi Web — Specific Tests
# =========================================================================
class TestCONTPAQiWeb:
    def test_default_endpoint(self):
        adapter = CONTPAQiWebAdapter()
        assert "contpaqi.com" in adapter.config.endpoint

    def test_mock_invoices_have_rfc(self):
        adapter = CONTPAQiWebAdapter()
        adapter.connect()
        invoices = adapter.get_invoices()
        assert all(inv.rfc for inv in invoices)

    def test_upload_returns_id_erp(self):
        adapter = CONTPAQiWebAdapter()
        adapter.connect()
        result = adapter.upload_poliza(_balanced_poliza())
        assert result["id_erp"].startswith("CTQ-POL-")


# =========================================================================
# Aspel Cloud — Specific Tests
# =========================================================================
class TestAspelCloud:
    def test_default_endpoint(self):
        adapter = AspelCloudAdapter()
        assert "aspelcloud.com" in adapter.config.endpoint

    def test_upload_returns_id_erp(self):
        adapter = AspelCloudAdapter()
        adapter.connect()
        result = adapter.upload_poliza(_balanced_poliza())
        assert result["id_erp"].startswith("ASP-POL-")


# =========================================================================
# Factor D — Specific Tests
# =========================================================================
class TestFactorD:
    def test_default_endpoint(self):
        adapter = FactorDAdapter()
        assert "factord.com.mx" in adapter.config.endpoint

    def test_upload_returns_id_erp(self):
        adapter = FactorDAdapter()
        adapter.connect()
        result = adapter.upload_poliza(_balanced_poliza())
        assert result["id_erp"].startswith("FD-POL-")


# =========================================================================
# Taxko — Specific Tests
# =========================================================================
class TestTaxko:
    def test_default_endpoint(self):
        adapter = TaxkoAdapter()
        assert "taxko.com" in adapter.config.endpoint

    def test_upload_returns_id_erp(self):
        adapter = TaxkoAdapter()
        adapter.connect()
        result = adapter.upload_poliza(_balanced_poliza())
        assert result["id_erp"].startswith("TK-POL-")


# =========================================================================
# FacturaDirecta — Specific Tests
# =========================================================================
class TestFacturaDirecta:
    def test_default_endpoint(self):
        adapter = FacturaDirectaAdapter()
        assert "facturadirecta.com" in adapter.config.endpoint

    def test_upload_returns_id_erp(self):
        adapter = FacturaDirectaAdapter()
        adapter.connect()
        result = adapter.upload_poliza(_balanced_poliza())
        assert result["id_erp"].startswith("FDX-POL-")


# =========================================================================
# Desktop Adapters — Specific Tests
# =========================================================================
class TestCONTPAQiDesktop:
    def test_default_endpoint(self):
        adapter = CONTPAQiDesktopAdapter()
        assert "CONTPAQi" in adapter.config.endpoint

    def test_mock_version_info(self):
        adapter = CONTPAQiDesktopAdapter()
        adapter.connect()
        assert "version" in adapter._empresa_info
        assert "base_datos" in adapter._empresa_info

    def test_upload_returns_id_erp(self):
        adapter = CONTPAQiDesktopAdapter()
        adapter.connect()
        result = adapter.upload_poliza(_balanced_poliza())
        assert result["id_erp"].startswith("CTQD-POL-")


class TestPeak:
    def test_default_endpoint(self):
        adapter = PeakAdapter()
        assert "Peak" in adapter.config.endpoint

    def test_upload_returns_id_erp(self):
        adapter = PeakAdapter()
        adapter.connect()
        result = adapter.upload_poliza(_balanced_poliza())
        assert result["id_erp"].startswith("PK-POL-")


class TestMultileg:
    def test_default_endpoint(self):
        adapter = MultilegAdapter()
        assert "Multileg" in adapter.config.endpoint

    def test_upload_returns_id_erp(self):
        adapter = MultilegAdapter()
        adapter.connect()
        result = adapter.upload_poliza(_balanced_poliza())
        assert result["id_erp"].startswith("MLG-POL-")


class TestEuroweb:
    def test_default_endpoint(self):
        adapter = EurowebAdapter()
        assert "Euroweb" in adapter.config.endpoint

    def test_upload_returns_id_erp(self):
        adapter = EurowebAdapter()
        adapter.connect()
        result = adapter.upload_poliza(_balanced_poliza())
        assert result["id_erp"].startswith("EWB-POL-")


class TestAbsis:
    def test_default_endpoint(self):
        adapter = AbsisAdapter()
        assert "Absis" in adapter.config.endpoint

    def test_upload_returns_id_erp(self):
        adapter = AbsisAdapter()
        adapter.connect()
        result = adapter.upload_poliza(_balanced_poliza())
        assert result["id_erp"].startswith("ABS-POL-")


# =========================================================================
# HTTP Client Tests
# =========================================================================
class TestHTTPClient:
    def test_erp_api_error(self):
        err = ERPAPIError("test error", status_code=500, attempts=3)
        assert str(err) == "test error"
        assert err.status_code == 500
        assert err.attempts == 3

    def test_erp_auth_error(self):
        err = ERPAuthError("auth failed", status_code=401)
        assert isinstance(err, ERPAPIError)
        assert err.status_code == 401

    def test_erp_connection_error(self):
        err = ERPConnectionError("connection refused", attempts=3)
        assert isinstance(err, ERPAPIError)
        assert err.attempts == 3


# =========================================================================
# Abstract Base Tests
# =========================================================================
class TestERPAdapterBase:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            ERPAdapter(ERPConfig(type=ERPType.GENERIC))

    def test_ensure_connected_raises(self):
        adapter = QuickBooksOnlineAdapter()
        with pytest.raises(ERPAdapterError):
            adapter._ensure_connected()

    def test_test_connection_when_not_connected(self):
        adapter = QuickBooksOnlineAdapter()
        result = adapter.test_connection()
        assert result["status"] == "error"

    def test_test_connection_when_connected(self):
        adapter = QuickBooksOnlineAdapter()
        adapter.connect()
        result = adapter.test_connection()
        assert result["status"] == "connected"


# =========================================================================
# Poliza Model Tests
# =========================================================================
class TestPolizaModel:
    def test_balanced_poliza(self):
        p = _balanced_poliza()
        assert p.esta_cuadrada()
        debe, haber = p.calcular_totales()
        assert debe == haber == 10000

    def test_unbalanced_poliza(self):
        p = _unbalanced_poliza()
        assert not p.esta_cuadrada()


# =========================================================================
# Environment Variable Fallback Tests
# =========================================================================
class TestEnvFallback:
    """Verify adapters fall back to mock when env vars are not set."""

    def test_quickbooks_uses_mock_without_env(self, monkeypatch):
        monkeypatch.delenv("QUICKBOOKS_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("QUICKBOOKS_REALM_ID", raising=False)
        adapter = QuickBooksOnlineAdapter()
        adapter.connect()
        assert adapter._use_mock is True

    def test_xero_uses_mock_without_env(self, monkeypatch):
        monkeypatch.delenv("XERO_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("XERO_TENANT_ID", raising=False)
        adapter = XeroAdapter()
        adapter.connect()
        assert adapter._use_mock is True

    def test_contpaqi_web_uses_mock_without_env(self, monkeypatch):
        monkeypatch.delenv("CONTPAQi_API_KEY", raising=False)
        adapter = CONTPAQiWebAdapter()
        adapter.connect()
        assert adapter._use_mock is True

    def test_aspel_uses_mock_without_env(self, monkeypatch):
        monkeypatch.delenv("ASPEL_API_KEY", raising=False)
        adapter = AspelCloudAdapter()
        adapter.connect()
        assert adapter._use_mock is True

    def test_factor_d_uses_mock_without_env(self, monkeypatch):
        monkeypatch.delenv("FACTOR_D_CLIENT_ID", raising=False)
        adapter = FactorDAdapter()
        adapter.connect()
        assert adapter._use_mock is True

    def test_taxko_uses_mock_without_env(self, monkeypatch):
        monkeypatch.delenv("TAXKO_API_KEY", raising=False)
        adapter = TaxkoAdapter()
        adapter.connect()
        assert adapter._use_mock is True

    def test_facturadirecta_uses_mock_without_env(self, monkeypatch):
        monkeypatch.delenv("FDIRECTA_API_KEY", raising=False)
        adapter = FacturaDirectaAdapter()
        adapter.connect()
        assert adapter._use_mock is True

    def test_desktop_adapters_use_mock_without_env(self, monkeypatch):
        monkeypatch.delenv("CONTPAQi_DB_HOST", raising=False)
        monkeypatch.delenv("CONTPAQi_DB_NAME", raising=False)
        adapter = CONTPAQiDesktopAdapter()
        adapter.connect()
        assert adapter._use_mock is True
