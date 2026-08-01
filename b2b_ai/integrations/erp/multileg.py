# -*- coding: utf-8 -*-
"""
multileg.py — Production-ready adapter for Multileg (Desktop).
Uses SQL Server direct access when credentials are available.
Falls back to mock data when not configured.
"""
from __future__ import annotations
import logging, os, uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from b2b_ai.integrations.erp.adapter import ERPAdapter, ERPAdapterError
from b2b_ai.integrations.erp.models import (
    BalanzaComprobacion, ChartOfAccounts, CuentaContable, CuentaPoliza,
    ERPConfig, ERPType, Invoice, Poliza, StatusPoliza, TipoCuenta,
)
logger = logging.getLogger(__name__)

_MOCK_CUENTAS = [
    CuentaContable(clave="1101", nombre="Caja", tipo=TipoCuenta.ACTIVO, saldo=30000, es_auxiliar=True),
    CuentaContable(clave="1102", nombre="Bancos", tipo=TipoCuenta.ACTIVO, saldo=175000, es_auxiliar=True),
    CuentaContable(clave="1201", nombre="Inventarios", tipo=TipoCuenta.ACTIVO, saldo=50000, es_auxiliar=True),
    CuentaContable(clave="2101", nombre="Proveedores", tipo=TipoCuenta.PASIVO, saldo=-30000, es_auxiliar=True),
    CuentaContable(clave="2102", nombre="Impuestos por pagar", tipo=TipoCuenta.PASIVO, saldo=-7000, es_auxiliar=True),
    CuentaContable(clave="3101", nombre="Capital social", tipo=TipoCuenta.CAPITAL, saldo=-80000),
    CuentaContable(clave="4101", nombre="Ingresos por servicios", tipo=TipoCuenta.INGRESO, saldo=-120000, es_auxiliar=True),
    CuentaContable(clave="5101", nombre="Sueldos y salarios", tipo=TipoCuenta.GASTO, saldo=55000, es_auxiliar=True),
    CuentaContable(clave="5102", nombre="Renta", tipo=TipoCuenta.GASTO, saldo=15000, es_auxiliar=True),
    CuentaContable(clave="5103", nombre="Servicios", tipo=TipoCuenta.GASTO, saldo=10000, es_auxiliar=True),
]
_MOCK_BALANZA = [
    {"cuenta": "1101", "nombre": "Caja", "deudor": 30000, "acreedor": 0},
    {"cuenta": "1102", "nombre": "Bancos", "deudor": 175000, "acreedor": 0},
    {"cuenta": "2101", "nombre": "Proveedores", "deudor": 0, "acreedor": 30000},
    {"cuenta": "3101", "nombre": "Capital social", "deudor": 0, "acreedor": 80000},
    {"cuenta": "4101", "nombre": "Ingresos", "deudor": 0, "acreedor": 120000},
    {"cuenta": "5101", "nombre": "Sueldos", "deudor": 55000, "acreedor": 0},
]


