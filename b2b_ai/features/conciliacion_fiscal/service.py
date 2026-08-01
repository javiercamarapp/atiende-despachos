# -*- coding: utf-8 -*-
"""
service.py — Fiscal Conciliation service (ERP vs SAT).

Cross-references ERP records with SAT filings, detects omissions
and discrepancies, and generates fiscal reports.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Dict, List, Optional

from .models import (
    DeclaracionTipo,
    DiscrepancySeverity,
    ERPRecord,
    FiscalComparison,
    FiscalDiscrepancy,
    FiscalReport,
    Omission,
    SATRecord,
)


# ---------------------------------------------------------------------------
# In-memory store (replaced by DB in production)
# ---------------------------------------------------------------------------
_comparisons: Dict[str, FiscalComparison] = {}
_reports: Dict[str, FiscalReport] = {}


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------

def compare_erp_vs_sat(
    tenant_id: str,
    month: int,
    year: int,
    erp_records: Optional[List[ERPRecord]] = None,
    sat_records: Optional[List[SATRecord]] = None,
) -> FiscalComparison:
    """Cross-reference ERP records with SAT filings for a given period.

    Args:
        tenant_id: Company/tenant identifier.
        month: Month (1-12).
        year: Year (e.g. 2026).
        erp_records: ERP records to compare. Empty list if none found.
        sat_records: SAT records to compare. Empty list if none found.

    Returns:
        FiscalComparison with totals, omissions, and discrepancies.
    """
    if erp_records is None:
        erp_records = []
    if sat_records is None:
        sat_records = []

    periodo = f"{year:04d}-{month:02d}"
    erp_total = sum(r.monto for r in erp_records)
    sat_total = sum(r.monto for r in sat_records)
    diferencia = abs(erp_total - sat_total)

    omisiones = detect_omissions(erp_records, sat_records, periodo)
    discrepancias = detect_discrepancies(erp_records, sat_records)

    comparison = FiscalComparison(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        periodo=periodo,
        erp_total=round(erp_total, 2),
        sat_total=round(sat_total, 2),
        diferencia=round(diferencia, 2),
        omisiones=omisiones,
        discrepancias=discrepancias,
        erp_records_count=len(erp_records),
        sat_records_count=len(sat_records),
        status="pending",
        created_at=datetime.utcnow(),
    )

    _comparisons[comparison.id] = comparison
    return comparison


def detect_omissions(
    erp_records: List[ERPRecord],
    sat_records: List[SATRecord],
    periodo: str = "",
) -> List[Omission]:
    """Find declarations present in ERP but missing from SAT filings.

    Compares by tipo (concept type). If ERP has records for a concept
    type but SAT has no corresponding filing, it's flagged as an omission.
    """
    omisiones: List[Omission] = []

    # Group ERP records by concept type
    erp_types: Dict[str, float] = {}
    for r in erp_records:
        key = r.concepto.lower()
        erp_types[key] = erp_types.get(key, 0) + r.monto

    # Group SAT records by type
    sat_types: set = set()
    for r in sat_records:
        sat_types.add(r.tipo.value.lower())

    # Map concept names to declaracion types
    concept_to_tipo: Dict[str, DeclaracionTipo] = {
        "diot": DeclaracionTipo.DIOT,
        "iva": DeclaracionTipo.IVA,
        "isr": DeclaracionTipo.ISR,
        "contabilidad_electronica": DeclaracionTipo.CONTABILIDAD_ELECTRONICA,
        "contabilidad": DeclaracionTipo.CONTABILIDAD_ELECTRONICA,
    }

    for concepto, monto in erp_types.items():
        if monto == 0:
            continue
        # Check if this concept has a SAT filing
        mapped_tipo = concept_to_tipo.get(concepto)
        if mapped_tipo is not None:
            if mapped_tipo.value.lower() not in sat_types:
                omisiones.append(
                    Omission(
                        tipo=mapped_tipo,
                        periodo=periodo,
                        monto=round(abs(monto), 2),
                        descripcion=f"ERP shows activity for {concepto} but no SAT filing found",
                    )
                )

    # If SAT has types not in ERP, also flag
    for sat_tipo in sat_types:
        if sat_tipo not in [ct.lower() for ct in concept_to_tipo.keys()]:
            # SAT type not mapped, skip
            continue

    return omisiones


def detect_discrepancies(
    erp_records: List[ERPRecord],
    sat_records: List[SATRecord],
) -> List[FiscalDiscrepancy]:
    """Find amount mismatches between ERP and SAT for the same concept.

    Matches ERP concepto to SAT tipo and calculates differences.
    """
    discrepancias: List[FiscalDiscrepancy] = []

    # Aggregate ERP by concept
    erp_by_concept: Dict[str, float] = {}
    for r in erp_records:
        key = r.concepto.lower()
        erp_by_concept[key] = erp_by_concept.get(key, 0) + r.monto

    # Aggregate SAT by type
    sat_by_type: Dict[str, float] = {}
    for r in sat_records:
        key = r.tipo.value.lower()
        sat_by_type[key] = sat_by_type.get(key, 0) + r.monto

    # Map concepts to SAT types
    concept_to_sat: Dict[str, str] = {
        "diot": "diot",
        "iva": "iva",
        "isr": "isr",
        "contabilidad_electronica": "contabilidad_electronica",
        "contabilidad": "contabilidad_electronica",
    }

    for concepto, erp_monto in erp_by_concept.items():
        sat_key = concept_to_sat.get(concepto)
        if sat_key is None:
            continue
        sat_monto = sat_by_type.get(sat_key, 0.0)
        diff = abs(erp_monto - sat_monto)

        if diff > 0.01:  # Ignore penny differences
            severity = _calculate_severity(diff, erp_monto)
            explanation = _suggest_explanation(diff, erp_monto, sat_monto)

            discrepancias.append(
                FiscalDiscrepancy(
                    erp_amount=round(erp_monto, 2),
                    sat_amount=round(sat_monto, 2),
                    diff=round(diff, 2),
                    explanation=explanation,
                    severity=severity,
                    concepto=concepto,
                )
            )

    return discrepancias


def generate_fiscal_report(comparison: FiscalComparison) -> FiscalReport:
    """Generate a summary report from a fiscal comparison."""
    total_omisiones = len(comparison.omisiones)
    total_discrepancias = len(comparison.discrepancias)
    total_diferencia = comparison.diferencia

    # Calculate risk level
    if total_omisiones == 0 and total_discrepancias == 0:
        risk_level = "low"
    elif total_diferencia < 10000 and total_omisiones <= 1:
        risk_level = "medium"
    elif total_diferencia < 50000:
        risk_level = "high"
    else:
        risk_level = "critical"

    # Generate recommendations
    recommendations = _generate_recommendations(
        comparison.omisiones, comparison.discrepancias, total_diferencia
    )

    # Build summary
    summary_parts = [
        f"Conciliación fiscal para el periodo {comparison.periodo}:",
        f"ERP total: ${comparison.erp_total:,.2f} MXN",
        f"SAT total: ${comparison.sat_total:,.2f} MXN",
        f"Diferencia: ${total_diferencia:,.2f} MXN",
        f"Omisiones detectadas: {total_omisiones}",
        f"Discrepancias detectadas: {total_discrepancias}",
    ]
    summary = " | ".join(summary_parts)

    report = FiscalReport(
        comparison_id=comparison.id,
        tenant_id=comparison.tenant_id,
        periodo=comparison.periodo,
        summary=summary,
        total_omisiones=total_omisiones,
        total_discrepancias=total_discrepancias,
        total_diferencia=round(total_diferencia, 2),
        risk_level=risk_level,
        recommendations=recommendations,
        created_at=datetime.utcnow(),
    )

    _reports[report.comparison_id] = report
    return report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _calculate_severity(diff: float, base_amount: float) -> DiscrepancySeverity:
    """Determine severity based on absolute and relative difference."""
    if base_amount == 0:
        return DiscrepancySeverity.HIGH if diff > 0 else DiscrepancySeverity.LOW

    relative = diff / abs(base_amount)

    if relative > 0.10:
        return DiscrepancySeverity.CRITICAL
    elif relative > 0.05:
        return DiscrepancySeverity.HIGH
    elif relative > 0.02:
        return DiscrepancySeverity.MEDIUM
    else:
        return DiscrepancySeverity.LOW


def _suggest_explanation(diff: float, erp: float, sat: float) -> str:
    """Suggest a plausible explanation for the discrepancy."""
    if sat == 0:
        return "SAT no presenta declaración para este concepto"
    if erp == 0:
        return "ERP no registra movimientos para este concepto"
    relative = diff / abs(max(erp, sat)) * 100
    if relative < 3:
        return "Diferencia menor — posible redondeo o ajuste contable"
    elif relative < 10:
        return "Diferencia moderada — revisar comprobantes y asientos pendientes"
    else:
        return "Diferencia significativa — requiere investigación detallada"


def _generate_recommendations(
    omisiones: List[Omission],
    discrepancias: List[FiscalDiscrepancy],
    total_diferencia: float,
) -> List[str]:
    """Generate actionable recommendations based on findings."""
    recs: List[str] = []

    if omisiones:
        tipos = set(o.tipo.value for o in omisiones)
        recs.append(
            f"Presentar declaraciones pendientes: {', '.join(tipos)}. "
            "Verificar multas y recargos acumulados."
        )

    for d in discrepancias:
        if d.severity in (DiscrepancySeverity.HIGH, DiscrepancySeverity.CRITICAL):
            recs.append(
                f"Revisar discrepancia en {d.concepto}: "
                f"ERP ${d.erp_amount:,.2f} vs SAT ${d.sat_amount:,.2f} "
                f"(diferencia ${d.diff:,.2f})."
            )

    if total_diferencia > 50000:
        recs.append("La diferencia total supera $50,000 MXN — escalar a revisión fiscal externa.")

    if not recs:
        recs.append("Sin acciones requeridas. Los registros concuerdan.")

    return recs


def get_comparison(comparison_id: str) -> Optional[FiscalComparison]:
    """Retrieve a comparison by ID."""
    return _comparisons.get(comparison_id)


def get_report(comparison_id: str) -> Optional[FiscalReport]:
    """Retrieve a fiscal report by comparison ID."""
    return _reports.get(comparison_id)


def resolve_discrepancy(comparison_id: str, discrepancy_index: int) -> bool:
    """Mark a specific discrepancy as resolved."""
    comp = _comparisons.get(comparison_id)
    if comp is None:
        return False
    if 0 <= discrepancy_index < len(comp.discrepancias):
        comp.discrepancias.pop(discrepancy_index)
        comp.status = "resolved" if not comp.discrepancias else "partial"
        return True
    return False
