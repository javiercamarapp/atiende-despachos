# -*- coding: utf-8 -*-
"""
quickbooks.py — Adaptador mock para QuickBooks Online (API REST).

Implementa la interfaz ERPAdapter con respuestas simuladas.
En producción, se conectaría a la QuickBooks API (https://developer.intuit.com/).
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


class QuickBooksOnlineAdapter(ERPAdapter):
    """Adaptador mock para QuickBooks Online.

    En producción, se conectaría a la QuickBooks API REST v3
    (https://developer.intuit.com/appinfo/qboappsconsole/).
    Usa OAuth 2.0 para autenticación.
    """

    def __init__(self, config: Optional[ERPConfig] = None):
        config = config or ERPConfig(type=ERPType.QUICKBOOKS_ONLINE)
        config.endpoint = config.endpoint or "https://quickbooks.api.intuit.com/v3"
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Simula la conexión a QuickBooks Online.

        En producción:
        1. Obtener OAuth 2.0 token con client_id/client_secret
        2. Intercambiar authorization_code por access_token
        3. Usar refresh_token para sesiones posteriores
        """
        logger.info("QuickBooksOnlineAdapter: conectando a QuickBooks Online (mock)...")
        self._connected = True
        self._empresa_info = {
            "nombre": "Empresa QB Mock S.A. DE C.V.",
            "rfc": "QBZ010101AAA",
            "ejercicio": 2026,
            "company_id": self.config.company_id or "QB-MOCK-123",
            "realm_id": "QB-REALM-456",
        }
        logger.info("QuickBooksOnlineAdapter: conexión exitosa (mock)")
        return True

    def disconnect(self) -> None:
        self._connected = False
        self._empresa_info = {}
        logger.info("QuickBooksOnlineAdapter: desconectado")

    def get_invoices(self, date_range: Optional[Dict[str, str]] = None) -> List[Invoice]:
        """Obtiene facturas mock de QuickBooks.

        En producción: GET /company/{realmId}/query?query=SELECT * FROM Invoice
        """
        self._ensure_connected()
        logger.info("QuickBooksOnlineAdapter: obteniendo facturas (mock)")

        now = datetime.now().strftime("%Y-%m-%d")
        return [
            Invoice(
                id=f"QB-INV-{i:04d}",
                uuid=str(_uuid.uuid4()),
                rfc="DDD040404DDD",
                fecha=now,
                monto=round(25000 + i * 5000, 2),
                subtotal=round(21551.72 + i * 4310.34, 2),
                iva=round(3448.28 + i * 689.66, 2),
                status="activa",
                concepto=f"Service invoice {i}",
                serie="QB",
                folio=str(4000 + i),
                moneda="MXN",
                forma_pago="03",
                metodo_pago="PUE",
            )
            for i in range(1, 4)
        ]

    def get_polizas(self, date_range: Optional[Dict[str, str]] = None) -> List[Poliza]:
        """Obtiene pólizas mock de QuickBooks.

        En producción: GET /company/{realmId}/query?query=SELECT * FROM JournalEntry
        """
        self._ensure_connected()
        logger.info("QuickBooksOnlineAdapter: obteniendo pólizas (mock)")

        now = datetime.now().strftime("%Y-%m-%d")
        return [
            Poliza(
                id=f"QB-POL-{i:04d}",
                fecha=now,
                concepto=f"Journal entry {i}",
                tipo="Diario",
                numero=i,
                cuentas=[
                    CuentaPoliza(cuenta="1000", descripcion="Checking", debe=10000 * i, haber=0),
                    CuentaPoliza(cuenta="4000", descripcion="Sales Revenue", debe=0, haber=10000 * i),
                ],
                monto_total=10000 * i,
                status=StatusPoliza.CONTABILIZADA,
            )
            for i in range(1, 3)
        ]

    def upload_poliza(self, poliza: Poliza) -> Dict[str, Any]:
        """Sube una póliza mock a QuickBooks.

        En producción: POST /company/{realmId}/journalentry
        """
        self._ensure_connected()
        logger.info(f"QuickBooksOnlineAdapter: subiendo póliza {poliza.id}")

        if not poliza.esta_cuadrada():
            return {"exito": False, "mensaje": "Journal entry not balanced"}

        return {
            "exito": True,
            "id_erp": f"QB-JE-{_uuid.uuid4().hex[:8].upper()}",
            "mensaje": "Journal entry created successfully (mock QuickBooks)",
            "fecha_registro": datetime.now().isoformat(),
        }

    def get_chart_of_accounts(self) -> ChartOfAccounts:
        """Obtiene catálogo de cuentas mock de QuickBooks.

        En producción: GET /company/{realmId}/query?query=SELECT * FROM Account
        """
        self._ensure_connected()
        logger.info("QuickBooksOnlineAdapter: obteniendo catálogo de cuentas (mock)")

        cuentas = [
            CuentaContable(clave="1000", nombre="Checking", tipo=TipoCuenta.ACTIVO),
            CuentaContable(clave="1001", nombre="Savings", tipo=TipoCuenta.ACTIVO),
            CuentaContable(clave="2000", nombre="Accounts Payable", tipo=TipoCuenta.PASIVO),
            CuentaContable(clave="3000", nombre="Equity", tipo=TipoCuenta.CAPITAL),
            CuentaContable(clave="4000", nombre="Sales Revenue", tipo=TipoCuenta.INGRESO),
            CuentaContable(clave="5000", nombre="Expenses", tipo=TipoCuenta.GASTO),
        ]

        return ChartOfAccounts(
            empresa=self._empresa_info.get("nombre", ""),
            ejercicio=2026,
            cuentas=cuentas,
            fecha_exportacion=datetime.now().isoformat(),
        )

    def get_balanza(self, ejercicio: int, mes: int) -> BalanzaComprobacion:
        """Obtiene balanza mock de QuickBooks.

        En producción: GET /company/{realmId}/reports/BalanceSheet
        """
        self._ensure_connected()
        logger.info(f"QuickBooksOnlineAdapter: obteniendo balanza {ejercicio}-{mes:02d} (mock)")

        cuentas = [
            {"cuenta": "1000", "nombre": "Checking", "deudor": 95000, "acreedor": 0},
            {"cuenta": "1001", "nombre": "Savings", "deudor": 50000, "acreedor": 0},
            {"cuenta": "2000", "nombre": "Accounts Payable", "deudor": 0, "acreedor": 35000},
            {"cuenta": "3000", "nombre": "Equity", "deudor": 0, "acreedor": 100000},
            {"cuenta": "4000", "nombre": "Sales Revenue", "deudor": 0, "acreedor": 180000},
            {"cuenta": "5000", "nombre": "Expenses", "deudor": 70000, "acreedor": 0},
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
