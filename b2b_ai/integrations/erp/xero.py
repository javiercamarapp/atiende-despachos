# -*- coding: utf-8 -*-
"""
xero.py — Production-ready adapter for Xero Accounting (REST API).

Uses httpx for real API calls with OAuth 2.0 authentication.
Falls back to mock data when XERO_ACCESS_TOKEN is not set.
"""
from __future__ import annotations

import logging
import os
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.erp.adapter import ERPAdapter, ERPAdapterError
from b2b_ai.integrations.erp.http_client import (
    ERPAPIError, ERPAuthError, make_request,
)
from b2b_ai.integrations.erp.models import (
    BalanzaComprobacion, ChartOfAccounts, CuentaContable, CuentaPoliza,
    ERPConfig, ERPType, Invoice, Poliza, StatusPoliza, TipoCuenta,
)

logger = logging.getLogger(__name__)


class XeroAdapter(ERPAdapter):
    """Production adapter for Xero Accounting.

    Connects to the Xero API (https://api.xero.com/api.xro/2.0/).
    Uses OAuth 2.0 for authentication. Falls back to mock when credentials
    are not configured (env vars: XERO_ACCESS_TOKEN, XERO_TENANT_ID).
    """

    def __init__(self, config: Optional[ERPConfig] = None):
        config = config or ERPConfig(type=ERPType.XERO)
        config.endpoint = config.endpoint or os.environ.get(
            "XERO_ENDPOINT", "https://api.xero.com/api.xro/2.0/"
        )
        super().__init__(config=config)
        self._access_token: Optional[str] = None
        self._tenant_id: Optional[str] = None
        self._use_mock: bool = True

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        creds = credentials or {}
        token = creds.get("access_token") or os.environ.get("XERO_ACCESS_TOKEN")
        tenant = creds.get("tenant_id") or os.environ.get("XERO_TENANT_ID")

        if token and tenant:
            self._access_token = token
            self._tenant_id = tenant
            self._use_mock = False
            logger.info("XeroAdapter: connecting to Xero (real)...")
            try:
                resp = make_request(
                    "GET",
                    f"{self.config.endpoint}connections",
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "Accept": "application/json",
                    },
                    timeout=self.config.timeout,
                    retry_attempts=self.config.retry_attempts,
                )
                connections = resp.json()
                self._empresa_info = {
                    "nombre": connections[0].get("tenantName", "Xero Company") if connections else "Xero Company",
                    "rfc": "N/A",
                    "ejercicio": datetime.now().year,
                    "tenant_id": self._tenant_id,
                }
            except ERPAuthError as e:
                raise ERPAdapterError(f"Xero authentication failed: {e.message}", code="AUTH_FAILED")
            except ERPAPIError as e:
                raise ERPAdapterError(f"Xero connection failed: {e.message}", code="CONNECTION_FAILED")
        else:
            self._use_mock = True
            self._empresa_info = {
                "nombre": "Empresa Xero Mock Ltd",
                "rfc": "XRO010101AAA", "ejercicio": 2026,
                "tenant_id": "XERO-TENANT-789",
            }
            logger.info("XeroAdapter: using mock (no credentials)")

        self._connected = True
        logger.info(f"XeroAdapter: connected (mock={self._use_mock})")
        return True

    def disconnect(self) -> None:
        self._connected = False
        self._access_token = None
        self._tenant_id = None
        self._empresa_info = {}
        logger.info("XeroAdapter: disconnected")

    def _xero_request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        self._ensure_connected()
        if self._use_mock:
            raise ERPAdapterError("Cannot make real API call in mock mode", code="MOCK_MODE")
        url = f"{self.config.endpoint}{path}"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Xero-Tenant-Id": self._tenant_id,
            "Accept": "application/json",
        }
        headers.update(kwargs.pop("headers", {}))
        resp = make_request(method, url, headers=headers,
                           timeout=self.config.timeout,
                           retry_attempts=self.config.retry_attempts, **kwargs)
        return resp.json()

    def get_invoices(self, date_range: Optional[Dict[str, str]] = None) -> List[Invoice]:
        self._ensure_connected()
        if self._use_mock:
            return self._mock_invoices()
        try:
            path = "Invoices"
            params = {}
            if date_range:
                if date_range.get("from"):
                    params["where"] = f"Date >= DateTime({date_range['from']})"
            data = self._xero_request("GET", path, params=params)
            invoices = []
            for inv in data.get("Invoices", []):
                invoices.append(Invoice(
                    id=inv.get("InvoiceID", ""),
                    rfc=inv.get("Contact", {}).get("Name", ""),
                    fecha=inv.get("Date", "")[:10],
                    monto=float(inv.get("Total", 0)),
                    subtotal=float(inv.get("SubTotal", 0)),
                    iva=float(inv.get("TotalTax", 0)),
                    status="activa" if inv.get("Status") == "AUTHORISED" else inv.get("Status", ""),
                    concepto=inv.get("Reference", "") or inv.get("InvoiceNumber", ""),
                    serie=inv.get("InvoiceNumber", ""),
                    folio=inv.get("InvoiceNumber", ""),
                    moneda=inv.get("CurrencyCode", "MXN"),
                ))
            return invoices
        except ERPAPIError as e:
            logger.error(f"Xero get_invoices error: {e.message}")
            raise ERPAdapterError(f"Failed to get invoices: {e.message}", code="API_ERROR")

    def _mock_invoices(self) -> List[Invoice]:
        now = datetime.now().strftime("%Y-%m-%d")
        return [
            Invoice(
                id=f"XERO-INV-{i:04d}", uuid=str(_uuid.uuid4()),
                rfc="EEE050505EEE", fecha=now,
                monto=round(30000 + i * 4000, 2),
                subtotal=round(25862.07 + i * 3448.28, 2),
                iva=round(4137.93 + i * 551.72, 2),
                status="activa", concepto=f"Xero invoice {i}",
                serie="XERO", folio=str(5000 + i), moneda="MXN",
            )
            for i in range(1, 4)
        ]

    def get_polizas(self, date_range: Optional[Dict[str, str]] = None) -> List[Poliza]:
        self._ensure_connected()
        if self._use_mock:
            return self._mock_polizas()
        try:
            data = self._xero_request("GET", "ManualJournals")
            polizas = []
            for mj in data.get("ManualJournals", []):
                lines = []
                for line in mj.get("JournalLines", []):
                    lines.append(CuentaPoliza(
                        cuenta=line.get("AccountCode", ""),
                        descripcion=line.get("Description", ""),
                        debe=float(line.get("LineAmount", 0)) if line.get("LineType") == "DEBIT" else 0,
                        haber=float(line.get("LineAmount", 0)) if line.get("LineType") == "CREDIT" else 0,
                    ))
                total = sum(c.debe for c in lines)
                polizas.append(Poliza(
                    id=mj.get("ManualJournalID", ""),
                    fecha=mj.get("JournalDate", "")[:10],
                    concepto=mj.get("Narration", ""),
                    tipo="Diario", cuentas=lines,
                    monto_total=total, status=StatusPoliza.CONTABILIZADA,
                ))
            return polizas
        except ERPAPIError as e:
            logger.error(f"Xero get_polizas error: {e.message}")
            raise ERPAdapterError(f"Failed to get polizas: {e.message}", code="API_ERROR")

    def _mock_polizas(self) -> List[Poliza]:
        now = datetime.now().strftime("%Y-%m-%d")
        return [
            Poliza(
                id=f"XERO-POL-{i:04d}", fecha=now,
                concepto=f"Manual journal {i}", tipo="Diario", numero=i,
                cuentas=[
                    CuentaPoliza(cuenta="090", descripcion="Bank Account", debe=15000 * i, haber=0),
                    CuentaPoliza(cuenta="200", descripcion="Sales", debe=0, haber=15000 * i),
                ],
                monto_total=15000 * i, status=StatusPoliza.CONTABILIZADA,
            )
            for i in range(1, 3)
        ]

    def upload_poliza(self, poliza: Poliza) -> Dict[str, Any]:
        self._ensure_connected()
        if not poliza.esta_cuadrada():
            return {"exito": False, "mensaje": "Manual journal not balanced"}
        if self._use_mock:
            return {
                "exito": True, "id_erp": f"XERO-MJ-{_uuid.uuid4().hex[:8].upper()}",
                "mensaje": "Manual journal created (mock Xero)",
                "fecha_registro": datetime.now().isoformat(),
            }
        try:
            lines = []
            for c in poliza.cuentas:
                if c.debe > 0:
                    lines.append({
                        "LineType": "DEBIT", "AccountCode": c.cuenta,
                        "Description": c.descripcion, "LineAmount": c.debe,
                    })
                if c.haber > 0:
                    lines.append({
                        "LineType": "CREDIT", "AccountCode": c.cuenta,
                        "Description": c.descripcion, "LineAmount": c.haber,
                    })
            body = {"ManualJournals": [{"Narration": poliza.concepto, "JournalLines": lines}]}
            data = self._xero_request("POST", "ManualJournals", json_body=body)
            mj = data.get("ManualJournals", [{}])[0] if data.get("ManualJournals") else {}
            return {
                "exito": True, "id_erp": mj.get("ManualJournalID", ""),
                "mensaje": "Manual journal created (Xero)",
                "fecha_registro": datetime.now().isoformat(),
            }
        except ERPAPIError as e:
            logger.error(f"Xero upload_poliza error: {e.message}")
            return {"exito": False, "mensaje": str(e.message)}

    def get_chart_of_accounts(self) -> ChartOfAccounts:
        self._ensure_connected()
        if self._use_mock:
            return self._mock_chart()
        try:
            data = self._xero_request("GET", "Accounts")
            cuentas = []
            for acc in data.get("Accounts", []):
                tipo_map = {
                    "CURRENT": TipoCuenta.ACTIVO, "CURRLIAB": TipoCuenta.PASIVO,
                    "EQUITY": TipoCuenta.CAPITAL, "REVENUE": TipoCuenta.INGRESO,
                    "EXPENSE": TipoCuenta.GASTO, "FIXED": TipoCuenta.ACTIVO,
                }
                cuentas.append(CuentaContable(
                    clave=acc.get("Code", ""),
                    nombre=acc.get("Name", ""),
                    tipo=tipo_map.get(acc.get("Type", ""), TipoCuenta.ACTIVO),
                    saldo=float(acc.get("Balance", 0)),
                ))
            return ChartOfAccounts(
                empresa=self._empresa_info.get("nombre", ""),
                ejercicio=datetime.now().year, cuentas=cuentas,
                fecha_exportacion=datetime.now().isoformat(),
            )
        except ERPAPIError as e:
            raise ERPAdapterError(f"Failed to get chart: {e.message}", code="API_ERROR")

    def _mock_chart(self) -> ChartOfAccounts:
        return ChartOfAccounts(
            empresa=self._empresa_info.get("nombre", ""),
            ejercicio=2026,
            cuentas=[
                CuentaContable(clave="090", nombre="Bank Account", tipo=TipoCuenta.ACTIVO),
                CuentaContable(clave="100", nombre="Accounts Receivable", tipo=TipoCuenta.ACTIVO),
                CuentaContable(clave="200", nombre="Sales", tipo=TipoCuenta.INGRESO),
                CuentaContable(clave="210", nombre="Other Income", tipo=TipoCuenta.INGRESO),
                CuentaContable(clave="310", nombre="Accounts Payable", tipo=TipoCuenta.PASIVO),
                CuentaContable(clave="400", nombre="Expenses", tipo=TipoCuenta.GASTO),
                CuentaContable(clave="410", nombre="Cost of Goods Sold", tipo=TipoCuenta.GASTO),
                CuentaContable(clave="500", nombre="Equity", tipo=TipoCuenta.CAPITAL),
            ],
            fecha_exportacion=datetime.now().isoformat(),
        )

    def get_balanza(self, ejercicio: int, mes: int) -> BalanzaComprobacion:
        self._ensure_connected()
        if self._use_mock:
            return self._mock_balanza(ejercicio, mes)
        try:
            data = self._xero_request("GET", "Reports/BalanceSheet")
            rows = []
            for section in data.get("reports", [{}])[0].get("Rows", []):
                for row in section.get("Rows", []):
                    cells = row.get("Cells", [])
                    if len(cells) >= 2:
                        rows.append({
                            "cuenta": cells[0].get("Value", ""),
                            "nombre": cells[0].get("Value", ""),
                            "deudor": float(cells[1].get("Value", 0) or 0) if float(cells[1].get("Value", 0) or 0) > 0 else 0,
                            "acreedor": abs(float(cells[1].get("Value", 0) or 0)) if float(cells[1].get("Value", 0) or 0) < 0 else 0,
                        })
            return BalanzaComprobacion(
                ejercicio=ejercicio, mes=mes,
                rfc=self._empresa_info.get("rfc", ""),
                cuentas=rows,
                total_deudor=sum(r["deudor"] for r in rows),
                total_acreedor=sum(r["acreedor"] for r in rows),
                fecha_generacion=datetime.now().isoformat(),
            )
        except ERPAPIError as e:
            raise ERPAdapterError(f"Failed to get balanza: {e.message}", code="API_ERROR")

    def _mock_balanza(self, ejercicio: int, mes: int) -> BalanzaComprobacion:
        cuentas = [
            {"cuenta": "090", "nombre": "Bank Account", "deudor": 110000, "acreedor": 0},
            {"cuenta": "100", "nombre": "Accounts Receivable", "deudor": 45000, "acreedor": 0},
            {"cuenta": "310", "nombre": "Accounts Payable", "deudor": 0, "acreedor": 40000},
            {"cuenta": "500", "nombre": "Equity", "deudor": 0, "acreedor": 120000},
            {"cuenta": "200", "nombre": "Sales", "deudor": 0, "acreedor": 220000},
            {"cuenta": "400", "nombre": "Expenses", "deudor": 85000, "acreedor": 0},
        ]
        return BalanzaComprobacion(
            ejercicio=ejercicio, mes=mes,
            rfc=self._empresa_info.get("rfc", ""),
            cuentas=cuentas,
            total_deudor=sum(c["deudor"] for c in cuentas),
            total_acreedor=sum(c["acreedor"] for c in cuentas),
            fecha_generacion=datetime.now().isoformat(),
        )

    def health_check(self) -> Dict[str, Any]:
        result = {"adapter": self.name, "mock": self._use_mock, "connected": self._connected}
        if not self._connected:
            result["status"] = "disconnected"
            return result
        if self._use_mock:
            result["status"] = "healthy_mock"
            return result
        try:
            self._xero_request("GET", "connections")
            result["status"] = "healthy"
        except Exception as e:
            result["status"] = "unhealthy"
            result["error"] = str(e)
        return result
