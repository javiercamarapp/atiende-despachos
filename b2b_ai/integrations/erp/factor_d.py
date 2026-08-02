# -*- coding: utf-8 -*-
"""
factor_d.py — Production-ready adapter for Factor D (Cloud/SaaS, REST API).
Uses httpx for real API calls with OAuth 2.0 authentication.
Falls back to mock data when FACTOR_D_CLIENT_ID is not set.
"""
from __future__ import annotations
import logging, os, uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from b2b_ai.integrations.erp.adapter import ERPAdapter, ERPAdapterError
from b2b_ai.integrations.erp.http_client import ERPAPIError, ERPAuthError, make_request
from b2b_ai.integrations.erp.models import (
    BalanzaComprobacion, ChartOfAccounts, CuentaContable, CuentaPoliza,
    ERPConfig, ERPType, Invoice, Poliza, StatusPoliza, TipoCuenta,
)
logger = logging.getLogger(__name__)

_MOCK_CUENTAS = [
    CuentaContable(clave="1101", nombre="Caja", tipo=TipoCuenta.ACTIVO, saldo=55000, es_auxiliar=True),
    CuentaContable(clave="1102", nombre="Bancos", tipo=TipoCuenta.ACTIVO, saldo=280000, es_auxiliar=True),
    CuentaContable(clave="1201", nombre="Inventarios", tipo=TipoCuenta.ACTIVO, saldo=90000, es_auxiliar=True),
    CuentaContable(clave="2101", nombre="Proveedores", tipo=TipoCuenta.PASIVO, saldo=-50000, es_auxiliar=True),
    CuentaContable(clave="2102", nombre="Impuestos por pagar", tipo=TipoCuenta.PASIVO, saldo=-15000, es_auxiliar=True),
    CuentaContable(clave="3101", nombre="Capital social", tipo=TipoCuenta.CAPITAL, saldo=-120000),
    CuentaContable(clave="4101", nombre="Ingresos por servicios", tipo=TipoCuenta.INGRESO, saldo=-250000, es_auxiliar=True),
    CuentaContable(clave="5101", nombre="Sueldos y salarios", tipo=TipoCuenta.GASTO, saldo=95000, es_auxiliar=True),
    CuentaContable(clave="5102", nombre="Renta", tipo=TipoCuenta.GASTO, saldo=28000, es_auxiliar=True),
    CuentaContable(clave="5103", nombre="Servicios", tipo=TipoCuenta.GASTO, saldo=18000, es_auxiliar=True),
]
_MOCK_BALANZA = [
    {"cuenta": "1101", "nombre": "Caja", "deudor": 55000, "acreedor": 0},
    {"cuenta": "1102", "nombre": "Bancos", "deudor": 280000, "acreedor": 0},
    {"cuenta": "2101", "nombre": "Proveedores", "deudor": 0, "acreedor": 50000},
    {"cuenta": "3101", "nombre": "Capital social", "deudor": 0, "acreedor": 120000},
    {"cuenta": "4101", "nombre": "Ingresos", "deudor": 0, "acreedor": 250000},
    {"cuenta": "5101", "nombre": "Sueldos", "deudor": 95000, "acreedor": 0},
]

