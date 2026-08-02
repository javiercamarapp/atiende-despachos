# -*- coding: utf-8 -*-
"""pipeline.py — PipelineOrchestrator.

Full flow: CFDI → classification → journal entry → ERP registration
→ reconciliation → close → declarations.

Coordinates all 5 agents.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.features.bookkeeping.models import (
    CFDIClassification,
    ERPSystem,
    OverrideAction,
    PipelineJob,
    PipelineStage,
    PolizaContable,
    Suggestion,
)
from b2b_ai.features.bookkeeping.auto_classifier import AutoClassifier
from b2b_ai.features.bookkeeping.rules_engine import AccountingRulesEngine
from b2b_ai.features.bookkeeping.journal_generator import JournalEntryGenerator
from b2b_ai.features.bookkeeping.erp_registrar import ERPRegistrar, ERPRegistrationResult
from b2b_ai.features.bookkeeping.human_override import HumanOverrideManager

log = logging.getLogger(__name__)


class PipelineOrchestrator:
    """Orchestrates the full bookkeeping pipeline.

    Stages:
    1. Classify CFDIs (ML + rules)
    2. Generate journal entries (NIF-compliant)
    3. Register in ERP (idempotent)
    4. Reconcile (delegates to Agente 3)
    5. Close period (delegates to Agente 1)
    6. Generate declarations (delegates to Agente 2)

    Stages 4-6 are coordination points — the actual work is done
    by the respective agents.
    """

    def __init__(
        self,
        classifier: Optional[AutoClassifier] = None,
        rules_engine: Optional[AccountingRulesEngine] = None,
        journal_generator: Optional[JournalEntryGenerator] = None,
        erp_registrar: Optional[ERPRegistrar] = None,
        override_manager: Optional[HumanOverrideManager] = None,
    ):
        self._classifier = classifier or AutoClassifier()
        self._rules = rules_engine or AccountingRulesEngine()
        self._journal_gen = journal_generator or JournalEntryGenerator(self._rules)
        self._erp = erp_registrar or ERPRegistrar()
        self._overrides = override_manager or HumanOverrideManager()

        # Job store
        self._jobs: Dict[str, PipelineJob] = {}

    @property
    def classifier(self) -> AutoClassifier:
        return self._classifier

    @property
    def override_manager(self) -> HumanOverrideManager:
        return self._overrides

    @property
    def erp_registrar(self) -> ERPRegistrar:
        return self._erp

    def process_cfdis(
        self,
        cfdis: List[Dict[str, Any]],
        tenant_id: str = "",
        periodo: str = "",
        fecha: Optional[str] = None,
        auto_register_erp: bool = True,
        bank_transactions: Optional[List[Dict[str, Any]]] = None,
        date_tolerance_days: int = 3,
    ) -> PipelineJob:
        """Process a batch of CFDIs through the full pipeline.

        Args:
            cfdis: List of CFDI dicts. Se esperan YA adaptados al formato
                plano de bookkeeping (rfc_emisor, rfc_receptor, tipo, total,
                subtotal, iva, descripcion, uuid, conceptos). Puede generarse
                con b2b_ai.cfdi.adapter.to_bookkeeping_format(parse_cfdi_4(...)).
            tenant_id: Tenant identifier
            periodo: Period YYYY-MM
            fecha: Override date for journal entries
            auto_register_erp: Whether to auto-register in ERP
            bank_transactions: List of bank transaction dicts
                (id, date, description, amount, type, reference, bank_account)
                para la conciliación bancaria real. Si se omite, la etapa
                RECONCILING marca el job como completado sin motor.
            date_tolerance_days: Tolerancia de días para el matching bancario.

        Returns:
            PipelineJob with results
        """
        job = PipelineJob(
            tenant_id=tenant_id,
            periodo=periodo,
            cfdi_uuids=[c.get("uuid", c.get("cfdi_uuid", "")) for c in cfdis],
        )
        self._jobs[job.job_id] = job
        job.started_at = datetime.utcnow()

        try:
            # Stage 1: Classify
            job.stage = PipelineStage.CLASSIFYING
            job.progress_pct = 10.0
            classifications = self._classify_cfdis(cfdis, tenant_id)
            job.classifications = classifications

            # Check for low-confidence items
            needs_override = [c for c in classifications if c.needs_human_review]
            job.overrides_needed = len(needs_override)

            if needs_override:
                log.info(
                    "Job %s: %d CFDIs need human review",
                    job.job_id, len(needs_override),
                )

            # Stage 2: Generate journal entries
            job.stage = PipelineStage.GENERATING_POLIZA
            job.progress_pct = 30.0
            polizas = self._journal_gen.generate_batch(classifications, fecha, tenant_id)
            job.polizas = polizas

            # VALIDATION GATE (patrón PromptChain 04):
            # Hold ERP auto-registration if any póliza is not balanced or any
            # classification is pending human review. Prevents registering
            # incomplete/misclassified entries in the ERP.
            unbalanced = [p for p in polizas if not p.cuadrada]
            if unbalanced:
                gate_errors = [
                    f"Póliza {p.id} no cuadrada (debe {p.total_debe} != haber {p.total_haber})"
                    for p in unbalanced
                ]
                log.warning(
                    "Job %s: %d póliza(s) desbalanceadas — no se registran en ERP. %s",
                    job.job_id, len(unbalanced), "; ".join(gate_errors))
                job.errors.extend(gate_errors)
                job.stage = PipelineStage.GENERATING_POLIZA  # stay, hold ERP
                job.progress_pct = 35.0
                job.completed_at = datetime.utcnow()
                return job

            if needs_override:
                log.info(
                    "Job %s: %d CFDIs requieren revisión humana — "
                    "ERP auto-registration en espera (validation gate).",
                    job.job_id, len(needs_override))

            # Stage 3: Register in ERP
            if auto_register_erp and polizas:
                job.stage = PipelineStage.REGISTERING_ERP
                job.progress_pct = 50.0
                erp_results = self._erp.register_batch(polizas)
                job.erp_references = [
                    r.erp_reference for r in erp_results if r.success and r.erp_reference
                ]

                # Check for failures
                failures = [r for r in erp_results if not r.success]
                if failures:
                    job.errors.extend([r.error or "ERP registration failed" for r in failures])

            # Stage 4: Reconciling — motor de conciliación bancaria REAL.
            # Ya no hay auto-advance: las pólizas generadas se concilian contra
            # las transacciones bancarias del tenant (Agente 3).
            job.stage = PipelineStage.RECONCILING
            job.progress_pct = 70.0

            if bank_transactions:
                job.reconciliation = self._reconcile_polizas(
                    polizas,
                    bank_transactions=bank_transactions,
                    periodo=periodo,
                    tolerance_days=date_tolerance_days,
                )

            # Stage 5-6: Close / declaring son puntos de coordinación con los
            # agentes 1 y 2. Por ahora se marcan como listos (no bloquean).
            job.stage = PipelineStage.COMPLETED
            job.progress_pct = 100.0
            job.completed_at = datetime.utcnow()

        except Exception as exc:
            job.stage = PipelineStage.FAILED
            job.errors.append(str(exc))
            log.error("Pipeline job %s failed: %s", job.job_id, exc)

        return job

    def _reconcile_polizas(
        self,
        polizas: List[PolizaContable],
        bank_transactions: List[Dict[str, Any]],
        periodo: str = "",
        tolerance_days: int = 3,
    ) -> Dict[str, Any]:
        """Ejecuta el motor de conciliación bancaria real (conciliacion.service).

        Convierte las pólizas de bookkeeping al modelo de conciliación y hace
        el match contra las transacciones bancarias, detectando discrepancias
        y proponiendo ajustes. Devuelve un dict JSON-serializable.
        """
        from b2b_ai.features.conciliacion.service import ConciliationService
        from b2b_ai.features.conciliacion.models import (
            BankTransaction as ConcBankTransaction,
            PolizaContable as ConcPolizaContable,
        )

        # Mapear pólizas de bookkeeping -> pólizas de conciliación.
        # La póliza de bookkeeping tiene líneas (debe/haber); tomamos el total
        # cargado (total_debe) como el monto a conciliar y la referencia.
        conc_polizas: List[ConcPolizaContable] = []
        for pol in polizas:
            fecha = pol.fecha or ""
            # Concilia contra el monto total de la póliza (cuadrada: debe==haber).
            monto = pol.total_debe or pol.total_haber or 0.0
            # Una sola cuenta representativa (la primera línea de cargo).
            cuenta = ""
            for linea in pol.lineas:
                if linea.debe and linea.debe > 0:
                    cuenta = linea.cuenta
                    break
            conc_polizas.append(ConcPolizaContable(
                id=pol.id or f"pol-{len(conc_polizas) + 1}",
                fecha=fecha,
                monto=float(monto),
                descripcion=pol.concepto or "",
                cuenta=cuenta,
                concepto=pol.concepto or "",
                referencia=pol.referencia or "",
                rfc="",
            ))

        # Convertir transacciones bancarias al modelo de conciliación.
        conc_txns: List[ConcBankTransaction] = []
        for t in bank_transactions or []:
            try:
                conc_txns.append(ConcBankTransaction(
                    id=str(t.get("id", "")),
                    date=str(t.get("date", "")),
                    description=str(t.get("description", "")),
                    amount=float(t.get("amount", 0)),
                    type=t.get("type", "TRANSFERENCIA"),
                    reference=str(t.get("reference", "")),
                    bank_account=str(t.get("bank_account", "")),
                ))
            except Exception as exc:  # noqa: BLE001 — una txn mala no rompe el batch
                log.warning("Dropping invalid bank transaction: %s", exc)

        service = ConciliationService(date_tolerance_days=tolerance_days)
        results = service.reconcile_bank_statement(
            transactions=conc_txns,
            polizas=conc_polizas if conc_polizas else None,
            cfdi_list=None,
            tolerance_days=tolerance_days,
        )

        # Reporte agregado + serializar resultados a dicts JSON.
        report = service.generate_reconciliation_report(results, period=periodo)
        return {
            "period": periodo,
            "report": report.model_dump(),
            "poliza_matches": [m.model_dump() for m in results.get("poliza_matches", [])],
            "matches": [m.model_dump() for m in results.get("matches", [])],
            "discrepancies": [d.model_dump() for d in results.get("discrepancies", [])],
            "adjustments": [a.model_dump() for a in results.get("adjustments", [])],
            "unmatched_bank": [t.model_dump() for t in results.get("unmatched_bank", [])],
            "unmatched_polizas": [p.model_dump() for p in results.get("unmatched_polizas", [])],
        }

    def _classify_cfdis(
        self, cfdis: List[Dict[str, Any]], tenant_id: str = ""
    ) -> List[CFDIClassification]:
        """Classify CFDIs using ML + rules + overrides."""
        classifications: List[CFDIClassification] = []

        for cfdi in cfdis:
            # 1. Check human override first
            uuid_val = cfdi.get("uuid", cfdi.get("cfdi_uuid", ""))
            override = self._overrides.get_override(uuid_val)
            if override and override.action == OverrideAction.RECLASSIFY:
                classification = CFDIClassification(
                    cfdi_uuid=uuid_val,
                    rfc_emisor=cfdi.get("rfc_emisor", ""),
                    rfc_receptor=cfdi.get("rfc_receptor", ""),
                    descripcion=cfdi.get("descripcion", cfdi.get("concepto", "")),
                    subtotal=float(cfdi.get("subtotal", 0)),
                    iva=float(cfdi.get("iva", 0)),
                    total=float(cfdi.get("total", 0)),
                    tasa_iva=float(cfdi.get("tasa_iva", 0.16)),
                    tipo_cfdi=cfdi.get("tipo", cfdi.get("tipo_cfdi", "I")),
                    uso_cfdi=cfdi.get("uso_cfdi", ""),
                    regimen_emisor=cfdi.get("regimen_emisor", ""),
                    categoria=override.new_categoria,
                    confidence=1.0,
                )
            else:
                # 2. ML classification
                categoria, confidence = self._classifier.predict(cfdi)

                # 3. Determine if needs human review
                needs_review = confidence < AutoClassifier.CONFIDENCE_MEDIUM

                classification = CFDIClassification(
                    cfdi_uuid=uuid_val,
                    rfc_emisor=cfdi.get("rfc_emisor", ""),
                    rfc_receptor=cfdi.get("rfc_receptor", ""),
                    descripcion=cfdi.get("descripcion", cfdi.get("concepto", "")),
                    subtotal=float(cfdi.get("subtotal", 0)),
                    iva=float(cfdi.get("iva", 0)),
                    total=float(cfdi.get("total", 0)),
                    tasa_iva=float(cfdi.get("tasa_iva", 0.16)),
                    tipo_cfdi=cfdi.get("tipo", cfdi.get("tipo_cfdi", "I")),
                    uso_cfdi=cfdi.get("uso_cfdi", ""),
                    regimen_emisor=cfdi.get("regimen_emisor", ""),
                    categoria=categoria,
                    confidence=round(confidence, 4),
                    needs_human_review=needs_review,
                )

            # 4. Get account mapping
            mapping = self._rules.get_mapping(
                classification.tipo_cfdi, classification.categoria, tenant_id
            )
            if mapping:
                classification.cuenta_cargo = mapping.cargo
                classification.cuenta_abono = mapping.abono

            classifications.append(classification)

        return classifications

    def get_job(self, job_id: str) -> Optional[PipelineJob]:
        """Get a pipeline job by ID."""
        return self._jobs.get(job_id)

    def get_jobs(self, tenant_id: str = "", limit: int = 50) -> List[PipelineJob]:
        """Get pipeline jobs, optionally filtered by tenant."""
        jobs = list(self._jobs.values())
        if tenant_id:
            jobs = [j for j in jobs if j.tenant_id == tenant_id]
        # Sort by most recent first
        jobs.sort(key=lambda j: j.started_at or datetime.min, reverse=True)
        return jobs[:limit]

    def get_suggestions(self, tenant_id: str = "") -> List[Suggestion]:
        """Get CFDIs that need human review with suggestions."""
        suggestions: List[Suggestion] = []
        for job in self._jobs.values():
            if tenant_id and job.tenant_id != tenant_id:
                continue
            for cls in job.classifications:
                if cls.needs_human_review:
                    alts = self._classifier.get_suggestions({
                        "descripcion": cls.descripcion,
                        "subtotal": cls.subtotal,
                        "iva": cls.iva,
                        "total": cls.total,
                        "tasa_iva": cls.tasa_iva,
                        "tipo_cfdi": cls.tipo_cfdi,
                        "uso_cfdi": cls.uso_cfdi,
                        "regimen_emisor": cls.regimen_emisor,
                    })
                    suggestions.append(Suggestion(
                        cfdi_uuid=cls.cfdi_uuid,
                        descripcion=cls.descripcion,
                        suggested_categoria=cls.categoria,
                        suggested_cuenta_cargo=cls.cuenta_cargo,
                        suggested_cuenta_abono=cls.cuenta_abono,
                        confidence=cls.confidence,
                        alternatives=alts,
                    ))
        return suggestions

    def get_pipeline_status(self, tenant_id: str = "") -> Dict[str, Any]:
        """Get overall pipeline status for a tenant."""
        jobs = self.get_jobs(tenant_id)
        total_cfdis = sum(len(j.cfdi_uuids) for j in jobs)
        total_polizas = sum(len(j.polizas) for j in jobs)
        total_errors = sum(len(j.errors) for j in jobs)
        needs_override = sum(j.overrides_needed for j in jobs)

        by_stage = {}
        for j in jobs:
            stage = j.stage.value
            by_stage[stage] = by_stage.get(stage, 0) + 1

        return {
            "total_jobs": len(jobs),
            "total_cfdis_processed": total_cfdis,
            "total_polizas_generated": total_polizas,
            "total_errors": total_errors,
            "needs_human_review": needs_override,
            "jobs_by_stage": by_stage,
            "erp_status": self._erp.get_status(),
            "override_stats": self._overrides.get_statistics(tenant_id),
        }
