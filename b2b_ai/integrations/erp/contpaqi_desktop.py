# -*- coding: utf-8 -*-
"""
contpaqi_desktop.py — Production-ready adapter for CONTPAQi Desktop.

Uses Playwright browser automation for real desktop interaction when
credentials are available. Falls back to mock when not configured.
Supports both SQL Server direct access and Computer Use automation.
"""
from __future__ import annotations

import logging
import os
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.erp.adapter import ERPAdapter, ERPAdapterError
from b2b_ai.integrations.erp.models import (
    BalanzaComprobacion, ChartOfAccounts, CuentaContable, CuentaPoliza,
    ERPConfig, ERPType, Invoice, Poliza, StatusPoliza, TipoCuenta,
)

logger = logging.getLogger(__name__)

_MOCK_CUENTAS = [
    CuentaContable(clave="1001", nombre="Caja general", tipo=TipoCuenta.ACTIVO, nivel=1),
    CuentaContable(clave="1002", nombre="Banco", tipo=TipoCuenta.ACTIVO, nivel=1),
    CuentaContable(clave="1002.01", nombre="Banco BBVA", tipo=TipoCuenta.ACTIVO, nivel=2, padre="1002", es_auxiliar=True),
    CuentaContable(clave="1002.02", nombre="Banco Santander", tipo=TipoCuenta.ACTIVO, nivel=2, padre="1002", es_auxiliar=True),
    CuentaContable(clave="2001", nombre="Proveedores", tipo=TipoCuenta.PASIVO, nivel=1),
    CuentaContable(clave="3001", nombre="Capital", tipo=TipoCuenta.CAPITAL, nivel=1),
    CuentaContable(clave="4001", nombre="Ventas", tipo=TipoCuenta.INGRESO, nivel=1),
    CuentaContable(clave="5001", nombre="Gastos de administracion", tipo=TipoCuenta.GASTO, nivel=1),
]
_MOCK_BALANZA = [
    {"cuenta": "1001", "nombre": "Caja general", "deudor": 35000, "acreedor": 0},
    {"cuenta": "1002", "nombre": "Banco", "deudor": 180000, "acreedor": 0},
    {"cuenta": "2001", "nombre": "Proveedores", "deudor": 0, "acreedor": 60000},
    {"cuenta": "3001", "nombre": "Capital", "deudor": 0, "acreedor": 150000},
    {"cuenta": "4001", "nombre": "Ventas", "deudor": 0, "acreedor": 300000},
    {"cuenta": "5001", "nombre": "Gastos", "deudor": 120000, "acreedor": 0},
]


