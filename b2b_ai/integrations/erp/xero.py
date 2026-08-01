# -*- coding: utf-8 -*-
"""
xero.py — Adaptador mock para Xero Accounting (API REST).

Implementa la interfaz ERPAdapter con respuestas simuladas.
En producción, se conectaría a la Xero API (https://developer.xero.com/).
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
class XeroAdapter(ERPAdapter):
    """Adaptador mock para Xero Accounting.

    En producción, se conectaría a la Xero API REST
    (https://api.xero.com/api.xro/2.0/).
    Usa OAuth 2.0 para autenticación.
    """

    def __init__(self, config: Optional[ERPConfig] = None):
        config = config or ERPConfig(type=ERPType.XERO)
        config.endpoint = config.endpoint or "https://api.xero.com/api.xro/2.0/"
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Simula la conexión a Xero.

        En producción:
        1. Obtener OAuth 2.0 token con client_id/client_secret
        2. Autorizar usuario en browser
        3. Intercambiar code por access_token
        """
        logger.info("XeroAdapter: conectando a Xero (mock)...")
        self._connected = True
        self._empresa_info = {
            "nombre": "Empresa Xero Mock Ltd",
            "rfc": "XRO010101AAA",
            "ejercicio": 2026,
            "tenant_id": "XERO-TENANT-789",
        }
        logger.info("XeroAdapter: conexión exitosa (mock)")
        return True

    def disconnect(self) -> None:
        self._connected = False
        self._empresa_info = {}
        logger.info("XeroAdapter: desconectado")

    def get_invoices(self, date_range: Optional[Dict[str, str]] = None) -> List[Invoice]:
        """Obtiene facturas mock de Xero.

        En producción: GET /Invoices
        """
        self._ensure_connected()
        logger.info("XeroAdapter: obteniendo facturas (mock)")

        now = datetime.now().strftime("%Y-%m-%d")
        return [
            Invoice(
                id=f"XERO-INV-{i:04d}",
                uuid=str(_uuid.uuid4()),
                rfc="EEE050505EEE",
                fecha=now,
                monto=round(30000 + i * 4000, 2),
                subtotal=round(25862.07 + i * 3448.28, 2),
                iva=round(4137.93 + i * 551.72, 2),
                status="activa",
                concepto=f"Xero invoice {i}",
                serie="XERO",
                folio=str(5000 + i),
                moneda="MXN",
            )
            for i in range(1, 4)
        ]

    def get_polizas(self, date_range: Optional[Dict[str, str]] = None) -> List[Poliza]:
        """Obtiene pólizas mock de Xero (Manual Journals).

        En producción: GET /ManualJournals
        """
        self._ensure_connected()
        logger.info("XeroAdapter: obteniendo pólizas (mock)")

        now = datetime.now().strftime("%Y-%m-%d")
        return [
            Poliza(
                id=f"XERO-POL-{i:04d}",
                fecha=now,
                concepto=f"Manual journal {i}",
                tipo="Diario",
                numero=i,
                cuentas=[
                    CuentaPoliza(cuenta="090", descripcion="Bank Account", debe=15000 * i, haber=0),
                    CuentaPoliza(cuenta="200", descripcion="Sales", debe=0, haber=15000 * i),
                ],
                monto_total=15000 * i,
                status=StatusPoliza.CONTABILIZADA,
            )
            for i in range(1, 3)
        ]

    def upload_poliza(self, poliza: Poliza) -> Dict[str, Any]:
        """Sube una póliza mock a Xero.

        En producción: POST /ManualJournals
        """
        self._ensure_connected()
        logger.info(f"XeroAdapter: subiendo póliza {poliza.id}")

        if not poliza.esta_cuadrada():
            return {"exito": False, "mensaje": "Manual journal not balanced"}

        return {
            "exito": True,
            "id_erp": f"XERO-MJ-{_uuid.uuid4().hex[:8].upper()}",
            "mensaje": "Manual journal created successfully (mock Xero)",
            "fecha_registro": datetime.now().isoformat(),
        }

    def get_chart_of_accounts(self) -> ChartOfAccounts:
        """Obtiene catálogo de cuentas mock de Xero.

        En producción: GET /Accounts
        """
        self._ensure_connected()
        logger.info("XeroAdapter: obteniendo catálogo de cuentas (mock)")

        cuentas = [
            CuentaContable(clave="090", nombre="Bank Account", tipo=TipoCuenta.ACTIVO),
            CuentaContable(clave="100", nombre="Accounts Receivable", tipo=TipoCuenta.ACTIVO),
            CuentaContable(clave="200", nombre="Sales", tipo=TipoCuenta.INGRESO),
            CuentaContable(clave="210", nombre="Other Income", tipo=TipoCuenta.INGRESO),
            CuentaContable(clave="310", nombre="Accounts Payable", tipo=TipoCuenta.PASIVO),
            CuentaContable(clave="400", nombre="Expenses", tipo=TipoCuenta.GASTO),
            CuentaContable(clave="410", nombre="Cost of Goods Sold", tipo=TipoCuenta.GASTO),
            CuentaContable(clave="500", nombre="Equity", tipo=TipoCuenta.CAPITAL),
        ]

        return ChartOfAccounts(
            empresa=self._empresa_info.get("nombre", ""),
            ejercicio=2026,
            cuentas=cuentas,
            fecha_exportacion=datetime.now().isoformat(),
        )

    def get_balanza(self, ejercicio: int, mes: int) -> BalanzaComprobacion:
        """Obtiene balanza mock de Xero.

        En producción: GET /Reports/BalanceSheet
        """
        self._ensure_connected()
        logger.info(f"XeroAdapter: obteniendo balanza {ejercicio}-{mes:02d} (mock)")

        cuentas = [
            {"cuenta": "090", "nombre": "Bank Account", "deudor": 110000, "acreedor": 0},
            {"cuenta": "100", "nombre": "Accounts Receivable", "deudor": 45000, "acreedor": 0},
            {"cuenta": "310", "nombre": "Accounts Payable", "deudor": 0, "acreedor": 40000},
            {"cuenta": "500", "nombre": "Equity", "deudor": 0, "acreedor": 120000},
            {"cuenta": "200", "nombre": "Sales", "deudor": 0, "acreedor": 220000},
            {"cuenta": "400", "nombre": "Expenses", "deudor": 85000, "acreedor": 0},
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
