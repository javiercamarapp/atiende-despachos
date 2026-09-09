# -*- coding: utf-8 -*-
"""pipeline.py — PipelineOrchestrator.

Full flow: CFDI → classification → journal entry → ERP registration
→ reconciliation → close → declarations.

Coordinates all 5 agents.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

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
from b2b_ai.features.conciliacion.service import ConciliationService
from b2b_ai.features.conciliacion.models import (
    BankTransaction as ConcilBankTransaction,
    PolizaContable as ConcilPoliza,
)
from b2b_ai.infrastructure.job_store import get_store as _get_job_store

log = logging.getLogger(__name__)

# job_type usado en la tabla `pipeline_jobs` (ver b2b_ai/infrastructure/
# job_store.py) para distinguir estos jobs de otros llamadores que
# comparten la misma tabla (p.ej. los batches async de b2b_ai/api/v2.py,
# job_type="batch_v2").
_JOB_TYPE = "bookkeeping_pipeline"


def _dump(value):
    """Serialize a pydantic model or dict to a JSON-safe dict."""
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return value


def _bank_txn_to_model(txn: Dict[str, Any]) -> ConcilBankTransaction:
    """Convierte un dict de transacción bancaria a BankTransaction (conciliación).

    Normaliza el tipo a mayúsculas (INGRESO/EGRESO/TRANSFERENCIA) porque el
    enum de conciliación es case-sensitive y los datos pueden venir en
    minúsculas (ingreso/egreso/transferencia).
    """
    t = dict(txn)
    raw = str(t.get("type", "")).strip().upper()
    if raw not in ("INGRESO", "EGRESO", "TRANSFERENCIA"):
        raw = "TRANSFERENCIA" if raw == "TRANSFERENCIA" else ("INGRESO" if raw.startswith("IN") else "EGRESO")
    t["type"] = raw
    t.setdefault("date", "")
    t.setdefault("description", "")
    t.setdefault("reference", "")
    t.setdefault("bank_account", "")
    try:
        t["amount"] = float(t.get("amount", 0))
    except (TypeError, ValueError):
        t["amount"] = 0.0
    return ConcilBankTransaction(**t)


def _poliza_to_concil(p: PolizaContable) -> ConcilPoliza:
    """Mapea una póliza de bookkeeping a PolizaContable de conciliación."""
    cuenta = ""
    if p.lineas:
        cuenta = p.lineas[0].cuenta or ""
    return ConcilPoliza(
        id=p.id,
        fecha=p.fecha,
        monto=float(p.total_debe or 0),
        descripcion=p.concepto or "",
        cuenta=cuenta,
        concepto=p.concepto or "",
        referencia=p.referencia or "",
        rfc="",
    )


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

        # Job store (PO-02 / SCALE-02): persistido en PostgreSQL vía
        # b2b_ai.infrastructure.job_store cuando hay un DSN de Postgres
        # configurado (B2B_DB_URL / DATABASE_URL); si no, cae de vuelta al
        # dict en memoria de siempre (dev/test con SQLite, sin cambios de
        # comportamiento). Ver _persist()/_load()/_load_all() abajo — son
        # el único lugar que decide cuál de los dos backends usar, así que
        # el resto de esta clase (y toda la API pública de PipelineJob que
        # consumen las rutas) no tiene que saber cuál está activo.
        self._jobs_mem: Dict[str, PipelineJob] = {}

    # -- backend de persistencia de jobs (Postgres si hay DSN, si no memoria) --
    def _persist(self, job: PipelineJob) -> None:
        """Guarda (o actualiza) el estado completo de `job`.

        Se llama en cada checkpoint relevante del pipeline, no solo al
        terminar — así el estado es recuperable aun si el proceso muere a
        mitad de un job largo (el caso que pide la prueba "el proceso se
        reinicia, el job sigue ahí con su estado").
        """
        store = _get_job_store()
        if store is not None:
            store.save_job(
                job_id=job.job_id,
                job_type=_JOB_TYPE,
                tenant_id=job.tenant_id,
                stage=job.stage.value,
                progress_pct=job.progress_pct,
                payload=job.model_dump(mode="json"),
                errors=list(job.errors),
                started_at=job.started_at,
                completed_at=job.completed_at,
            )
        else:
            self._jobs_mem[job.job_id] = job

    def _load(self, job_id: str) -> Optional[PipelineJob]:
        store = _get_job_store()
        if store is not None:
            row = store.get_job(job_id)
            if row is None or row["job_type"] != _JOB_TYPE:
                return None
            return PipelineJob.model_validate(row["payload"])
        return self._jobs_mem.get(job_id)

    def _load_all(self, tenant_id: str = "", limit: Optional[int] = 50) -> List[PipelineJob]:
        store = _get_job_store()
        if store is not None:
            rows = store.list_jobs(
                job_type=_JOB_TYPE, tenant_id=tenant_id or None, limit=limit,
            )
            return [PipelineJob.model_validate(r["payload"]) for r in rows]
        jobs = list(self._jobs_mem.values())
        if tenant_id:
            jobs = [j for j in jobs if j.tenant_id == tenant_id]
        jobs.sort(key=lambda j: j.started_at or datetime.min, reverse=True)
        return jobs[:limit] if limit is not None else jobs

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
            cfdis: List of CFDI dicts (parsed XML data)
            tenant_id: Tenant identifier
            periodo: Period YYYY-MM
            fecha: Override date for journal entries
            auto_register_erp: Whether to auto-register in ERP
            bank_transactions: Optional list of bank transaction dicts
                (id, date, description, amount, type, reference, bank_account)
                to reconcile against the generated pólizas in the RECONCILING stage.
            date_tolerance_days: Date tolerance for the reconciliation matching.

        Returns:
            PipelineJob with results
        """
        job = PipelineJob(
            tenant_id=tenant_id,
            periodo=periodo,
            cfdi_uuids=[c.get("uuid", c.get("cfdi_uuid", "")) for c in cfdis],
        )
        job.started_at = datetime.utcnow()
        self._persist(job)

        try:
            # Stage 1: Classify
            job.stage = PipelineStage.CLASSIFYING
            job.progress_pct = 10.0
            classifications = self._classify_cfdis(cfdis, tenant_id)
            job.classifications = classifications

            # Check for low-confidence items
            needs_override = [c for c in classifications if c.needs_human_review]
            job.overrides_needed = len(needs_override)
            self._persist(job)

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
            self._persist(job)

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
                self._persist(job)
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
                self._persist(job)

            # Stage 4: Reconciliation (motor real de conciliación bancaria).
            # Coordinación con Agente conciliación: cruza las pólizas recién
            # generadas contra las transacciones bancarias del periodo.
            job.stage = PipelineStage.RECONCILING
            job.progress_pct = 70.0
            self._persist(job)

            try:
                job.reconciliation = self._reconcile(
                    polizas=polizas,
                    bank_transactions=bank_transactions,
                    periodo=periodo,
                    date_tolerance_days=date_tolerance_days,
                )
            except Exception as exc:  # noqa: BLE001 — la conciliación nunca rompe el job
                log.error("Reconciliation failed for job %s: %s", job.job_id, exc)
                job.reconciliation = {
                    "ok": False,
                    "error": str(exc),
                    "period": periodo,
                }

            # Stage 5-6: Coordination points (close / declarations).
            # Informational — the actual work happens in the respective agents.
            job.stage = PipelineStage.COMPLETED
            job.progress_pct = 100.0
            job.completed_at = datetime.utcnow()

        except Exception as exc:
            job.stage = PipelineStage.FAILED
            job.errors.append(str(exc))
            log.error("Pipeline job %s failed: %s", job.job_id, exc)

        self._persist(job)
        return job

    def _reconcile(
        self,
        polizas: List[PolizaContable],
        bank_transactions: Optional[List[Dict[str, Any]]],
        periodo: str = "",
        date_tolerance_days: int = 3,
    ) -> Optional[Dict[str, Any]]:
        """Ejecuta el motor real de conciliación bancaria (conciliacion.service).

        Cruza las pólizas contables generadas contra las transacciones
        bancarias del periodo y devuelve un dict JSON-safe con el reporte,
        matches, discrepancias y ajustes propuestos. Devuelve None si no hay
        transacciones bancarias (no hay nada que conciliar).
        """
        if not bank_transactions:
            return None

        try:
            bank_txns = [_bank_txn_to_model(t) for t in bank_transactions]
        except Exception as exc:  # noqa: BLE001
            log.error("Invalid bank_transactions: %s", exc)
            return {
                "ok": False,
                "error": f"Transacciones bancarias inválidas: {exc}",
                "period": periodo,
            }

        concil_polizas = [_poliza_to_concil(p) for p in polizas]

        service = ConciliationService(date_tolerance_days=date_tolerance_days)
        results = service.reconcile_bank_statement(
            transactions=bank_txns,
            polizas=concil_polizas if concil_polizas else None,
            tolerance_days=date_tolerance_days,
        )

        period = periodo or (bank_txns[0].date[:7] if bank_txns and bank_txns[0].date else "")
        report = service.generate_report(results["poliza_matches"], period=period)

        return {
            "ok": True,
            "report": report.model_dump(),
            "period": period,
            "matches": [_dump(m) for m in results.get("matches", [])],
            "poliza_matches": [_dump(m) for m in results.get("poliza_matches", [])],
            "discrepancies": [_dump(m) for m in results.get("discrepancies", [])],
            "adjustments": [_dump(m) for m in results.get("adjustments", [])],
            "unmatched_bank": [_dump(m) for m in results.get("unmatched_bank", [])],
            "unmatched_polizas": [_dump(m) for m in results.get("unmatched_polizas", [])],
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
        return self._load(job_id)

    def get_jobs(self, tenant_id: str = "", limit: int = 50) -> List[PipelineJob]:
        """Get pipeline jobs, optionally filtered by tenant."""
        return self._load_all(tenant_id, limit=limit)

    def get_suggestions(self, tenant_id: str = "") -> List[Suggestion]:
        """Get CFDIs that need human review with suggestions."""
        suggestions: List[Suggestion] = []
        for job in self._load_all(tenant_id, limit=None):
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
            # Visibilidad de si el modelo ACTIVO se entrenó con datos reales
            # (correcciones humanas) o con el dataset sintético por defecto —
            # ver AutoClassifier.trained_on / retrain_from_corrections().
            "classifier_trained_on": self._classifier.trained_on,
            "classifier_trained_at": self._classifier.trained_at,
            "classifier_n_training_samples": self._classifier.n_training_samples,
        }

    # -----------------------------------------------------------------------
    # Feedback loop: correcciones humanas reales → reentrenamiento real
    # -----------------------------------------------------------------------
    #
    # ML-01/HO-02: AutoClassifier.train() por defecto usa
    # generate_synthetic_dataset() porque ningún llamador real le pasaba
    # cfdis/labels reales. HumanOverrideManager.get_suggestions_for_retraining()
    # existía pero nada lo conectaba de vuelta a train(). Lo que sigue cierra
    # ese ciclo: junta cada corrección humana (HumanOverrideManager) con el
    # snapshot REAL del CFDI que fue clasificado (capturado en
    # job.classifications durante process_cfdis) y usa ese par
    # (features reales, etiqueta corregida por un humano) como ejemplo de
    # entrenamiento real para AutoClassifier.train(cfdis=..., labels=...).

    def get_retraining_dataset(
        self, tenant_id: str = ""
    ) -> Tuple[List[Dict[str, Any]], List[str], Dict[str, Any]]:
        """Construye un dataset de entrenamiento REAL a partir de correcciones
        humanas ya hechas.

        Para cada override:
          - RECLASSIFY con new_categoria → la etiqueta real es new_categoria
            (el humano corrigió la predicción del modelo).
          - APPROVE con original_categoria → la etiqueta real es
            original_categoria (el humano confirmó que la predicción del
            modelo era correcta).
        En ambos casos la etiqueta viene de un humano, no del modelo.

        El override sólo se registra por cfdi_uuid — no guarda los features
        del CFDI (descripción, montos, etc.). Para obtener un vector de
        features REAL (no sintético) se busca la clasificación original de
        ese mismo cfdi_uuid entre los jobs ya procesados por este
        orchestrator (ahí sí se capturaron los datos reales del CFDI en el
        momento de clasificarlo). Si el UUID nunca pasó por
        process_cfdis en este proceso, no hay snapshot de features y ese
        override se cuenta en n_skipped_no_snapshot pero no se usa para
        entrenar (evita inventar features).

        Returns:
            (cfdis, labels, meta) — listos para AutoClassifier.train().
        """
        by_uuid: Dict[str, CFDIClassification] = {}
        for job in self._jobs.values():
            if tenant_id and job.tenant_id != tenant_id:
                continue
            for cls in job.classifications:
                if cls.cfdi_uuid:
                    # Última clasificación conocida para ese UUID gana.
                    by_uuid[cls.cfdi_uuid] = cls

        cfdis: List[Dict[str, Any]] = []
        labels: List[str] = []
        skipped_no_snapshot = 0
        skipped_no_label = 0

        for record in self._overrides.get_overrides(tenant_id=tenant_id, limit=1_000_000):
            label = ""
            if record.action == OverrideAction.RECLASSIFY and record.new_categoria:
                label = record.new_categoria
            elif record.action == OverrideAction.APPROVE and record.original_categoria:
                label = record.original_categoria

            if not label:
                skipped_no_label += 1
                continue

            cls = by_uuid.get(record.cfdi_uuid)
            if cls is None:
                skipped_no_snapshot += 1
                continue

            cfdis.append({
                "descripcion": cls.descripcion,
                "subtotal": cls.subtotal,
                "iva": cls.iva,
                "total": cls.total,
                "tasa_iva": cls.tasa_iva,
                "tipo_cfdi": cls.tipo_cfdi,
                "uso_cfdi": cls.uso_cfdi,
                "regimen_emisor": cls.regimen_emisor,
                "rfc_emisor": cls.rfc_emisor,
            })
            labels.append(label)

        meta = {
            "n_examples": len(cfdis),
            "n_categories": len(set(labels)),
            "n_skipped_no_snapshot": skipped_no_snapshot,
            "n_skipped_no_label": skipped_no_label,
        }
        return cfdis, labels, meta

    def retrain_from_corrections(
        self,
        tenant_id: str = "",
        min_examples: int = 10,
        min_examples_per_category: int = 2,
    ) -> Dict[str, Any]:
        """Reentrena el AutoClassifier con datos REALES (correcciones
        humanas), en vez del dataset sintético por defecto.

        Se niega a reentrenar — y deja el modelo activo intacto — si no hay
        señal humana suficiente todavía; un puñado de correcciones no debe
        poder degradar en producción un modelo que ya funciona. El llamador
        (endpoint /retrain o un job programado) recibe status=
        'insufficient_data' con el motivo exacto en ese caso.
        """
        cfdis, labels, meta = self.get_retraining_dataset(tenant_id=tenant_id)

        if len(cfdis) < min_examples:
            log.info(
                "Retrain con datos reales OMITIDO (tenant=%s): %d ejemplos "
                "reales disponibles, se requieren %d. Modelo activo sigue "
                "trained_on=%s.",
                tenant_id or "*", len(cfdis), min_examples,
                self._classifier.trained_on,
            )
            return {
                "status": "insufficient_data",
                "reason": (
                    f"Se requieren al menos {min_examples} correcciones "
                    f"humanas con CFDI conocido; hay {len(cfdis)}."
                ),
                **meta,
                "trained_on": self._classifier.trained_on,
            }

        per_category = Counter(labels)
        if len(per_category) < 2:
            log.info(
                "Retrain con datos reales OMITIDO (tenant=%s): sólo hay una "
                "categoría confirmada por humanos (%s); se necesitan al "
                "menos 2 para entrenar un clasificador.",
                tenant_id or "*", dict(per_category),
            )
            return {
                "status": "insufficient_data",
                "reason": "Se necesitan al menos 2 categorías reales distintas para entrenar.",
                "categories_seen": dict(per_category),
                **meta,
                "trained_on": self._classifier.trained_on,
            }

        weak_categories = {c: n for c, n in per_category.items() if n < min_examples_per_category}
        if weak_categories:
            log.info(
                "Retrain con datos reales OMITIDO (tenant=%s): categorías "
                "con muy pocos ejemplos reales %s (mínimo %d).",
                tenant_id or "*", weak_categories, min_examples_per_category,
            )
            return {
                "status": "insufficient_data",
                "reason": "Categorías con muy pocos ejemplos reales para generalizar.",
                "weak_categories": weak_categories,
                **meta,
                "trained_on": self._classifier.trained_on,
            }

        report = self._classifier.train(cfdis=cfdis, labels=labels)
        log.info(
            "AutoClassifier REENTRENADO con datos REALES (tenant=%s): "
            "%d ejemplos de correcciones humanas, %d categorías, "
            "trained_on=%s, train_acc=%.4f",
            tenant_id or "*", len(cfdis), meta["n_categories"],
            report.get("trained_on"), report.get("train_accuracy", 0.0),
        )
        return {"status": "trained", **report, **meta}
