# -*- coding: utf-8 -*-
"""
aspel_cloud.py — Adaptador mock para Aspel Cloud (API REST).

Implementa la interfaz ERPAdapter con respuestas simuladas.
En producción, se conectaría a la API REST de Aspel Cloud.
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


import os
class AspelCloudAdapter(ERPAdapter):
    """Adaptador mock para Aspel Cloud.

    En producción, se conectaría a la API REST de Aspel Cloud
    (https://api.aspelcloud.com/ o similar).
    """

    def __init__(self, config: Optional[ERPConfig] = None):
        config = config or ERPConfig(type=ERPType.ASPEL_CLOUD)
        config.endpoint = config.endpoint or "https://api.aspelcloud.com/v1/"
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Simula la conexión a Aspel Cloud."""
        logger.info("AspelCloudAdapter: conectando a Aspel Cloud (mock)...")
        self._connected = True
        self._empresa_info = {
            "nombre": "Empresa Aspel Mock S.A. DE C.V.",
            "rfc": "ASP010101AAA",
            "ejercicio": 2026,
            "empresa_id": "ASPEL-EMP-001",
        }
        logger.info("AspelCloudAdapter: conexión exitosa (mock)")
        return True

    def disconnect(self) -> None:
        self._connected = False
        self._empresa_info = {}
        logger.info("AspelCloudAdapter: desconectado")

    def get_invoices(self, date_range: Optional[Dict[str, str]] = None) -> List[Invoice]:
        """Obtiene facturas mock de Aspel Cloud."""
        self._ensure_connected()
        logger.info("AspelCloudAdapter: obteniendo facturas (mock)")

        now = datetime.now().strftime("%Y-%m-%d")
        return [
            Invoice(
                id=f"ASP-INV-{i:04d}",
                uuid=str(_uuid.uuid4()),
                rfc="CCC030303CCC",
                fecha=now,
                monto=round(15000 + i * 2000, 2),
                subtotal=round(12931.03 + i * 1724.14, 2),
                iva=round(2068.97 + i * 275.86, 2),
                status="activa",
                concepto=f"Servicio de consultoría {i}",
                serie="C",
                folio=str(3000 + i),
            )
            for i in range(1, 4)
        ]

    def get_polizas(self, date_range: Optional[Dict[str, str]] = None) -> List[Poliza]:
        """Obtiene pólizas mock de Aspel Cloud."""
        self._ensure_connected()
        logger.info("AspelCloudAdapter: obteniendo pólizas (mock)")

        now = datetime.now().strftime("%Y-%m-%d")
        return [
            Poliza(
                id=f"ASP-POL-{i:04d}",
                fecha=now,
                concepto=f"Póliza de egresos {i}",
                tipo="Egresos",
                numero=200 + i,
                cuentas=[
                    CuentaPoliza(cuenta="5101", descripcion="Sueldos", debe=12000 * i, haber=0),
                    CuentaPoliza(cuenta="1102", descripcion="Bancos", debe=0, haber=12000 * i),
                ],
                monto_total=12000 * i,
                status=StatusPoliza.CONTABILIZADA,
            )
            for i in range(1, 3)
        ]

    def upload_poliza(self, poliza: Poliza) -> Dict[str, Any]:
        """Sube una póliza mock a Aspel Cloud."""
        self._ensure_connected()
        logger.info(f"AspelCloudAdapter: subiendo póliza {poliza.id}")

        if not poliza.esta_cuadrada():
            return {"exito": False, "mensaje": "La póliza no está cuadrada"}

        return {
            "exito": True,
            "id_erp": f"ASP-POL-{_uuid.uuid4().hex[:8].upper()}",
            "mensaje": "Póliza subida exitosamente (mock Aspel Cloud)",
            "fecha_registro": datetime.now().isoformat(),
        }

    def get_chart_of_accounts(self) -> ChartOfAccounts:
        """Obtiene catálogo de cuentas mock de Aspel Cloud."""
        self._ensure_connected()
        logger.info("AspelCloudAdapter: obteniendo catálogo de cuentas (mock)")

        cuentas = [
            CuentaContable(clave="1.01", nombre="Caja", tipo=TipoCuenta.ACTIVO),
            CuentaContable(clave="1.02", nombre="Bancos", tipo=TipoCuenta.ACTIVO),
            CuentaContable(clave="2.01", nombre="Proveedores", tipo=TipoCuenta.PASIVO),
            CuentaContable(clave="3.01", nombre="Capital social", tipo=TipoCuenta.CAPITAL),
            CuentaContable(clave="4.01", nombre="Ingresos", tipo=TipoCuenta.INGRESO),
            CuentaContable(clave="5.01", nombre="Gastos generales", tipo=TipoCuenta.GASTO),
        ]

        return ChartOfAccounts(
            empresa=self._empresa_info.get("nombre", ""),
            ejercicio=2026,
            cuentas=cuentas,
            fecha_exportacion=datetime.now().isoformat(),
        )

    def get_balanza(self, ejercicio: int, mes: int) -> BalanzaComprobacion:
        """Obtiene balanza mock de Aspel Cloud."""
        self._ensure_connected()
        logger.info(f"AspelCloudAdapter: obteniendo balanza {ejercicio}-{mes:02d} (mock)")

        cuentas = [
            {"cuenta": "1.01", "nombre": "Caja", "deudor": 42000, "acreedor": 0},
            {"cuenta": "1.02", "nombre": "Bancos", "deudor": 210000, "acreedor": 0},
            {"cuenta": "2.01", "nombre": "Proveedores", "deudor": 0, "acreedor": 55000},
            {"cuenta": "3.01", "nombre": "Capital", "deudor": 0, "acreedor": 120000},
            {"cuenta": "4.01", "nombre": "Ingresos", "deudor": 0, "acreedor": 250000},
            {"cuenta": "5.01", "nombre": "Gastos", "deudor": 95000, "acreedor": 0},
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
