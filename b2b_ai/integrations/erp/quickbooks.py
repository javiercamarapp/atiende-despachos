# -*- coding: utf-8 -*-
"""
quickbooks.py — Production-ready adapter for QuickBooks Online (REST API v3).

Uses httpx for real API calls with OAuth 2.0 authentication.
Falls back to mock data when QUICKBOOKS_ACCESS_TOKEN is not set.
"""
from __future__ import annotations

import logging
import os
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.erp.adapter import ERPAdapter, ERPAdapterError
from b2b_ai.integrations.erp.http_client import (
    ERPAPIError,
    ERPAuthError,
    ERPConnectionError,
    make_request,
)
from b2b_ai.integrations.erp.models import (
    BalanzaComprobacion,
    ChartOfAccounts,
    CuentaContable,
    CuentaPoliza,
    ERPConfig,
    ERPType,
    Invoice,
    Poliza,
    StatusPoliza,
    TipoCuenta,
)

logger = logging.getLogger(__name__)


class QuickBooksOnlineAdapter(ERPAdapter):
    """Production adapter for QuickBooks Online.

    Connects to the QuickBooks API REST v3 (https://developer.intuit.com).
    Uses OAuth 2.0 for authentication. Falls back to mock when credentials
    are not configured (env vars: QUICKBOOKS_ACCESS_TOKEN, QUICKBOOKS_REALM_ID).
    """

    def __init__(self, config: Optional[ERPConfig] = None):
        config = config or ERPConfig(type=ERPType.QUICKBOOKS_ONLINE)
        config.endpoint = config.endpoint or os.environ.get(
            "QUICKBOOKS_ENDPOINT", "https://quickbooks.api.intuit.com/v3"
        )
        super().__init__(config=config)
        self._access_token: Optional[str] = None
        self._realm_id: Optional[str] = None
        self._use_mock: bool = True

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------
    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Connect to QuickBooks Online.

        Real mode: Uses QUICKBOOKS_ACCESS_TOKEN + QUICKBOOKS_REALM_ID env vars.
        Mock mode: When env vars are not set.
        """
        creds = credentials or {}
        token = creds.get("access_token") or os.environ.get("QUICKBOOKS_ACCESS_TOKEN")
        realm_id = creds.get("realm_id") or os.environ.get("QUICKBOOKS_REALM_ID")

        if token and realm_id:
            self._access_token = token
            self._realm_id = realm_id
            self._use_mock = False
            logger.info(f"QuickBooksOnlineAdapter: connecting to QuickBooks Online (real)...")
            try:
                resp = make_request(
                    "GET",
                    f"{self.config.endpoint}/company/{realm_id}/companyinfo/{realm_id}",
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "Accept": "application/json",
                    },
                    timeout=self.config.timeout,
                    retry_attempts=self.config.retry_attempts,
                )
                data = resp.json()
                company = data.get("CompanyInfo", {})
                self._empresa_info = {
                    "nombre": company.get("CompanyName", "QuickBooks Company"),
                    "rfc": "N/A",
                    "ejercicio": datetime.now().year,
                    "company_id": realm_id,
                    "realm_id": realm_id,
                }
            except ERPAuthError as e:
                logger.error(f"QuickBooks auth failed: {e.message}")
                raise ERPAdapterError(
                    f"QuickBooks authentication failed: {e.message}",
                    code="AUTH_FAILED",
                )
            except ERPAPIError as e:
                logger.error(f"QuickBooks connect error: {e.message}")
                raise ERPAdapterError(
                    f"QuickBooks connection failed: {e.message}",
                    code="CONNECTION_FAILED",
                )
        else:
            self._use_mock = True
            self._empresa_info = {
                "nombre": "Empresa QB Mock S.A. DE C.V.",
                "rfc": "QBZ010101AAA",
                "ejercicio": 2026,
                "company_id": "QB-MOCK-123",
                "realm_id": "QB-REALM-456",
            }
            logger.info("QuickBooksOnlineAdapter: using mock (no credentials)")

        self._connected = True
        logger.info(f"QuickBooksOnlineAdapter: connected (mock={self._use_mock})")
        return True

    def disconnect(self) -> None:
        self._connected = False
        self._access_token = None
        self._realm_id = None
        self._empresa_info = {}
        logger.info("QuickBooksOnlineAdapter: disconnected")

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------
    def _qbo_request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        """Make an authenticated request to QuickBooks API."""
        self._ensure_connected()
        if self._use_mock:
            raise ERPAdapterError("Cannot make real API call in mock mode", code="MOCK_MODE")
        url = f"{self.config.endpoint}/company/{self._realm_id}/{path}"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
        }
        headers.update(kwargs.pop("headers", {}))
        resp = make_request(
            method, url, headers=headers,
            timeout=self.config.timeout,
            retry_attempts=self.config.retry_attempts,
            **kwargs,
        )
        return resp.json()

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------
    def get_invoices(self, date_range: Optional[Dict[str, str]] = None) -> List[Invoice]:
        self._ensure_connected()
        if self._use_mock:
            return self._mock_invoices()

        try:
            query = "SELECT * FROM Invoice MAXRESULTS 100"
            if date_range:
                start = date_range.get("from", "")
                end = date_range.get("to", "")
                if start and end:
                    query += f" WHERE TxnDate >= \'{start}\' AND TxnDate <= \'{end}\'"
            data = self._qbo_request("GET", f"query?query={query}")
            invoices = []
            for inv in data.get("QueryResponse", {}).get("Invoice", []):
                invoices.append(Invoice(
                    id=str(inv.get("Id", "")),
                    uuid=inv.get("SyncToken", ""),
                    rfc=inv.get("CustomerRef", {}).get("name", ""),
                    fecha=inv.get("TxnDate", ""),
                    monto=float(inv.get("TotalAmt", 0)),
                    subtotal=float(inv.get("Balance", 0)),
                    iva=float(inv.get("GlobalTaxCalculation", {}).replace("TaxInclusive", "0") or 0),
                    status="activa" if inv.get("Balance", 0) > 0 else "pagada",
                    concepto=inv.get("DocNumber", ""),
                    serie=inv.get("DocNumber", ""),
                    folio=inv.get("DocNumber", ""),
                    moneda=inv.get("CurrencyRef", {}).get("value", "MXN"),
                ))
            return invoices
        except ERPAPIError as e:
            logger.error(f"QuickBooks get_invoices error: {e.message}")
            raise ERPAdapterError(f"Failed to get invoices: {e.message}", code="API_ERROR")

    def _mock_invoices(self) -> List[Invoice]:
        now = datetime.now().strftime("%Y-%m-%d")
        return [
            Invoice(
                id=f"QB-INV-{i:04d}", uuid=str(_uuid.uuid4()),
                rfc="DDD040404DDD", fecha=now,
                monto=round(25000 + i * 5000, 2),
                subtotal=round(21551.72 + i * 4310.34, 2),
                iva=round(3448.28 + i * 689.66, 2),
                status="activa", concepto=f"Service invoice {i}",
                serie="QB", folio=str(4000 + i), moneda="MXN",
                forma_pago="03", metodo_pago="PUE",
            )
            for i in range(1, 4)
        ]

    # ------------------------------------------------------------------
    # Polizas (Journal Entries)
    # ------------------------------------------------------------------
    def get_polizas(self, date_range: Optional[Dict[str, str]] = None) -> List[Poliza]:
        self._ensure_connected()
        if self._use_mock:
            return self._mock_polizas()

        try:
            data = self._qbo_request("GET", "query?query=SELECT * FROM JournalEntry MAXRESULTS 100")
            polizas = []
            for je in data.get("QueryResponse", {}).get("JournalEntry", []):
                line_items = []
                for line in je.get("Line", []):
                    detail = line.get("JournalEntryLineDetail", {})
                    posting = detail.get("PostingType", "Debit")
                    account = detail.get("AccountRef", {})
                    line_items.append(CuentaPoliza(
                        cuenta=account.get("value", ""),
                        descripcion=account.get("name", ""),
                        debe=float(line.get("Amount", 0)) if posting == "Debit" else 0,
                        haber=float(line.get("Amount", 0)) if posting == "Credit" else 0,
                    ))
                total = sum(c.debe for c in line_items)
                polizas.append(Poliza(
                    id=str(je.get("Id", "")),
                    fecha=je.get("TxnDate", ""),
                    concepto=f"Journal Entry {je.get('DocNumber', '')}",
                    tipo="Diario", numero=int(je.get("DocNumber", 0) or 0),
                    cuentas=line_items, monto_total=total,
                    status=StatusPoliza.CONTABILIZADA,
                ))
            return polizas
        except ERPAPIError as e:
            logger.error(f"QuickBooks get_polizas error: {e.message}")
            raise ERPAdapterError(f"Failed to get polizas: {e.message}", code="API_ERROR")

    def _mock_polizas(self) -> List[Poliza]:
        now = datetime.now().strftime("%Y-%m-%d")
        return [
            Poliza(
                id=f"QB-POL-{i:04d}", fecha=now,
                concepto=f"Journal entry {i}", tipo="Diario", numero=i,
                cuentas=[
                    CuentaPoliza(cuenta="1000", descripcion="Checking", debe=10000 * i, haber=0),
                    CuentaPoliza(cuenta="4000", descripcion="Sales Revenue", debe=0, haber=10000 * i),
                ],
                monto_total=10000 * i, status=StatusPoliza.CONTABILIZADA,
            )
            for i in range(1, 3)
        ]

    # ------------------------------------------------------------------
    # Upload Poliza
    # ------------------------------------------------------------------
    def upload_poliza(self, poliza: Poliza) -> Dict[str, Any]:
        self._ensure_connected()
        if not poliza.esta_cuadrada():
            return {"exito": False, "mensaje": "Journal entry not balanced"}

        if self._use_mock:
            return {
                "exito": True,
                "id_erp": f"QB-JE-{_uuid.uuid4().hex[:8].upper()}",
                "mensaje": "Journal entry created (mock QuickBooks)",
                "fecha_registro": datetime.now().isoformat(),
            }

        try:
            lines = []
            for c in poliza.cuentas:
                if c.debe > 0:
                    lines.append({
                        "DetailType": "JournalEntryLineDetail",
                        "Amount": c.debe,
                        "JournalEntryLineDetail": {
                            "PostingType": "Debit",
                            "AccountRef": {"value": c.cuenta},
                        },
                    })
                if c.haber > 0:
                    lines.append({
                        "DetailType": "JournalEntryLineDetail",
                        "Amount": c.haber,
                        "JournalEntryLineDetail": {
                            "PostingType": "Credit",
                            "AccountRef": {"value": c.cuenta},
                        },
                    })
            body = {"Line": lines, "TxnDate": poliza.fecha}
            data = self._qbo_request("POST", "journalentry", json_body=body)
            je = data.get("JournalEntry", {})
            return {
                "exito": True,
                "id_erp": str(je.get("Id", "")),
                "mensaje": "Journal entry created (QuickBooks)",
                "fecha_registro": datetime.now().isoformat(),
            }
        except ERPAPIError as e:
            logger.error(f"QuickBooks upload_poliza error: {e.message}")
            return {"exito": False, "mensaje": str(e.message)}

    # ------------------------------------------------------------------
    # Chart of Accounts
    # ------------------------------------------------------------------
    def get_chart_of_accounts(self) -> ChartOfAccounts:
        self._ensure_connected()
        if self._use_mock:
            return self._mock_chart()

        try:
            data = self._qbo_request("GET", "query?query=SELECT * FROM Account")
            cuentas = []
            for acc in data.get("QueryResponse", {}).get("Account", []):
                tipo_map = {
                    "Asset": TipoCuenta.ACTIVO, "Liability": TipoCuenta.PASIVO,
                    "Equity": TipoCuenta.CAPITAL, "Income": TipoCuenta.INGRESO,
                    "Expense": TipoCuenta.GASTO,
                }
                cuentas.append(CuentaContable(
                    clave=acc.get("Code", acc.get("Id", "")),
                    nombre=acc.get("Name", ""),
                    tipo=tipo_map.get(acc.get("AccountType", ""), TipoCuenta.ACTIVO),
                    saldo=float(acc.get("CurrentBalance", 0)),
                    es_auxiliar=acc.get("AccountSubType", "") != "",
                ))
            return ChartOfAccounts(
                empresa=self._empresa_info.get("nombre", ""),
                ejercicio=datetime.now().year, cuentas=cuentas,
                fecha_exportacion=datetime.now().isoformat(),
            )
        except ERPAPIError as e:
            logger.error(f"QuickBooks get_chart error: {e.message}")
            raise ERPAdapterError(f"Failed to get chart of accounts: {e.message}", code="API_ERROR")

    def _mock_chart(self) -> ChartOfAccounts:
        return ChartOfAccounts(
            empresa=self._empresa_info.get("nombre", ""),
            ejercicio=2026,
            cuentas=[
                CuentaContable(clave="1000", nombre="Checking", tipo=TipoCuenta.ACTIVO),
                CuentaContable(clave="1001", nombre="Savings", tipo=TipoCuenta.ACTIVO),
                CuentaContable(clave="2000", nombre="Accounts Payable", tipo=TipoCuenta.PASIVO),
                CuentaContable(clave="3000", nombre="Equity", tipo=TipoCuenta.CAPITAL),
                CuentaContable(clave="4000", nombre="Sales Revenue", tipo=TipoCuenta.INGRESO),
                CuentaContable(clave="5000", nombre="Expenses", tipo=TipoCuenta.GASTO),
            ],
            fecha_exportacion=datetime.now().isoformat(),
        )

    # ------------------------------------------------------------------
    # Balanza
    # ------------------------------------------------------------------
    def get_balanza(self, ejercicio: int, mes: int) -> BalanzaComprobacion:
        self._ensure_connected()
        if self._use_mock:
            return self._mock_balanza(ejercicio, mes)

        try:
            data = self._qbo_request("GET", "reports/BalanceSheet")
            # Parse QuickBooks report response
            rows = []
            for section in data.get("reports", [{}])[0].get("rows", []):
                for row in section.get("rows", []):
                    cells = row.get("cells", [])
                    if len(cells) >= 2:
                        rows.append({
                            "cuenta": cells[0].get("value", ""),
                            "nombre": cells[0].get("value", ""),
                            "deudor": float(cells[1].get("value", 0)) if float(cells[1].get("value", 0)) > 0 else 0,
                            "acreedor": abs(float(cells[1].get("value", 0))) if float(cells[1].get("value", 0)) < 0 else 0,
                        })
            total_deudor = sum(r["deudor"] for r in rows)
            total_acreedor = sum(r["acreedor"] for r in rows)
            return BalanzaComprobacion(
                ejercicio=ejercicio, mes=mes,
                rfc=self._empresa_info.get("rfc", ""),
                cuentas=rows,
                total_deudor=total_deudor, total_acreedor=total_acreedor,
                fecha_generacion=datetime.now().isoformat(),
            )
        except ERPAPIError as e:
            logger.error(f"QuickBooks get_balanza error: {e.message}")
            raise ERPAdapterError(f"Failed to get balanza: {e.message}", code="API_ERROR")

    def _mock_balanza(self, ejercicio: int, mes: int) -> BalanzaComprobacion:
        cuentas = [
            {"cuenta": "1000", "nombre": "Checking", "deudor": 95000, "acreedor": 0},
            {"cuenta": "1001", "nombre": "Savings", "deudor": 50000, "acreedor": 0},
            {"cuenta": "2000", "nombre": "Accounts Payable", "deudor": 0, "acreedor": 35000},
            {"cuenta": "3000", "nombre": "Equity", "deudor": 0, "acreedor": 100000},
            {"cuenta": "4000", "nombre": "Sales Revenue", "deudor": 0, "acreedor": 180000},
            {"cuenta": "5000", "nombre": "Expenses", "deudor": 70000, "acreedor": 0},
        ]
        return BalanzaComprobacion(
            ejercicio=ejercicio, mes=mes,
            rfc=self._empresa_info.get("rfc", ""),
            cuentas=cuentas,
            total_deudor=sum(c["deudor"] for c in cuentas),
            total_acreedor=sum(c["acreedor"] for c in cuentas),
            fecha_generacion=datetime.now().isoformat(),
        )

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------
    def health_check(self) -> Dict[str, Any]:
        """Check if QuickBooks adapter is healthy."""
        result = {
            "adapter": self.name,
            "mock": self._use_mock,
            "connected": self._connected,
        }
        if not self._connected:
            result["status"] = "disconnected"
            return result
        if self._use_mock:
            result["status"] = "healthy_mock"
            return result
        try:
            self._qbo_request("GET", f"company/{self._realm_id}/companyinfo/{self._realm_id}")
            result["status"] = "healthy"
        except Exception as e:
            result["status"] = "unhealthy"
            result["error"] = str(e)
        return result
