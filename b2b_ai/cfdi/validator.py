# -*- coding: utf-8 -*-
"""SAT compliance checks for a parsed CFDI 4.0 document."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

__all__ = ["SATError", "check_cfdi_compliance", "validate_rfc_format"]

# RFC patterns: generic / foreign / legal entity / individual
_RFC_GENERIC_RE = re.compile(r"^XAXX[0-9]{6}$")  # Público en general
_RFC_FOREIGN_RE = re.compile(r"^XEXX[0-9]{6}$")  # Extranjero
_RFC_PERSONA_RE = re.compile(
    r"^[A-Z&Ñ]{4}[0-9]{6}[A-Z0-9]{3}$"  # Persona física
)
_RFC_MORAL_RE = re.compile(
    r"^[A-Z&Ñ]{3}[0-9]{6}[A-Z0-9]{3}$"  # Persona moral
)

# Valid fiscal regimen codes (simplified list — covers 601, 603, 605, 606, 608, 609)
_VALID_REGIMEN = {
    "601", "603", "605", "606", "607", "608", "609", "610", "611", "612",
    "613", "614", "615", "616", "620", "621", "622", "623", "624", "625",
    "626", "627", "628", "629", "630",
}

# Valid UsoCFDI codes
_VALID_USO_CFDI = {
    "G01", "G02", "G03", "G04", "G05", "G06", "G07", "G08", "G09", "G10",
    "G11", "G12", "G13", "I01", "I02", "I03", "I04", "I05", "I06", "I07",
    "I08", "D01", "D02", "D03", "D04", "D05", "D06", "D07", "D08", "D09",
    "D10", "P01", "S01", "CP01", "CN01", "R01", "R02", "R03", "R04", "R05",
    "R06", "R07", "R08", "R09", "R10",
}


@dataclass
class SATError:
    code: str
    message: str
    field: Optional[str] = None
    severity: str = "error"  # "error" | "warning"


def validate_rfc_format(rfc: str) -> list[SATError]:
    """Validate RFC format and return list of errors/warnings."""
    errors: list[SATError] = []
    if not rfc:
        errors.append(
            SATError(
                code="rfc_ausente",
                message="RFC no presente en el campo.",
                field="rfc",
                severity="error",
            )
        )
        return errors

    rfc_upper = rfc.strip().upper()
    if (
        _RFC_GENERIC_RE.match(rfc_upper)
        or _RFC_FOREIGN_RE.match(rfc_upper)
    ):
        # Generic / foreign RFC — no further format check needed
        return errors

    if not (
        _RFC_PERSONA_RE.match(rfc_upper) or _RFC_MORAL_RE.match(rfc_upper)
    ):
        errors.append(
            SATError(
                code="rfc_emisor_invalido",
                message=f"El RFC '{rfc}' no tiene formato válido de persona física o moral.",
                field="emisor.rfc",
                severity="error",
            )
        )
    return errors


def check_cfdi_compliance(parsed: dict[str, Any]) -> tuple[list[SATError], list[SATError]]:
    """Run all SAT compliance checks against a parsed CFDI dict.

    Returns (errors, warnings).
    """
    errors: list[SATError] = []
    warnings: list[SATError] = []

    # 1. Sello digital presente
    if not parsed.get("sello"):
        errors.append(
            SATError(
                code="sello_faltante",
                message="El CFDI no contiene el atributo Sello (firma digital).",
                field="sello",
                severity="error",
            )
        )

    # 2. Versión CFDI
    version = parsed.get("version", "")
    if version != "4.0":
        errors.append(
            SATError(
                code="version_invalida",
                message=f"Versión CFDI '{version}', se esperaba '4.0'.",
                field="version",
                severity="error",
            )
        )

    # 3. RFC emisor
    emisor_rfc = parsed.get("emisor", {}).get("rfc", "")
    rfc_errors = validate_rfc_format(emisor_rfc)
    for e in rfc_errors:
        if e.code == "rfc_ausente":
            errors.append(e)
        else:
            warnings.append(e)

    # 4. RFC receptor
    receptor_rfc = parsed.get("receptor", {}).get("rfc", "")
    receptor_rfc_upper = receptor_rfc.strip().upper()
    if not receptor_rfc:
        errors.append(
            SATError(
                code="receptor_rfc_ausente",
                message="RFC del receptor no presente.",
                field="receptor.rfc",
                severity="error",
            )
        )
    elif (
        not _RFC_GENERIC_RE.match(receptor_rfc_upper)
        and not _RFC_FOREIGN_RE.match(receptor_rfc_upper)
        and not _RFC_PERSONA_RE.match(receptor_rfc_upper)
        and not _RFC_MORAL_RE.match(receptor_rfc_upper)
    ):
        warnings.append(
            SATError(
                code="receptor_rfc_invalido",
                message=f"El RFC del receptor '{receptor_rfc}' tiene formato sospechoso.",
                field="receptor.rfc",
                severity="warning",
            )
        )

    # 5. Régimen fiscal emisor
    regimen = parsed.get("emisor", {}).get("regimen_fiscal", "")
    if regimen and regimen not in _VALID_REGIMEN:
        warnings.append(
            SATError(
                code="regimen_fiscal_desconocido",
                message=f"Régimen fiscal '{regimen}' no reconocido por el SAT.",
                field="emisor.regimen_fiscal",
                severity="warning",
            )
        )

    # 6. UsoCFDI receptor
    uso_cfdi = parsed.get("receptor", {}).get("uso_cfdi", "")
    if uso_cfdi and uso_cfdi not in _VALID_USO_CFDI:
        warnings.append(
            SATError(
                code="uso_cfdi_desconocido",
                message=f"Uso CFDI '{uso_cfdi}' no está en el catálogo SAT.",
                field="receptor.uso_cfdi",
                severity="warning",
            )
        )

    # 7. Folio fiscal (UUID) del timbre
    if not parsed.get("uuid"):
        warnings.append(
            SATError(
                code="timbre_fiscal_faltante",
                message="No se encontró TimbreFiscalDigital (UUID). "
                        "El CFDI puede no estar timbrado por un PAC.",
                field="complemento.timbre_fiscal.uuid",
                severity="warning",
            )
        )

    # 8. Fecha del comprobante
    if not parsed.get("fecha"):
        warnings.append(
            SATError(
                code="fecha_ausente",
                message="Fecha del comprobante no presente.",
                field="fecha",
                severity="warning",
            )
        )

    # 9. Total > 0 para ingresos
    tipo = parsed.get("tipo_de_comprobante", "")
    total = parsed.get("total")
    if tipo in ("I", "E") and (total is None or total <= 0):
        warnings.append(
            SATError(
                code="total_cero_invalido",
                message=f"Comprobante tipo '{tipo}' con total {total}. "
                        "Verificar que sea intencional.",
                field="total",
                severity="warning",
            )
        )

    # 10. Conceptos
    conceptos = parsed.get("conceptos", [])
    if not conceptos:
        errors.append(
            SATError(
                code="sin_conceptos",
                message="El CFDI no contiene conceptos.",
                field="conceptos",
                severity="error",
            )
        )

    # 11. Certificados
    if not parsed.get("no_certificado"):
        warnings.append(
            SATError(
                code="certificado_ausente",
                message="Número de certificado ausente.",
                field="no_certificado",
                severity="warning",
            )
        )

    return errors, warnings
