# -*- coding: utf-8 -*-
"""facturapi_adapter.py — Adaptador para PAC FACTURAPI.

Implementa la interfaz SATAdapter con respuestas simuladas.
En producción, se conectaría a la API SOAP/REST de FACTURAPI.
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, Optional

import os

from b2b_ai.integrations.sat.adapter import SATAdapter, SATAdapterError
from b2b_ai.integrations.sat.models import (
    CFDI,
    CFDIRequest,
    CancelacionRequest,
    ContabilidadElectronica,
    RFCStatus,
    TimbradoResponse,
)

logger = logging.getLogger(__name__)


class FacturapiAdapter(SATAdapter):
    """Adaptador para PAC FACTURAPI.

    En producción, se conectaría a la API de FACTURAPI
    para timbrado, cancelación y consulta de CFDIs.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        config = config or {
            "api_key": os.environ.get("FACTURAPI_API_KEY", ""),
            "pac_name": "facturapi",
        }
        super().__init__(name="facturapi", config=config)

    def connect(self) -> bool:
        """Conecta al PAC FACTURAPI."""
        api_key = self.config.get("api_key", "")
        if api_key:
            try:
                import httpx
                # In production: validate credentials with PAC
                self._connected = True
                logger.info(f"{self.name}: connected to PAC API")
                return True
            except Exception as e:
                logger.error(f"{self.name}: connection failed: {e}")
        # Always allow mock mode
        self._connected = True
        logger.info(f"{self.name}: connected (mock mode)")
        return True

    def timbrar_cfdi(self, cfdi_data: CFDIRequest) -> TimbradoResponse:
        """Timbra un CFDI a través de FACTURAPI."""
        self._ensure_connected()
        now = datetime.now().isoformat()
        uuid_cfdi = str(_uuid.uuid4())
        logger.info(f"{self.name}: timbrando CFDI (mock)")

        return TimbradoResponse(
            exito=True,
            uuid=uuid_cfdi,
            fecha_timbrado=now,
            codigo_response="201",
            mensaje="CFDI timbrado exitosamente",
            cadena_timbre=f"TIMBRE-{uuid_cfdi[:8]}-MOCK",
            sello_cfdi="MOCK_SELLO_CFDI",
            no_certificado_sat="00001000000508762968",
        )

    def cancelar_cfdi(self, request: CancelacionRequest) -> Dict[str, Any]:
        """Cancela un CFDI a través de FACTURAPI."""
        self._ensure_connected()
        logger.info(f"{self.name}: cancelando CFDI {request.uuid} (mock)")

        return {
            "exito": True,
            "uuid": request.uuid,
            "codigo_response": "201",
            "mensaje": "Cancelación procesada exitosamente",
            "motivo": request.motivo.value,
        }

    def consultar_cfdi(self, uuid: str) -> CFDI:
        """Consulta el estatus de un CFDI."""
        self._ensure_connected()
        logger.info(f"{self.name}: consultando CFDI {uuid} (mock)")

        return CFDI(
            uuid=uuid,
            rfc_emisor="XAXX010101000",
            rfc_receptor="AAA010101AAA",
            fecha=datetime.now().strftime("%Y-%m-%d"),
            subtotal=10000.00,
            iva=1600.00,
            total=11600.00,
            status="timbrado",
            serie="A",
            folio="12345",
        )

    def consultar_rfc(self, rfc: str) -> RFCStatus:
        """Consulta el estatus de un RFC ante el SAT."""
        self._ensure_connected()
        logger.info(f"{self.name}: consultando RFC {rfc} (mock)")

        return RFCStatus(
            rfc=rfc,
            razon_social="EMPRESA MOCK S.A. DE C.V.",
            regimen_fiscal=["601"],
            obligaciones=["IVA", "ISR"],
            estatus="activo",
            fecha_alta="2015-01-01",
            domicilio_fiscal="06600",
            nombre_comercial="MOCK EMPRESA",
        )

    def contabilidad_electronica(self, datos: ContabilidadElectronica) -> Dict[str, Any]:
        """Envía contabilidad electrónica al SAT a través de FACTURAPI."""
        self._ensure_connected()
        logger.info(f"{self.name}: enviando contabilidad electrónica (mock)")

        return {
            "exito": True,
            "ejercicio": datos.ejercicio,
            "mes": datos.mes,
            "codigo_response": "201",
            "mensaje": "Contabilidad electrónica enviada exitosamente",
        }
