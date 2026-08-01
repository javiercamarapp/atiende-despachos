import os
# -*- coding: utf-8 -*-
"""
contpaqi_web.py — Adaptador mock para CONTPAQi versión web (API REST).

Implementa la interfaz ERPAdapter con respuestas simuladas.
En producción, se conectaría a la API REST de CONTPAQi Web.
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


class CONTPAQiWebAdapter(ERPAdapter):
    """Adaptador mock para CONTPAQi versión web (API REST).

    En producción, se conectaría a la API de CONTPAQi Web
    (https://api.contpaqi.com/ o similar).
    """

    def __init__(self, config: Optional[ERPConfig] = None):
        config = config or ERPConfig(type=ERPType.CONTPAQi_WEB)
        config.endpoint = config.endpoint or "https://api.contpaqi.com/v1/"
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Simula la conexión a CONTPAQi Web."""
        logger.info("CONTPAQiWebAdapter: conectando a CONTPAQi Web (mock)...")
        # En producción: POST /auth/login con credenciales
        self._connected = True
        self._empresa_info = {
            "nombre": "Empresa CONTPAQi Mock S.A. DE C.V.",
            "rfc": "CTQ010101AAA",
            "ejercicio": 2026,
        }
        logger.info("CONTPAQiWebAdapter: conexión exitosa (mock)")
        return True

    def disconnect(self) -> None:
        """Desconecta de CONTPAQi Web."""
        self._connected = False
        self._empresa_info = {}
        logger.info("CONTPAQiWebAdapter: desconectado")

    def get_invoices(self, date_range: Optional[Dict[str, str]] = None) -> List[Invoice]:
        """Obtiene facturas mock de CONTPAQi."""
        self._ensure_connected()
        logger.info("CONTPAQiWebAdapter: obteniendo facturas (mock)")

        now = datetime.now().strftime("%Y-%m-%d")
        return [
            Invoice(
                id=f"CTQ-INV-{i:04d}",
                uuid=str(_uuid.uuid4()),
                rfc="AAA010101AAA",
                fecha=now,
                monto=round(10000 + i * 1500, 2),
                subtotal=round(8620.69 + i * 1293.10, 2),
                iva=round(1379.31 + i * 206.90, 2),
                status="activa",
                concepto=f"Servicio profesional {i}",
                serie="A",
                folio=str(1000 + i),
            )
            for i in range(1, 4)
        ]

    def get_polizas(self, date_range: Optional[Dict[str, str]] = None) -> List[Poliza]:
        """Obtiene pólizas mock de CONTPAQi."""
        self._ensure_connected()
        logger.info("CONTPAQiWebAdapter: obteniendo pólizas (mock)")

        now = datetime.now().strftime("%Y-%m-%d")
        return [
            Poliza(
                id=f"CTQ-POL-{i:04d}",
                fecha=now,
                concepto=f"Póliza contable mock {i}",
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
        """Sube una póliza mock a CONTPAQi."""
        self._ensure_connected()
        logger.info(f"CONTPAQiWebAdapter: subiendo póliza {poliza.id}")

        if not poliza.esta_cuadrada():
            return {
                "exito": False,
                "mensaje": "La póliza no está cuadrada (debe != haber)",
                "total_debe": poliza.calcular_totales()[0],
                "total_haber": poliza.calcular_totales()[1],
            }

        return {
            "exito": True,
            "id_erp": f"CTQ-POL-{_uuid.uuid4().hex[:8].upper()}",
            "mensaje": "Póliza subida exitosamente (mock CONTPAQi)",
            "fecha_registro": datetime.now().isoformat(),
        }

    def get_chart_of_accounts(self) -> ChartOfAccounts:
        """Obtiene catálogo de cuentas mock de CONTPAQi."""
        self._ensure_connected()
        logger.info("CONTPAQiWebAdapter: obteniendo catálogo de cuentas (mock)")

        cuentas = [
            CuentaContable(clave="1101", nombre="Caja", tipo=TipoCuenta.ACTIVO, saldo=50000, es_auxiliar=True),
            CuentaContable(clave="1102", nombre="Bancos", tipo=TipoCuenta.ACTIVO, saldo=250000, es_auxiliar=True),
            CuentaContable(clave="1201", nombre="Inventarios", tipo=TipoCuenta.ACTIVO, saldo=80000, es_auxiliar=True),
            CuentaContable(clave="2101", nombre="Proveedores", tipo=TipoCuenta.PASIVO, saldo=-45000, es_auxiliar=True),
            CuentaContable(clave="2102", nombre="Impuestos por pagar", tipo=TipoCuenta.PASIVO, saldo=-12000, es_auxiliar=True),
            CuentaContable(clave="3101", nombre="Capital social", tipo=TipoCuenta.CAPITAL, saldo=-100000),
            CuentaContable(clave="4101", nombre="Ingresos por servicios", tipo=TipoCuenta.INGRESO, saldo=-200000, es_auxiliar=True),
            CuentaContable(clave="5101", nombre="Sueldos y salarios", tipo=TipoCuenta.GASTO, saldo=85000, es_auxiliar=True),
            CuentaContable(clave="5102", nombre="Renta", tipo=TipoCuenta.GASTO, saldo=24000, es_auxiliar=True),
            CuentaContable(clave="5103", nombre="Servicios", tipo=TipoCuenta.GASTO, saldo=15000, es_auxiliar=True),
        ]

        return ChartOfAccounts(
            empresa=self._empresa_info.get("nombre", ""),
            ejercicio=2026,
            cuentas=cuentas,
            fecha_exportacion=datetime.now().isoformat(),
        )

    def get_balanza(self, ejercicio: int, mes: int) -> BalanzaComprobacion:
        """Obtiene balanza de comprobación mock de CONTPAQi."""
        self._ensure_connected()
        logger.info(f"CONTPAQiWebAdapter: obteniendo balanza {ejercicio}-{mes:02d} (mock)")

        cuentas = [
            {"cuenta": "1101", "nombre": "Caja", "deudor": 50000, "acreedor": 0},
            {"cuenta": "1102", "nombre": "Bancos", "deudor": 250000, "acreedor": 0},
            {"cuenta": "2101", "nombre": "Proveedores", "deudor": 0, "acreedor": 45000},
            {"cuenta": "3101", "nombre": "Capital social", "deudor": 0, "acreedor": 100000},
            {"cuenta": "4101", "nombre": "Ingresos", "deudor": 0, "acreedor": 200000},
            {"cuenta": "5101", "nombre": "Sueldos", "deudor": 85000, "acreedor": 0},
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
