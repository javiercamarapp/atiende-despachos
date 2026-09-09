# -*- coding: utf-8 -*-
"""
validator.py — Verificación de estatus de CFDI y RFC ante el SAT (mock).

`SATValidator` consulta el estatus de un CFDI (Vigente / Cancelado / No
encontrado), valida el RFC y verifica la cadena de custodia (chain of
custody) de un folio fiscal.

HONESTIDAD / ESTADO ACTUAL (FIS-024, ver docs/AUDIT-FINAL-FISCAL.md):
    100% MOCK. Sin red, sin credenciales, sin conexión al SAT real. El
    estatus se deriva de forma DETERMINISTA y ARBITRARIA del folio fiscal
    (los folios que terminan en '0' se reportan como "cancelado", el resto
    "vigente" — esto NO tiene relación con el estatus real ante el SAT).
    La cadena de custodia que devuelve `verify_chain()` es una lista de
    eventos fabricada, no una consulta real.

    Todo diccionario que este módulo devuelve incluye `"simulado": True`
    de forma explícita para que ningún llamador (API, scheduler, agente)
    pueda confundir esta simulación con una respuesta real del SAT.

Contrato de la integración real pendiente: ver
docs/CONTRATO-SAT-INTEGRACION-REAL.md (Web Service de Estatus de CFDI del
SAT / "Consulta de estatus de un CFDI").
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from b2b_ai.common.rfc import RFC_RE, is_valid_rfc, normalize_rfc

logger = logging.getLogger("b2b_ai.sat.validator")


def _es_rfc_valido(rfc: str) -> bool:
    """Valida RFC usando la función canónica centralizada."""
    return is_valid_rfc(rfc)


def _normalize_folio(folio: str) -> str:
    return (folio or "").strip()


class SATValidator:
    """STUB — valida estatus de CFDI/RFC y cadena de custodia (FIS-024).

    100% mock determinista, sin conexión real al SAT. Ver docstring del
    módulo y docs/CONTRATO-SAT-INTEGRACION-REAL.md.
    """

    backend = "SAT Estatus (mock)"

    def __init__(self, db=None, tenant_id: Optional[Any] = None):
        self.db = db
        self.tenant_id = tenant_id
        logger.warning(
            "SATValidator instanciado en modo MOCK (FIS-024): las consultas "
            "de estatus de CFDI/RFC son deterministas y NO reflejan el "
            "estatus real ante el SAT. Ver docs/CONTRATO-SAT-INTEGRACION-REAL.md."
        )

    # ------------------------------------------------------------------ #
    # Estatus de CFDI
    # ------------------------------------------------------------------ #
    def check_status(self, folio_fiscal: str) -> Dict[str, Any]:
        """Consulta el estatus de un CFDI por folio fiscal (UUID).

        Mock: folios cuyo último char es '0' → 'cancelado'; el resto 'vigente'.
        Devuelve {ok, folio_fiscal, estado, descripcion, consultado_en}.
        """
        folio = _normalize_folio(folio_fiscal)
        if not folio:
            return {"ok": False, "error": "folio_fiscal es obligatorio.",
                    "backend": self.backend, "simulado": True}
        if len(folio) < 8:
            # Folios demasiado cortos → no encontrados.
            return {"ok": True, "folio_fiscal": folio, "estado": "no_encontrado",
                    "descripcion": "No se localizó el CFDI en el SAT.",
                    "consultado_en": datetime.now().isoformat(timespec="seconds"),
                    "backend": self.backend, "simulado": True}
        if folio[-1] == "0":
            estado = "cancelado"
            desc = "El CFDI fue cancelado (estatus según SAT)."
        else:
            estado = "vigente"
            desc = "El CFDI está vigente y es válido para su uso."
        return {"ok": True, "folio_fiscal": folio, "estado": estado,
                "descripcion": desc,
                "consultado_en": datetime.now().isoformat(timespec="seconds"),
                "backend": self.backend, "simulado": True}

    def verify_cfdi(self, folio_fiscal: str) -> Dict[str, Any]:
        """Verificación completa de un CFDI: estatus + cadena."""
        folio = _normalize_folio(folio_fiscal)
        if not folio:
            return {"ok": False, "error": "folio_fiscal es obligatorio.",
                    "backend": self.backend, "simulado": True}
        status = self.check_status(folio)
        chain = self.verify_chain(folio)
        valid = status.get("estado") == "vigente" and chain.get("ok")
        return {
            "ok": valid,
            "folio_fiscal": folio,
            "estado": status.get("estado"),
            "valido": valid,
            "estatus": status,
            "cadena": chain,
            "backend": self.backend, "simulado": True,
        }

    # ------------------------------------------------------------------ #
    # Validación de RFC
    # ------------------------------------------------------------------ #
    def verify_rfc(self, rfc: str) -> Dict[str, Any]:
        """Valida el formato de un RFC y su existencia (mock).

        NOTA: En modo mock, NO se puede verificar la existencia real del RFC.
        Solo se valida el formato. El campo 'registrado' NO es confiable
        en modo mock — usar SAT real para determinación definitiva.
        """
        rfc_n = (rfc or "").strip().upper()
        if not _es_rfc_valido(rfc_n):
            return {"ok": False, "rfc": rfc_n, "valido": False,
                    "detalle": "El RFC no cumple el formato oficial.",
                    "backend": self.backend, "simulado": True}
        # Mock: solo valida formato, NO puede determinar existencia real.
        # RFCs genéricos (XAXX, XEXX) se marcan como no registrados.
        es_generico = rfc_n.startswith("XAXX") or rfc_n.startswith("XEXX")
        return {"ok": True, "rfc": rfc_n, "valido": True,
                "registrado": None if not es_generico else False,
                "detalle": ("RFC con formato válido. Existencia NO verificada "
                            "(modo mock). Usar servicio SAT real para confirmar."
                            if not es_generico
                            else "RFC genérico (no corresponde a un contribuyente único)."),
                "backend": self.backend, "simulado": True}

    # ------------------------------------------------------------------ #
    # Cadena de custodia
    # ------------------------------------------------------------------ #
    def verify_chain(self, folio_fiscal: str) -> Dict[str, Any]:
        """Verifica la cadena de custodia de un CFDI (mock).

        Devuelve el emisor, receptor, estatus y un historial simulado de
        certificación. Con integración real, consultaría el servicio de
        estatus SAT y validaría el sello (SelloCFDI + FechaTimbrado).
        """
        folio = _normalize_folio(folio_fiscal)
        if not folio:
            return {"ok": False, "error": "folio_fiscal es obligatorio.",
                    "backend": self.backend, "simulado": True}
        estado = self.check_status(folio).get("estado", "no_encontrado")
        ok = estado in ("vigente",)
        now = datetime.now().isoformat(timespec="seconds")
        return {
            "ok": ok,
            "folio_fiscal": folio,
            "estado": estado,
            "cadena": [
                {"evento": "Timbrado", "fecha": now, "autoridad": "PAC"},
                {"evento": "Registro SAT", "fecha": now, "autoridad": "SAT"},
                {"evento": "Consulta", "fecha": now, "autoridad": "B2B AI"},
            ],
            "sello_valido": ok,
            "certificacion": "cfdi40 (mock)",
            "backend": self.backend, "simulado": True,
        }
