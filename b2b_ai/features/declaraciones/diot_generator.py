# -*- coding: utf-8 -*-
"""diot_generator.py — DIOTGenerator: pipe-delimited DIOT export.

Generates the pipe-delimited TXT file per RMF 3.10.7 for SAT upload.

Format (pipe-delimited):
|TipoOperacion|TipoTercero|TipoDocumento|Moneda|TipoCambio|NumRegIdTrib|
|RFC|Nombre|Pais|RFCProv|Fecha|IVA_Trasladado16|IVA_Trasladado0|
|IVA_Acreditable16|IVA_Acreditable0|IVA_Exento|IVA_Retenido|

Generic RFCs (XAXX010101000, XEXX010101000) are excluded per RMF 3.10.7.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .engine import DiotRecord, DiotResult, is_generic_rfc, GENERIC_RFCS


# RMF 3.10.7 pipe-delimited header
DIOT_HEADER = (
    "TipoOperacion|"
    "TipoTercero|"
    "TipoDocumento|"
    "NumRegIdTrib|"
    "RFC|"
    "Nombre|"
    "Pais|"
    "Moneda|"
    "TipoCambio|"
    "Fecha|"
    "MontoActosGravados16|"
    "MontoActosGravados0|"
    "MontoActosExentos|"
    "IVA_Trasladado16|"
    "IVA_Trasladado0|"
    "IVA_Acreditable16|"
    "IVA_Acreditable0|"
    "IVA_Exento|"
    "IVA_Retenido"
)


def _validate_record(record: DiotRecord) -> List[str]:
    """Validate a single DIOT record against RMF 3.10.7 rules."""
    errors: List[str] = []

    # Generic RFCs must not appear
    if is_generic_rfc(record.rfc_tercero):
        errors.append(
            f"RFC genérico '{record.rfc_tercero}' no va en DIOT (RMF 3.10.7)"
        )

    # RFC must be non-empty
    if not record.rfc_tercero or not record.rfc_tercero.strip():
        errors.append("RFC del tercero no puede estar vacío")

    # TipoOperacion must be valid
    valid_tipos = {"01", "02", "03", "04", "05", "06", "07", "08"}
    if record.tipo_operacion not in valid_tipos:
        errors.append(
            f"TipoOperacion '{record.tipo_operacion}' no es válido. "
            f"Válidos: {', '.join(sorted(valid_tipos))}"
        )

    return errors


def format_diot_record(record: DiotRecord) -> str:
    """Format a single DIOT record as a pipe-delimited line."""
    return "|".join([
        record.tipo_operacion,
        record.tipo_tercero,
        record.tipo_documento,
        record.num_reg_id_trib or "",
        record.rfc_tercero,
        record.nombre or "",
        "MX",  # País (default México)
        record.moneda or "MXN",
        f"{record.tipo_cambio:.4f}" if record.tipo_cambio != 1.0 else "",
        record.fecha or "",
        # Montos por tasa (base gravable, no IVA)
        f"{record.monto_neto:.2f}" if record.iva_trasladado_16 > 0 else "",
        f"{record.monto_neto:.2f}" if record.iva_trasladado_0 > 0 and record.iva_trasladado_16 == 0 else "",
        f"{record.iva_exento:.2f}" if record.iva_exento > 0 else "",
        # IVA trasladado
        f"{record.iva_trasladado_16:.2f}" if record.iva_trasladado_16 > 0 else "",
        f"{record.iva_trasladado_0:.2f}" if record.iva_trasladado_0 > 0 else "",
        # IVA acreditable
        f"{record.iva_acreditable_16:.2f}" if record.iva_acreditable_16 > 0 else "",
        f"{record.iva_acreditable_0:.2f}" if record.iva_acreditable_0 > 0 else "",
        # IVA exento
        f"{record.iva_exento:.2f}" if record.iva_exento > 0 else "",
        # IVA retenido
        f"{record.iva_retenido:.2f}" if record.iva_retenido > 0 else "",
    ])


class DIOTGenerator:
    """Generate DIOT pipe-delimited file per RMF 3.10.7.

    Usage:
        gen = DIOTGenerator()
        result = gen.generate(diot_result)
        gen.export_txt(result, "/tmp/diot")
    """

    def __init__(self):
        self._errors: List[str] = []
        self._warnings: List[str] = []

    @property
    def errors(self) -> List[str]:
        return self._errors

    @property
    def warnings(self) -> List[str]:
        return self._warnings

    def validate(self, diot_result: DiotResult) -> bool:
        """Validate all records in a DIOT result."""
        self._errors = []
        self._warnings = []

        if not diot_result.records:
            self._errors.append("No hay registros DIOT para validar")
            return False

        for i, record in enumerate(diot_result.records):
            errs = _validate_record(record)
            for e in errs:
                self._errors.append(f"Registro #{i+1} ({record.rfc_tercero}): {e}")

            # Warning for zero amounts
            if record.monto_neto <= 0:
                self._warnings.append(
                    f"Registro #{i+1} ({record.rfc_tercero}): monto neto es 0"
                )

        return len(self._errors) == 0

    def generate(self, diot_result: DiotResult) -> str:
        """Generate pipe-delimited DIOT content.

        Returns the full TXT content as a string.
        """
        # Validate first
        self.validate(diot_result)

        lines: List[str] = []

        for record in diot_result.records:
            # Skip generic RFCs even if they made it this far
            if is_generic_rfc(record.rfc_tercero):
                continue
            lines.append(format_diot_record(record))

        return "\n".join(lines)

    def export_txt(
        self,
        diot_result: DiotResult,
        output_dir: str = "/tmp/diot",
    ) -> str:
        """Export DIOT to a pipe-delimited TXT file.

        Returns the path to the generated file.
        """
        content = self.generate(diot_result)

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        filename = (
            f"DIOT_{diot_result.rfc_contribuyente}_"
            f"{diot_result.periodo.replace('-', '')}.txt"
        )
        filepath = out / filename
        filepath.write_text(content, encoding="utf-8")

        return str(filepath)

    def get_summary(self) -> dict:
        """Return summary of last generation/validation."""
        return {
            "errors": self._errors,
            "warnings": self._warnings,
            "has_errors": len(self._errors) > 0,
            "error_count": len(self._errors),
            "warning_count": len(self._warnings),
        }
