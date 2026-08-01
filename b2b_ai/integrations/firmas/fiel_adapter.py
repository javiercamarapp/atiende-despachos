import os
# -*- coding: utf-8 -*-
"""
fiel_adapter.py — Adaptador mock para FIEL/e.firma del SAT.

Implementa la interfaz SignatureAdapter con respuestas simuladas.
En producción, usaría la llave privada y certificado del SAT para firmar CFDI.
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.firmas.adapter import SignatureAdapter
from b2b_ai.integrations.firmas.models import (
    Envelope,
    EnvelopeStatus,
    SignatureConfig,
    SignatureProvider,
    Signer,
    SignerStatus,
    SigningRequest,
    SigningStatus,
)

logger = logging.getLogger(__name__)


class FIELAdapter(SignatureAdapter):
    """Adaptador mock para FIEL/e.firma del SAT.

    En producción, usaría la llave privada (.key) y certificado (.cer)
    del SAT para firmar digitalmente CFDI y otros documentos fiscales.
    Usa criptografía RSA-SHA256 según estándar del SAT.
    """

    def __init__(self, config: Optional[SignatureConfig] = None):
        config = config or SignatureConfig(
            provider=SignatureProvider.FIEL,
            fiel_cert_path="/path/to/certificado.cer",
            fiel_key_path="/path/to/llave.key",
            fiel_password="MockFIELPassword123",
        )
        super().__init__(config=config)

    def connect(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """Simula la conexión/validación de FIEL.

        En producción:
        1. Leer y validar el certificado .cer
        2. Descifrar la llave privada .key con la contraseña
        3. Verificar que el certificado no esté revocado
        """
        logger.info("FIELAdapter: validando FIEL/e.firma (mock)...")
        self._connected = True
        logger.info("FIELAdapter: FIEL válida (mock)")
        return True

    def create_envelope(self, request: SigningRequest) -> Envelope:
        """Firma electrónicamente un documento con FIEL.

        En producción:
        1. Generar sello digital con RSA-SHA256
        2. Insertar sello en CFDI XML
        3. Timbrar en PAC (Ecodex/Finkok)
        """
        self._ensure_connected()
        now = datetime.now().isoformat()

        logger.info(f"FIELAdapter: firmando documento '{request.document_name}' con FIEL")

        return Envelope(
            id=f"fiel_{_uuid.uuid4().hex[:24]}",
            status=EnvelopeStatus.COMPLETED,
            signers=[
                Signer(
                    name=request.signers[0].name if request.signers else "Titular FIEL",
                    email=request.signers[0].email if request.signers else "rfc@sat.gob.mx",
                    role="fiscal_signer",
                    order=1,
                    status=SignerStatus.SIGNED,
                )
            ],
            document_name=request.document_name,
            created_at=now,
            completed_at=now,
            metadata={**request.metadata, "signature_type": "FIEL_SAT", "algorithm": "RSA-SHA256"},
        )

    def get_status(self, envelope_id: str) -> SigningStatus:
        """FIEL firma de forma síncrona, siempre completado.

        En producción: el estado se obtiene del timbre del PAC.
        """
        self._ensure_connected()
        logger.info(f"FIELAdapter: consultando estado {envelope_id}")

        return SigningStatus(
            envelope_id=envelope_id,
            status=EnvelopeStatus.COMPLETED,
            signers=[
                Signer(
                    name="Titular FIEL",
                    email="rfc@sat.gob.mx",
                    status=SignerStatus.SIGNED,
                )
            ],
            percent_complete=100,
            details="Documento firmado con FIEL exitosamente",
        )

    def download_signed(self, envelope_id: str) -> bytes:
        """Descarga el documento firmado con FIEL.

        En producción: retorna el XML CFDI timbrado.
        """
        self._ensure_connected()
        logger.info(f"FIELAdapter: descargando documento firmado {envelope_id}")
        return b"<xml version='1.0' encoding='UTF-8'?><CFDI mock signed with FIEL/>"

    def cancel(self, envelope_id: str) -> bool:
        """Cancela la operación (solo antes de timbrar).

        En producción: una vez timbrado, la cancelación va por el PAC.
        """
        self._ensure_connected()
        logger.info(f"FIELAdapter: cancelando operación {envelope_id}")
        return True
