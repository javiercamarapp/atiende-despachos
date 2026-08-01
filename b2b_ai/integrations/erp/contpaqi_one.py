# -*- coding: utf-8 -*-
"""
contpaqi_one.py — Adaptador mock para CONTPAQi One (cloud).
Implementa la interfaz ERPAdapter con respuestas simuladas.
En producción, se conectaría a la API REST de CONTPAQi One.
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.erp.adapter import ERPAdapter
from b2b_ai.integrations.erp.models import (
    BalanzaComprobacion,
    ChartOfAccounts,
    CuentaContable,
    CuentaPoliza,
    ERPConfig,
    ERPType,
    Invoice,
    Poliza,
)

logger = logging.getLogger(__name__)


class CONTPAQiOneAdapter(ERPAdapter):
    """Adaptador mock para CONTPAQi One (cloud).

    En producción, se conectaría a la API REST de CONTPAQi One
    (https://contpaqi.com/contpaqi-one/).
    """

    def __init__(self, config: Optional[ERPConfig] = None):
        config = config or ERPConfig(type=ERPType.CONTPAQi_ONE, empresa="CONTPAQi One Mock")
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Simula la conexión a CONTPAQi One."""
        logger.info("CONTPAQiOneAdapter: conectando (mock)...")
        self._connected = True
        self._empresa_info = {"nombre": self.config.empresa or "CONTPAQi One Mock", "rfc": "XAXX010101000"}
        logger.info("CONTPAQiOneAdapter: conexión exitosa (mock)")
        return True

    def disconnect(self) -> None:
        self._connected = False
        logger.info("CONTPAQiOneAdapter: desconectado")

    def get_invoices(self, date_range: Optional[Dict[str, str]] = None) -> List[Invoice]:
        self._ensure_connected()
        return [Invoice(
            id=f"CO-{i:04d}", uuid=str(_uuid.uuid4()), rfc="AAA010101AAA",
            fecha=f"2026-01-{10+i:02d}", monto=5000.0 + i * 1000,
            subtotal=5000.0 + i * 1000, iva=800.0 + i * 160,
            status="activa", concepto=f"Servicio CONTPAQi One #{i}",
        ) for i in range(1, 4)]

    def get_polizas(self, date_range: Optional[Dict[str, str]] = None) -> List[Poliza]:
        self._ensure_connected()
        return [Poliza(
            id=f"POL-CO-{i:04d}", fecha=f"2026-01-{10+i:02d}",
            concepto=f"Póliza CONTPAQi One #{i}", tipo="Diario",
            cuentas=[CuentaPoliza(cuenta="1101", debe=5000, haber=0), CuentaPoliza(cuenta="4101", debe=0, haber=5000)],
        ) for i in range(1, 3)]

    def upload_poliza(self, poliza: Poliza) -> Dict[str, Any]:
        self._ensure_connected()
        return {"exito": poliza.esta_cuadrada(), "id": poliza.id, "mensaje": "Póliza subida (mock)"}

    def get_chart_of_accounts(self) -> ChartOfAccounts:
        self._ensure_connected()
        return ChartOfAccounts(empresa=self.config.empresa or "CONTPAQi One", cuentas=[
            CuentaContable(clave="1101", nombre="Caja", tipo="activo"),
            CuentaContable(clave="4101", nombre="Ingresos", tipo="ingreso"),
        ])

    def get_balanza(self, ejercicio: int, mes: int) -> BalanzaComprobacion:
        self._ensure_connected()
        return BalanzaComprobacion(ejercicio=ejercicio, mes=mes, rfc=self._empresa_info.get("rfc", ""),
                                   total_deudor=150000.0, total_acreedor=150000.0)
