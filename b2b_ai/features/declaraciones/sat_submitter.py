# -*- coding: utf-8 -*-
"""sat_submitter.py — SATSubmitter: SOAP submission to SAT web services.

STUB — NOT a real SAT integration (FIS-019). What this module actually does
today:
  - Validates the signed XML looks well-formed (has a Sello) before
    proceeding.
  - Enforces an explicit `confirm=True` before doing anything.
  - In sandbox (`test_mode=True`): fabricates a deterministic `SIM-` folio
    and returns PENDING — never ACCEPTED.
  - In "production" (`test_mode=False`): calls `_send_soap()`, which is
    also a stub — it does NOT authenticate with FIEL, does NOT build a SOAP
    envelope, and does NOT contact DeclaraSAT. It returns PENDING/ERROR with
    a message saying so.
  - Tracks submission status locally via `check_status()`.

What a real integration would still need to add (see
docs/CONTRATO-SAT-INTEGRACION-REAL.md):
  - FIEL authentication (WSSecurity with X.509 binary token)
  - Real SOAP envelope construction and transport
  - Actual submission to DeclaraSAT and parsing of its acuse/rechazo

Note: SAT does NOT have a public REST API for declarations.
The real integration would use the SOAP/WSSecurity protocol that DeclaraSAT
uses (see docs/CONTRATO-SAT-INTEGRACION-REAL.md for the target interface).

HONESTIDAD / ESTADO ACTUAL (FIS-019, ver docs/AUDIT-FINAL-FISCAL.md):
    Este módulo NO envía nada al SAT. `_send_soap()` es un stub: no
    construye ningún cliente SOAP, no autentica con FIEL, no abre ninguna
    conexión de red. Esto es cierto tanto si `test_mode=True` (sandbox
    explícito) como si `test_mode=False` ("producción") — en ambos casos
    el método regresa una respuesta fabricada localmente. Todo
    `SubmissionResult` que produce este módulo trae `simulado=True` y
    nunca `SubmissionStatus.ACCEPTED`, precisamente para que ningún llamador
    pueda confundir esta simulación con una presentación real ante el SAT.

    Hasta que exista una implementación real, la única vía para presentar
    una declaración es: a) subida manual al portal SAT de los archivos que
    genera este sistema, o b) integración con software de despacho
    (CONTPAQi, Aspel, etc.) o un PAC.

    Prototipo de una tercera vía (RPA sobre el portal público, opción 2 de
    docs/CONTRATO-SAT-INTEGRACION-REAL.md §2): ver
    `sat_portal_rpa_driver.SATPortalRPADriver` en este mismo paquete. Sigue
    sin estar verificado contra el SAT real (`VERIFICADO_CONTRA_SAT_REAL =
    False` en ese módulo) — probado solo contra un simulador local.
"""
from __future__ import annotations

import base64
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("b2b_ai.declaraciones.sat_submitter")


class SubmissionStatus(str, Enum):
    """Status of a declaration submission."""
    PENDING = "pending"           # Queued for submission
    SUBMITTED = "submitted"       # Sent to SAT
    ACCEPTED = "accepted"         # Accepted by SAT
    REJECTED = "rejected"         # Rejected by SAT
    ERROR = "error"               # Error during submission
    TIMEOUT = "timeout"           # SAT service timeout
    PROCESSING = "processing"     # SAT is processing


@dataclass
class SubmissionResult:
    """Result of a declaration submission."""
    status: SubmissionStatus
    folio: Optional[str] = None         # SAT folio/receipt number
    fecha_recepcion: Optional[str] = None
    mensaje: str = ""
    codigo_error: Optional[str] = None
    acuse_xml: Optional[str] = None     # Receipt XML from SAT
    raw_response: Optional[str] = None
    attempts: int = 0
    declaration_id: Optional[str] = None
    simulado: bool = True  # True = esta respuesta NO vino del SAT real.
    # Honestidad (FIS-019): por defecto True porque, hoy, NINGÚN código de
    # este módulo llega a hablar con el SAT — ni en modo sandbox ni en modo
    # "producción" (_send_soap sigue siendo un stub). Cuando exista una
    # implementación real (ver docs/CONTRATO-SAT-INTEGRACION-REAL.md), esa
    # ruta debe construir el resultado con simulado=False explícitamente.


