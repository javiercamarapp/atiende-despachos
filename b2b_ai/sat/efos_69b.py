# -*- coding: utf-8 -*-
"""
efos_69b.py — Verificación de lista 69-B del CFF (EFOS/EDOS).

El artículo 69-B del Código Fiscal de la Federación (CFF) establece que el SAT
puede presumir que los contribuyentes que expiden comprobantes sin contar con
actividades, empleados o infraestructura para realizarlas (Empresas que
Facturan Operaciones Simuladas — EFOS) están cometiendo un delito fiscal.

Efectos para el RECEPTOR:
- Art. 69-B tercer párrafo CFF: las operaciones amparadas por comprobantes
  emitidos por contribuyentes en la lista definitiva del 69-B NO producen
  efecto fiscal alguno (no deducibles, IVA no acreditable), salvo que el
  contribuyente acredite la materialidad de las operaciones (art. 69-B
  cuarto párrafo).

Implementación actual: mock determinista + lista estática de RFCs conocidos.
En producción, la lista debe descargarse periódicamente del SAT:
https://www.sat.gob.mx/consultas/21423/genera-tu-archivo-con-la-informacion-de-la-lista-de-contribuyentes-que-realizan-operaciones-con-efos

Reglas aplicables:
- CFF art. 69-B: presunción de operaciones simuladas
- RMF 2.7.1.39: lista de contribuyentes del 69-B
- CFF art. 29-A último párrafo: efecto fiscal del comprobante

NOTA IMPORTANTE: Esta lista DEBE actualizarse periódicamente con los datos
del SAT. Los RFCs de ejemplo aquí son solo para propósitos de testing.
En producción, usar el archivo descargable del SAT y actualizar al menos
mensualmente.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Lista de RFCs en la lista definitiva 69-B del SAT.
# EN PRODUCCIÓN: reemplazar con la carga del archivo CSV del SAT.
# Esta lista de ejemplo incluye RFCs genéricos de prueba.
# El RFC XEXX010101000 es genérico (extranjeros) y NO aplica para 69-B.
EJEMPLOS_69B = {
    # RFCs de ejemplo para testing — NO son RFCs reales de contribuyentes
    "AAA010101AAA",  # RFC de prueba genérico
    "EFOS000101ABC", # RFC ficticio para testing
}


class EFOSChecker:
    """Verifica si un emisor de CFDI está en la lista definitiva del 69-B CFF.

    En modo mock (default), usa una lista estática de ejemplo.
    En producción, debe cargarse la lista descargable del SAT.
    """

    def __init__(self, rfc_list: Optional[set] = None):
        self.rfc_list = rfc_list or EJEMPLOS_69B
        self.backend = "mock (lista estática)"

    def check_rfc(self, rfc: str) -> Dict[str, Any]:
        """Verifica si un RFC está en la lista 69-B.

        Devuelve {ok, rfc, en_lista_69b, efecto_fiscal, referencia}.
        """
        rfc_n = (rfc or "").strip().upper()
        if not rfc_n:
            return {"ok": False, "error": "RFC es obligatorio."}

        en_lista = rfc_n in self.rfc_list
        if en_lista:
            return {
                "ok": True,
                "rfc": rfc_n,
                "en_lista_69b": True,
                "efecto_fiscal": (
                    "Las operaciones amparadas por comprobantes de este "
                    "contribuyente NO producen efecto fiscal alguno, salvo "
                    "que se acredite la materialidad (CFF art. 69-B tercer "
                    "y cuarto párrafo)."
                ),
                "referencia": "CFF art. 69-B, RMF 2.7.1.39",
                "requiere_revision_humana": True,
                "backend": self.backend,
            }
        return {
            "ok": True,
            "rfc": rfc_n,
            "en_lista_69b": False,
            "efecto_fiscal": "No está en la lista 69-B. Operación válida en principio.",
            "referencia": "CFF art. 69-B",
            "requiere_revision_humana": False,
            "backend": self.backend,
        }

    def validate_cfdi_emisor(self, datos: Dict[str, Any]) -> Dict[str, Any]:
        """Valida el emisor de un CFDI contra la lista 69-B.

        Devuelve {ok, emisor_rfc, en_lista_69b, issues, warnings}.
        """
        emisor_rfc = datos.get("emisor_rfc", "")
        result = self.check_rfc(emisor_rfc)

        issues = []
        warnings = []
        if result.get("en_lista_69b"):
            issues.append({
                "code": "emisor_69b_efos",
                "mensaje": (
                    f"El emisor RFC '{emisor_rfc}' está en la lista definitiva "
                    "del art. 69-B CFF (EFOS). Las operaciones amparadas por "
                    "sus comprobantes no producen efecto fiscal (no deducible, "
                    "IVA no acreditable) salvo acreditamiento de materialidad."
                ),
                "ref": "CFF art. 69-B",
                "severidad": "error",
            })

        # UUID duplicado check (art. 69-B bis CFF)
        # En producción esto requeriría una DB de UUIDs ya procesados.
        folio_fiscal = datos.get("folio_fiscal", "")
        if folio_fiscal:
            # Placeholder para verificación de UUID duplicado
            pass

        return {
            "ok": len(issues) == 0,
            "emisor_rfc": emisor_rfc,
            "en_lista_69b": result.get("en_lista_69b", False),
            "issues": issues,
            "warnings": warnings,
            "requiere_revision_humana": result.get("requiere_revision_humana", False),
        }
