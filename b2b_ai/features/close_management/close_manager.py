# -*- coding: utf-8 -*-
"""
close_manager.py — CloseManager: orchestrates the monthly close process.

Flow:
  1. Create checklist (13-17 steps)
  2. Run automatic validations (CFDIs, conciliación, nómina, pólizas)
  3. Generate adjustment policies (13 types)
  4. Post adjustments to ERP
  5. Generate balanza de comprobación
  6. Prepare declaration drafts (IVA, ISR, DIOT)
  7. Mark steps for human review
  8. Finalize on approval
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.features.close_management.adjustment_policies import (
    ADJUSTMENT_CALCULATORS,
    calculate_depreciacion,
    calculate_amortizacion,
    calculate_provision_aguinaldo,
    calculate_provision_vacaciones,
    calculate_provision_ptu,
    calculate_provision_isr,
    calculate_provision_imss,
    calculate_ajuste_inflacion,
    calculate_ajuste_prepagos,
    calculate_ajuste_inventarios,
    calculate_diferencias_cambiarias,
    calculate_provision_incobrables,
    calculate_valuacion_inversiones,
)
from b2b_ai.features.close_management.erp_writer import ERPWriter, ERPWriterError
from b2b_ai.features.close_management.models import (
    AdjustmentPolicy,
    AdjustmentType,
    ChecklistStep,
    ClosePeriod,
    ClosePeriodStatus,
    CloseStepStatus,
    CloseStartRequest,
    ERPType,
    ValidationResult,
    ValidationType,
)
from b2b_ai.features.close_management.validation_engine import ValidationEngine

logger = logging.getLogger(__name__)

# In-memory store (in production, use DB/Redis)
_CLOSES: Dict[str, ClosePeriod] = {}


def _default_checklist() -> List[ChecklistStep]:
    """Generate the default close checklist (17 steps)."""
    return [
        ChecklistStep(step=1, name="CFDIs procesados", is_automatic=True),
        ChecklistStep(step=2, name="Conciliación bancaria completada", is_automatic=True),
        ChecklistStep(step=3, name="Nóminas quincenales registradas", is_automatic=True),
        ChecklistStep(step=4, name="Pólizas cuadradas (debe == haber)", is_automatic=True),
        ChecklistStep(step=5, name="Pre-auditoría fiscal", is_automatic=True),
        ChecklistStep(step=6, name="Depreciaciones del mes", is_automatic=True),
        ChecklistStep(step=7, name="Provisiones laborales (aguinaldo, vacaciones, PTU)", is_automatic=True),
        ChecklistStep(step=8, name="Provisión ISR", is_automatic=True),
        ChecklistStep(step=9, name="Provisión IMSS", is_automatic=True),
        ChecklistStep(step=10, name="Diferencias de cambio", is_automatic=True),
        ChecklistStep(step=11, name="Ajuste por inflación", is_automatic=True),
        ChecklistStep(step=12, name="Ajuste de inventarios", is_automatic=True, requires_approval=True),
        ChecklistStep(step=13, name="Balanza de comprobación", is_automatic=True),
        ChecklistStep(step=14, name="Pólizas de ajuste al ERP", is_automatic=True),
        ChecklistStep(step=15, name="Borrador declaración IVA", is_automatic=True, requires_approval=True),
        ChecklistStep(step=16, name="Borrador declaración ISR provisional", is_automatic=True, requires_approval=True),
        ChecklistStep(step=17, name="Borrador DIOT", is_automatic=True, requires_approval=True),
    ]


class CloseManager:
    """Orchestrates the monthly close process.

    Integrates with:
      - Agente 1 (reconciliación bancaria) for step 2
      - Agente 2 (declaraciones) for steps 15-17
      - ValidationEngine for all validations
      - ERPWriter for posting adjustments
    """

    def __init__(
        self,
        erp_writer: Optional[ERPWriter] = None,
        validation_engine: Optional[ValidationEngine] = None,
        reconciliation_agent: Optional[Any] = None,
        declaraciones_agent: Optional[Any] = None,
    ):
        self.erp_writer = erp_writer or ERPWriter()
        self.validation_engine = validation_engine or ValidationEngine()
        self.reconciliation_agent = reconciliation_agent
        self.declaraciones_agent = declaraciones_agent

    def start_close(self, request: CloseStartRequest) -> ClosePeriod:
        """Start a new monthly close process.

        Creates the checklist and marks the period as in_progress.
        """
        close_id = f"close-{request.periodo}-{uuid.uuid4().hex[:8]}"
        close = ClosePeriod(
            id=close_id,
            periodo=request.periodo,
            tenant_id=request.tenant_id,
            rfc=request.rfc,
            status=ClosePeriodStatus.IN_PROGRESS,
            steps=_default_checklist(),
        )
        close.update_summary()
        _CLOSES[close_id] = close
        logger.info(f"Close started: {close_id} for period {request.periodo}")
        return close

    def get_close(self, close_id: str) -> Optional[ClosePeriod]:
        """Get a close period by ID."""
        return _CLOSES.get(close_id)

    def list_closes(
        self,
        tenant_id: Optional[int] = None,
    ) -> List[ClosePeriod]:
        """List all close periods, optionally filtered by tenant."""
        closes = list(_CLOSES.values())
        if tenant_id is not None:
            closes = [c for c in closes if c.tenant_id == tenant_id]
        return sorted(closes, key=lambda c: c.periodo, reverse=True)

    def approve_step(
        self,
        close_id: str,
        step_num: int,
        approved: bool = True,
        by: str = "contador",
        notes: Optional[str] = None,
    ) -> ClosePeriod:
        """Approve or reject a specific step in the checklist."""
        close = _CLOSES.get(close_id)
        if close is None:
            raise ValueError(f"Close {close_id} not found")

        step = next((s for s in close.steps if s.step == step_num), None)
        if step is None:
            raise ValueError(f"Step {step_num} not found in close {close_id}")

        if approved:
            step.approve(by=by, notes=notes)
        else:
            step.mark_failed(f"Rejected by {by}: {notes or ''}")

        close.update_summary()
        return close

    def run_automatic_steps(
        self,
        close_id: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> ClosePeriod:
        """Execute all automatic close steps.

        Args:
            close_id: The close period ID.
            data: Input data for calculations. Keys:
                - activos: Fixed assets for depreciation
                - intangibles: Intangible assets for amortization
                - empleados: Employee data for labor provisions
                - utilidad_fiscal: Fiscal utility for PTU/ISR
                - cuentas_fx: FX accounts for currency adjustments
                - tc_oficial: Official exchange rate
                - factor_inpc: INPC inflation factor
                - prepagos: Prepaid expenses
                - inventarios: Inventory items for NRV adjustment
                - cartera: Accounts receivable for doubtful accounts
                - nominas: Payroll records
                - balance_data: Trial balance totals
                - iva_data: IVA calculation data
                - reconciliation_data: Bank reconciliation data
                - polizas: Journal entries for validation
        """
        close = _CLOSES.get(close_id)
        if close is None:
            raise ValueError(f"Close {close_id} not found")

        data = data or {}

        # Step 1: CFDIs procesados
        self._run_step(close, 1, self._check_cfdis, data)

        # Step 2: Conciliación bancaria
        self._run_step(close, 2, self._check_conciliacion, data)

        # Step 3: Nóminas registradas
        self._run_step(close, 3, self._check_nominas, data)

        # Step 4: Pólizas cuadradas
        self._run_step(close, 4, self._check_polizas_cuadradas, data)

        # Step 5: Pre-auditoría
        self._run_step(close, 5, self._check_pre_auditoria, data)

        # Step 6: Depreciaciones
        self._run_step(close, 6, self._calc_depreciaciones, data)

        # Step 7: Provisiones laborales
        self._run_step(close, 7, self._calc_provisiones_laborales, data)

        # Step 8: ISR
        self._run_step(close, 8, self._calc_isr, data)

        # Step 9: IMSS
        self._run_step(close, 9, self._calc_imss, data)

        # Step 10: Diferencias cambiarias
        self._run_step(close, 10, self._calc_fx, data)

        # Step 11: Ajuste por inflación
        self._run_step(close, 11, self._calc_inflacion, data)

        # Step 12: Inventarios
        self._run_step(close, 12, self._calc_inventarios, data)

        # Step 13: Balanza
        self._run_step(close, 13, self._gen_balanza, data)

        # Step 14: ERP posting
        self._run_step(close, 14, self._post_to_erp, data)

        # Steps 15-17: Declaration drafts
        self._run_step(close, 15, self._draft_iva, data)
        self._run_step(close, 16, self._draft_isr, data)
        self._run_step(close, 17, self._draft_diot, data)

        # Run validations
        close.validations = self.validation_engine.run_all(
            balance_data=data.get("balance_data"),
            iva_data=data.get("iva_data"),
            isr_data=data.get("isr_data"),
            nominas=data.get("nominas"),
            reconciliation_data=data.get("reconciliation_data"),
            polizas=data.get("polizas"),
        )

        close.update_summary()
        return close

    def finalize(
        self,
        close_id: str,
        closed_by: str = "contador",
        force: bool = False,
    ) -> ClosePeriod:
        """Finalize (close) a period.

        All steps must be approved/skipped, and all validations must pass,
        unless force=True.
        """
        close = _CLOSES.get(close_id)
        if close is None:
            raise ValueError(f"Close {close_id} not found")

        # Check all steps are done
        pending = [
            s for s in close.steps
            if s.status in (CloseStepStatus.PENDING, CloseStepStatus.IN_PROGRESS)
        ]
        if pending and not force:
            raise ValueError(
                f"Cannot close: {len(pending)} steps still pending "
                f"({', '.join(s.name for s in pending[:3])})"
            )

        # Check validations
        if not close.all_validations_passed and not force:
            failed = [v for v in close.validations if not v.passed]
            raise ValueError(
                f"Cannot close: {len(failed)} validations failed "
                f"({', '.join(v.type.value for v in failed[:3])})"
            )

        # Mark all remaining steps as closed
        for step in close.steps:
            if step.status in (
                CloseStepStatus.APPROVED,
                CloseStepStatus.SKIPPED,
            ):
                step.status = CloseStepStatus.CLOSED

        close.status = ClosePeriodStatus.CLOSED
        close.closed_at = datetime.utcnow().isoformat()
        close.closed_by = closed_by
        close.update_summary()

        logger.info(f"Close finalized: {close_id} by {closed_by}")
        return close

    # ------------------------------------------------------------------
    # Internal step runners
    # ------------------------------------------------------------------

    def _run_step(
        self,
        close: ClosePeriod,
        step_num: int,
        fn: Any,
        data: Dict[str, Any],
    ) -> None:
        """Run a single step and handle errors."""
        step = next((s for s in close.steps if s.step == step_num), None)
        if step is None:
            return
        step.mark_started()
        try:
            result = fn(data)
            if result is not None:
                if isinstance(result, dict):
                    step.mark_completed(result)
                else:
                    step.mark_completed({"result": str(result)})
        except Exception as e:
            step.mark_failed(str(e))
            logger.error(f"Step {step_num} ({step.name}) failed: {e}")

    # Step implementations

    def _check_cfdis(self, data: Dict) -> Dict:
        """Step 1: Check CFDIs processed."""
        total = data.get("total_cfdis", 0)
        procesados = data.get("cfdis_procesados", total)
        errors = data.get("cfdis_errors", 0)
        pending = total - procesados
        return {
            "total_cfdis": total,
            "procesados": procesados,
            "errores": errors,
            "pendientes": max(0, pending),
        }

    def _check_conciliacion(self, data: Dict) -> Dict:
        """Step 2: Check bank reconciliation (integrates with Agente 1)."""
        recon = data.get("reconciliation_data", {})
        return {
            "match_rate": recon.get("match_rate", 0.0),
            "total_movements": recon.get("total_movements", 0),
            "matched": recon.get("matched", 0),
            "unmatched": recon.get("unmatched", 0),
            "source": "agente_1" if self.reconciliation_agent else "manual",
        }

    def _check_nominas(self, data: Dict) -> Dict:
        """Step 3: Check payrolls registered."""
        nominas = data.get("nominas_info", {})
        return {
            "quincena_1": nominas.get("q1", {"empleados": 0, "registrada": False}),
            "quincena_2": nominas.get("q2", {"empleados": 0, "registrada": False}),
        }

    def _check_polizas_cuadradas(self, data: Dict) -> Dict:
        """Step 4: Check all polizas balance."""
        polizas = data.get("polizas", [])
        desfase = sum(
            abs(round(p.get("total_debe", 0) - p.get("total_haber", 0), 2))
            for p in polizas
        )
        return {
            "total_polizas": len(polizas),
            "cuadradas": sum(1 for p in polizas if abs(p.get("total_debe", 0) - p.get("total_haber", 0)) < 0.01),
            "desfase": round(desfase, 2),
        }

    def _check_pre_auditoria(self, data: Dict) -> Dict:
        """Step 5: Pre-audit checks."""
        audit = data.get("pre_auditoria", {})
        return {
            "deducibles": audit.get("deducibles", 0),
            "no_deducibles": audit.get("no_deducibles", 0),
            "sin_cfdi": audit.get("sin_cfdi", 0),
            "warnings": audit.get("warnings", []),
        }

    def _calc_depreciaciones(self, data: Dict) -> Dict:
        """Step 6: Calculate depreciation."""
        activos = data.get("activos", [])
        periodo = data.get("periodo", "")
        if activos:
            policy = calculate_depreciacion(activos, periodo)
            data.setdefault("_adjustments", []).append(policy)
            return {
                "activos_depreciados": len(activos),
                "depreciacion_total": policy.total_debe,
            }
        return {"activos_depreciados": 0, "depreciacion_total": 0}

    def _calc_provisiones_laborales(self, data: Dict) -> Dict:
        """Step 7: Calculate labor provisions."""
        empleados = data.get("empleados", [])
        periodo = data.get("periodo", "")
        aguinaldo_amt = vacaciones_amt = ptu_amt = 0.0

        if empleados:
            p_ag = calculate_provision_aguinaldo(empleados, periodo)
            data.setdefault("_adjustments", []).append(p_ag)
            aguinaldo_amt = p_ag.total_debe

            p_vac = calculate_provision_vacaciones(empleados, periodo)
            data.setdefault("_adjustments", []).append(p_vac)
            vacaciones_amt = p_vac.total_debe

        utilidad = data.get("utilidad_fiscal", 0.0)
        if utilidad > 0:
            p_ptu = calculate_provision_ptu(utilidad, periodo)
            data.setdefault("_adjustments", []).append(p_ptu)
            ptu_amt = p_ptu.total_debe

        return {
            "aguinaldo": aguinaldo_amt,
            "vacaciones": vacaciones_amt,
            "ptu": ptu_amt,
        }

    def _calc_isr(self, data: Dict) -> Dict:
        """Step 8: Calculate ISR provision."""
        utilidad = data.get("utilidad_fiscal", 0.0)
        periodo = data.get("periodo", "")
        policy = calculate_provision_isr(utilidad, periodo)
        data.setdefault("_adjustments", []).append(policy)
        return {"isr_provision": policy.total_debe, "utilidad_fiscal": utilidad}

    def _calc_imss(self, data: Dict) -> Dict:
        """Step 9: Calculate IMSS provision."""
        empleados = data.get("empleados_imss", data.get("empleados", []))
        periodo = data.get("periodo", "")
        if empleados:
            policy = calculate_provision_imss(empleados, periodo)
            data.setdefault("_adjustments", []).append(policy)
            return {"imss_total": policy.total_debe, "empleados": len(empleados)}
        return {"imss_total": 0, "empleados": 0}

    def _calc_fx(self, data: Dict) -> Dict:
        """Step 10: Calculate FX adjustments."""
        cuentas_fx = data.get("cuentas_fx", [])
        tc = data.get("tc_oficial", 17.0)
        periodo = data.get("periodo", "")
        if cuentas_fx:
            policy = calculate_diferencias_cambiarias(cuentas_fx, tc, periodo)
            data.setdefault("_adjustments", []).append(policy)
            return {
                "cuentas_en_usd": len(cuentas_fx),
                "tc_oficial": tc,
                "ajuste_total": policy.total_debe,
            }
        return {"cuentas_en_usd": 0, "tc_oficial": tc, "ajuste_total": 0}

    def _calc_inflacion(self, data: Dict) -> Dict:
        """Step 11: Calculate inflation adjustment."""
        saldo = data.get("saldo_acumulado", 0.0)
        factor = data.get("factor_inpc", 0.0)
        periodo = data.get("periodo", "")
        policy = calculate_ajuste_inflacion(saldo, factor, periodo)
        data.setdefault("_adjustments", []).append(policy)
        return {
            "saldo_acumulado": saldo,
            "factor_inpc": factor,
            "ajuste": policy.total_debe,
        }

    def _calc_inventarios(self, data: Dict) -> Dict:
        """Step 12: Calculate inventory adjustments."""
        invs = data.get("inventarios", [])
        periodo = data.get("periodo", "")
        if invs:
            policy = calculate_ajuste_inventarios(invs, periodo)
            data.setdefault("_adjustments", []).append(policy)
            return {
                "articulos_evaluados": len(invs),
                "ajuste_total": policy.total_debe,
            }
        return {"articulos_evaluados": 0, "ajuste_total": 0}

    def _gen_balanza(self, data: Dict) -> Dict:
        """Step 13: Generate trial balance."""
        bal = data.get("balance_data", {})
        total_debe = bal.get("total_debe", 0.0)
        total_haber = bal.get("total_haber", 0.0)
        return {
            "total_debe": total_debe,
            "total_haber": total_haber,
            "cuadrada": abs(total_debe - total_haber) < 1.0,
        }

    def _post_to_erp(self, data: Dict) -> Dict:
        """Step 14: Post adjustments to ERP."""
        adjustments: List[AdjustmentPolicy] = data.get("_adjustments", [])
        if not adjustments:
            return {"posted": 0, "message": "No adjustments to post"}
        try:
            results = self.erp_writer.post_batch(adjustments)
            for adj in adjustments:
                adj.erp_written = True
                adj.status = "posted"
            return {
                "posted": len(results),
                "references": [r.get("reference") for r in results],
            }
        except ERPWriterError as e:
            return {"posted": 0, "error": str(e)}

    def _draft_iva(self, data: Dict) -> Dict:
        """Step 15: Draft IVA declaration (integrates with Agente 2)."""
        iva = data.get("iva_data", {})
        return {
            "iva_trasladado": iva.get("iva_trasladado", 0.0),
            "iva_acreditable": iva.get("iva_acreditable", 0.0),
            "iva_pagar": iva.get("iva_trasladado", 0) - iva.get("iva_acreditable", 0),
            "deadline": f"{data.get('periodo', 'XXXX-XX')[:4]}-{int(data.get('periodo', 'XXXX-XX')[5:7] or 0)+1:02d}-17" if data.get("periodo") else "N/A",
            "source": "agente_2" if self.declaraciones_agent else "manual",
        }

    def _draft_isr(self, data: Dict) -> Dict:
        """Step 16: Draft ISR declaration."""
        isr = data.get("isr_data", {})
        return {
            "ingresos_acumulables": isr.get("ingresos", 0.0),
            "deducciones_autorizadas": isr.get("deducciones", 0.0),
            "utilidad_fiscal": isr.get("utilidad_fiscal", 0.0),
            "isr_pagar": isr.get("isr_provision", 0.0),
            "source": "agente_2" if self.declaraciones_agent else "manual",
        }

    def _draft_diot(self, data: Dict) -> Dict:
        """Step 17: Draft DIOT."""
        diot = data.get("diot_data", {})
        return {
            "operaciones_terceros": diot.get("operaciones", 0),
            "total_operaciones": diot.get("total", 0.0),
            "source": "agente_2" if self.declaraciones_agent else "manual",
        }
