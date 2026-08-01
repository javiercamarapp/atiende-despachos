# -*- coding: utf-8 -*-
"""
absis.py — Adaptador mock para Absis (Desktop, sin API).

Implementa la interfaz ERPAdapter con respuestas simuladas.
En producción, usaría Computer Use (Playwright) para automatizar la
interfaz gráfica de Absis Desktop.
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


class AbsisAdapter(ERPAdapter):
    """Adaptador mock para Absis (Desktop).

    Absis es un ERP contable mexicano de escritorio sin API oficial.
    En producción, se usaría Computer Use (Playwright) para automatizar
    la interfaz gráfica de Absis Desktop.
    """

    def __init__(self, config: Optional[ERPConfig] = None):
        config = config or ERPConfig(type=ERPType.ABSIS)
        config.endpoint = config.endpoint or os.environ.get(
            "ABSIS_ENDPOINT", "C:\\Program Files\\Absis\\"
        )
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Simula la conexión a Absis Desktop.

        En producción:
        - Computer Use para automatizar la UI de Absis
        - Alternativamente, acceso directo a la BD
        """
        logger.info("AbsisAdapter: conectando a Absis Desktop (mock)...")
        self._connected = True
        self._empresa_info = {
            "nombre": "Empresa Absis Mock S.A. DE C.V.",
            "rfc": "ABS010101AAA",
            "ejercicio": 2026,
            "version": "2024.1.0",
            "base_datos": "Absis_Empresa01",
        }
        logger.info("AbsisAdapter: conexión exitosa (mock)")
        return True

    def disconnect(self) -> None:
        self._connected = False
        self._empresa_info = {}
        logger.info("AbsisAdapter: desconectado")

    def get_invoices(self, date_range: Optional[Dict[str, str]] = None) -> List[Invoice]:
        """Obtiene facturas mock de Absis.

        En producción: Computer Use para navegar módulo de facturas.
        """
        self._ensure_connected()
        logger.info("AbsisAdapter: obteniendo facturas (mock)")

        now = datetime.now().strftime("%Y-%m-%d")
        return [
            Invoice(
                id=f"ABS-INV-{i:04d}",
                uuid=str(_uuid.uuid4()),
                rfc="ABC010101AAA",
                fecha=now,
                monto=round(7000 + i * 1200, 2),
                subtotal=round(6034.48 + i * 1034.48, 2),
                iva=round(965.52 + i * 165.52, 2),
                status="activa",
                concepto=f"Servicio Absis {i}",
                serie="AB",
                folio=str(6000 + i),
                moneda="MXN",
            )
            for i in range(1, 4)
        ]

    def get_polizas(self, date_range: Optional[Dict[str, str]] = None) -> List[Poliza]:
        """Obtiene pólizas mock de Absis.

        En producción: Computer Use para navegar módulo contable.
        """
        self._ensure_connected()
        logger.info("AbsisAdapter: obteniendo pólizas (mock)")

        now = datetime.now().strftime("%Y-%m-%d")
        return [
            Poliza(
                id=f"ABS-POL-{i:04d}",
                fecha=now,
                concepto=f"Póliza contable Absis {i}",
                tipo="Diario",
                numero=i,
                cuentas=[
                    CuentaPoliza(cuenta="1101", descripcion="Caja", debe=5000 * i, haber=0),
                    CuentaPoliza(cuenta="4101", descripcion="Ingresos por servicios", debe=0, haber=5000 * i),
                ],
                monto_total=5000 * i,
                status=StatusPoliza.CONTABILIZADA,
            )
            for i in range(1, 3)
        ]

    def upload_poliza(self, poliza: Poliza) -> Dict[str, Any]:
        """Sube una póliza mock a Absis.

        En producción: Computer Use para registrar póliza en la UI.
        """
        self._ensure_connected()
        logger.info(f"AbsisAdapter: subiendo póliza {poliza.id}")

        if not poliza.esta_cuadrada():
            return {"exito": False, "mensaje": "La póliza no está cuadrada (debe != haber)"}

        return {
            "exito": True,
            "id_erp": f"ABS-POL-{_uuid.uuid4().hex[:8].upper()}",
            "mensaje": "Póliza subida exitosamente (mock Absis)",
            "fecha_registro": datetime.now().isoformat(),
        }

    def get_chart_of_accounts(self) -> ChartOfAccounts:
        """Obtiene catálogo de cuentas mock de Absis.

        En producción: Computer Use o exportación de archivo.
        """
        self._ensure_connected()
        logger.info("AbsisAdapter: obteniendo catálogo de cuentas (mock)")

        cuentas = [
            CuentaContable(clave="1101", nombre="Caja", tipo=TipoCuenta.ACTIVO, saldo=20000, es_auxiliar=True),
            CuentaContable(clave="1102", nombre="Bancos", tipo=TipoCuenta.ACTIVO, saldo=130000, es_auxiliar=True),
            CuentaContable(clave="1201", nombre="Inventarios", tipo=TipoCuenta.ACTIVO, saldo=40000, es_auxiliar=True),
            CuentaContable(clave="2101", nombre="Proveedores", tipo=TipoCuenta.PASIVO, saldo=-22000, es_auxiliar=True),
            CuentaContable(clave="2102", nombre="Impuestos por pagar", tipo=TipoCuenta.PASIVO, saldo=-5000, es_auxiliar=True),
            CuentaContable(clave="3101", nombre="Capital social", tipo=TipoCuenta.CAPITAL, saldo=-65000),
            CuentaContable(clave="4101", nombre="Ingresos por servicios", tipo=TipoCuenta.INGRESO, saldo=-90000, es_auxiliar=True),
            CuentaContable(clave="5101", nombre="Sueldos y salarios", tipo=TipoCuenta.GASTO, saldo=45000, es_auxiliar=True),
            CuentaContable(clave="5102", nombre="Renta", tipo=TipoCuenta.GASTO, saldo=10000, es_auxiliar=True),
            CuentaContable(clave="5103", nombre="Servicios", tipo=TipoCuenta.GASTO, saldo=7000, es_auxiliar=True),
        ]

        return ChartOfAccounts(
            empresa=self._empresa_info.get("nombre", ""),
            ejercicio=2026,
            cuentas=cuentas,
            fecha_exportacion=datetime.now().isoformat(),
        )

    def get_balanza(self, ejercicio: int, mes: int) -> BalanzaComprobacion:
        """Obtiene balanza de comprobación mock de Absis.

        En producción: Computer Use o exportación de reporte.
        """
        self._ensure_connected()
        logger.info(f"AbsisAdapter: obteniendo balanza {ejercicio}-{mes:02d} (mock)")

        cuentas = [
            {"cuenta": "1101", "nombre": "Caja", "deudor": 20000, "acreedor": 0},
            {"cuenta": "1102", "nombre": "Bancos", "deudor": 130000, "acreedor": 0},
            {"cuenta": "2101", "nombre": "Proveedores", "deudor": 0, "acreedor": 22000},
            {"cuenta": "3101", "nombre": "Capital social", "deudor": 0, "acreedor": 65000},
            {"cuenta": "4101", "nombre": "Ingresos", "deudor": 0, "acreedor": 90000},
            {"cuenta": "5101", "nombre": "Sueldos", "deudor": 45000, "acreedor": 0},
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
