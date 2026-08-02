# -*- coding: utf-8 -*-
"""
orchestrator.py — Orquestador end-to-end del flujo:
CFDI upload → parse → adapt → bookkeeping entries → conciliación bancaria.

Cablea los bloques que antes estaban desconectados:
  1. parse:        b2b_ai.cfdi.parser.parse_cfdi_4
  2. adapt:        b2b_ai.cfdi.adapter.to_bookkeeping_format
  3. bookkeeping:  b2b_ai.features.bookkeeping.pipeline.PipelineOrchestrator
  4. conciliación: motor real de conciliación (conciliacion.service) vía la
                   etapa RECONCILING del pipeline.

Expone `upload_cfdis(xml_files, tenant_id)` que devuelve un dict con el
estado completo del flujo (status + resultados de cada etapa).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from b2b_ai.cfdi.adapter import to_bookkeeping_format
from b2b_ai.cfdi.parser import CFDIError, parse_cfdi_4
from b2b_ai.features.bookkeeping.pipeline import PipelineOrchestrator as BkPipeline

log = logging.getLogger(__name__)


class EndToEndPipelineError(Exception):
    """Error de nivel del orquestador (parse / adaptación)."""


class EndToEndOrchestrator:
    """Orquesta el flujo completo CFDI → bookkeeping → conciliación."""

    def __init__(
        self,
        bookkeeping_pipeline: Optional[BkPipeline] = None,
    ):
        self._bookkeeping = bookkeeping_pipeline or BkPipeline()

    @property
    def bookkeeping(self) -> BkPipeline:
        """Acceso al pipeline de bookkeeping subyacente (tests / inyección)."""
        return self._bookkeeping

    # ------------------------------------------------------------------
    # Etapa 1 + 2: parse y adaptación de CFDIs
    # ------------------------------------------------------------------
    def parse_and_adapt(self, xml_files: List[Tuple[str, str]]) -> Dict[str, Any]:
        """Parsea y adapta una lista de (nombre, contenido_xml).

        Devuelve dict con `cfdis` (adaptados al formato de bookkeeping) y
        `errors` (por archivo que no parsea, sin abortar el lote).
        """
        cfdis: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []

        for name, content in xml_files or []:
            try:
                parsed = parse_cfdi_4(content)
            except CFDIError as exc:
                errors.append({"file": name, "error": str(exc)})
                continue
            except Exception as exc:  # noqa: BLE001 — un CFDI malo no rompe el lote
                log.warning("Unexpected parse error for %s: %s", name, exc)
                errors.append({"file": name, "error": str(exc)})
                continue
            cfdis.append(to_bookkeeping_format(parsed))

        return {"cfdis": cfdis, "errors": errors}

    # ------------------------------------------------------------------
    # Flujo completo
    # ------------------------------------------------------------------
    def upload_cfdis(
        self,
        xml_files: List[Tuple[str, str]],
        tenant_id: str = "",
        periodo: str = "",
        fecha: Optional[str] = None,
        auto_register_erp: bool = True,
        bank_transactions: Optional[List[Dict[str, Any]]] = None,
        date_tolerance_days: int = 3,
    ) -> Dict[str, Any]:
        """Flujo end-to-end: parse → adapt → generate_entries → reconcile.

        Args:
            xml_files: List[(nombre, contenido_xml)].
            tenant_id: Tenant autenticado.
            periodo: Periodo YYYY-MM.
            fecha: Fecha override de las pólizas.
            auto_register_erp: Registrar en ERP (mock por defecto).
            bank_transactions: Transacciones bancarias para conciliar.
            date_tolerance_days: Tolerancia del matching bancario.

        Returns:
            dict con status, resultados por etapa y errores.
        """
        if not xml_files:
            raise EndToEndPipelineError("No se recibieron archivos XML para procesar.")

        # Etapa 1+2: parse + adapt.
        parsed = self.parse_and_adapt(xml_files)
        cfdis = parsed["cfdis"]
        parse_errors = parsed["errors"]

        if not cfdis:
            return {
                "status": "failed",
                "stage": "parse",
                "cfdis_parsed": 0,
                "cfdis_adapted": 0,
                "errors": parse_errors or ["Ningún CFDI pudo parsearse."],
                "reconciliation": None,
            }

        # Etapa 3+4: bookkeeping (incluye conciliación real en RECONCILING).
        job = self._bookkeeping.process_cfdis(
            cfdis=cfdis,
            tenant_id=tenant_id,
            periodo=periodo,
            fecha=fecha,
            auto_register_erp=auto_register_erp,
            bank_transactions=bank_transactions,
            date_tolerance_days=date_tolerance_days,
        )

        return {
            "status": job.stage.value,
            "stage": job.stage.value,
            "job_id": job.job_id,
            "cfdis_parsed": len(cfdis),
            "cfdis_adapted": len(cfdis),
            "parse_errors": parse_errors,
            "classifications_count": len(job.classifications),
            "polizas_count": len(job.polizas),
            "erp_references": job.erp_references,
            "overrides_needed": job.overrides_needed,
            "errors": job.errors,
            "reconciliation": job.reconciliation,
        }


__all__ = ["EndToEndOrchestrator", "EndToEndPipelineError"]
