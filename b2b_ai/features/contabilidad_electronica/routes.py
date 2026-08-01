# -*- coding: utf-8 -*-
"""
routes.py — Endpoints FastAPI para el módulo de Contabilidad Electrónica SAT.

Endpoints:
    POST /contabilidad-electronica/balanza       — Genera Balanza XML.
    POST /contabilidad-electronica/catalogo      — Genera Catálogo XML.
    POST /contabilidad-electronica/validate      — Valida antes de enviar.
    GET  /contabilidad-electronica/obligaciones/{rfc} — Obligaciones SAT.

El router se construye con `build_contabilidad_electronica_router()` para
seguir el patrón `build_*_router()` del proyecto.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException

from b2b_ai.features.contabilidad_electronica.models import (
    BalanzaRequest,
    CatalogoCuenta,
    ContabilidadElectronicaResponse,
    TipoCuenta,
)
from b2b_ai.features.contabilidad_electronica.generator import (
    generate_balanza_xml,
    generate_catalogo_xml,
)
from b2b_ai.features.contabilidad_electronica.validators import (
    validate_balanza,
    validate_catalogo,
    validate_balanza_totals,
)


# --------------------------------------------------------------------------- #
# Obligaciones SAT por RFC (datos de referencia)
# --------------------------------------------------------------------------- #

# Obligaciones mensuales/anuales del SAT por régimen fiscal
_OBLIGACIONES_POR_REGIMEN = {
    "601": {  # General de Ley Personas Morales
        "mensuales": [
            "Declaración mensual de IVA",
            "Declaración mensual de ISR",
            "Balanza de Comprobación",
            "Nóminas (si aplica)",
        ],
        "anuales": [
            "Declaración anual de ISR",
            "Balanza de Comprobación anual",
            "Catálogo de Cuentas (Contabilidad Electrónica)",
            "Estado de Resultados (Contabilidad Electrónica)",
        ],
    },
    "612": {  # Personas Físicas con Actividades Empresariales
        "mensuales": [
            "Declaración mensual de IVA",
            "Declaración mensual de ISR",
            "Balanza de Comprobación",
        ],
        "anuales": [
            "Declaración anual de ISR",
            "Balanza de Comprobación anual",
            "Catálogo de Cuentas (Contabilidad Electrónica)",
        ],
    },
    "606": {  # Servicios Profesionales
        "mensuales": [
            "Declaración mensual de IVA",
            "Declaración mensual de ISR",
        ],
        "anuales": [
            "Declaración anual de ISR",
        ],
    },
    "626": {  # Régimen Simplificado de Confianza
        "mensuales": [
            "Pago mensual de ISR (RESICO)",
        ],
        "anuales": [
            "Declaración anual de ISR",
        ],
    },
}


def _get_obligaciones_by_rfc(rfc: str) -> dict:
    """Determina las obligaciones fiscales de un RFC.

    Usa el régimen fiscal para definir qué debe presentar.
    Si el RFC no se reconoce, retorna obligaciones genéricas.
    """
    if not rfc:
        return {
            "rfc": "",
            "regimen": "desconocido",
            "mensuales": [],
            "anuales": [],
            "mensaje": "RFC no proporcionado.",
        }

    # Determinar régimen (simplificado: primeros 4 chars del RFC)
    # En producción, esto consultaría el SAT/RFC.
    regimen = "601"  # Default: General de Ley
    if len(rfc) >= 4:
        # Heurística simple para el demo
        if rfc.startswith("XAXX"):
            regimen = "616"  # Sin actividades económicas
        elif rfc.startswith("E"):
            regimen = "601"  # Sociedad mercantil
        else:
            regimen = "601"

    obligaciones = _OBLIGACIONES_POR_REGIMEN.get(regimen, {})

    return {
        "rfc": rfc,
        "regimen": regimen,
        "mensuales": obligaciones.get("mensuales", []),
        "anuales": obligaciones.get("anuales", []),
        "contabilidad_electronica": regimen in ("601", "612"),
        "fecha_consulta": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #

def build_contabilidad_electronica_router(require_api_key=None) -> APIRouter:
    """Devuelve un APIRouter con endpoints /contabilidad-electronica/*.

    Sigue el patrón `build_*_router()` del proyecto.
    """
    from fastapi import Depends as _Depends

    router = APIRouter(
        prefix="/contabilidad-electronica",
        tags=["contabilidad-electronica"],
    )
    if require_api_key:
        router.dependencies.append(_Depends(require_api_key))

    # ---- POST /balanza ---------------------------------------------------
    @router.post(
        "/balanza",
        summary="Genera el XML de Balanza de Comprobación SAT.",
        response_model=None,
    )
    def generate_balanza_endpoint(req: BalanzaRequest):
        """Genera el XML de Balanza de Comprobación conforme al XSD del SAT.

        Recibe periodo, ejercicio, mes y las líneas de la balanza.
        Retorna el XML listo para envío o errores de validación.
        """
        # Validar antes de generar
        errores = validate_balanza(req)
        if errores:
            return ContabilidadElectronicaResponse(
                estado="error",
                errores=errores,
            )

        try:
            xml = generate_balanza_xml(req)
            return ContabilidadElectronicaResponse(
                estado="generado",
                xml_content=xml,
            )
        except Exception as e:
            return ContabilidadElectronicaResponse(
                estado="error",
                errores=[f"Error generando XML: {type(e).__name__}: {e}"],
            )

    # ---- POST /catalogo --------------------------------------------------
    @router.post(
        "/catalogo",
        summary="Genera el XML de Catálogo de Cuentas SAT.",
        response_model=None,
    )
    def generate_catalogo_endpoint(cuentas: List[CatalogoCuenta]):
        """Genera el XML del Catálogo de Cuentas conforme al XSD del SAT.

        Recibe la lista de cuentas y el ejercicio fiscal.
        Retorna el XML listo para envío o errores de validación.
        """
        # Validar antes de generar
        errores = validate_catalogo(cuentas)
        if errores:
            return ContabilidadElectronicaResponse(
                estado="error",
                errores=errores,
            )

        try:
            # Obtener ejercicio de la primera cuenta o usar el actual
            ejercicio = datetime.now().year
            xml = generate_catalogo_xml(cuentas, ejercicio=ejercicio)
            return ContabilidadElectronicaResponse(
                estado="generado",
                xml_content=xml,
            )
        except Exception as e:
            return ContabilidadElectronicaResponse(
                estado="error",
                errores=[f"Error generando XML: {type(e).__name__}: {e}"],
            )

    # ---- POST /validate --------------------------------------------------
    @router.post(
        "/validate",
        summary="Valida balanza y/o catálogo antes de envío al SAT.",
        response_model=None,
    )
    def validate_endpoint(
        balanza: Optional[BalanzaRequest] = None,
        catalogo: Optional[List[CatalogoCuenta]] = None,
    ):
        """Valida balanza y/o catálogo contra las reglas del SAT.

        Retorna ok=true si todo está válido, o la lista de errores.
        """
        errores: List[str] = []
        validacion_balanza = None
        validacion_catalogo = None

        if balanza is not None:
            errores_balanza = validate_balanza(balanza)
            validacion_balanza = {
                "ok": len(errores_balanza) == 0,
                "errores": errores_balanza,
            }
            errores.extend(errores_balanza)

        if catalogo is not None:
            errores_catalogo = validate_catalogo(catalogo)
            validacion_catalogo = {
                "ok": len(errores_catalogo) == 0,
                "errores": errores_catalogo,
            }
            errores.extend(errores_catalogo)

        if balanza is None and catalogo is None:
            return {
                "ok": False,
                "errores": ["Debe proporcionar balanza y/o catálogo para validar."],
            }

        return {
            "ok": len(errores) == 0,
            "errores": errores,
            "balanza": validacion_balanza,
            "catalogo": validacion_catalogo,
        }

    # ---- GET /obligaciones/{rfc} ----------------------------------------
    @router.get(
        "/obligaciones/{rfc}",
        summary="Consulta las obligaciones fiscales de un RFC.",
        response_model=None,
    )
    def get_obligaciones_endpoint(rfc: str):
        """Retorna las obligaciones fiscales mensuales y anuales de un RFC,
        incluyendo si requiere contabilidad electrónica.
        """
        if not rfc or not rfc.strip():
            raise HTTPException(
                status_code=400,
                detail="El RFC es obligatorio.",
            )

        return _get_obligaciones_by_rfc(rfc.strip())

    return router
