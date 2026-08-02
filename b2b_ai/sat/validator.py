# -*- coding: utf-8 -*-
"""
validator.py — Verificación de estatus de CFDI y RFC ante el SAT (mock).

`SATValidator` consulta el estatus de un CFDI (Vigente / Cancelado / No
encontrado), valida el RFC y verifica la cadena de custodia (chain of
custody) de un folio fiscal.

MODO MOCK-FIRST: sin red ni credenciales. El estatus se deriva de forma
determinista del folio fiscal: los folios que terminan en '0' se reportan
como cancelados (para poder testear el flujo de alertas), el resto vigente.
La verificación de cadena devuelve una lista de eventos simulada.

Patrón de integración real: sustituir los cuerpos por la consulta al Web
Service de Estatus de CFDI del SAT (SAT/CFDI). `validar_cadena` consultaría
el servicio "Consulta de estatus de un CFDI" (SAT).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from b2b_ai.common.rfc import RFC_RE, is_valid_rfc, normalize_rfc


def _es_rfc_valido(rfc: str) -> bool:
    """Valida RFC usando la función canónica centralizada."""
    return is_valid_rfc(rfc)


def _normalize_folio(folio: str) -> str:
    return (folio or "").strip()


class SATValidator:
    """Valida estatus de CFDI/RFC y cadena de custodia (mock determinista)."""

    backend = "SAT Estatus (mock)"

    def __init__(self, db=None, tenant_id: Optional[Any] = None):
        self.db = db
        self.tenant_id = tenant_id

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
                    "backend": self.backend}
        if len(folio) < 8:
            # Folios demasiado cortos → no encontrados.
            return {"ok": True, "folio_fiscal": folio, "estado": "no_encontrado",
                    "descripcion": "No se localizó el CFDI en el SAT.",
                    "consultado_en": datetime.now().isoformat(timespec="seconds"),
                    "backend": self.backend}
        if folio[-1] == "0":
            estado = "cancelado"
            desc = "El CFDI fue cancelado (estatus según SAT)."
        else:
            estado = "vigente"
            desc = "El CFDI está vigente y es válido para su uso."
        return {"ok": True, "folio_fiscal": folio, "estado": estado,
                "descripcion": desc,
                "consultado_en": datetime.now().isoformat(timespec="seconds"),
                "backend": self.backend}

    def verify_cfdi(self, folio_fiscal: str) -> Dict[str, Any]:
        """Verificación completa de un CFDI: estatus + cadena."""
        folio = _normalize_folio(folio_fiscal)
        if not folio:
            return {"ok": False, "error": "folio_fiscal es obligatorio.",
                    "backend": self.backend}
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
            "backend": self.backend,
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
                    "backend": self.backend}
        # Mock: solo valida formato, NO puede determinar existencia real.
        # RFCs genéricos (XAXX, XEXX) se marcan como no registrados.
        es_generico = rfc_n.startswith("XAXX") or rfc_n.startswith("XEXX")
        return {"ok": True, "rfc": rfc_n, "valido": True,
                "registrado": None if not es_generico else False,
                "detalle": ("RFC con formato válido. Existencia NO verificada "
                            "(modo mock). Usar servicio SAT real para confirmar."
                            if not es_generico
                            else "RFC genérico (no corresponde a un contribuyente único)."),
                "backend": self.backend}

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
                    "backend": self.backend}
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
            "backend": self.backend,
        }