class MultilegAdapter(ERPAdapter):
    def __init__(self, config: Optional[ERPConfig] = None):
        config = config or ERPConfig(type=ERPType.MULTILEG)
        config.endpoint = config.endpoint or os.environ.get("MULTILEG_ENDPOINT", "C:\\Program Files\\Multileg\\")
        super().__init__(config=config)
        self._db_conn: Any = None
        self._use_mock: bool = True

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        creds = credentials or {}
        db_host = creds.get("db_host") or os.environ.get("MULTILEG_DB_HOST")
        db_name = creds.get("db_name") or os.environ.get("MULTILEG_DB_NAME")
        db_user = creds.get("db_user") or os.environ.get("MULTILEG_DB_USER")
        db_pass = creds.get("db_pass") or os.environ.get("MULTILEG_DB_PASS")
        if db_host and db_name and db_user and db_pass:
            self._use_mock = False
            try:
                import pymssql
                self._db_conn = pymssql.connect(server=db_host, database=db_name,
                    user=db_user, password=db_pass, timeout=self.config.timeout)
                cursor = self._db_conn.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
                self._empresa_info = {"nombre": "Multileg Desktop (SQL Server)", "rfc": "N/A",
                    "ejercicio": datetime.now().year, "base_datos": db_name}
            except ImportError:
                import pyodbc
                conn_str = (f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={db_host};"
                    f"DATABASE={db_name};UID={db_user};PWD={db_pass};Timeout={self.config.timeout};")
                self._db_conn = pyodbc.connect(conn_str)
                self._empresa_info = {"nombre": "Multileg Desktop (ODBC)", "rfc": "N/A",
                    "ejercicio": datetime.now().year, "base_datos": db_name}
            except Exception as e:
                raise ERPAdapterError(f"Multileg SQL connection failed: {e}", code="CONNECTION_FAILED")
        else:
            self._use_mock = True
            self._empresa_info = {"nombre": "Empresa Multileg Mock S.A. DE C.V.", "rfc": "MLG010101AAA",
                "ejercicio": 2026, "version": "2024.1.0", "base_datos": "Multileg_Empresa01"}
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False
        if self._db_conn:
            try: self._db_conn.close()
            except: pass
        self._db_conn = None
        self._empresa_info = {}

    def _sql_query(self, query: str) -> List[Dict[str, Any]]:
        self._ensure_connected()
        if self._use_mock:
            raise ERPAdapterError("Cannot query SQL in mock mode", code="MOCK_MODE")
        cursor = self._db_conn.cursor()
        cursor.execute(query)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        cursor.close()
        return rows

    def get_invoices(self, date_range: Optional[Dict[str, str]] = None) -> List[Invoice]:
        self._ensure_connected()
        if self._use_mock:
            now = datetime.now().strftime("%Y-%m-%d")
            return [Invoice(id=f"MLG-INV-{i:04d}", uuid=str(_uuid.uuid4()), rfc="MLC010101AAA", fecha=now,
                monto=round(9000+i*1800, 2), subtotal=round(7758.62+i*1551.72, 2),
                iva=round(1241.38+i*248.28, 2), status="activa", concepto=f"Servicio Multileg {i}",
                serie="ML", folio=str(4000+i), moneda="MXN") for i in range(1, 4)]
        try:
            where = ""
            if date_range:
                s, e = date_range.get("from", ""), date_range.get("to", "")
                if s and e: where = f"WHERE Fecha >= '{s}' AND Fecha <= '{e}'"
            rows = self._sql_query(f"SELECT TOP 100 * FROM Multileg_Comprobantes {where} ORDER BY Fecha DESC")
            return [Invoice(id=str(r.get("Id", "")), rfc=str(r.get("RFC", "")),
                fecha=str(r.get("Fecha", ""))[:10], monto=float(r.get("Total", 0)),
                subtotal=float(r.get("Subtotal", 0)), iva=float(r.get("IVA", 0)),
                status="activa", concepto=str(r.get("Concepto", "")),
                serie=str(r.get("Serie", "")), folio=str(r.get("Folio", ""))) for r in rows]
        except Exception as e:
            raise ERPAdapterError(f"Failed to get invoices: {e}", code="SQL_ERROR")

    def get_polizas(self, date_range: Optional[Dict[str, str]] = None) -> List[Poliza]:
        self._ensure_connected()
        if self._use_mock:
            now = datetime.now().strftime("%Y-%m-%d")
            return [Poliza(id=f"MLG-POL-{i:04d}", fecha=now, concepto=f"Poliza Multileg {i}", tipo="Diario", numero=i,
                cuentas=[CuentaPoliza(cuenta="1101", descripcion="Caja", debe=6000*i, haber=0),
                         CuentaPoliza(cuenta="4101", descripcion="Ingresos", debe=0, haber=6000*i)],
                monto_total=6000*i, status=StatusPoliza.CONTABILIZADA) for i in range(1, 3)]
        try:
            where = ""
            if date_range:
                s, e = date_range.get("from", ""), date_range.get("to", "")
                if s and e: where = f"WHERE Fecha >= '{s}' AND Fecha <= '{e}'"
            rows = self._sql_query(f"SELECT TOP 100 * FROM Multileg_Polizas {where} ORDER BY Fecha DESC")
            polizas = []
            for r in rows:
                pid = r.get("IdPoliza", "")
                movs = self._sql_query(f"SELECT * FROM Multileg_Movimientos WHERE IdPoliza = {pid}")
                cuentas = [CuentaPoliza(cuenta=str(m.get("Cuenta", "")), descripcion=str(m.get("Descripcion", "")),
                    debe=float(m.get("Debe", 0)), haber=float(m.get("Haber", 0))) for m in movs]
                polizas.append(Poliza(id=str(pid), fecha=str(r.get("Fecha", ""))[:10],
                    concepto=str(r.get("Concepto", "")), tipo=str(r.get("Tipo", "Diario")),
                    cuentas=cuentas, monto_total=sum(c.debe for c in cuentas),
                    status=StatusPoliza.CONTABILIZADA))
            return polizas
        except Exception as e:
            raise ERPAdapterError(f"Failed to get polizas: {e}", code="SQL_ERROR")

    def upload_poliza(self, poliza: Poliza) -> Dict[str, Any]:
        self._ensure_connected()
        if not poliza.esta_cuadrada():
            return {"exito": False, "mensaje": "La poliza no esta cuadrada"}
        if self._use_mock:
            return {"exito": True, "id_erp": f"MLG-POL-{_uuid.uuid4().hex[:8].upper()}",
                    "mensaje": "Poliza subida (mock Multileg)", "fecha_registro": datetime.now().isoformat()}
        try:
            cursor = self._db_conn.cursor()
            cursor.execute("INSERT INTO Multileg_Polizas (Fecha, Concepto, Tipo) VALUES (%s, %s, %s) RETURNING IdPoliza",
                (poliza.fecha, poliza.concepto, poliza.tipo))
            pid = cursor.fetchone()[0]
            for c in poliza.cuentas:
                cursor.execute("INSERT INTO Multileg_Movimientos (IdPoliza, Cuenta, Descripcion, Debe, Haber) "
                    "VALUES (%s, %s, %s, %s, %s)", (pid, c.cuenta, c.descripcion, c.debe, c.haber))
            self._db_conn.commit()
            cursor.close()
            return {"exito": True, "id_erp": str(pid), "mensaje": "Poliza creada (Multileg SQL)",
                    "fecha_registro": datetime.now().isoformat()}
        except Exception as e:
            self._db_conn.rollback()
            return {"exito": False, "mensaje": str(e)}

    def get_chart_of_accounts(self) -> ChartOfAccounts:
        self._ensure_connected()
        if self._use_mock:
            return ChartOfAccounts(empresa=self._empresa_info.get("nombre", ""), ejercicio=2026,
                cuentas=_MOCK_CUENTAS, fecha_exportacion=datetime.now().isoformat())
        try:
            rows = self._sql_query("SELECT * FROM Multileg_Cuentas ORDER BY Clave")
            return ChartOfAccounts(empresa=self._empresa_info.get("nombre", ""),
                ejercicio=datetime.now().year,
                cuentas=[CuentaContable(clave=str(r.get("Clave", "")), nombre=str(r.get("Nombre", "")),
                    tipo=TipoCuenta.ACTIVO, saldo=float(r.get("Saldo", 0)),
                    es_auxiliar=bool(r.get("EsAuxiliar", False))) for r in rows],
                fecha_exportacion=datetime.now().isoformat())
        except Exception as e:
            raise ERPAdapterError(f"Failed to get chart: {e}", code="SQL_ERROR")

    def get_balanza(self, ejercicio: int, mes: int) -> BalanzaComprobacion:
        self._ensure_connected()
        if self._use_mock:
            return BalanzaComprobacion(ejercicio=ejercicio, mes=mes, rfc=self._empresa_info.get("rfc", ""),
                cuentas=_MOCK_BALANZA, total_deudor=sum(c["deudor"] for c in _MOCK_BALANZA),
                total_acreedor=sum(c["acreedor"] for c in _MOCK_BALANZA), fecha_generacion=datetime.now().isoformat())
        try:
            rows = self._sql_query(f"SELECT * FROM Multileg_Balanza WHERE Ejercicio={ejercicio} AND Mes={mes}")
            cuentas = [{"cuenta": str(r.get("Cuenta", "")), "nombre": str(r.get("Nombre", "")),
                "deudor": float(r.get("Deudor", 0)), "acreedor": float(r.get("Acreedor", 0))} for r in rows]
            return BalanzaComprobacion(ejercicio=ejercicio, mes=mes, rfc=self._empresa_info.get("rfc", ""),
                cuentas=cuentas, total_deudor=sum(c["deudor"] for c in cuentas),
                total_acreedor=sum(c["acreedor"] for c in cuentas), fecha_generacion=datetime.now().isoformat())
        except Exception as e:
            raise ERPAdapterError(f"Failed to get balanza: {e}", code="SQL_ERROR")

    def health_check(self) -> Dict[str, Any]:
        result = {"adapter": self.name, "mock": self._use_mock, "connected": self._connected}
        if not self._connected:
            result["status"] = "disconnected"
            return result
        if self._use_mock:
            result["status"] = "healthy_mock"
            return result
        try:
            cursor = self._db_conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            result["status"] = "healthy"
        except Exception as e:
            result["status"] = "unhealthy"
            result["error"] = str(e)
        return result
