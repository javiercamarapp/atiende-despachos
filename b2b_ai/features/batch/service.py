# -*- coding: utf-8 -*-
"""
service.py — Lógica de negocio del módulo de procesamiento batch de CFDIs.

BatchService:
  - extract_xmls      : extrae CFDIs desde un ZIP de XML o desde un CSV
  - create_job        : crea un BatchJob con sus BatchItems (limites validados)
  - get_job           : consulta estado y progreso
  - process_job       : procesa cada CFDI (parse + compliance) actualizando progreso
  - publish_completed : dispara el webhook cfdi.batch.completed al terminar

Límites (entregable 8):
  - MAX_ITEMS   = 500  CFDIs por batch
  - MAX_UPLOAD  = 10 MB (zip/csv)  — validado en la capa de rutas sobre el bytes
"""
from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from b2b_ai.cfdi.parser import CFDIError, parse_cfdi_4
from b2b_ai.cfdi.validator import SATError, check_cfdi_compliance
from b2b_ai.features.batch.models import BatchItem, BatchItemStatus, BatchJob, BatchJobStatus
from b2b_ai.features.webhooks.models import WebhookEventType
from b2b_ai.features.webhooks.service import WebhookService

logger = logging.getLogger("b2b_ai.batch")

MAX_ITEMS = 500
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_XML_EXTENSIONS = (".xml",)


class BatchLimitError(Exception):
    """Se superó un límite del batch (índice o tamaño)."""


# Store en memoria, coherente con el patrón del módulo de webhooks.
# Tenant-isolated: _jobs[tenant_id][batch_id] — un lote jamás es visible
# para otro tenant (P1-1). La clave tenant_id se deriva SIEMPRE del token
# autenticado (auth_info), nunca del body del cliente.
_jobs: Dict[str, Dict[str, BatchJob]] = {}


def _dec_to_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_item_result(parsed: dict, errors: List[SATError], warnings: List[SATError]) -> dict:
    """Normaliza el resultado por CFDI (misma forma que /validate)."""
    critical = [e for e in errors if e.severity == "error"]
    status = "VALIDO" if not errors else ("INVALIDO" if critical else "CON_OBSERVACIONES")
    emisor = parsed.get("emisor", {}) or {}
    receptor = parsed.get("receptor", {}) or {}
    receptor_rfc = receptor.get("rfc", "") or ""
    diot_reportable = receptor_rfc not in ("XAXX010101000", "XEXX010101000", "")

    return {
        "status": status,
        "ok": status == "VALIDO",
        "comprobante": {
            "serie": parsed.get("serie"),
            "folio": parsed.get("folio"),
            "fecha": parsed.get("fecha"),
            "tipo": parsed.get("tipo_de_comprobante"),
            "moneda": parsed.get("moneda"),
            "total": parsed.get("total"),
            "subtotal": parsed.get("subtotal"),
        },
        "emisor": {
            "rfc": emisor.get("rfc", ""),
            "nombre": emisor.get("nombre"),
            "regimen_fiscal": emisor.get("regimen_fiscal"),
        },
        "receptor": {
            "rfc": receptor.get("rfc", ""),
            "nombre": receptor.get("nombre"),
            "uso_cfdi": receptor.get("uso_cfdi"),
            "diot_reportable": diot_reportable,
        },
        "folio_fiscal": parsed.get("uuid"),
        "fecha_timbrado": parsed.get("fecha_timbrado"),
        "validacion": {
            "ok": status == "VALIDO",
            "checks_pass": len(warnings),
            "checks_fail": len(errors),
            "errores_sat": [
                {"code": e.code, "message": e.message, "field": e.field or ""}
                for e in errors
            ],
            "advertencias_sat": [
                {"code": w.code, "message": w.message, "field": w.field or ""}
                for w in warnings
            ],
        },
    }


