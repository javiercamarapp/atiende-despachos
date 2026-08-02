"""DIOT service layer — generation, validation, export.

All business logic lives here.  The service is stateless: it receives data,
validates it, aggregates it, and exports the result.  Persistence (DB reads /
writes) is expected to be injected by the caller or a repository layer.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import (
    CFDIInvoiceInput,
    DiotEntry,
    DiotReport,
    DiotSummary,
    EstatusDIOT,
    Inconsistencia,
    TipoIva,
    TipoOperacion,
)
from .validators import (
    ValidationResult,
    validate_diot_entries,
    validate_invoices,
)
from b2b_ai.features.compliance import (
    FiscalOutput, AuditTrail, sanitize_string, mask_rfc,
    verify_tenant_access, SafeError, SAFE_ERRORS, ManualProcessMixin,
)

# ---------------------------------------------------------------------------
# In-memory store (replace with real DB in production)
# ---------------------------------------------------------------------------

_reports: Dict[str, DiotReport] = {}


# ---------------------------------------------------------------------------
# Aggregation: invoices -> DIOT entries
# ---------------------------------------------------------------------------

def _aggregate_invoices(invoices: list[CFDIInvoiceInput]) -> list[DiotEntry]:
    """Group invoices by (rfc, tipo_operacion, tipo_iva) and sum amounts."""
    groups: dict[tuple[str, TipoOperacion, TipoIva], dict] = defaultdict(lambda: {
        "nombre": "",
        "monto_neto": 0.0,
        "iva_trasladado": 0.0,
        "iva_acreditable": 0.0,
        "count": 0,
        "uuids": [],
    })

    for inv in invoices:
        # Normalize MXN amounts
        neto = inv.subtotal * inv.tipo_cambio
        iva_t = inv.iva_trasladado * inv.tipo_cambio
        iva_a = inv.iva_acreditable * inv.tipo_cambio

        key = (inv.rfc_emisor, inv.tipo_operacion, inv.tipo_iva)
        g = groups[key]
        g["nombre"] = inv.nombre_emisor  # last-wins, should be consistent per RFC
        g["monto_neto"] += neto
        g["iva_trasladado"] += iva_t
        g["iva_acreditable"] += iva_a
        g["count"] += 1
        g["uuids"].append(inv.uuid)

    entries: list[DiotEntry] = []
    for (rfc, tipo_op, tipo_iva), g in sorted(groups.items()):
        entries.append(DiotEntry(
            rfc_tercero=rfc,
            nombre=g["nombre"],
            tipo_operacion=tipo_op,
            tipo_iva=tipo_iva,
            monto_neto=round(g["monto_neto"], 2),
            iva_trasladado=round(g["iva_trasladado"], 2),
            iva_acreditable=round(g["iva_acreditable"], 2),
            numero_facturas=g["count"],
            uuids=g["uuids"],
        ))
    return entries


# ---------------------------------------------------------------------------
# Public functions (module-level API)
# ---------------------------------------------------------------------------

def generate_diot(
    month: int,
    year: int,
    tenant_id: str,
    invoices: list[CFDIInvoiceInput] | None = None,
) -> DiotReport:
    """Generate DIOT report. CFF Art. 85 compliant — DIOT must match CFDI data."""
    """Generate a complete DIOT report.

    Parameters
    ----------
    month : 1-12
    year  : fiscal year (>= 2014)
    tenant_id : platform tenant
    invoices  : list of captured CFDI invoices; if *None* the caller is
                expected to have already fetched them from the DB.

    Returns
    -------
    DiotReport  with entries, summary, and any inconsistencies detected.
    """
    report = DiotReport(
        month=month,
        year=year,
        tenant_id=tenant_id,
        estatus=EstatusDIOT.VALIDANDO,
    )

    if not invoices:
        report.estatus = EstatusDIOT.ERROR
        report.inconsistencies = [
            Inconsistencia(
                tipo="sin_facturas",
                severidad="critical",
                descripcion="No se proporcionaron facturas para generar la DIOT",
            ),
        ]
        _reports[report.id] = report
        return report

    # 1. Validate invoices
    inv_validation = validate_invoices(invoices)

    # 2. Aggregate into DIOT entries
    entries = _aggregate_invoices(invoices)

    # 3. Validate entries
    entry_validation = validate_diot_entries(entries, invoices)

    # 4. Merge all inconsistencies
    all_inconsistencies = inv_validation.inconsistencies + entry_validation.inconsistencies

    # 5. Build report
    report.entries = entries
    report.inconsistencies = all_inconsistencies
    report.recompute_summary()
    report.generated_at = datetime.utcnow()

    if entry_validation.valid and inv_validation.valid:
        report.estatus = EstatusDIOT.GENERADA
    else:
        report.estatus = EstatusDIOT.GENERADA  # generate anyway; mark issues

    # CFF Art. 89: Add compliance metadata
    report.referencia_legal = "CFF Art. 85"
    report.supuesto = "DIOT debe coincidir con datos CFDI"
    report.requires_human_review = len(all_inconsistencies) > 0
    report.human_review_reason = f"{len(all_inconsistencies)} inconsistencia(s) detectada(s)" if all_inconsistencies else ""
    report.escalation_path = "review_by_contador"

    _reports[report.id] = report
    return report


def validate_diot_data(
    invoices: list[CFDIInvoiceInput] | list[dict],
) -> ValidationResult:
    """Validate invoice data before DIOT generation.

    Returns a ``ValidationResult`` with ``.valid``, ``.inconsistencies``,
    ``.errors``, and ``.warnings``.
    """
    return validate_invoices(invoices)


def detect_inconsistencies(
    entries: list[DiotEntry],
    invoices: list[CFDIInvoiceInput] | None = None,
) -> list[Inconsistencia]:
    """Run inconsistency detection on existing DIOT entries."""
    result = validate_diot_entries(entries, invoices)
    return result.inconsistencies


def export_diot_xml(diot_report: DiotReport, output_dir: str = "/tmp/diot") -> str:
    """Export DIOT report to SAT XML format.

    Follows the SAT layout for the DIOT declaracion informativa.

    Returns
    -------
    str : path to the generated XML file
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    filename = f"DIOT_{diot_report.tenant_id}_{diot_report.year}_{diot_report.month:02d}.xml"
    filepath = out / filename

    # Build XML — xmlns is injected as a raw attribute after serialization
    # so child elements keep plain tag names (simplifies parsing).
    root = ET.Element("PlacasDiarioDiario")

    # Header
    header = ET.SubElement(root, "Encabezado")
    ET.SubElement(header, "RFC").text = diot_report.tenant_id
    ET.SubElement(header, "Mes").text = str(diot_report.month).zfill(2)
    ET.SubElement(header, "Anio").text = str(diot_report.year)
    ET.SubElement(header, "TotalOperaciones").text = str(diot_report.summary.total_operaciones)
    ET.SubElement(header, "TotalMontoNeto").text = f"{diot_report.summary.total_monto_neto:.2f}"
    ET.SubElement(header, "TotalIVATrasladado").text = f"{diot_report.summary.total_iva_trasladado:.2f}"
    ET.SubElement(header, "TotalIVAAcreditable").text = f"{diot_report.summary.total_iva_acreditable:.2f}"

    # Entries
    for entry in diot_report.entries:
        row = ET.SubElement(root, "Registro")
        row.set("rfc", entry.rfc_tercero)
        ET.SubElement(row, "Nombre").text = entry.nombre
        ET.SubElement(row, "TipoOperacion").text = entry.tipo_operacion.value
        ET.SubElement(row, "TipoIVA").text = entry.tipo_iva.value
        ET.SubElement(row, "MontoNeto").text = f"{entry.monto_neto:.2f}"
        ET.SubElement(row, "IVATrasladado").text = f"{entry.iva_trasladado:.2f}"
        ET.SubElement(row, "IVAAcreditable").text = f"{entry.iva_acreditable:.2f}"
        ET.SubElement(row, "NumFacturas").text = str(entry.numero_facturas)
        ET.SubElement(row, "Uuids").text = "|".join(entry.uuids)

    # Inconsistencies (if any)
    if diot_report.inconsistencies:
        incs = ET.SubElement(root, "Inconsistencias")
        for inc in diot_report.inconsistencies:
            inc_el = ET.SubElement(incs, "Inconsistencia")
            inc_el.set("tipo", inc.tipo)
            inc_el.set("severidad", inc.severidad)
            inc_el.text = inc.descripcion

    # Write
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(str(filepath), encoding="UTF-8", xml_declaration=True)

    # Also save a JSON sidecar for programmatic consumption
    json_path = filepath.with_suffix(".json")
    json_path.write_text(
        json.dumps(diot_report.model_dump(mode="json"), indent=2, default=str),
        encoding="utf-8",
    )

    return str(filepath)


