# -*- coding: utf-8 -*-
"""
service.py — FiscalConciliationService: comparación ERP vs SAT, detección de
omisiones, discrepancias y generación de reportes fiscales.

This service:
  - Compares ERP records against SAT declarations
  - Detects omissions (invoices in one system but not the other)
  - Detects discrepancies (amount/date/RFC mismatches)
  - Generates consolidated fiscal reports with recommendations
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.features.conciliacion_fiscal.models import (
    FiscalComparison,
    FiscalDiscrepancy,
    FiscalReport,
    Omission,
    TipoDiscrepancia,
    TipoOmicion,
)
from b2b_ai.features.conciliacion_fiscal.validators import (
    cross_reference_data,
    validate_fiscal_amounts,
    validate_fiscal_period,
)
from b2b_ai.features.compliance import (
    FiscalOutput, AuditTrail, sanitize_string, mask_rfc,
    verify_tenant_access, SafeError, SAFE_ERRORS, ManualProcessMixin,
)


class FiscalConciliationService(ManualProcessMixin):
    """Core service for fiscal conciliation (ERP vs SAT)."""

    def __init__(self):
        super().__init__()
        self._reports: Dict[str, FiscalReport] = {}
        self._comparisons: Dict[str, FiscalComparison] = {}

    # -------------------------------------------------------------------
    # Compare ERP vs SAT
    # -------------------------------------------------------------------

    def compare_erp_vs_sat(
        self,
        tenant_id: Optional[str],
        month: int,
        year: int,
        erp_data: Optional[List[dict]] = None,
        sat_data: Optional[List[dict]] = None,
    ) -> FiscalComparison:
        """Compare ERP records against SAT declarations for a period.

        Parameters
        ----------
        tenant_id : Optional[str]
            Tenant identifier.
        month : int
            Month (1-12).
        year : int
            Year.
        erp_data : Optional[List[dict]]
            ERP records (uuid, rfc, monto, fecha, concepto).
        sat_data : Optional[List[dict]]
            SAT records (uuid, rfc, monto, fecha, concepto).

        Returns
        -------
        FiscalComparison
        """
        erp_data = erp_data or []
        sat_data = sat_data or []
        periodo = f"{year}-{month:02d}"

        erp_total = sum(float(r.get("monto", 0)) for r in erp_data)
        sat_total = sum(float(r.get("monto", 0)) for r in sat_data)

        validate_fiscal_amounts(erp_total, sat_total)

        # Detect omissions
        omisiones = self.detect_omissions(erp_data, sat_data, periodo)

        # Detect discrepancies
        discrepancias = self.detect_discrepancies(erp_data, sat_data, periodo)

        comparison = FiscalComparison(
            erp_total=erp_total,
            sat_total=sat_total,
            diferencia=erp_total - sat_total,
            omisiones=omisiones,
            discrepancias=discrepancias,
            periodo=periodo,
            tenant_id=tenant_id,
            created_at=datetime.now().isoformat(),
        )

        self._comparisons[periodo] = comparison
        return comparison

    # -------------------------------------------------------------------
    # Detect omissions
    # -------------------------------------------------------------------

    def detect_omissions(
        self,
        erp_data: List[dict],
        sat_data: List[dict],
        periodo: str = "",
    ) -> List[Omission]:
        """Detect omissions between ERP and SAT data.

        Omissions:
          - ERP records not in SAT (potential under-reporting)
          - SAT records not in ERP (potential over-reporting or missing entries)
        """
        omissions: List[Omission] = []

        # Build UUID lookup maps
        erp_by_uuid: Dict[str, dict] = {}
        for r in erp_data:
            uuid = r.get("uuid", "")
            if uuid:
                erp_by_uuid[uuid] = r

        sat_by_uuid: Dict[str, dict] = {}
        for r in sat_data:
            uuid = r.get("uuid", "")
            if uuid:
                sat_by_uuid[uuid] = r

        # ERP records not in SAT
        erp_only = set(erp_by_uuid.keys()) - set(sat_by_uuid.keys())
        for uuid in erp_only:
            rec = erp_by_uuid[uuid]
            omissions.append(Omission(
                id=f"OM-ERP-{str(_uuid.uuid4())[:8]}",
                tipo=TipoOmicion.FACTURA_ERP,
                periodo=periodo,
                monto=float(rec.get("monto", 0)),
                rfc=rec.get("rfc"),
                uuid_cfdi=uuid,
                detalle=(
                    f"CFDI '{uuid}' registrado en ERP pero no encontrado en SAT. "
                    f"RFC: {rec.get('rfc', '?')}, monto: {rec.get('monto', '?')}."
                ),
            ))

        # SAT records not in ERP
        sat_only = set(sat_by_uuid.keys()) - set(erp_by_uuid.keys())
        for uuid in sat_only:
            rec = sat_by_uuid[uuid]
            omissions.append(Omission(
                id=f"OM-SAT-{str(_uuid.uuid4())[:8]}",
                tipo=TipoOmicion.FACTURA_SAT,
                periodo=periodo,
                monto=float(rec.get("monto", 0)),
                rfc=rec.get("rfc"),
                uuid_cfdi=uuid,
                detalle=(
                    f"CFDI '{uuid}' registrado en SAT pero no encontrado en ERP. "
                    f"RFC: {rec.get('rfc', '?')}, monto: {rec.get('monto', '?')}."
                ),
            ))

        return omissions

    # -------------------------------------------------------------------
    # Detect discrepancies
    # -------------------------------------------------------------------

    def detect_discrepancies(
        self,
        erp_data: List[dict],
        sat_data: List[dict],
        periodo: str = "",
    ) -> List[FiscalDiscrepancy]:
        """Detect discrepancies in matching records between ERP and SAT.

        Checks:
          - Amount differences
          - RFC mismatches
          - Concepto differences
        """
        discrepancies: List[FiscalDiscrepancy] = []

        # Build UUID lookup maps
        erp_by_uuid: Dict[str, dict] = {}
        for r in erp_data:
            uuid = r.get("uuid", "")
            if uuid:
                erp_by_uuid[uuid] = r

        sat_by_uuid: Dict[str, dict] = {}
        for r in sat_data:
            uuid = r.get("uuid", "")
            if uuid:
                sat_by_uuid[uuid] = r

        # Only check records present in both
        common_uuids = set(erp_by_uuid.keys()) & set(sat_by_uuid.keys())

        for uuid in common_uuids:
            erp_rec = erp_by_uuid[uuid]
            sat_rec = sat_by_uuid[uuid]

            erp_monto = float(erp_rec.get("monto", 0))
            sat_monto = float(sat_rec.get("monto", 0))

            # Amount discrepancy
            if abs(erp_monto - sat_monto) > 0.01:
                diff = erp_monto - sat_monto
                discrepancies.append(FiscalDiscrepancy(
                    id=f"DISC-MONTO-{str(_uuid.uuid4())[:8]}",
                    tipo=TipoDiscrepancia.MONTO,
                    erp_amount=erp_monto,
                    sat_amount=sat_monto,
                    diff=diff,
                    explanation=(
                        f"Monto en ERP ({erp_monto}) difiere de SAT ({sat_monto}). "
                        f"Diferencia: {diff:.2f}."
                    ),
                    rfc=erp_rec.get("rfc"),
                    periodo=periodo,
                ))

            # RFC discrepancy
            erp_rfc = erp_rec.get("rfc", "").strip().upper()
            sat_rfc = sat_rec.get("rfc", "").strip().upper()
            if erp_rfc and sat_rfc and erp_rfc != sat_rfc:
                discrepancies.append(FiscalDiscrepancy(
                    id=f"DISC-RFC-{str(_uuid.uuid4())[:8]}",
                    tipo=TipoDiscrepancia.RFC,
                    erp_amount=erp_monto,
                    sat_amount=sat_monto,
                    diff=0.0,
                    explanation=(
                        f"RFC en ERP ({erp_rfc}) difiere de SAT ({sat_rfc}) "
                        f"para CFDI '{uuid}'."
                    ),
                    rfc=erp_rfc,
                    periodo=periodo,
                ))

            # Concepto discrepancy
            erp_concepto = erp_rec.get("concepto", "").strip().lower()
            sat_concepto = sat_rec.get("concepto", "").strip().lower()
            if erp_concepto and sat_concepto and erp_concepto != sat_concepto:
                discrepancies.append(FiscalDiscrepancy(
                    id=f"DISC-CONC-{str(_uuid.uuid4())[:8]}",
                    tipo=TipoDiscrepancia.CONCEPTO,
                    erp_amount=erp_monto,
                    sat_amount=sat_monto,
                    diff=0.0,
                    explanation=(
                        f"Concepto en ERP ('{erp_concepto}') difiere de SAT ('{sat_concepto}') "
                        f"para CFDI '{uuid}'."
                    ),
                    rfc=erp_rec.get("rfc"),
                    periodo=periodo,
                ))

        return discrepancies

    # -------------------------------------------------------------------
    # Generate fiscal report
    # -------------------------------------------------------------------

    def generate_fiscal_report(
        self,
        comparison: FiscalComparison,
    ) -> FiscalReport:
        """Generate a consolidated fiscal report from a comparison.

        Includes recommendations based on the types of issues found.
        """
        recommendations: List[str] = []

        # Recommendations for omissions
        erp_only = [o for o in comparison.omisiones if o.tipo == TipoOmicion.FACTURA_ERP]
        sat_only = [o for o in comparison.omisiones if o.tipo == TipoOmicion.FACTURA_SAT]

        if erp_only:
            total_erp_only = sum(o.monto for o in erp_only)
            recommendations.append(
                f"Se encontraron {len(erp_only)} facturas en ERP no declaradas en SAT "
                f"(monto total: {total_erp_only:.2f}). Verificar declaración SAT."
            )

        if sat_only:
            total_sat_only = sum(o.monto for o in sat_only)
            recommendations.append(
                f"Se encontraron {len(sat_only)} facturas en SAT no registradas en ERP "
                f"(monto total: {total_sat_only:.2f}). Actualizar registros ERP."
            )

        # Recommendations for discrepancies
        monto_disc = [d for d in comparison.discrepancias if d.tipo == TipoDiscrepancia.MONTO]
        if monto_disc:
            total_diff = sum(abs(d.diff) for d in monto_disc)
            recommendations.append(
                f"Se encontraron {len(monto_disc)} discrepancias de monto "
                f"(diferencia total: {total_diff:.2f}). Revisar registros."
            )

        rfc_disc = [d for d in comparison.discrepancias if d.tipo == TipoDiscrepancia.RFC]
        if rfc_disc:
            recommendations.append(
                f"Se encontraron {len(rfc_disc)} discrepancias de RFC. "
                "Verificar que los RFC coincidan entre ERP y SAT."
            )

        if not comparison.omisiones and not comparison.discrepancias:
            recommendations.append("No se encontraron omisiones ni discrepancias. Los registros están conciliados.")

        report_id = f"FR-{comparison.periodo}-{str(_uuid.uuid4())[:8]}"

        # CFF Art. 89: Compliance metadata
        has_issues = bool(comparison.omisiones or comparison.discrepancias)

        report = FiscalReport(
            id=report_id,
            comparison=comparison,
            total_omisiones=len(comparison.omisiones),
            total_discrepancias=len(comparison.discrepancias),
            monto_total_omisiones=sum(o.monto for o in comparison.omisiones),
            monto_total_discrepancias=sum(abs(d.diff) for d in comparison.discrepancias),
            recomendaciones=recommendations,
            created_at=datetime.now().isoformat(),
        )

        # Add compliance fields
        report.referencia_legal = "CFF Art. 89"
        report.supuesto = "Conciliación fiscal ERP vs SAT"
        report.requires_human_review = has_issues
        report.human_review_reason = f"{len(comparison.omisiones)} omision(es), {len(comparison.discrepancias)} discrepancia(s)" if has_issues else ""
        report.escalation_path = "review_by_contador"

        self._reports[report_id] = report
        self.log_audit(user=comparison.tenant_id or "system", action="generate_fiscal_report", module="conciliacion_fiscal", result="success", tenant_id=comparison.tenant_id or "")
        return report

    # -------------------------------------------------------------------
    # Get report
    # -------------------------------------------------------------------

    def get_report(self, report_id: str) -> Optional[FiscalReport]:
        """Retrieve a fiscal report by ID."""
        return self._reports.get(report_id)

    # -------------------------------------------------------------------
    # Resolve omission
    # -------------------------------------------------------------------

    def resolve_omission(
        self,
        comparison_periodo: str,
        omission_id: str,
    ) -> bool:
        """Mark an omission as resolved."""
        comparison = self._comparisons.get(comparison_periodo)
        if not comparison:
            return False

        for o in comparison.omisiones:
            if o.id == omission_id:
                o.resuelta = True
                return True

        return False
