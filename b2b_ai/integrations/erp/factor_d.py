import os
# -*- coding: utf-8 -*-
"""
factor_d.py — Adaptador mock para ERP Factor D (cloud).
"""
from __future__ import annotations

import logging
import uuid as _uuid
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.erp.adapter import ERPAdapter
from b2b_ai.integrations.erp.models import (
    BalanzaComprobacion, ChartOfAccounts, CuentaContable, CuentaPoliza,
    ERPConfig, ERPType, Invoice, Poliza,
)

logger = logging.getLogger(__name__)


class FactorDAdapter(ERPAdapter):
    """Adaptador mock para Factor D ERP (cloud)."""

    def __init__(self, config: Optional[ERPConfig] = None):
        config = config or ERPConfig(type=ERPType.FACTOR_D, empresa="Factor D Mock")
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        self._connected = True
        self._empresa_info = {"nombre": "Factor D Mock", "rfc": "XAXX010101000"}
        logger.info("FactorDAdapter: conexión exitosa (mock)")
        return True

    def disconnect(self) -> None:
        self._connected = False

    def get_invoices(self, date_range: Optional[Dict[str, str]] = None) -> List[Invoice]:
        self._ensure_connected()
        return [Invoice(id=f"FD-{i:04d}", uuid=str(_uuid.uuid4()), rfc="AAA010101AAA",
                        fecha=f"2026-01-{10+i:02d}", monto=9000.0 + i * 1200, subtotal=9000.0, iva=1440.0,
                        status="activa", concepto=f"Servicio Factor D #{i}")
                for i in range(1, 4)]

    def get_polizas(self, date_range: Optional[Dict[str, str]] = None) -> List[Poliza]:
        self._ensure_connected()
        return [Poliza(id=f"POL-FD-{i:04d}", fecha=f"2026-01-{10+i:02d}", concepto=f"Póliza Factor D #{i}",
                       cuentas=[CuentaPoliza(cuenta="1101", debe=9000, haber=0), CuentaPoliza(cuenta="4101", debe=0, haber=9000)])
                for i in range(1, 3)]

    def upload_poliza(self, poliza: Poliza) -> Dict[str, Any]:
        self._ensure_connected()
        return {"exito": poliza.esta_cuadrada(), "id": poliza.id, "mensaje": "Póliza subida (mock)"}

    def get_chart_of_accounts(self) -> ChartOfAccounts:
        self._ensure_connected()
        return ChartOfAccounts(empresa="Factor D Mock", cuentas=[
            CuentaContable(clave="1101", nombre="Caja", tipo="activo"),
            CuentaContable(clave="4101", nombre="Ingresos", tipo="ingreso"),
        ])

    def get_balanza(self, ejercicio: int, mes: int) -> BalanzaComprobacion:
        self._ensure_connected()
        return BalanzaComprobacion(ejercicio=ejercicio, mes=mes, total_deudor=220000.0, total_acreedor=220000.0)
