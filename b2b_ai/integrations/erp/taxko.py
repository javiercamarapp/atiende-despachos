# -*- coding: utf-8 -*-
"""
taxko.py — Adaptador mock para Taxko (Cloud/SaaS, REST API).

Implementa la interfaz ERPAdapter con respuestas simuladas.
En producción, se conectaría a la API REST de Taxko.
Autenticación: API Key
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


class TaxkoAdapter(ERPAdapter):
    """Adaptador mock para Taxko (Cloud/SaaS).

    Taxko es una plataforma mexicana de facturación electrónica (CFDI).
    En producción, se conectaría a la API REST de Taxko
    (https://api.taxko.com).
    Usa API Key para autenticación.
    """

    def __init__(self, config: Optional[ERPConfig] = None):
        config = config or ERPConfig(type=ERPType.TAXKO)
        config.endpoint = config.endpoint or os.environ.get(
            "TAXKO_ENDPOINT", "https://api.taxko.com/v1/"
        )
        config.api_key = config.api_key or os.environ.get("TAXKO_API_KEY")
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Simula la conexión a Taxko.

        En producción:
        1. Validar API Key con GET /auth/validate
        2. Usar X-API-Key header en todas las llamadas
        """
        logger.info("TaxkoAdapter: conectando a Taxko (mock)...")
        creds = credentials or {}
        api_key = creds.get("api_key") or self.config.api_key or "mock-api-key"
        if api_key == "mock-api-key":
            logger.info("TaxkoAdapter: usando API key mock")
        self._connected = True
        self._empresa_info = {
            "nombre": "Empresa Taxko Mock S.A. DE C.V.",
            "rfc": "TK010101AAA",
            "ejercicio": 2026,
            "api_key": api_key[:8] + "..." if len(api_key) > 8 else api_key,
        }
        logger.info("TaxkoAdapter: conexión exitosa (mock)")
        return True

    def disconnect(self) -> None:
        self._connected = False
        self._empresa_info = {}
        logger.info("TaxkoAdapter: desconectado")

    def get_invoices(self, date_range: Optional[Dict[str, str]] = None) -> List[Invoice]:
        """Obtiene facturas mock de Taxko (CFDI emitidos).

        En producción: GET /cfdi?tipo=emitido&fecha_inicio=...&fecha_fin=...
        """
        self._ensure_connected()
        logger.info("TaxkoAdapter: obteniendo facturas (mock)")

        now = datetime.now().strftime("%Y-%m-%d")
        return [
            Invoice(
                id=f"TK-INV-{i:04d}",
                uuid=str(_uuid.uuid4()),
                rfc="TKC010101AAA",
                fecha=now,
                monto=round(11000 + i * 2500, 2),
                subtotal=round(9482.76 + i * 2155.17, 2),
                iva=round(1517.24 + i * 344.83, 2),
                status="activa",
                concepto=f"CFDI emitido {i}",
                serie="TK",
                folio=str(8000 + i),
                moneda="MXN",
                forma_pago="01",
                metodo_pago="PUE",
            )
            for i in range(1, 4)
        ]

    def get_polizas(self, date_range: Optional[Dict[str, str]] = None) -> List[Poliza]:
        """Obtiene pólizas mock de Taxko.

        Nota: Taxko es foco exclusivo en facturación, no módulo contable.
        En producción: GET /cfdi/polizas (si disponible)
        """
        self._ensure_connected()
        logger.info("TaxkoAdapter: obteniendo pólizas (mock)")

        now = datetime.now().strftime("%Y-%m-%d")
        return [
            Poliza(
                id=f"TK-POL-{i:04d}",
                fecha=now,
                concepto=f"Póliza por CFDI {i}",
                tipo="Ingresos",
                numero=i,
                cuentas=[
                    CuentaPoliza(cuenta="1102", descripcion="Bancos", debe=6500 * i, haber=0),
                    CuentaPoliza(cuenta="4101", descripcion="Ingresos por ventas", debe=0, haber=6500 * i),
                ],
                monto_total=6500 * i,
                status=StatusPoliza.CONTABILIZADA,
            )
            for i in range(1, 3)
        ]

    def upload_poliza(self, poliza: Poliza) -> Dict[str, Any]:
        """Sube una póliza mock a Taxko.

        En producción: POST /cfdi/polizas (si disponible)
        """
        self._ensure_connected()
        logger.info(f"TaxkoAdapter: subiendo póliza {poliza.id}")

        if not poliza.esta_cuadrada():
            return {"exito": False, "mensaje": "Póliza no cuadrada"}

        return {
            "exito": True,
            "id_erp": f"TK-POL-{_uuid.uuid4().hex[:8].upper()}",
            "mensaje": "Póliza creada exitosamente (mock Taxko)",
            "fecha_registro": datetime.now().isoformat(),
        }

    def get_chart_of_accounts(self) -> ChartOfAccounts:
        """Obtiene catálogo de cuentas mock de Taxko.

        Nota: Taxko es foco en facturación, catálogo básico.
        En producción: GET /catalogo-cuentas (si disponible)
        """
        self._ensure_connected()
        logger.info("TaxkoAdapter: obteniendo catálogo de cuentas (mock)")

        cuentas = [
            CuentaContable(clave="1101", nombre="Caja", tipo=TipoCuenta.ACTIVO, saldo=35000, es_auxiliar=True),
            CuentaContable(clave="1102", nombre="Bancos", tipo=TipoCuenta.ACTIVO, saldo=200000, es_auxiliar=True),
            CuentaContable(clave="2101", nombre="Proveedores", tipo=TipoCuenta.PASIVO, saldo=-30000, es_auxiliar=True),
            CuentaContable(clave="2102", nombre="IVA acreditable", tipo=TipoCuenta.PASIVO, saldo=-8000, es_auxiliar=True),
            CuentaContable(clave="3101", nombre="Capital social", tipo=TipoCuenta.CAPITAL, saldo=-80000),
            CuentaContable(clave="4101", nombre="Ingresos por ventas", tipo=TipoCuenta.INGRESO, saldo=-180000, es_auxiliar=True),
            CuentaContable(clave="5101", nombre="Gastos de administración", tipo=TipoCuenta.GASTO, saldo=60000, es_auxiliar=True),
        ]

        return ChartOfAccounts(
            empresa=self._empresa_info.get("nombre", ""),
            ejercicio=2026,
            cuentas=cuentas,
            fecha_exportacion=datetime.now().isoformat(),
        )

    def get_balanza(self, ejercicio: int, mes: int) -> BalanzaComprobacion:
        """Obtiene balanza de comprobación mock de Taxko.

        En producción: GET /contabilidad/balanza?ejercicio=...&mes=...
        """
        self._ensure_connected()
        logger.info(f"TaxkoAdapter: obteniendo balanza {ejercicio}-{mes:02d} (mock)")

        cuentas = [
            {"cuenta": "1101", "nombre": "Caja", "deudor": 35000, "acreedor": 0},
            {"cuenta": "1102", "nombre": "Bancos", "deudor": 200000, "acreedor": 0},
            {"cuenta": "2101", "nombre": "Proveedores", "deudor": 0, "acreedor": 30000},
            {"cuenta": "3101", "nombre": "Capital social", "deudor": 0, "acreedor": 80000},
            {"cuenta": "4101", "nombre": "Ingresos", "deudor": 0, "acreedor": 180000},
            {"cuenta": "5101", "nombre": "Gastos", "deudor": 60000, "acreedor": 0},
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
