# -*- coding: utf-8 -*-
"""
aspel_cloud.py — Production-ready adapter for Aspel Cloud (REST API).
Uses httpx for real API calls with API Key authentication.
Falls back to mock data when ASPEL_API_KEY is not set.
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
    CuentaContable(clave="1.01", nombre="Caja", tipo=TipoCuenta.ACTIVO),
    CuentaContable(clave="1.02", nombre="Bancos", tipo=TipoCuenta.ACTIVO),
    CuentaContable(clave="2.01", nombre="Proveedores", tipo=TipoCuenta.PASIVO),
    CuentaContable(clave="3.01", nombre="Capital social", tipo=TipoCuenta.CAPITAL),
    CuentaContable(clave="4.01", nombre="Ingresos", tipo=TipoCuenta.INGRESO),
    CuentaContable(clave="5.01", nombre="Gastos generales", tipo=TipoCuenta.GASTO),
]
_MOCK_BALANZA = [
    {"cuenta": "1.01", "nombre": "Caja", "deudor": 42000, "acreedor": 0},
    {"cuenta": "1.02", "nombre": "Bancos", "deudor": 210000, "acreedor": 0},
    {"cuenta": "2.01", "nombre": "Proveedores", "deudor": 0, "acreedor": 55000},
    {"cuenta": "3.01", "nombre": "Capital", "deudor": 0, "acreedor": 120000},
    {"cuenta": "4.01", "nombre": "Ingresos", "deudor": 0, "acreedor": 250000},
    {"cuenta": "5.01", "nombre": "Gastos", "deudor": 95000, "acreedor": 0},
]

class AspelCloudAdapter(ERPAdapter):
    def __init__(self, config: Optional[ERPConfig] = None):
        config = config or ERPConfig(type=ERPType.ASPEL_CLOUD)
        config.endpoint = config.endpoint or os.environ.get("ASPEL_ENDPOINT", "https://api.aspelcloud.com/v1/")
        config.api_key = config.api_key or os.environ.get("ASPEL_API_KEY")
        super().__init__(config=config)
        self._auth_token: Optional[str] = None
        self._use_mock: bool = True

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        creds = credentials or {}
        api_key = creds.get("api_key") or self.config.api_key
        if api_key:
            self._use_mock = False
            self._auth_token = api_key
            try:
                resp = make_request("GET", f"{self.config.endpoint}auth/validate",
                    headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
                    timeout=self.config.timeout, retry_attempts=self.config.retry_attempts)
                data = resp.json()
                self._empresa_info = {"nombre": data.get("company_name", "Aspel Company"),
                    "rfc": data.get("rfc", "N/A"), "ejercicio": datetime.now().year}
            except ERPAuthError as e:
                raise ERPAdapterError(f"Aspel auth failed: {e.message}", code="AUTH_FAILED")
            except ERPAPIError as e:
                raise ERPAdapterError(f"Aspel connection failed: {e.message}", code="CONNECTION_FAILED")
        else:
            self._use_mock = True
            self._empresa_info = {"nombre": "Empresa Aspel Cloud S.A. DE C.V.", "rfc": "ASP010101AAA", "ejercicio": 2026}
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
            return self._mock_invoices()
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

    def _mock_invoices(self) -> List[Invoice]:
        now = datetime.now().strftime("%Y-%m-%d")
        return [Invoice(id=f"ASP-INV-{i:04d}", uuid=str(_uuid.uuid4()), rfc="CCC030303CCC", fecha=now,
            monto=round(15000+i*2000, 2), subtotal=round(12931.03+i*1724.14, 2),
            iva=round(2068.97+i*275.86, 2), status="activa", concepto=f"Consultoria {i}",
            serie="C", folio=str(3000+i)) for i in range(1, 4)]

    def get_polizas(self, date_range: Optional[Dict[str, str]] = None) -> List[Poliza]:
        self._ensure_connected()
        if self._use_mock:
            return self._mock_polizas()
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

    def _mock_polizas(self) -> List[Poliza]:
        now = datetime.now().strftime("%Y-%m-%d")
        return [Poliza(id=f"ASP-POL-{i:04d}", fecha=now, concepto=f"P egresos {i}", tipo="Egresos", numero=200+i,
            cuentas=[CuentaPoliza(cuenta="5101", descripcion="Sueldos", debe=12000*i, haber=0),
                     CuentaPoliza(cuenta="1102", descripcion="Bancos", debe=0, haber=12000*i)],
            monto_total=12000*i, status=StatusPoliza.CONTABILIZADA) for i in range(1, 3)]

    def upload_poliza(self, poliza: Poliza) -> Dict[str, Any]:
        self._ensure_connected()
        if not poliza.esta_cuadrada():
            return {"exito": False, "mensaje": "La poliza no esta cuadrada"}
        if self._use_mock:
            return {"exito": True, "id_erp": f"ASP-POL-{_uuid.uuid4().hex[:8].upper()}",
                    "mensaje": "Poliza subida (mock Aspel)", "fecha_registro": datetime.now().isoformat()}
        try:
            movements = [{"cuenta": c.cuenta, "descripcion": c.descripcion, "debe": c.debe, "haber": c.haber}
                         for c in poliza.cuentas]
            body = {"fecha": poliza.fecha, "concepto": poliza.concepto, "tipo": poliza.tipo, "movimientos": movements}
            data = self._api_request("POST", "contabilidad/polizas", json_body=body)
            return {"exito": True, "id_erp": str(data.get("id", "")),
                    "mensaje": "Poliza creada (Aspel)", "fecha_registro": datetime.now().isoformat()}
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
