# -*- coding: utf-8 -*-
"""
quickbooks.py — Backward-compatibility shim for QuickBooks ERP integration.

DEPRECATED: Use b2b_ai.integrations.erp.quickbooks.QuickBooksOnlineAdapter instead.
This module re-exports QuickBooksOnlineAdapter and provides QuickBooksConnector
as a legacy wrapper for backward compatibility with existing tests and consumers
that use the ERPInterface / AbstractERPConnector contract.

Migration path:
    # OLD (deprecated):
    from b2b_ai.erp.quickbooks import QuickBooksConnector
    q = QuickBooksConnector(mock=True)

    # NEW (recommended):
    from b2b_ai.integrations.erp.quickbooks import QuickBooksOnlineAdapter
    adapter = QuickBooksOnlineAdapter()
    adapter.connect()
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from b2b_ai.erp.base import ERPInterface
from b2b_ai.erp.connector import AbstractERPConnector, _dec, cuentas_para_categoria

# Re-export production adapter for consumers migrating to the new interface
from b2b_ai.integrations.erp.quickbooks import QuickBooksOnlineAdapter  # noqa: F401

QBO_API_BASE = "https://quickbooks.api.intuit.com/v3"
QBO_MOCK_MODE = os.environ.get("QBO_MOCK_MODE", "1") == "1"


class QuickBooksConnector(AbstractERPConnector, ERPInterface):
    """Legacy connector for QuickBooks Online — wraps mock logic.

    .. deprecated::
        Use :class:`b2b_ai.integrations.erp.quickbooks.QuickBooksOnlineAdapter`
        for production use. This class is retained only for backward compatibility
        with the ERPInterface / AbstractERPConnector contract.
    """

    backend = "QuickBooks Online"

    _CATALOGO = [
        {"codigo": "1010", "descripcion": "Efectivo", "tipo": "deudora", "qbo_type": "Bank"},
        {"codigo": "1020", "descripcion": "Cuentas por cobrar", "tipo": "deudora", "qbo_type": "AccountsReceivable"},
        {"codigo": "1110", "descripcion": "Inventarios", "tipo": "deudora", "qbo_type": "OtherCurrentAsset"},
        {"codigo": "1130", "descripcion": "Bancos", "tipo": "deudora", "qbo_type": "Bank"},
        {"codigo": "1150", "descripcion": "Prepagos", "tipo": "deudora", "qbo_type": "OtherCurrentAsset"},
        {"codigo": "1210", "descripcion": "Mobiliario y equipo", "tipo": "deudora", "qbo_type": "FixedAsset"},
        {"codigo": "1115", "descripcion": "Gastos de instalación", "tipo": "deudora", "qbo_type": "OtherAsset"},
        {"codigo": "2010", "descripcion": "Proveedores", "tipo": "acreedora", "qbo_type": "AccountsPayable"},
        {"codigo": "2020", "descripcion": "Impuestos por pagar", "tipo": "acreedora", "qbo_type": "OtherCurrentLiability"},
        {"codigo": "2030", "descripcion": "IVA acreditable", "tipo": "acreedora", "qbo_type": "OtherCurrentLiability"},
        {"codigo": "3010", "descripcion": "Capital social", "tipo": "acreedora", "qbo_type": "Equity"},
        {"codigo": "3020", "descripcion": "Resultados acumulados", "tipo": "acreedora", "qbo_type": "Equity"},
        {"codigo": "4010", "descripcion": "Ingresos por servicios", "tipo": "acreedora", "qbo_type": "Income"},
        {"codigo": "4020", "descripcion": "Ingresos por ventas", "tipo": "acreedora", "qbo_type": "Income"},
        {"codigo": "5010", "descripcion": "Costo de servicios", "tipo": "deudora", "qbo_type": "CostOfGoodsSold"},
        {"codigo": "6100", "descripcion": "Gastos por clasificar", "tipo": "deudora", "qbo_type": "Expense"},
        {"codigo": "6110", "descripcion": "Sueldos y salarios", "tipo": "deudora", "qbo_type": "Expense"},
        {"codigo": "6131", "descripcion": "Gastos generales", "tipo": "deudora", "qbo_type": "Expense"},
        {"codigo": "6140", "descripcion": "Gastos de viaje", "tipo": "deudora", "qbo_type": "Expense"},
        {"codigo": "6150", "descripcion": "Servicios profesionales", "tipo": "deudora", "qbo_type": "Expense"},
        {"codigo": "6160", "descripcion": "Mantenimiento y reparaciones", "tipo": "deudora", "qbo_type": "Expense"},
    ]

    def __init__(
        self,
        empresa: str = "Despacho Demo",
        company_id: str | None = None,
        access_token: str | None = None,
        mock: bool | None = None,
    ):
        super().__init__(empresa)
        self.company_id = company_id or os.environ.get("QBO_COMPANY_ID", "")
        self.access_token = access_token or os.environ.get("QBO_ACCESS_TOKEN", "")
        if mock is not None:
            self._mock = mock
        else:
            self._mock = bool(QBO_MOCK_MODE)
        self._accounts_cache: list[dict] | None = None

    # ------------------------------------------------------------------
    # AbstractERPConnector (Phase 2 contract)
    # ------------------------------------------------------------------

    def create_voucher(self, voucher: dict) -> dict:
        """Crea un JournalEntry (póliza) en QuickBooks Online."""
        folio = voucher.get("folio_fiscal") or voucher.get("concepto")
        if not folio:
            return {
                "ok": False,
                "poliza": None,
                "status": "error",
                "audit_ref": self._audit_ref("QBO"),
                "message": "Sin folio fiscal para registrar la póliza.",
            }

        categoria = voucher.get("categoria", "desconocido")
        cargo, abono = cuentas_para_categoria(categoria)
        total = _dec(voucher.get("total"))
        poliza_id = "QBO-" + uuid.uuid4().hex[:10].upper()

        entry = {
            "poliza": poliza_id,
            "folio_fiscal": folio,
            "emisor_rfc": voucher.get("emisor_rfc", ""),
            "total": total,
            "fecha": voucher.get("fecha", ""),
            "categoria": categoria,
            "cuenta_cargo": cargo,
            "cuenta_abono": abono,
            "fecha_registro": self._now(),
            "status": "registrada",
        }

        self._polizas[folio] = entry
        status_msg = "registrada" if self._mock else "registrada (mock — real API requires OAuth token refresh)"
        return {
            "ok": True,
            "poliza": poliza_id,
            "cuenta_cargo": cargo,
            "cuenta_abono": abono,
            "status": status_msg,
            "audit_ref": self._audit_ref("QBO"),
            "message": f"Póliza {poliza_id} registrada en QuickBooks Online (mock).",
        }

    def get_account_catalog(self) -> list:
        """Catálogo de cuentas del ERP."""
        if self._accounts_cache is not None:
            return self._accounts_cache
        self._accounts_cache = list(self._CATALOGO)
        return self._accounts_cache

    def check_connection(self) -> dict:
        """Verifica la conexión con QuickBooks Online."""
        if self._mock:
            return {
                "ok": True,
                "backend": f"{self.backend} (mock)",
                "audit_ref": self._audit_ref("QBO"),
                "audited_at": self._now(),
                "detail": "QuickBooks Online API simulada operativa (sin conexión real).",
            }
        return {
            "ok": bool(self.company_id and self.access_token),
            "backend": self.backend,
            "audit_ref": self._audit_ref("QBO"),
            "audited_at": self._now(),
            "detail": (
                f"Company ID: {self.company_id[:8]}..."
                if self.company_id
                else "Sin QBO_COMPANY_ID configurado."
            ),
        }

    # ------------------------------------------------------------------
    # ERPInterface (legacy contract)
    # ------------------------------------------------------------------

    def register_invoice(self, invoice: dict) -> dict:
        """Alias de create_voucher para compatibilidad con ERPInterface."""
        return self.create_voucher(invoice)

    def get_invoice(self, folio_fiscal: str) -> dict | None:
        """Consulta una póliza por folio fiscal."""
        return self._polizas.get(folio_fiscal)

    def health(self) -> dict:
        """Health check compatible con ERPInterface."""
        conn = self.check_connection()
        backend_label = f"{self.backend} (mock)" if self._mock else self.backend
        return {
            "ok": conn["ok"],
            "backend": backend_label,
            "detail": conn["detail"],
            "mock": self._mock,
            "company_id": self.company_id[:8] + "..." if self.company_id else None,
            "voucher_count": len(self._polizas),
        }

    # ------------------------------------------------------------------
    # QBO-specific helpers (legacy interface)
    # ------------------------------------------------------------------

    def create_bill(self, vendor_name: str, line_items: list[dict],
                    due_date: str | None = None) -> dict:
        """Crea un Bill (factura de proveedor) en QBO."""
        bill_id = "QBO-BILL-" + uuid.uuid4().hex[:8].upper()
        total = sum(_dec(item.get("amount", 0)) for item in line_items)
        return {
            "ok": True,
            "bill_id": bill_id,
            "vendor": vendor_name,
            "total": total,
            "due_date": due_date or "",
            "status": "draft",
            "message": f"Bill {bill_id} creado para {vendor_name} (mock).",
        }

    def create_invoice(self, customer_name: str, line_items: list[dict],
                       due_date: str | None = None) -> dict:
        """Crea una Invoice (factura de venta) en QBO."""
        invoice_id = "QBO-INV-" + uuid.uuid4().hex[:8].upper()
        total = sum(_dec(item.get("amount", 0)) for item in line_items)
        return {
            "ok": True,
            "invoice_id": invoice_id,
            "customer": customer_name,
            "total": total,
            "due_date": due_date or "",
            "status": "draft",
            "message": f"Invoice {invoice_id} creado para {customer_name} (mock).",
        }

    def list_vendors(self, max_results: int = 100) -> list[dict]:
        """Lista proveedores de QBO."""
        if self._mock:
            return [
                {"id": "1", "name": "Proveedor Demo A", "balance": 0},
                {"id": "2", "name": "Proveedor Demo B", "balance": 15000},
            ]
        return []

    def list_customers(self, max_results: int = 100) -> list[dict]:
        """Lista clientes de QBO."""
        if self._mock:
            return [
                {"id": "1", "name": "Cliente Demo A", "balance": 5000},
                {"id": "2", "name": "Cliente Demo B", "balance": 0},
            ]
        return []
