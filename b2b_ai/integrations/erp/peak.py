# -*- coding: utf-8 -*-
"""
peak.py — Adaptador mock para Peak Contabilidad (Desktop, sin API).

Implementa la interfaz ERPAdapter con respuestas simuladas.
En producción, usaría Computer Use (Playwright) para automatizar la
interfaz gráfica de Peak Desktop.
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


class PeakAdapter(ERPAdapter):
    """Adaptador mock para Peak Contabilidad (Desktop).

    Peak es un ERP contable mexicano de escritorio sin API oficial.
    En producción, se usaría Computer Use (Playwright) para automatizar
    la interfaz gráfica, o acceso directo a la base de datos SQL Server.
    """

    def __init__(self, config: Optional[ERPConfig] = None):
        config = config or ERPConfig(type=ERPType.PEAK)
        config.endpoint = config.endpoint or os.environ.get(
            "PEAK_ENDPOINT", "C:\\Program Files\\Peak\\"
        )
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Simula la conexión a Peak Desktop.

        En producción:
        - Opción 1: Computer Use para automatizar la UI de Peak
        - Opción 2: Conexión directa a SQL Server
        - Opción 3: Importación de archivos TXT/CSV
        """
        logger.info("PeakAdapter: conectando a Peak Desktop (mock)...")
        self._connected = True
        self._empresa_info = {
            "nombre": "Empresa Peak Mock S.A. DE C.V.",
            "rfc": "PK010101AAA",
            "ejercicio": 2026,
            "version": "2024.1.0",
            "base_datos": "Peak_Empresa01",
        }
        logger.info("PeakAdapter: conexión exitosa (mock)")
        return True

    def disconnect(self) -> None:
        self._connected = False
        self._empresa_info = {}
        logger.info("PeakAdapter: desconectado")

    def get_invoices(self, date_range: Optional[Dict[str, str]] = None) -> List[Invoice]:
        """Obtiene facturas mock de Peak.

        En producción: Computer Use para navegar módulo de facturas.
        """
        self._ensure_connected()
        logger.info("PeakAdapter: obteniendo facturas (mock)")

        now = datetime.now().strftime("%Y-%m-%d")
        return [
            Invoice(
                id=f"PK-INV-{i:04d}",
                uuid=str(_uuid.uuid4()),
                rfc="PKC010101AAA",
                fecha=now,
                monto=round(12000 + i * 2000, 2),
                subtotal=round(10344.83 + i * 1724.14, 2),
                iva=round(1655.17 + i * 275.86, 2),
                status="activa",
                concepto=f"Servicio profesional Peak {i}",
                serie="PK",
                folio=str(3000 + i),
                moneda="MXN",
            )
            for i in range(1, 4)
        ]

    def get_polizas(self, date_range: Optional[Dict[str, str]] = None) -> List[Poliza]:
        """Obtiene pólizas mock de Peak.

        En producción: Computer Use para navegar módulo contable.
        """
        self._ensure_connected()
        logger.info("PeakAdapter: obteniendo pólizas (mock)")

        now = datetime.now().strftime("%Y-%m-%d")
        return [
            Poliza(
                id=f"PK-POL-{i:04d}",
                fecha=now,
                concepto=f"Póliza contable Peak {i}",
                tipo="Diario",
                numero=i,
                cuentas=[
                    CuentaPoliza(cuenta="1101", descripcion="Caja", debe=7000 * i, haber=0),
                    CuentaPoliza(cuenta="4101", descripcion="Ingresos por servicios", debe=0, haber=7000 * i),
                ],
                monto_total=7000 * i,
                status=StatusPoliza.CONTABILIZADA,
            )
            for i in range(1, 3)
        ]

    def upload_poliza(self, poliza: Poliza) -> Dict[str, Any]:
        """Sube una póliza mock a Peak.

        En producción: Computer Use para registrar póliza en la UI.
        """
        self._ensure_connected()
        logger.info(f"PeakAdapter: subiendo póliza {poliza.id}")

        if not poliza.esta_cuadrada():
            return {"exito": False, "mensaje": "La póliza no está cuadrada (debe != haber)"}

        return {
            "exito": True,
            "id_erp": f"PK-POL-{_uuid.uuid4().hex[:8].upper()}",
            "mensaje": "Póliza subida exitosamente (mock Peak)",
            "fecha_registro": datetime.now().isoformat(),
        }

    def get_chart_of_accounts(self) -> ChartOfAccounts:
        """Obtiene catálogo de cuentas mock de Peak.

        En producción: Computer Use o exportación de archivo TXT.
        """
        self._ensure_connected()
        logger.info("PeakAdapter: obteniendo catálogo de cuentas (mock)")

        cuentas = [
            CuentaContable(clave="1101", nombre="Caja", tipo=TipoCuenta.ACTIVO, saldo=40000, es_auxiliar=True),
            CuentaContable(clave="1102", nombre="Bancos", tipo=TipoCuenta.ACTIVO, saldo=200000, es_auxiliar=True),
            CuentaContable(clave="1201", nombre="Inventarios", tipo=TipoCuenta.ACTIVO, saldo=60000, es_auxiliar=True),
            CuentaContable(clave="2101", nombre="Proveedores", tipo=TipoCuenta.PASIVO, saldo=-35000, es_auxiliar=True),
            CuentaContable(clave="2102", nombre="Impuestos por pagar", tipo=TipoCuenta.PASIVO, saldo=-8000, es_auxiliar=True),
            CuentaContable(clave="3101", nombre="Capital social", tipo=TipoCuenta.CAPITAL, saldo=-100000),
            CuentaContable(clave="4101", nombre="Ingresos por servicios", tipo=TipoCuenta.INGRESO, saldo=-150000, es_auxiliar=True),
            CuentaContable(clave="5101", nombre="Sueldos y salarios", tipo=TipoCuenta.GASTO, saldo=65000, es_auxiliar=True),
            CuentaContable(clave="5102", nombre="Renta", tipo=TipoCuenta.GASTO, saldo=18000, es_auxiliar=True),
            CuentaContable(clave="5103", nombre="Servicios", tipo=TipoCuenta.GASTO, saldo=12000, es_auxiliar=True),
        ]

        return ChartOfAccounts(
            empresa=self._empresa_info.get("nombre", ""),
            ejercicio=2026,
            cuentas=cuentas,
            fecha_exportacion=datetime.now().isoformat(),
        )

    def get_balanza(self, ejercicio: int, mes: int) -> BalanzaComprobacion:
        """Obtiene balanza de comprobación mock de Peak.

        En producción: Computer Use o exportación de reporte.
        """
        self._ensure_connected()
        logger.info(f"PeakAdapter: obteniendo balanza {ejercicio}-{mes:02d} (mock)")

        cuentas = [
            {"cuenta": "1101", "nombre": "Caja", "deudor": 40000, "acreedor": 0},
            {"cuenta": "1102", "nombre": "Bancos", "deudor": 200000, "acreedor": 0},
            {"cuenta": "2101", "nombre": "Proveedores", "deudor": 0, "acreedor": 35000},
            {"cuenta": "3101", "nombre": "Capital social", "deudor": 0, "acreedor": 100000},
            {"cuenta": "4101", "nombre": "Ingresos", "deudor": 0, "acreedor": 150000},
            {"cuenta": "5101", "nombre": "Sueldos", "deudor": 65000, "acreedor": 0},
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