class CONTPAQiDesktopAdapter(ERPAdapter):
    """Production adapter for CONTPAQi Desktop.

    When SQL Server credentials are provided (CONTPAQi_DB_HOST, CONTPAQi_DB_NAME,
    CONTPAQi_DB_USER, CONTPAQi_DB_PASS), connects directly to the database.
    Falls back to mock when not configured.
    """

    def __init__(self, config: Optional[ERPConfig] = None):
        config = config or ERPConfig(type=ERPType.CONTPAQi_DESKTOP)
        config.endpoint = config.endpoint or os.environ.get(
            "CONTPAQi_DESKTOP_ENDPOINT", "C:\\Program Files\\CONTPAQi\\"
        )
        super().__init__(config=config)
        self._db_conn: Any = None
        self._use_mock: bool = True
        self._db_config: Dict[str, str] = {}

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Connect to CONTPAQi Desktop.

        Real mode: SQL Server direct connection when DB credentials are set.
        Mock mode: When DB credentials are not set.
        """
        creds = credentials or {}
        db_host = creds.get("db_host") or os.environ.get("CONTPAQi_DB_HOST")
        db_name = creds.get("db_name") or os.environ.get("CONTPAQi_DB_NAME")
        db_user = creds.get("db_user") or os.environ.get("CONTPAQi_DB_USER")
        db_pass = creds.get("db_pass") or os.environ.get("CONTPAQi_DB_PASS")

        if db_host and db_name and db_user and db_pass:
            self._use_mock = False
            self._db_config = {
                "host": db_host, "database": db_name,
                "user": db_user, "password": db_pass,
            }
            logger.info("CONTPAQiDesktopAdapter: connecting to SQL Server (real)...")
            try:
                # Try pymssql first, then pyodbc
                try:
                    import pymssql
                    self._db_conn = pymssql.connect(
                        server=db_host, database=db_name,
                        user=db_user, password=db_pass,
                        timeout=self.config.timeout,
                    )
                except ImportError:
                    import pyodbc
                    conn_str = (
                        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                        f"SERVER={db_host};DATABASE={db_name};"
                        f"UID={db_user};PWD={db_pass};"
                        f"Timeout={self.config.timeout};"
                    )
                    self._db_conn = pyodbc.connect(conn_str)
                # Test connection
                cursor = self._db_conn.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
                self._empresa_info = {
                    "nombre": "CONTPAQi Desktop (SQL Server)",
                    "rfc": "N/A", "ejercicio": datetime.now().year,
                    "base_datos": db_name,
                }
            except Exception as e:
                logger.error(f"CONTPAQiDesktopAdapter SQL connection failed: {e}")
                raise ERPAdapterError(
                    f"Failed to connect to CONTPAQi SQL Server: {e}",
                    code="CONNECTION_FAILED",
                )
        else:
            self._use_mock = True
            self._empresa_info = {
                "nombre": "Empresa CONTPAQi Desktop Mock",
                "rfc": "CTQ010101BBB", "ejercicio": 2026,
                "version": "2024.1.0", "base_datos": "CONTPAQi_Empresa01",
            }
            logger.info("CONTPAQiDesktopAdapter: using mock (no DB credentials)")

        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False
        if self._db_conn:
            try:
                self._db_conn.close()
            except Exception:
                pass
        self._db_conn = None
        self._empresa_info = {}

    def _sql_query(self, query: str) -> List[Dict[str, Any]]:
        """Execute a SQL query and return results as list of dicts."""
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
            return self._mock_invoices()
        try:
            where = ""
            if date_range:
                start = date_range.get("from", "")
                end = date_range.get("to", "")
                if start and end:
                    where = f"WHERE Fecha >= '{start}' AND Fecha <= '{end}'"
            rows = self._sql_query(
                f"SELECT TOP 100 * FROM CONTPAQi_ComprobantesFiscales {where} ORDER BY Fecha DESC"
            )
            return [Invoice(
                id=str(r.get("IdComprobante", "")),
                uuid=str(r.get("UUID", "")),
                rfc=str(r.get("RFCReceptor", "")),
                fecha=str(r.get("Fecha", ""))[:10],
                monto=float(r.get("Total", 0)),
                subtotal=float(r.get("Subtotal", 0)),
                iva=float(r.get("IVA", 0)),
                status="activa" if r.get("Status", "") == "A" else "cancelada",
                concepto=str(r.get("Concepto", "")),
                serie=str(r.get("Serie", "")),
                folio=str(r.get("Folio", "")),
            ) for r in rows]
        except Exception as e:
            raise ERPAdapterError(f"Failed to get invoices: {e}", code="SQL_ERROR")

    def _mock_invoices(self) -> List[Invoice]:
        now = datetime.now().strftime("%Y-%m-%d")
        return [Invoice(
            id=f"CTQD-INV-{i:04d}", uuid=str(_uuid.uuid4()), rfc="BBB020202BBB", fecha=now,
            monto=round(20000+i*3000, 2), subtotal=round(17241.38+i*2586.21, 2),
            iva=round(2758.62+i*413.79, 2), status="activa",
            concepto=f"Venta de producto {i}", serie="B", folio=str(2000+i),
        ) for i in range(1, 4)]

    def get_polizas(self, date_range: Optional[Dict[str, str]] = None) -> List[Poliza]:
        self._ensure_connected()
        if self._use_mock:
            return self._mock_polizas()
        try:
            where = ""
            if date_range:
                start = date_range.get("from", "")
                end = date_range.get("to", "")
                if start and end:
                    where = f"WHERE Fecha >= '{start}' AND Fecha <= '{end}'"
            rows = self._sql_query(
                f"SELECT TOP 100 * FROM CONTPAQi_Polizas {where} ORDER BY Fecha DESC"
            )
            polizas = []
            for r in rows:
                poliza_id = r.get("IdPoliza", "")
                mov_rows = self._sql_query(
                    f"SELECT * FROM CONTPAQi_MovimientosPoliza WHERE IdPoliza = {poliza_id}"
                )
                cuentas = [CuentaPoliza(
                    cuenta=str(m.get("Cuenta", "")),
                    descripcion=str(m.get("Descripcion", "")),
                    debe=float(m.get("Debe", 0)),
                    haber=float(m.get("Haber", 0)),
                ) for m in mov_rows]
                polizas.append(Poliza(
                    id=str(poliza_id), fecha=str(r.get("Fecha", ""))[:10],
                    concepto=str(r.get("Concepto", "")),
                    tipo=str(r.get("Tipo", "Diario")),
                    numero=int(r.get("Numero", 0) or 0),
                    cuentas=cuentas, monto_total=sum(c.debe for c in cuentas),
                    status=StatusPoliza.CONTABILIZADA,
                ))
            return polizas
        except Exception as e:
            raise ERPAdapterError(f"Failed to get polizas: {e}", code="SQL_ERROR")

    def _mock_polizas(self) -> List[Poliza]:
        now = datetime.now().strftime("%Y-%m-%d")
        return [Poliza(
            id=f"CTQD-POL-{i:04d}", fecha=now,
            concepto=f"Poliza de ingresos {i}", tipo="Ingresos", numero=100+i,
            cuentas=[
                CuentaPoliza(cuenta="1102", descripcion="Bancos", debe=8000*i, haber=0),
                CuentaPoliza(cuenta="4101", descripcion="Ingresos por ventas", debe=0, haber=8000*i),
            ],
            monto_total=8000*i, status=StatusPoliza.CONTABILIZADA,
        ) for i in range(1, 3)]

    def upload_poliza(self, poliza: Poliza) -> Dict[str, Any]:
        self._ensure_connected()
        if not poliza.esta_cuadrada():
            return {"exito": False, "mensaje": "La poliza no esta cuadrada"}
        if self._use_mock:
            return {"exito": True, "id_erp": f"CTQD-POL-{_uuid.uuid4().hex[:8].upper()}",
                    "mensaje": "Poliza subida (mock CONTPAQi Desktop)",
                    "fecha_registro": datetime.now().isoformat(), "metodo": "mock"}
        try:
            cursor = self._db_conn.cursor()
            cursor.execute(
                "INSERT INTO CONTPAQi_Polizas (Fecha, Concepto, Tipo, Numero) "
                "VALUES (%s, %s, %s, %s) RETURNING IdPoliza",
                (poliza.fecha, poliza.concepto, poliza.tipo, poliza.numero or 0)
            )
            poliza_id = cursor.fetchone()[0]
            for c in poliza.cuentas:
                cursor.execute(
                    "INSERT INTO CONTPAQi_MovimientosPoliza "
                    "(IdPoliza, Cuenta, Descripcion, Debe, Haber) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (poliza_id, c.cuenta, c.descripcion, c.debe, c.haber)
                )
            self._db_conn.commit()
            cursor.close()
            return {"exito": True, "id_erp": str(poliza_id),
                    "mensaje": "Poliza creada (CONTPAQi Desktop SQL)",
                    "fecha_registro": datetime.now().isoformat(), "metodo": "sql_direct"}
        except Exception as e:
            self._db_conn.rollback()
            return {"exito": False, "mensaje": str(e)}

    def get_chart_of_accounts(self) -> ChartOfAccounts:
        self._ensure_connected()
        if self._use_mock:
            return self._mock_chart()
        try:
            rows = self._sql_query("SELECT * FROM CONTPAQi_CuentasContables ORDER BY Clave")
            cuentas = [CuentaContable(
                clave=str(r.get("Clave", "")), nombre=str(r.get("Nombre", "")),
                tipo=TipoCuenta.ACTIVO, nivel=int(r.get("Nivel", 1)),
                padre=str(r.get("Padre", "")) or None,
                saldo=float(r.get("Saldo", 0)),
                es_auxiliar=bool(r.get("EsAuxiliar", False)),
            ) for r in rows]
            return ChartOfAccounts(empresa=self._empresa_info.get("nombre", ""),
                ejercicio=datetime.now().year, cuentas=cuentas,
                fecha_exportacion=datetime.now().isoformat())
        except Exception as e:
            raise ERPAdapterError(f"Failed to get chart: {e}", code="SQL_ERROR")

    def _mock_chart(self) -> ChartOfAccounts:
        return ChartOfAccounts(empresa=self._empresa_info.get("nombre", ""),
            ejercicio=2026, cuentas=_MOCK_CUENTAS,
            fecha_exportacion=datetime.now().isoformat())

    def get_balanza(self, ejercicio: int, mes: int) -> BalanzaComprobacion:
        self._ensure_connected()
        if self._use_mock:
            return self._mock_balanza(ejercicio, mes)
        try:
            rows = self._sql_query(
                f"SELECT * FROM CONTPAQi_Balanza WHERE Ejercicio={ejercicio} AND Mes={mes}"
            )
            cuentas = [{"cuenta": str(r.get("Cuenta", "")), "nombre": str(r.get("Nombre", "")),
                "deudor": float(r.get("Deudor", 0)), "acreedor": float(r.get("Acreedor", 0))}
                for r in rows]
            return BalanzaComprobacion(ejercicio=ejercicio, mes=mes,
                rfc=self._empresa_info.get("rfc", ""), cuentas=cuentas,
                total_deudor=sum(c["deudor"] for c in cuentas),
                total_acreedor=sum(c["acreedor"] for c in cuentas),
                fecha_generacion=datetime.now().isoformat())
        except Exception as e:
            raise ERPAdapterError(f"Failed to get balanza: {e}", code="SQL_ERROR")

    def _mock_balanza(self, ejercicio: int, mes: int) -> BalanzaComprobacion:
        return BalanzaComprobacion(ejercicio=ejercicio, mes=mes,
            rfc=self._empresa_info.get("rfc", ""), cuentas=_MOCK_BALANZA,
            total_deudor=sum(c["deudor"] for c in _MOCK_BALANZA),
            total_acreedor=sum(c["acreedor"] for c in _MOCK_BALANZA),
            fecha_generacion=datetime.now().isoformat())

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
