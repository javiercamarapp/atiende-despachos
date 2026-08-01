import os
# -*- coding: utf-8 -*-
"""
finkok.py — Adaptador mock para el PAC Finkok.

Implementa la interfaz SATAdapter con respuestas simuladas.
En producción, se conectaría a la API SOAP/REST de Finkok.
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


class FinkokAdapter(SATAdapter):
    """Adaptador mock para el PAC Finkok.

    Simula las operaciones de timbrado, cancelación y consulta
    del PAC Finkok. En producción, reemplazar con llamadas SOAP/REST
    a la API de Finkok (https://portalcfdi.finkok.com/).
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        config = config or {}
        config.setdefault("api_url", "https://portalcfdi.finkok.com/servicios/soap/")
        config.setdefault("username", "usuario@finkok.com")
        config.setdefault("password", "********")
        config.setdefault("api_key", os.environ.get("FINKOK_API_KEY", ""))        config.setdefault("production", False)
        super().__init__(name="finkok", config=config)
        self._cfdis: Dict[str, CFDI] = {}

    def connect(self) -> bool:
        """Simula la conexión al PAC Finkok."""
        logger.info("FinkokAdapter: conectando a PAC Finkok (mock)...")
        # En producción: POST /login o SOAP autenticar
        self._connected = True
        logger.info("FinkokAdapter: conexión exitosa (mock)")
        return True

    def timbrar_cfdi(self, cfdi_data: CFDIRequest) -> TimbradoResponse:
        """Simula el timbrado de un CFDI vía Finkok.

        En producción:
        1. Generar XML del CFDI con schema SAT 4.0
        2. Firmar con certificado y llave privada
        3. POST /stamp con el XML
        4. Recibir respuesta con UUID y complemento de timbre
        """
        self._ensure_connected()
        logger.info(f"FinkokAdapter: timbrando CFDI de {cfdi_data.rfc_emisor} a {cfdi_data.rfc_receptor}")

        cfdi_uuid = str(_uuid.uuid4())
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        response = TimbradoResponse(
            exito=True,
            uuid=cfdi_uuid,
            fecha_timbrado=now,
            codigo_response="0",
            mensaje="Timbrado exitoso (mock Finkok)",
            xml_timbrado=f"<cfdi:Comprobante UUID='{cfdi_uuid}' Version='4.0' ...>",
            cadena_timbre=f"||1.1|{cfdi_uuid}|{now}|MOCK-FINKOK-SELLO||",
            sello_cfdi="MOCK-SELLO-CFDI-FINKOK",
            no_certificado_sat="00001000000508023456",
        )

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

        logger.info(f"FinkokAdapter: CFDI timbrado con UUID {cfdi_uuid}")
        return response

    def cancelar_cfdi(self, request: CancelacionRequest) -> Dict[str, Any]:
        """Simula la cancelación de un CFDI vía Finkok."""
        self._ensure_connected()
        logger.info(f"FinkokAdapter: cancelando CFDI {request.uuid}")

        cfdi = self._cfdis.get(request.uuid)
        if cfdi:
            cfdi.status = CFDIStatus.CANCELADO
        else:
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
            "mensaje": "CFDI cancelado exitosamente (mock Finkok)",
            "fecha_cancelacion": datetime.now().isoformat(),
            "acuse_recibo": f"ACUSE-FINKOK-{_uuid.uuid4().hex[:8]}",
        }

    def consultar_cfdi(self, uuid: str) -> CFDI:
        """Simula la consulta de un CFDI vía Finkok."""
        self._ensure_connected()
        logger.info(f"FinkokAdapter: consultando CFDI {uuid}")

        if uuid in self._cfdis:
            return self._cfdis[uuid]

        return CFDI(
            uuid=uuid,
            status=CFDIStatus.PENDIENTE,
            fecha=datetime.now().strftime("%Y-%m-%d"),
        )

    def consultar_rfc(self, rfc: str) -> RFCStatus:
        """Simula la consulta de un RFC ante el SAT."""
        self._ensure_connected()
        logger.info(f"FinkokAdapter: consultando RFC {rfc}")

        return RFCStatus(
            rfc=rfc,
            razon_social="EMPRESA FINKOK MOCK S.A. DE C.V.",
            regimen_fiscal=["601"],
            obligaciones=["IVA", "ISR", "DIOT"],
            estatus="activo",
            fecha_alta="2018-06-15",
            domicilio_fiscal="03100",
            nombre_comercial="FINKOK MOCK",
        )

    def contabilidad_electronica(self, datos: ContabilidadElectronica) -> Dict[str, Any]:
        """Simula el envío de contabilidad electrónica al SAT vía Finkok."""
        self._ensure_connected()
        logger.info(f"FinkokAdapter: enviando contabilidad electrónica {datos.ejercicio}-{datos.mes}")

        return {
            "exito": True,
            "ejercicio": datos.ejercicio,
            "mes": datos.mes,
            "rfc": datos.rfc,
            "mensaje": "Contabilidad electrónica enviada (mock Finkok)",
            "folio": f"CE-FINKOK-{_uuid.uuid4().hex[:8]}",
            "fecha_envio": datetime.now().isoformat(),
            "archivos_enviados": {
                "balanza": bool(datos.balanza),
                "catalogo": bool(datos.catalogo),
                "polizas": len(datos.polizas),
            },
        }
