# -*- coding: utf-8 -*-
"""
ecodex.py — Adaptador mock para el PAC Ecodex.

Implementa la interfaz SATAdapter con respuestas simuladas.
En producción, se conectaría a la API REST de Ecodex.
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, Optional

from b2b_ai.integrations.sat.adapter import SATAdapter, SATAdapterError
from b2b_ai.integrations.sat.models import (
    CancelacionRequest,
    CFDI,
    CFDIRequest,
    CFDIStatus,
    ContabilidadElectronica,
    RFCStatus,
    TimbradoResponse,
)

logger = logging.getLogger(__name__)


import os
class EcodexAdapter(SATAdapter):
    """Adaptador mock para el PAC Ecodex.

    Simula las operaciones de timbrado, cancelación y consulta
    del PAC Ecodex. En producción, reemplazar con llamadas HTTP
    a la API de Ecodex (https://app.ecodex.com.mx/).
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        config = config or {}
        config.setdefault("api_url", "https://app.ecodex.com.mx/v2/")
        config.setdefault("empresa_id", "MOCK-EMPRESA-ID")
        config.setdefault("usuario", "usuario@ecodex.com")
        config.setdefault("password", "********")
        config.setdefault("api_key", os.environ.get("ECODEX_API_KEY", ""))
        super().__init__(name="ecodex", config=config)
        self._cfdis: Dict[str, CFDI] = {}

    def connect(self) -> bool:
        """Simula la conexión al PAC Ecodex."""
        logger.info("EcodexAdapter: conectando a PAC Ecodex (mock)...")
        # En producción: POST /autenticar
        self._connected = True
        logger.info("EcodexAdapter: conexión exitosa (mock)")
        return True

    def timbrar_cfdi(self, cfdi_data: CFDIRequest) -> TimbradoResponse:
        """Simula el timbrado de un CFDI vía Ecodex.

        En producción:
        1. Serializar el XML del CFDI
        2. POST /timbrar con el XML y credenciales
        3. Recibir respuesta con UUID y timbre fiscal digital
        """
        self._ensure_connected()
        logger.info(f"EcodexAdapter: timbrando CFDI de {cfdi_data.rfc_emisor} a {cfdi_data.rfc_receptor}")

        # Generar UUID simulado
        cfdi_uuid = str(_uuid.uuid4())
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        response = TimbradoResponse(
            exito=True,
            uuid=cfdi_uuid,
            fecha_timbrado=now,
            codigo_response="201",
            mensaje="CFDI timbrado exitosamente (mock)",
            xml_timbrado=f"<cfdi:Comprobante UUID='{cfdi_uuid}' ...>",
            cadena_timbre=f"||1.1|{cfdi_uuid}|{now}|MOCK-SAT-SELLO||",
            sello_cfdi="MOCK-SELLO-CFDI-ECODEX",
            no_certificado_sat="00001000000508023456",
        )

        # Guardar CFDI timbrado
        cfdi = CFDI(
            uuid=cfdi_uuid,
            rfc_emisor=cfdi_data.rfc_emisor,
            rfc_receptor=cfdi_data.rfc_receptor,
            fecha=cfdi_data.fecha,
            subtotal=cfdi_data.subtotal,
            iva=cfdi_data.iva,
            total=cfdi_data.total,
            status=CFDIStatus.TIMBRADO,
            tipo=cfdi_data.tipo,
            serie=cfdi_data.serie,
            fecha_timbrado=now,
            no_certificado="30001000000500003416",
        )
        self._cfdis[cfdi_uuid] = cfdi

        logger.info(f"EcodexAdapter: CFDI timbrado con UUID {cfdi_uuid}")
        return response

    def cancelar_cfdi(self, request: CancelacionRequest) -> Dict[str, Any]:
        """Simula la cancelación de un CFDI vía Ecodex.

        En producción:
        1. POST /cancelar con UUID, motivo y credenciales
        2. Recibir acuse de recibo
        """
        self._ensure_connected()
        logger.info(f"EcodexAdapter: cancelando CFDI {request.uuid}")

        cfdi = self._cfdis.get(request.uuid)
        if cfdi:
            cfdi.status = CFDIStatus.CANCELADO
        else:
            # Crear registro ficticio para cancelación
            cfdi = CFDI(
                uuid=request.uuid,
                rfc_emisor=request.rfc,
                status=CFDIStatus.CANCELADO,
            )
            self._cfdis[request.uuid] = cfdi

        return {
            "exito": True,
            "uuid": request.uuid,
            "motivo": request.motivo.value,
            "mensaje": "CFDI cancelado exitosamente (mock)",
            "fecha_cancelacion": datetime.now().isoformat(),
            "acuse_recibo": f"ACUSE-ECODEX-{_uuid.uuid4().hex[:8]}",
        }

    def consultar_cfdi(self, uuid: str) -> CFDI:
        """Simula la consulta de un CFDI vía Ecodex."""
        self._ensure_connected()
        logger.info(f"EcodexAdapter: consultando CFDI {uuid}")

        if uuid in self._cfdis:
            return self._cfdis[uuid]

        # Retornar CFDI mock si no existe
        return CFDI(
            uuid=uuid,
            status=CFDIStatus.PENDIENTE,
            fecha=datetime.now().strftime("%Y-%m-%d"),
        )

    def consultar_rfc(self, rfc: str) -> RFCStatus:
        """Simula la consulta de un RFC ante el SAT."""
        self._ensure_connected()
        logger.info(f"EcodexAdapter: consultando RFC {rfc}")

        # Mock: retornar estatus genérico
        return RFCStatus(
            rfc=rfc,
            razon_social="EMPRESA MOCK S.A. DE C.V.",
            regimen_fiscal=["601", "612"],
            obligaciones=["IVA", "ISR"],
            estatus="activo",
            fecha_alta="2015-01-01",
            domicilio_fiscal="06600",
            nombre_comercial="MOCK EMPRESA",
        )

    def contabilidad_electronica(self, datos: ContabilidadElectronica) -> Dict[str, Any]:
        """Simula el envío de contabilidad electrónica al SAT."""
        self._ensure_connected()
        logger.info(f"EcodexAdapter: enviando contabilidad electrónica {datos.ejercicio}-{datos.mes}")

        return {
            "exito": True,
            "ejercicio": datos.ejercicio,
            "mes": datos.mes,
            "rfc": datos.rfc,
            "mensaje": "Contabilidad electrónica enviada exitosamente (mock)",
            "folio": f"CE-ECODEX-{_uuid.uuid4().hex[:8]}",
            "fecha_envio": datetime.now().isoformat(),
            "archivos_enviados": {
                "balanza": bool(datos.balanza),
                "catalogo": bool(datos.catalogo),
                "polizas": len(datos.polizas),
            },
        }