class FactorDAdapter(ERPAdapter):
    def __init__(self, config: Optional[ERPConfig] = None):
        config = config or ERPConfig(type=ERPType.FACTOR_D)
        config.endpoint = config.endpoint or os.environ.get("FACTOR_D_ENDPOINT", "https://app.factord.com.mx/api/v1/")
        config.api_key = config.api_key or os.environ.get("FACTOR_D_CLIENT_ID")
        super().__init__(config=config)
        self._auth_token: Optional[str] = None
        self._use_mock: bool = True

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        creds = credentials or {}
        client_id = creds.get("client_id") or self.config.api_key
        client_secret = creds.get("client_secret") or os.environ.get("FACTOR_D_CLIENT_SECRET", "")
        if client_id and client_secret:
            self._use_mock = False
            try:
                resp = make_request("POST", f"{self.config.endpoint}auth/token",
                    json_body={"client_id": client_id, "client_secret": client_secret},
                    timeout=self.config.timeout, retry_attempts=self.config.retry_attempts)
                self._auth_token = resp.json().get("access_token", client_id)
                self._empresa_info = {"nombre": "Factor D Company", "rfc": "N/A", "ejercicio": datetime.now().year}
            except ERPAuthError as e:
                raise ERPAdapterError(f"Factor D auth failed: {e.message}", code="AUTH_FAILED")
            except ERPAPIError as e:
                raise ERPAdapterError(f"Factor D connection failed: {e.message}", code="CONNECTION_FAILED")
        elif client_id:
            self._use_mock = False
            self._auth_token = client_id
            self._empresa_info = {"nombre": "Factor D Company", "rfc": "N/A", "ejercicio": datetime.now().year}
        else:
            self._use_mock = True
            self._empresa_info = {"nombre": "Empresa Factor D Mock S.A. DE C.V.", "rfc": "FD010101AAA", "ejercicio": 2026}
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False
        self._auth_token = None
        self._empresa_info = {}

    def _api_request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        self._ensure_connected()
        if self._use_mock:
            raise ERPAdapterError("Cannot make real API call in mock mode", code="MOCK_MODE")
        url = f"{self.config.endpoint}{path}"
        headers = {"Authorization": f"Bearer {self._auth_token}", "Accept": "application/json"}
        headers.update(kwargs.pop("headers", {}))
        resp = make_request(method, url, headers=headers,
            timeout=self.config.timeout, retry_attempts=self.config.retry_attempts, **kwargs)
        return resp.json()

    def get_invoices(self, date_range: Optional[Dict[str, str]] = None) -> List[Invoice]:
        self._ensure_connected()
        if self._use_mock:
            return [Invoice(id=f"FD-INV-{i:04d}", uuid=str(_uuid.uuid4()), rfc="FDC010101AAA",
                fecha=datetime.now().strftime("%Y-%m-%d"), monto=round(15000+i*3000, 2),
                subtotal=round(12931.03+i*2586.21, 2), iva=round(2068.97+i*413.79, 2),
                status="activa", concepto=f"Servicio Facturacion {i}", serie="FD", folio=str(7000+i),
                moneda="MXN", forma_pago="03", metodo_pago="PUE") for i in range(1, 4)]
        try:
            params = {}
            if date_range:
                params["fecha_inicio"] = date_range.get("from", "")
                params["fecha_fin"] = date_range.get("to", "")
            data = self._api_request("GET", "facturas", params=params)
            return [Invoice(id=str(inv.get("id", "")), uuid=inv.get("uuid", ""),
                rfc=inv.get("rfc", ""), fecha=inv.get("fecha", "")[:10],
                monto=float(inv.get("total", 0)), subtotal=float(inv.get("subtotal", 0)),
                iva=float(inv.get("iva", 0)), status=inv.get("status", "activa"),
                concepto=inv.get("concepto", ""), serie=inv.get("serie", ""),
                folio=str(inv.get("folio", "")), moneda=inv.get("moneda", "MXN"))
                for inv in data.get("facturas", [])]
        except ERPAPIError as e:
            raise ERPAdapterError(f"Failed to get invoices: {e.message}", code="API_ERROR")

    def get_polizas(self, date_range: Optional[Dict[str, str]] = None) -> List[Poliza]:
        self._ensure_connected()
        if self._use_mock:
            now = datetime.now().strftime("%Y-%m-%d")
            return [Poliza(id=f"FD-POL-{i:04d}", fecha=now, concepto=f"Poliza FD {i}", tipo="Diario", numero=i,
                cuentas=[CuentaPoliza(cuenta="1101", descripcion="Caja", debe=9000*i, haber=0),
                         CuentaPoliza(cuenta="4101", descripcion="Ingresos", debe=0, haber=9000*i)],
                monto_total=9000*i, status=StatusPoliza.CONTABILIZADA) for i in range(1, 3)]
        try:
            params = {}
            if date_range:
                params["fecha_inicio"] = date_range.get("from", "")
                params["fecha_fin"] = date_range.get("to", "")
            data = self._api_request("GET", "contabilidad/polizas", params=params)
            polizas = []
            for p in data.get("polizas", []):
                lines = [CuentaPoliza(cuenta=l.get("cuenta", ""), descripcion=l.get("descripcion", ""),
                    debe=float(l.get("debe", 0)), haber=float(l.get("haber", 0)))
                    for l in p.get("movimientos", [])]
                polizas.append(Poliza(id=str(p.get("id", "")), fecha=p.get("fecha", "")[:10],
                    concepto=p.get("concepto", ""), tipo=p.get("tipo", "Diario"),
                    cuentas=lines, monto_total=sum(c.debe for c in lines),
                    status=StatusPoliza.CONTABILIZADA))
            return polizas
        except ERPAPIError as e:
            raise ERPAdapterError(f"Failed to get polizas: {e.message}", code="API_ERROR")

    def upload_poliza(self, poliza: Poliza) -> Dict[str, Any]:
        self._ensure_connected()
        if not poliza.esta_cuadrada():
            return {"exito": False, "mensaje": "Journal entry not balanced"}
        if self._use_mock:
            return {"exito": True, "id_erp": f"FD-POL-{_uuid.uuid4().hex[:8].upper()}",
                    "mensaje": "Poliza creada (mock Factor D)", "fecha_registro": datetime.now().isoformat()}
        try:
            movements = [{"cuenta": c.cuenta, "descripcion": c.descripcion, "debe": c.debe, "haber": c.haber}
                         for c in poliza.cuentas]
            body = {"fecha": poliza.fecha, "concepto": poliza.concepto, "tipo": poliza.tipo, "movimientos": movements}
            data = self._api_request("POST", "contabilidad/polizas", json_body=body)
            return {"exito": True, "id_erp": str(data.get("id", "")),
                    "mensaje": "Poliza creada (Factor D)", "fecha_registro": datetime.now().isoformat()}
        except ERPAPIError as e:
            return {"exito": False, "mensaje": str(e.message)}

    def get_chart_of_accounts(self) -> ChartOfAccounts:
        self._ensure_connected()
        if self._use_mock:
            return ChartOfAccounts(empresa=self._empresa_info.get("nombre", ""), ejercicio=2026,
                cuentas=_MOCK_CUENTAS, fecha_exportacion=datetime.now().isoformat())
        try:
            data = self._api_request("GET", "contabilidad/catalogo-cuentas")
            tipo_map = {"activo": TipoCuenta.ACTIVO, "pasivo": TipoCuenta.PASIVO,
                        "capital": TipoCuenta.CAPITAL, "ingreso": TipoCuenta.INGRESO, "gasto": TipoCuenta.GASTO}
            cuentas = [CuentaContable(clave=a.get("clave", ""), nombre=a.get("nombre", ""),
                tipo=tipo_map.get(a.get("tipo", "").lower(), TipoCuenta.ACTIVO),
                saldo=float(a.get("saldo", 0)), es_auxiliar=a.get("es_auxiliar", False))
                for a in data.get("cuentas", [])]
            return ChartOfAccounts(empresa=self._empresa_info.get("nombre", ""),
                ejercicio=datetime.now().year, cuentas=cuentas, fecha_exportacion=datetime.now().isoformat())
        except ERPAPIError as e:
            raise ERPAdapterError(f"Failed to get chart: {e.message}", code="API_ERROR")

    def get_balanza(self, ejercicio: int, mes: int) -> BalanzaComprobacion:
        self._ensure_connected()
        if self._use_mock:
            return BalanzaComprobacion(ejercicio=ejercicio, mes=mes, rfc=self._empresa_info.get("rfc", ""),
                cuentas=_MOCK_BALANZA, total_deudor=sum(c["deudor"] for c in _MOCK_BALANZA),
                total_acreedor=sum(c["acreedor"] for c in _MOCK_BALANZA), fecha_generacion=datetime.now().isoformat())
        try:
            data = self._api_request("GET", "contabilidad/balanza", params={"ejercicio": ejercicio, "mes": mes})
            cuentas = [{"cuenta": c.get("cuenta", ""), "nombre": c.get("nombre", ""),
                "deudor": float(c.get("deudor", 0)), "acreedor": float(c.get("acreedor", 0))}
                for c in data.get("cuentas", [])]
            return BalanzaComprobacion(ejercicio=ejercicio, mes=mes, rfc=self._empresa_info.get("rfc", ""),
                cuentas=cuentas, total_deudor=sum(c["deudor"] for c in cuentas),
                total_acreedor=sum(c["acreedor"] for c in cuentas), fecha_generacion=datetime.now().isoformat())
        except ERPAPIError as e:
            raise ERPAdapterError(f"Failed to get balanza: {e.message}", code="API_ERROR")

    def health_check(self) -> Dict[str, Any]:
        result = {"adapter": self.name, "mock": self._use_mock, "connected": self._connected}
        if not self._connected:
            result["status"] = "disconnected"
            return result
        if self._use_mock:
            result["status"] = "healthy_mock"
            return result
        try:
            self._api_request("GET", "auth/validate")
            result["status"] = "healthy"
        except Exception as e:
            result["status"] = "unhealthy"
            result["error"] = str(e)
        return result
