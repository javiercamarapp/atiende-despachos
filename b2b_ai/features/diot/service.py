# -*- coding: utf-8 -*-
"""
service.py — DiotService: generación, validación, inconsistencias y exportación XML.

This service:
  - Generates a DIOT from a list of CFDI invoices
  - Validates DIOT data against CFDI records
  - Detects inconsistencies (missing RFC, IVA mismatches, duplicates)
  - Exports DIOT to SAT XML format
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from xml.etree.ElementTree import Element, SubElement, tostring

from b2b_ai.features.diot.models import (
    DiotEntry,
    DiotReport,
    DiotSummary,
    EstatusDIOT,
    OperacionType,
)
from b2b_ai.features.diot.validators import (
    validate_diot_entries,
    validate_iva_amount,
    validate_rfc,
)


class DiotService:
    """Core service for DIOT generation and validation."""

    def __init__(self):
        self._reports: Dict[str, DiotReport] = {}

    # -------------------------------------------------------------------
    # Generate DIOT from invoices
    # -------------------------------------------------------------------

    def generate_diot(
        self,
        month: int,
        year: int,
        tenant_id: Optional[str] = None,
        invoices: Optional[List[dict]] = None,
    ) -> DiotReport:
        """Generate a DIOT report for a given month/year from invoice data.

        Parameters
        ----------
        month : int
            Month (1-12).
        year : int
            Year.
        tenant_id : Optional[str]
            Tenant identifier.
        invoices : Optional[List[dict]]
            Raw invoice dicts with keys: rfc_tercero, nombre, tipo_operacion,
            monto_neto, iva_trasladado, iva_acreditable, uuid_cfdi, fecha.

        Returns
        -------
        DiotReport
        """
        entries: List[DiotEntry] = []

        if invoices:
            for inv in invoices:
                try:
                    entry = DiotEntry(
                        rfc_tercero=inv.get("rfc_tercero", ""),
                        nombre=inv.get("nombre", ""),
                        tipo_operacion=inv.get("tipo_operacion", "01"),
                        monto_neto=float(inv.get("monto_neto", 0)),
                        iva_trasladado=float(inv.get("iva_trasladado", 0)),
                        iva_acreditable=float(inv.get("iva_acreditable", 0)),
                        uuid_cfdi=inv.get("uuid_cfdi"),
                        fecha=inv.get("fecha"),
                    )
                    entries.append(entry)
                except Exception:
                    continue

        # Build summary
        summary = self._build_summary(entries)

        # Detect inconsistencies
        inconsistencies = self.detect_inconsistencies(entries)

        report_id = f"DIOT-{year}-{month:02d}-{str(_uuid.uuid4())[:8]}"
        report = DiotReport(
            id=report_id,
            month=month,
            year=year,
            tenant_id=tenant_id,
            entries=entries,
            summary=summary,
            inconsistencies=inconsistencies,
            estatus=EstatusDIOT.PENDIENTE,
            created_at=datetime.now().isoformat(),
        )

        self._reports[report_id] = report
        return report

    # -------------------------------------------------------------------
    # Validate DIOT data
    # -------------------------------------------------------------------

    def validate_diot_data(
        self,
        invoices: List[dict],
    ) -> Dict[str, Any]:
        """Validate invoice data before DIOT generation.

        Returns dict with:
          - is_valid: bool
          - errors: List[str]
          - warnings: List[str]
          - valid_entries: int
          - total_entries: int
        """
        is_valid, errors = validate_diot_entries(invoices)
        warnings: List[str] = []

        # Additional warnings for edge cases
        for i, inv in enumerate(invoices, 1):
            rfc = inv.get("rfc_tercero", "")
            if rfc:
                is_valid_rfc, _ = validate_rfc(rfc)
                if not is_valid_rfc:
                    warnings.append(f"Entrada #{i}: RFC '{rfc}' no pasa validación estricta.")

            monto_neto = inv.get("monto_neto", 0)
            iva_trasladado = inv.get("iva_trasladado", 0)
            if monto_neto and monto_neto > 0 and iva_trasladado == 0:
                warnings.append(
                    f"Entrada #{i}: monto_neto={monto_neto} pero iva_trasladado=0. "
                    "¿Operación exenta de IVA?"
                )

        return {
            "is_valid": is_valid,
            "errors": errors,
            "warnings": warnings,
            "valid_entries": sum(1 for _ in invoices if True) - len(errors),
            "total_entries": len(invoices),
        }

    # -------------------------------------------------------------------
    # Detect inconsistencies
    # -------------------------------------------------------------------

    def detect_inconsistencies(
        self,
        entries: List[DiotEntry],
    ) -> List[Dict[str, Any]]:
        """Detect inconsistencies in DIOT entries.

        Checks:
          - IVA amount doesn't match monto_neto × rate
          - RFC format invalid
          - Missing required data
          - Duplicate entries
          - IVA acreditable > IVA trasladado (red flag)
        """
        inconsistencies: List[Dict[str, Any]] = []
        seen_rfc_tipo: Dict[tuple, int] = {}

        for i, entry in enumerate(entries, 1):
            # RFC validation
            is_valid_rfc, rfc_err = validate_rfc(entry.rfc_tercero)
            if not is_valid_rfc:
                inconsistencies.append({
                    "type": "RFC_INVALIDO",
                    "entry_index": i,
                    "rfc": entry.rfc_tercero,
                    "detail": rfc_err,
                    "severity": "error",
                })

            # IVA amount validation
            if entry.monto_neto > 0:
                is_valid_iva, iva_err = validate_iva_amount(
                    entry.monto_neto, entry.iva_trasladado
                )
                if not is_valid_iva:
                    inconsistencies.append({
                        "type": "IVA_MISMATCH",
                        "entry_index": i,
                        "rfc": entry.rfc_tercero,
                        "detail": iva_err,
                        "severity": "warning",
                    })

            # IVA acreditable > IVA trasladado
            if entry.iva_acreditable > entry.iva_trasladado:
                inconsistencies.append({
                    "type": "IVA_ACREDITABLE_MAYOR",
                    "entry_index": i,
                    "rfc": entry.rfc_tercero,
                    "detail": (
                        f"IVA acreditable ({entry.iva_acreditable}) es mayor que "
                        f"IVA trasladado ({entry.iva_trasladado})."
                    ),
                    "severity": "warning",
                })

            # Duplicate detection
            key = (entry.rfc_tercero.strip().upper(), entry.tipo_operacion)
            if key in seen_rfc_tipo:
                inconsistencies.append({
                    "type": "DUPLICADO",
                    "entry_index": i,
                    "rfc": entry.rfc_tercero,
                    "detail": (
                        f"Entrada duplicada para RFC='{entry.rfc_tercero}' "
                        f"tipo='{entry.tipo_operacion}'."
                    ),
                    "severity": "warning",
                })
            seen_rfc_tipo[key] = seen_rfc_tipo.get(key, 0) + 1

            # Missing data
            if not entry.nombre:
                inconsistencies.append({
                    "type": "NOMBRE_FALTANTE",
                    "entry_index": i,
                    "rfc": entry.rfc_tercero,
                    "detail": "Nombre o razón social del tercero no proporcionado.",
                    "severity": "info",
                })

        return inconsistencies

    # -------------------------------------------------------------------
    # Export to XML
    # -------------------------------------------------------------------

    def export_diot_xml(
        self,
        diot_data: DiotReport,
    ) -> str:
        """Export a DIOT report to SAT XML format.

        Returns the XML as a string.

        SAT DIOT XML structure (simplified):
          <DIOT>
            <Periodo mes="MM" anio="AAAA"/>
            <Operaciones>
              <Operacion rfc="..." tipo="..." montoNeto="..." ivaTrasladado="..." ivaAcreditable="..."/>
              ...
            </Operaciones>
          </DIOT>
        """
        root = Element("DIOT")
        root.set("version", "1.0")

        # Periodo
        periodo = SubElement(root, "Periodo")
        periodo.set("mes", f"{diot_data.month:02d}")
        periodo.set("anio", str(diot_data.year))

        # Operaciones
        operaciones = SubElement(root, "Operaciones")

        for entry in diot_data.entries:
            op = SubElement(operaciones, "Operacion")
            op.set("rfc", entry.rfc_tercero)
            op.set("tipo", entry.tipo_operacion.value)
            op.set("montoNeto", f"{entry.monto_neto:.2f}")
            op.set("ivaTrasladado", f"{entry.iva_trasladado:.2f}")
            op.set("ivaAcreditable", f"{entry.iva_acreditable:.2f}")
            if entry.uuid_cfdi:
                op.set("uuidCFDI", entry.uuid_cfdi)

        # Summary
        resumen = SubElement(root, "Resumen")
        resumen.set("totalOperaciones", str(diot_data.summary.total_operaciones))
        resumen.set("totalIvaTrasladado", f"{diot_data.summary.total_iva_trasladado:.2f}")
        resumen.set("totalIvaAcreditable", f"{diot_data.summary.total_iva_acreditable:.2f}")
        resumen.set("diferencias", f"{diot_data.summary.diferencias:.2f}")

        xml_bytes = tostring(root, encoding="unicode", xml_declaration=False)
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_bytes

    # -------------------------------------------------------------------
    # Get report
    # -------------------------------------------------------------------

    def get_report(self, report_id: str) -> Optional[DiotReport]:
        """Retrieve a DIOT report by ID."""
        return self._reports.get(report_id)

    def get_history(
        self,
        tenant_id: Optional[str] = None,
    ) -> List[DiotReport]:
        """Get all DIOT reports, optionally filtered by tenant."""
        reports = list(self._reports.values())
        if tenant_id:
            reports = [r for r in reports if r.tenant_id == tenant_id]
        return sorted(reports, key=lambda r: (r.year, r.month), reverse=True)

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    def _build_summary(self, entries: List[DiotEntry]) -> DiotSummary:
        """Build a summary from DIOT entries."""
        total_neto = sum(e.monto_neto for e in entries)
        total_trasladado = sum(e.iva_trasladado for e in entries)
        total_acreditable = sum(e.iva_acreditable for e in entries)

        return DiotSummary(
            total_operaciones=len(entries),
            total_iva_trasladado=total_trasladado,
            total_iva_acreditable=total_acreditable,
            diferencias=total_trasladado - total_acreditable,
            total_monto_neto=total_neto,
        )
