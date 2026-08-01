import os
# -*- coding: utf-8 -*-
"""
contpaqi_desktop.py — Adaptador mock para CONTPAQi versión de escritorio.

Implementa la interfaz ERPAdapter con respuestas simuladas.
En producción, usaría computer_use para automatizar la interfaz de CONTPAQi Desktop.
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.erp.adapter import ERPAdapter, ERPAdapterError
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


class CONTPAQiDesktopAdapter(ERPAdapter):
    """Adaptador mock para CONTPAQi versión de escritorio.

    En producción, usaría computer_use para automatizar la interfaz
    gráfica de CONTPAQi Desktop, ya que no expone una API REST.
    Alternativamente, podría conectarse directamente a la base de datos
    SQL Server de CONTPAQi.
    """

    def __init__(self, config: Optional[ERPConfig] = None):
        config = config or ERPConfig(type=ERPType.CONTPAQi_DESKTOP)
        config.endpoint = config.endpoint or "C:\\Program Files\\CONTPAQi\\"
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Simula la conexión a CONTPAQi Desktop.

        En producción:
        - Opción 1: Computer use para automatizar la UI
        - Opción 2: Conexión directa a SQL Server
        - Opción 3: Usar COM API de CONTPAQi
        """
        logger.info("CONTPAQiDesktopAdapter: conectando a CONTPAQi Desktop (mock)...")
        self._connected = True
        self._empresa_info = {
            "nombre": "Empresa CONTPAQi Desktop Mock",
            "rfc": "CTQ010101BBB",
            "ejercicio": 2026,
            "version": "2024.1.0",
            "base_datos": "CONTPAQi_Empresa01",
        }
        logger.info("CONTPAQiDesktopAdapter: conexión exitosa (mock)")
        return True

    def disconnect(self) -> None:
        self._connected = False
        self._empresa_info = {}
        logger.info("CONTPAQiDesktopAdapter: desconectado")

    def get_invoices(self, date_range: Optional[Dict[str, str]] = None) -> List[Invoice]:
        """Obtiene facturas mock de CONTPAQi Desktop."""
        self._ensure_connected()
        logger.info("CONTPAQiDesktopAdapter: obteniendo facturas (mock)")

        now = datetime.now().strftime("%Y-%m-%d")
        return [
            Invoice(
                id=f"CTQD-INV-{i:04d}",
                uuid=str(_uuid.uuid4()),
                rfc="BBB020202BBB",
                fecha=now,
                monto=round(20000 + i * 3000, 2),
                subtotal=round(17241.38 + i * 2586.21, 2),
                iva=round(2758.62 + i * 413.79, 2),
                status="activa",
                concepto=f"Venta de producto {i}",
                serie="B",
                folio=str(2000 + i),
            )
            for i in range(1, 4)
        ]

    def get_polizas(self, date_range: Optional[Dict[str, str]] = None) -> List[Poliza]:
        """Obtiene pólizas mock de CONTPAQi Desktop."""
        self._ensure_connected()
        logger.info("CONTPAQiDesktopAdapter: obteniendo pólizas (mock)")

        now = datetime.now().strftime("%Y-%m-%d")
        return [
            Poliza(
                id=f"CTQD-POL-{i:04d}",
                fecha=now,
                concepto=f"Póliza de ingresos {i}",
                tipo="Ingresos",
                numero=100 + i,
                cuentas=[
                    CuentaPoliza(cuenta="1102", descripcion="Bancos", debe=8000 * i, haber=0),
                    CuentaPoliza(cuenta="4101", descripcion="Ingresos por ventas", debe=0, haber=8000 * i),
                ],
                monto_total=8000 * i,
                status=StatusPoliza.CONTABILIZADA,
            )
            for i in range(1, 3)
        ]

    def upload_poliza(self, poliza: Poliza) -> Dict[str, Any]:
        """Sube una póliza mock a CONTPAQi Desktop."""
        self._ensure_connected()
        logger.info(f"CONTPAQiDesktopAdapter: subiendo póliza {poliza.id}")

        if not poliza.esta_cuadrada():
            return {
                "exito": False,
                "mensaje": "La póliza no está cuadrada",
            }

        return {
            "exito": True,
            "id_erp": f"CTQD-POL-{_uuid.uuid4().hex[:8].upper()}",
            "mensaje": "Póliza subida exitosamente (mock CONTPAQi Desktop)",
            "fecha_registro": datetime.now().isoformat(),
            "metodo": "computer_use" if False else "sql_direct",
        }

    def get_chart_of_accounts(self) -> ChartOfAccounts:
        """Obtiene catálogo de cuentas mock de CONTPAQi Desktop."""
        self._ensure_connected()
        logger.info("CONTPAQiDesktopAdapter: obteniendo catálogo de cuentas (mock)")

        cuentas = [
            CuentaContable(clave="1001", nombre="Caja general", tipo=TipoCuenta.ACTIVO, nivel=1),
            CuentaContable(clave="1002", nombre="Banco", tipo=TipoCuenta.ACTIVO, nivel=1),
            CuentaContable(clave="1002.01", nombre="Banco BBVA", tipo=TipoCuenta.ACTIVO, nivel=2, padre="1002", es_auxiliar=True),
            CuentaContable(clave="1002.02", nombre="Banco Santander", tipo=TipoCuenta.ACTIVO, nivel=2, padre="1002", es_auxiliar=True),
            CuentaContable(clave="2001", nombre="Proveedores", tipo=TipoCuenta.PASIVO, nivel=1),
            CuentaContable(clave="3001", nombre="Capital", tipo=TipoCuenta.CAPITAL, nivel=1),
            CuentaContable(clave="4001", nombre="Ventas", tipo=TipoCuenta.INGRESO, nivel=1),
            CuentaContable(clave="5001", nombre="Gastos de administración", tipo=TipoCuenta.GASTO, nivel=1),
        ]

        return ChartOfAccounts(
            empresa=self._empresa_info.get("nombre", ""),
            ejercicio=2026,
            cuentas=cuentas,
            fecha_exportacion=datetime.now().isoformat(),
        )

    def get_balanza(self, ejercicio: int, mes: int) -> BalanzaComprobacion:
        """Obtiene balanza mock de CONTPAQi Desktop."""
        self._ensure_connected()
        logger.info(f"CONTPAQiDesktopAdapter: obteniendo balanza {ejercicio}-{mes:02d} (mock)")

        cuentas = [
            {"cuenta": "1001", "nombre": "Caja general", "deudor": 35000, "acreedor": 0},
            {"cuenta": "1002", "nombre": "Banco", "deudor": 180000, "acreedor": 0},
            {"cuenta": "2001", "nombre": "Proveedores", "deudor": 0, "acreedor": 60000},
            {"cuenta": "3001", "nombre": "Capital", "deudor": 0, "acreedor": 150000},
            {"cuenta": "4001", "nombre": "Ventas", "deudor": 0, "acreedor": 300000},
            {"cuenta": "5001", "nombre": "Gastos", "deudor": 120000, "acreedor": 0},
        ]

        return BalanzaComprobacion(
            ejercicio=ejercicio,
            mes=mes,
            rfc=self._empresa_info.get("rfc", ""),
            cuentas=cuentas,
            total_deudor=sum(c["deudor"] for c in cuentas),
            total_acreedor=sum(c["acreedor"] for c in cuentas),
            fecha_generacion=datetime.now().isoformat(),
        )
