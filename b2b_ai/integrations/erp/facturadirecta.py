# -*- coding: utf-8 -*-
"""
facturadirecta.py — Adaptador mock para FacturaDirecta (Cloud/SaaS, REST API).

Implementa la interfaz ERPAdapter con respuestas simuladas.
En producción, se conectaría a la API REST de FacturaDirecta.
Autenticación: API Key + Token
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


class FacturaDirectaAdapter(ERPAdapter):
    """Adaptador mock para FacturaDirecta (Cloud/SaaS).

    FacturaDirecta es una plataforma mexicana de facturación electrónica
    que también actúa como PAC (Proveedor Autorizado de Certificación).
    En producción, se conectaría a la API REST de FacturaDirecta
    (https://www.facturadirecta.com/develop).
    Usa API Key + Token para autenticación.
    """

    def __init__(self, config: Optional[ERPConfig] = None):
        config = config or ERPConfig(type=ERPType.FACTURADIRECTA)
        config.endpoint = config.endpoint or os.environ.get(
            "FDIRECTA_ENDPOINT", "https://www.facturadirecta.com/develop/api/"
        )
        config.api_key = config.api_key or os.environ.get("FDIRECTA_API_KEY")
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Simula la conexión a FacturaDirecta.

        En producción:
        1. Autenticar con API Key + Token
        2. Validar CSD de prueba en sandbox
        3. Usar Bearer token en headers
        """
        logger.info("FacturaDirectaAdapter: conectando a FacturaDirecta (mock)...")
        creds = credentials or {}
        api_key = creds.get("api_key") or self.config.api_key or "mock-fd-api-key"
        if api_key == "mock-fd-api-key":
            logger.info("FacturaDirectaAdapter: usando credenciales mock")
        self._connected = True
        self._empresa_info = {
            "nombre": "Empresa FacturaDirecta Mock S.A. DE C.V.",
            "rfc": "FDX010101AAA",
            "ejercicio": 2026,
            "api_key": api_key[:8] + "..." if len(api_key) > 8 else api_key,
        }
        logger.info("FacturaDirectaAdapter: conexión exitosa (mock)")
        return True

    def disconnect(self) -> None:
        self._connected = False
        self._empresa_info = {}
        logger.info("FacturaDirectaAdapter: desconectado")

    def get_invoices(self, date_range: Optional[Dict[str, str]] = None) -> List[Invoice]:
        """Obtiene facturas mock de FacturaDirecta.

        En producción: GET /cfdi?tipo=emitido&fecha_inicio=...&fecha_fin=...
        """
        self._ensure_connected()
        logger.info("FacturaDirectaAdapter: obteniendo facturas (mock)")

        now = datetime.now().strftime("%Y-%m-%d")
        return [
            Invoice(
                id=f"FDX-INV-{i:04d}",
                uuid=str(_uuid.uuid4()),
                rfc="FDXC010101AAA",
                fecha=now,
                monto=round(13000 + i * 2800, 2),
                subtotal=round(11206.90 + i * 2413.79, 2),
                iva=round(1793.10 + i * 386.21, 2),
                status="activa",
                concepto=f"CFDI FacturaDirecta {i}",
                serie="FDX",
                folio=str(9000 + i),
                moneda="MXN",
                forma_pago="01",
                metodo_pago="PUE",
            )
            for i in range(1, 4)
        ]

    def get_polizas(self, date_range: Optional[Dict[str, str]] = None) -> List[Poliza]:
        """Obtiene pólizas mock de FacturaDirecta.

        Nota: FacturaDirecta es foco en facturación, módulo contable limitado.
        En producción: GET /contabilidad/polizas (si disponible)
        """
        self._ensure_connected()
        logger.info("FacturaDirectaAdapter: obteniendo pólizas (mock)")

        now = datetime.now().strftime("%Y-%m-%d")
        return [
            Poliza(
                id=f"FDX-POL-{i:04d}",
                fecha=now,
                concepto=f"Póliza por CFDI {i}",
                tipo="Ingresos",
                numero=i,
                cuentas=[
                    CuentaPoliza(cuenta="1102", descripcion="Bancos", debe=7500 * i, haber=0),
                    CuentaPoliza(cuenta="4101", descripcion="Ingresos por ventas", debe=0, haber=7500 * i),
                ],
                monto_total=7500 * i,
                status=StatusPoliza.CONTABILIZADA,
            )
            for i in range(1, 3)
        ]

    def upload_poliza(self, poliza: Poliza) -> Dict[str, Any]:
        """Sube una póliza mock a FacturaDirecta.

        En producción: POST /contabilidad/polizas (si disponible)
        """
        self._ensure_connected()
        logger.info(f"FacturaDirectaAdapter: subiendo póliza {poliza.id}")

        if not poliza.esta_cuadrada():
            return {"exito": False, "mensaje": "Póliza no cuadrada"}

        return {
            "exito": True,
            "id_erp": f"FDX-POL-{_uuid.uuid4().hex[:8].upper()}",
            "mensaje": "Póliza creada exitosamente (mock FacturaDirecta)",
            "fecha_registro": datetime.now().isoformat(),
        }

    def get_chart_of_accounts(self) -> ChartOfAccounts:
        """Obtiene catálogo de cuentas mock de FacturaDirecta.

        Nota: FacturaDirecta es foco en facturación, catálogo básico.
        En producción: GET /catalogo-cuentas (si disponible)
        """
        self._ensure_connected()
        logger.info("FacturaDirectaAdapter: obteniendo catálogo de cuentas (mock)")

        cuentas = [
            CuentaContable(clave="1101", nombre="Caja", tipo=TipoCuenta.ACTIVO, saldo=45000, es_auxiliar=True),
            CuentaContable(clave="1102", nombre="Bancos", tipo=TipoCuenta.ACTIVO, saldo=230000, es_auxiliar=True),
            CuentaContable(clave="2101", nombre="Proveedores", tipo=TipoCuenta.PASIVO, saldo=-35000, es_auxiliar=True),
            CuentaContable(clave="2102", nombre="IVA acreditable", tipo=TipoCuenta.PASIVO, saldo=-10000, es_auxiliar=True),
            CuentaContable(clave="3101", nombre="Capital social", tipo=TipoCuenta.CAPITAL, saldo=-90000),
            CuentaContable(clave="4101", nombre="Ingresos por ventas", tipo=TipoCuenta.INGRESO, saldo=-200000, es_auxiliar=True),
            CuentaContable(clave="5101", nombre="Gastos de administración", tipo=TipoCuenta.GASTO, saldo=70000, es_auxiliar=True),
        ]

        return ChartOfAccounts(
            empresa=self._empresa_info.get("nombre", ""),
            ejercicio=2026,
            cuentas=cuentas,
            fecha_exportacion=datetime.now().isoformat(),
        )

    def get_balanza(self, ejercicio: int, mes: int) -> BalanzaComprobacion:
        """Obtiene balanza de comprobación mock de FacturaDirecta.

        En producción: GET /contabilidad/balanza?ejercicio=...&mes=...
        """
        self._ensure_connected()
        logger.info(f"FacturaDirectaAdapter: obteniendo balanza {ejercicio}-{mes:02d} (mock)")

        cuentas = [
            {"cuenta": "1101", "nombre": "Caja", "deudor": 45000, "acreedor": 0},
            {"cuenta": "1102", "nombre": "Bancos", "deudor": 230000, "acreedor": 0},
            {"cuenta": "2101", "nombre": "Proveedores", "deudor": 0, "acreedor": 35000},
            {"cuenta": "3101", "nombre": "Capital social", "deudor": 0, "acreedor": 90000},
            {"cuenta": "4101", "nombre": "Ingresos", "deudor": 0, "acreedor": 200000},
            {"cuenta": "5101", "nombre": "Gastos", "deudor": 70000, "acreedor": 0},
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
