# -*- coding: utf-8 -*-
"""
factor_d.py — Adaptador mock para Factor D (Cloud/SaaS, REST API).

Implementa la interfaz ERPAdapter con respuestas simuladas.
En producción, se conectaría a la API REST de Factor D.
Autenticación: OAuth 2.0
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


class FactorDAdapter(ERPAdapter):
    """Adaptador mock para Factor D (Cloud/SaaS).

    Factor D es una plataforma mexicana de facturación y contabilidad.
    En producción, se conectaría a la API REST de Factor D
    (https://app.factord.com.mx/api/).
    Usa OAuth 2.0 para autenticación.
    """

    def __init__(self, config: Optional[ERPConfig] = None):
        config = config or ERPConfig(type=ERPType.FACTOR_D)
        config.endpoint = config.endpoint or os.environ.get(
            "FACTOR_D_ENDPOINT", "https://app.factord.com.mx/api/v1/"
        )
        config.api_key = config.api_key or os.environ.get("FACTOR_D_CLIENT_ID")
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Simula la conexión a Factor D.

        En producción:
        1. Obtener OAuth 2.0 token con client_id/client_secret
        2. Usar access_token para llamadas API
        3. Renovar con refresh_token
        """
        logger.info("FactorDAdapter: conectando a Factor D (mock)...")
        creds = credentials or {}
        client_id = creds.get("client_id") or self.config.api_key or "mock-client-id"
        if client_id == "mock-client-id":
            logger.info("FactorDAdapter: usando credenciales mock")
        self._connected = True
        self._empresa_info = {
            "nombre": "Empresa Factor D Mock S.A. DE C.V.",
            "rfc": "FD010101AAA",
            "ejercicio": 2026,
            "client_id": client_id,
        }
        logger.info("FactorDAdapter: conexión exitosa (mock)")
        return True

    def disconnect(self) -> None:
        self._connected = False
        self._empresa_info = {}
        logger.info("FactorDAdapter: desconectado")

    def get_invoices(self, date_range: Optional[Dict[str, str]] = None) -> List[Invoice]:
        """Obtiene facturas mock de Factor D.

        En producción: GET /facturas?fecha_inicio=...&fecha_fin=...
        """
        self._ensure_connected()
        logger.info("FactorDAdapter: obteniendo facturas (mock)")

        now = datetime.now().strftime("%Y-%m-%d")
        return [
            Invoice(
                id=f"FD-INV-{i:04d}",
                uuid=str(_uuid.uuid4()),
                rfc="FDC010101AAA",
                fecha=now,
                monto=round(15000 + i * 3000, 2),
                subtotal=round(12931.03 + i * 2586.21, 2),
                iva=round(2068.97 + i * 413.79, 2),
                status="activa",
                concepto=f"Servicio Facturación {i}",
                serie="FD",
                folio=str(7000 + i),
                moneda="MXN",
                forma_pago="03",
                metodo_pago="PUE",
            )
            for i in range(1, 4)
        ]

    def get_polizas(self, date_range: Optional[Dict[str, str]] = None) -> List[Poliza]:
        """Obtiene pólizas mock de Factor D.

        En producción: GET /contabilidad/polizas?fecha_inicio=...&fecha_fin=...
        """
        self._ensure_connected()
        logger.info("FactorDAdapter: obteniendo pólizas (mock)")

        now = datetime.now().strftime("%Y-%m-%d")
        return [
            Poliza(
                id=f"FD-POL-{i:04d}",
                fecha=now,
                concepto=f"Póliza contable Factor D {i}",
                tipo="Diario",
                numero=i,
                cuentas=[
                    CuentaPoliza(cuenta="1101", descripcion="Caja", debe=9000 * i, haber=0),
                    CuentaPoliza(cuenta="4101", descripcion="Ingresos por facturación", debe=0, haber=9000 * i),
                ],
                monto_total=9000 * i,
                status=StatusPoliza.CONTABILIZADA,
            )
            for i in range(1, 3)
        ]

    def upload_poliza(self, poliza: Poliza) -> Dict[str, Any]:
        """Sube una póliza mock a Factor D.

        En producción: POST /contabilidad/polizas
        """
        self._ensure_connected()
        logger.info(f"FactorDAdapter: subiendo póliza {poliza.id}")

        if not poliza.esta_cuadrada():
            return {"exito": False, "mensaje": "Journal entry not balanced"}

        return {
            "exito": True,
            "id_erp": f"FD-POL-{_uuid.uuid4().hex[:8].upper()}",
            "mensaje": "Póliza creada exitosamente (mock Factor D)",
            "fecha_registro": datetime.now().isoformat(),
        }

    def get_chart_of_accounts(self) -> ChartOfAccounts:
        """Obtiene catálogo de cuentas mock de Factor D.

        En producción: GET /contabilidad/catalogo-cuentas
        """
        self._ensure_connected()
        logger.info("FactorDAdapter: obteniendo catálogo de cuentas (mock)")

        cuentas = [
            CuentaContable(clave="1101", nombre="Caja", tipo=TipoCuenta.ACTIVO, saldo=55000, es_auxiliar=True),
            CuentaContable(clave="1102", nombre="Bancos", tipo=TipoCuenta.ACTIVO, saldo=280000, es_auxiliar=True),
            CuentaContable(clave="1201", nombre="Inventarios", tipo=TipoCuenta.ACTIVO, saldo=90000, es_auxiliar=True),
            CuentaContable(clave="2101", nombre="Proveedores", tipo=TipoCuenta.PASIVO, saldo=-50000, es_auxiliar=True),
            CuentaContable(clave="2102", nombre="Impuestos por pagar", tipo=TipoCuenta.PASIVO, saldo=-15000, es_auxiliar=True),
            CuentaContable(clave="3101", nombre="Capital social", tipo=TipoCuenta.CAPITAL, saldo=-120000),
            CuentaContable(clave="4101", nombre="Ingresos por servicios", tipo=TipoCuenta.INGRESO, saldo=-250000, es_auxiliar=True),
            CuentaContable(clave="5101", nombre="Sueldos y salarios", tipo=TipoCuenta.GASTO, saldo=95000, es_auxiliar=True),
            CuentaContable(clave="5102", nombre="Renta", tipo=TipoCuenta.GASTO, saldo=28000, es_auxiliar=True),
            CuentaContable(clave="5103", nombre="Servicios", tipo=TipoCuenta.GASTO, saldo=18000, es_auxiliar=True),
        ]

        return ChartOfAccounts(
            empresa=self._empresa_info.get("nombre", ""),
            ejercicio=2026,
            cuentas=cuentas,
            fecha_exportacion=datetime.now().isoformat(),
        )

    def get_balanza(self, ejercicio: int, mes: int) -> BalanzaComprobacion:
        """Obtiene balanza de comprobación mock de Factor D.

        En producción: GET /contabilidad/balanza?ejercicio=...&mes=...
        """
        self._ensure_connected()
        logger.info(f"FactorDAdapter: obteniendo balanza {ejercicio}-{mes:02d} (mock)")

        cuentas = [
            {"cuenta": "1101", "nombre": "Caja", "deudor": 55000, "acreedor": 0},
            {"cuenta": "1102", "nombre": "Bancos", "deudor": 280000, "acreedor": 0},
            {"cuenta": "2101", "nombre": "Proveedores", "deudor": 0, "acreedor": 50000},
            {"cuenta": "3101", "nombre": "Capital social", "deudor": 0, "acreedor": 120000},
            {"cuenta": "4101", "nombre": "Ingresos", "deudor": 0, "acreedor": 250000},
            {"cuenta": "5101", "nombre": "Sueldos", "deudor": 95000, "acreedor": 0},
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