class BatchService:
    """Servicio para crear y procesar lotes de CFDIs."""

    def __init__(self, webhook_service: Optional[WebhookService] = None):
        self.webhooks = webhook_service or WebhookService()

    # ------------------------------------------------------------------
    # Extracción de CFDIs desde ZIP / CSV
    # ------------------------------------------------------------------
    def extract_xmls(self, data: bytes, filename: str) -> List[Tuple[str, str]]:
        """Extrae pares (nombre, contenido_xml) desde un ZIP de XML o un CSV.

        - .zip : cada archivo .xml dentro del zip es un CFDI.
        - .csv : cada fila con columna ``xml_content`` (o una única columna
                 con XML) es un CFDI.
        """
        name = (filename or "").lower()
        if name.endswith(".zip"):
            return self._extract_from_zip(data)
        if name.endswith(".csv"):
            return self._extract_from_csv(data)
        raise ValueError(
            "Formato no soportado. Sube un .zip con archivos .xml o un .csv."
        )

    def _extract_from_zip(self, data: bytes) -> List[Tuple[str, str]]:
        pairs: List[Tuple[str, str]] = []
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise ValueError(f"ZIP inválido: {exc}") from exc
        names = sorted(
            n for n in zf.namelist()
            if n.lower().endswith(ALLOWED_XML_EXTENSIONS) and not n.endswith("/")
        )
        for n in names:
            raw = zf.read(n)
            pairs.append((n, raw.decode("utf-8", errors="replace")))
        return pairs

    def _extract_from_csv(self, data: bytes) -> List[Tuple[str, str]]:
        text = data.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            raise ValueError("CSV vacío o sin encabezado.")

        xml_col = None
        for cand in ("xml_content", "xml", "contenido", "content"):
            if cand in reader.fieldnames:
                xml_col = cand
                break

        pairs: List[Tuple[str, str]] = []
        if xml_col:
            for idx, row in enumerate(reader, start=1):
                content = (row.get(xml_col) or "").strip()
                if not content:
                    continue
                pairs.append((f"row_{idx}.xml", content))
            return pairs

        # Sin columna de xml: si hay una sola columna, trátala como XML.
        if len(reader.fieldnames) == 1:
            col = reader.fieldnames[0]
            for idx, row in enumerate(reader, start=1):
                content = (row.get(col) or "").strip()
                if not content:
                    continue
                pairs.append((f"row_{idx}.xml", content))
            return pairs

        raise ValueError(
            "CSV debe contener una columna 'xml_content' (o una única columna con XML)."
        )

    # ------------------------------------------------------------------
    # Creación y consulta de lotes
    # ------------------------------------------------------------------
    def create_job(self, tenant_id: str, xmls: List[Tuple[str, str]]) -> BatchJob:
        """Crea el BatchJob y sus BatchItems. Valida el límite de 500 ítems.

        El job se guarda en el namespace del tenant: _jobs[tenant_id][job.id]
        para garantizar aislamiento entre tenants (P1-1).
        """
        if not xmls:
            raise ValueError("No se encontraron CFDIs en el archivo subido.")
        if len(xmls) > MAX_ITEMS:
            raise BatchLimitError(
                f"El batch supera el límite de {MAX_ITEMS} CFDIs por operación "
                f"(recibidos: {len(xmls)})."
            )
        job = BatchJob(
            status=BatchJobStatus.PENDING,
            total_items=len(xmls),
            items=[
                BatchItem(filename=name)
                for name, _content in xmls
            ],
        )
        # Guardamos el contenido en el item para poder procesar después.
        for item, (_name, content) in zip(job.items, xmls):
            item.result = {"_pending_xml": content}
        _jobs.setdefault(tenant_id, {})[job.id] = job
        logger.info("batch created tenant=%s id=%s items=%d", tenant_id, job.id, job.total_items)
        return job

    def get_job(self, tenant_id: str, job_id: str) -> Optional[BatchJob]:
        """Consulta un job SOLO dentro del namespace del tenant autenticado.

        Un tenant jamás puede leer el job de otro tenant (P1-1).
        """
        return _jobs.get(tenant_id, {}).get(job_id)

    # ------------------------------------------------------------------
    # Procesamiento
    # ------------------------------------------------------------------
    def process_job(self, tenant_id: str, job_id: str) -> BatchJob:
        """Procesa cada CFDI del lote y emite el webhook al terminar.

        Opera únicamente dentro del namespace del tenant autenticado (P1-1).
        """
        job = _jobs.get(tenant_id, {}).get(job_id)
        if job is None:
            raise KeyError(f"Batch job no encontrado: {job_id}")
        if job.status in (BatchJobStatus.COMPLETED, BatchJobStatus.FAILED):
            return job

        job.status = BatchJobStatus.PROCESSING
        for item in job.items:
            item.status = BatchItemStatus.PROCESSING
            content = ""
            if isinstance(item.result, dict):
                content = item.result.pop("_pending_xml", "") or ""
            try:
                parsed = parse_cfdi_4(content)
                errors, warnings = check_cfdi_compliance(parsed)
                item.total = _dec_to_float(parsed.get("total"))
                item.uuid = parsed.get("uuid")
                item.result = _build_item_result(parsed, errors, warnings)
                item.status = BatchItemStatus.SUCCESS
                job.success_count += 1
                if item.total:
                    job.total_amount += item.total
                iva = _dec_to_float(parsed.get("total_impuestos_trasladados"))
                if iva:
                    job.total_iva += iva
            except (CFDIError, Exception) as exc:  # noqa: BLE001 — ítem falla, no el lote
                item.status = BatchItemStatus.FAILED
                item.error = str(exc)
                item.result = None
                job.failed_count += 1
            job.processed_items += 1

        job.completed_at = datetime.utcnow()
        job.status = BatchJobStatus.COMPLETED
        logger.info("batch completed id=%s ok=%d fail=%d",
                    job.id, job.success_count, job.failed_count)

        # Webhook cfdi.batch.completed (entregable 5)
        self.publish_completed(job)
        return job

    def publish_completed(self, job: BatchJob) -> None:
        """Publica el evento cfdi.batch.completed con el resumen del lote."""
        try:
            self.webhooks.publish(
                WebhookEventType.CFDI_BATCH_COMPLETED,
                payload={"batch": job.summary()},
            )
        except Exception as exc:  # noqa: BLE001 — el webhook no debe romper el batch
            logger.warning("batch webhook publish failed job=%s err=%s", job.id, exc)


def reset_state() -> None:
    """Limpia el estado en memoria (uso en tests)."""
    _jobs.clear()