@dataclass
class SubmissionRecord:
    """Historical submission record."""
    declaration_id: str
    declaration_type: str  # "iva", "isr_provisional", "isr_anual", "diot"
    periodo: str
    rfc: str
    status: SubmissionStatus
    folio: Optional[str] = None
    submitted_at: Optional[str] = None
    accepted_at: Optional[str] = None
    error_message: Optional[str] = None


# AVISO DE HONESTIDAD (FIS-019) — estas tres constantes NO se usan en
# ningún punto de este módulo (búsqueda en todo el repo: cero referencias
# fuera de esta definición) y NO deben tomarse como una URL ya investigada
# y lista para usar:
#
# - SAT_WSDL_PRODUCTION / SAT_WSDL_TEST apuntan al mismo host que el
#   servicio de DESCARGA MASIVA de CFDI (ver b2b_ai/sat/downloader.py y
#   docs/APIs-INTEGRACION-MEXICO.md) — un servicio real y documentado, pero
#   que es para DESCARGAR CFDIs, no para ENVIAR declaraciones. Están mal
#   etiquetadas aquí (probable copy-paste) y ambas apuntan a la misma URL
#   pese a llamarse "PRODUCTION" y "TEST".
# - DECLARASAT_ENDPOINT no pudo verificarse: no se encontró documentación
#   pública de un web service SOAP para el envío automatizado de
#   declaraciones bajo esa URL ni ninguna otra. A diferencia de la Descarga
#   Masiva de CFDI (que sí tiene un WSDL público documentado), la evidencia
#   disponible indica que el SAT expone la presentación de declaraciones
#   solo vía la aplicación DeclaraSAT / el portal web "Presenta tu
#   declaración" (autenticado con CIEC o e.firma vía navegador), no como un
#   servicio SOAP de terceros. Ver docs/CONTRATO-SAT-INTEGRACION-REAL.md.
#
# Ninguna de las dos se usa en `_send_soap()`; se dejan aquí sin borrar
# para no perder la pista de qué se investigó, pero no deben copiarse a una
# implementación real sin volver a verificarlas contra la documentación
# oficial vigente del SAT.
SAT_WSDL_PRODUCTION = (
    "https://cfdidescargamasiva.cloud.sat.gob.mx/"
    "DescargaMasivaService.svc?wsdl"
)
SAT_WSDL_TEST = (
    "https://cfdidescargamasiva.cloud.sat.gob.mx/"
    "DescargaMasivaService.svc?wsdl"
)

DECLARASAT_ENDPOINT = "https://declara.sat.gob.mx/IntermediaDeContribuyente/servicioSolicitud"  # NO VERIFICADO — ver aviso arriba.