# ---------------------------------------------------------------------------
# Report store helpers
# ---------------------------------------------------------------------------

def get_report(report_id: str) -> Optional[DiotReport]:
    """Retrieve a generated DIOT report by ID."""
    return _reports.get(report_id)


def list_reports(
    tenant_id: str | None = None,
    month: int | None = None,
    year: int | None = None,
) -> list[DiotReport]:
    """List reports with optional filters."""
    results = list(_reports.values())
    if tenant_id:
        results = [r for r in results if r.tenant_id == tenant_id]
    if month is not None:
        results = [r for r in results if r.month == month]
    if year is not None:
        results = [r for r in results if r.year == year]
    return sorted(results, key=lambda r: (r.year, r.month), reverse=True)


# ---------------------------------------------------------------------------
# DiotService class — wraps module-level functions for router use
# ---------------------------------------------------------------------------

class DiotService:
    """Stateless service class that wraps DIOT generation and validation.

    Used by the FastAPI router. All methods delegate to module-level functions.
    """

    def generate_diot(
        self,
        month: int,
        year: int,
        tenant_id: str,
        invoices: list | None = None,
    ) -> DiotReport:
        # Convert dict invoices to CFDIInvoiceInput if needed
        typed_invoices = self._coerce_invoices(invoices)
        return generate_diot(month, year, tenant_id, typed_invoices)

    def validate_diot_data(self, invoices: list) -> ValidationResult:
        typed_invoices = self._coerce_invoices(invoices)
        return validate_diot_data(typed_invoices)

    def get_report(self, report_id: str) -> Optional[DiotReport]:
        return get_report(report_id)

    def get_history(self, tenant_id: str | None = None) -> list[DiotReport]:
        return list_reports(tenant_id=tenant_id)

    def export_diot_xml(self, report: DiotReport, output_dir: str = "/tmp/diot") -> str:
        return export_diot_xml(report, output_dir)

    @staticmethod
    def _coerce_invoices(invoices: list | None) -> list[CFDIInvoiceInput] | None:
        """Convert dicts to CFDIInvoiceInput objects."""
        if not invoices:
            return None
        result = []
        for inv in invoices:
            if isinstance(inv, CFDIInvoiceInput):
                result.append(inv)
            elif isinstance(inv, dict):
                result.append(CFDIInvoiceInput(**inv))
            else:
                result.append(CFDIInvoiceInput(**inv.model_dump()))
        return result