class SATSubmitter:
    """STUB de presentación de declaraciones al SAT (FIS-019, NO real).

    Ningún método de esta clase abre una conexión real hacia el SAT. Todo
    `SubmissionResult` que produce trae `simulado=True` y nunca
    `SubmissionStatus.ACCEPTED`. Ver docstring del módulo y
    docs/CONTRATO-SAT-INTEGRACION-REAL.md.

    Usage:
        submitter = SATSubmitter(
            cer_path="certificates/ABC/rfc.cer",
            key_path="certificates/ABC/rfc.key",
            password="password123",
        )
        result = submitter.submit_declaration(xml_signed, "iva", "2024-07")
    """

    def __init__(
        self,
        cer_path: Optional[str] = None,
        key_path: Optional[str] = None,
        password: Optional[str] = None,
        test_mode: bool = True,
    ):
        self._cer_path = cer_path
        self._key_path = key_path
        self._password = password
        self._test_mode = test_mode
        self._submissions: Dict[str, SubmissionRecord] = {}

    def submit_declaration(
        self,
        xml_signed: bytes,
        declaration_type: str,
        periodo: str,
        rfc: str,
        declaration_id: Optional[str] = None,
        confirm: bool = False,
    ) -> SubmissionResult:
        """Submit a signed declaration XML to SAT.

        Args:
            xml_signed: Signed XML bytes (must already have Sello, Certificado, NoCertificado)
            declaration_type: "iva", "isr_provisional", "isr_anual", "diot"
            periodo: Period (YYYY-MM or YYYY)
            rfc: Taxpayer RFC
            declaration_id: Internal declaration ID for tracking

        Returns:
            SubmissionResult with status, folio, and details
        """
        logger.info(
            "Submitting %s declaration for %s period %s",
            declaration_type, rfc[:6] + "***", periodo,
        )

        # Validate inputs
        if not xml_signed:
            return SubmissionResult(
                status=SubmissionStatus.ERROR,
                mensaje="XML firmado no puede estar vacío",
                declaration_id=declaration_id,
            )

        # Check for signature in XML
        xml_str = xml_signed.decode("utf-8", errors="replace")
        if "Sello=" not in xml_str and "Sello =" not in xml_str:
            return SubmissionResult(
                status=SubmissionStatus.ERROR,
                mensaje="XML no contiene sello digital. Debe firmarse primero.",
                declaration_id=declaration_id,
            )

        # BUG-2 fix: la presentación SAT exige confirmación explícita.
        # Sin confirm=True nunca se procede (en simulación NI SE TIMBRA).
        if not confirm:
            return SubmissionResult(
                status=SubmissionStatus.PENDING,
                mensaje=(
                    "Confirmación explícita requerida (confirm=True). "
                    "Ninguna declaración se envía a SAT sin confirmación. "
                    "Estado: PENDING — pendiente de confirmación."
                ),
                codigo_error="CONFIRM_REQUIRED",
                declaration_id=declaration_id,
                attempts=0,
            )

        # Build submission record
        record = SubmissionRecord(
            declaration_id=declaration_id or "",
            declaration_type=declaration_type,
            periodo=periodo,
            rfc=rfc,
            status=SubmissionStatus.SUBMITTED,
            submitted_at=datetime.now().isoformat(),
        )

        # In test mode, do NOT simulate acceptance — this is a sandbox.
        # BUG-2 fix: NUNCA devolver ACCEPTED en simulación (no hay timbre real).
        if self._test_mode:
            logger.warning(
                "SATSubmitter en modo sandbox (test_mode=True): la "
                "declaración %s NO se envía al SAT, se fabrica un folio "
                "SIM- localmente.", declaration_id or "(sin id)",
            )
            # Fake sandbox folio only, not a cryptographic use.
            folio = f"SIM-{hashlib.md5(xml_signed, usedforsecurity=False).hexdigest()[:12].upper()}"
            result = SubmissionResult(
                status=SubmissionStatus.PENDING,
                folio=folio,
                fecha_recepcion=datetime.now().isoformat(),
                mensaje=(
                    "SANDBOX (modo simulación): la declaración NO fue timbrada ni "
                    "presentada ante el SAT. Estado PENDING. NOTA: cambiar a "
                    "test_mode=False tampoco presenta al SAT hoy — esa ruta "
                    "sigue siendo un stub sin implementar (FIS-019); ver "
                    "docs/CONTRATO-SAT-INTEGRACION-REAL.md."
                ),
                declaration_id=declaration_id,
                attempts=1,
                simulado=True,
            )
            record.status = SubmissionStatus.PENDING
            record.folio = folio
            # NO set accepted_at: nunca se aceptó en simulación
        else:
            # Production: send via SOAP
            result = self._send_soap(xml_signed, declaration_type, periodo, rfc)
            result.declaration_id = declaration_id
            record.status = result.status
            record.folio = result.folio
            record.error_message = result.mensaje if result.status != SubmissionStatus.ACCEPTED else None
            if result.status == SubmissionStatus.ACCEPTED:
                record.accepted_at = datetime.now().isoformat()

        # Store record
        self._submissions[declaration_id or ""] = record

        return result

    def check_status(self, declaration_id: str) -> Optional[SubmissionResult]:
        """Check the status of a previous submission."""
        record = self._submissions.get(declaration_id)
        if record is None:
            return None

        return SubmissionResult(
            status=record.status,
            folio=record.folio,
            fecha_recepcion=record.submitted_at,
            mensaje=f"Estado: {record.status.value}",
            declaration_id=declaration_id,
        )

    def get_submission_history(
        self,
        rfc: Optional[str] = None,
    ) -> List[SubmissionRecord]:
        """Get submission history, optionally filtered by RFC."""
        records = list(self._submissions.values())
        if rfc:
            records = [r for r in records if r.rfc == rfc]
        return records

    def _send_soap(
        self,
        xml_signed: bytes,
        declaration_type: str,
        periodo: str,
        rfc: str,
    ) -> SubmissionResult:
        """STUB — no envía nada al SAT. NO llamar esperando un envío real.

        Este método NO construye un cliente SOAP, NO arma el header
        WSSecurity con el token binario FIEL, NO abre ninguna conexión de
        red hacia DeclaraSAT y NO parsea ninguna respuesta del SAT. La
        única lógica real que ejecuta es comprobar si `zeep` está
        instalado; el resto es un mensaje fabricado localmente.

        El contrato que una implementación real tendría que cumplir está
        documentado en `docs/CONTRATO-SAT-INTEGRACION-REAL.md` (WSSecurity
        con FIEL, construcción del sobre SOAP, envío vía zeep.Client,
        parseo de acuse/rechazo). Este stub existe solo para que el resto
        del pipeline (cálculo → XML → firma → intento de envío) tenga un
        punto de integración ya cableado el día que haya credenciales de
        e.firma reales para probarlo.

        Siempre regresa `simulado=True` y nunca `SubmissionStatus.ACCEPTED`.
        """
        logger.warning(
            "SATSubmitter._send_soap() es un STUB: NO se está enviando "
            "ninguna declaración al SAT (rfc=%s, tipo=%s, periodo=%s). "
            "Ver docs/CONTRATO-SAT-INTEGRACION-REAL.md para la implementación "
            "real pendiente (FIS-019).",
            rfc[:6] + "***" if rfc else rfc, declaration_type, periodo,
        )
        try:
            # Se verifica que la dependencia exista porque una implementación
            # real la necesitaría, pero NO se construye ningún cliente SOAP
            # (eso es exactamente lo que falta implementar — FIS-019).
            import zeep  # noqa: F401

            return SubmissionResult(
                status=SubmissionStatus.PENDING,
                mensaje=(
                    "NO IMPLEMENTADO (stub): este método no envía la "
                    "declaración al SAT bajo ninguna circunstancia todavía. "
                    "Para una implementación real se requiere: "
                    "1) Autenticación WSSecurity con FIEL, "
                    "2) Endpoint DeclaraSAT activo, "
                    "3) Certificado vigente, "
                    "4) Construir y enviar el sobre SOAP con zeep.Client "
                    "(contrato en docs/CONTRATO-SAT-INTEGRACION-REAL.md). "
                    "Alternativa mientras tanto: subir manualmente al portal "
                    "SAT los archivos que este sistema ya genera."
                ),
                attempts=1,
                simulado=True,
            )

        except ImportError:
            logger.warning("zeep not installed; SOAP submission unavailable")
            return SubmissionResult(
                status=SubmissionStatus.ERROR,
                mensaje=(
                    "Librería zeep no instalada. "
                    "Instale con: pip install zeep. "
                    "Nota: aunque se instale, _send_soap sigue sin estar "
                    "implementado (stub, FIS-019)."
                ),
                codigo_error="ZEEP_NOT_INSTALLED",
                attempts=1,
                simulado=True,
            )
        except Exception as e:
            logger.error("SOAP submission error: %s", e)
            return SubmissionResult(
                status=SubmissionStatus.ERROR,
                mensaje=f"Error en envío SOAP: {str(e)[:200]}",
                codigo_error="SOAP_ERROR",
                attempts=1,
                simulado=True,
            )
