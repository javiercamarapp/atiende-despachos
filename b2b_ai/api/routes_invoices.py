# -*- coding: utf-8 -*-
"""routes_invoices.py — Invoice processing, listing, stats, and legacy routes.

Extracted from app.py to reduce monolith size.
"""
from __future__ import annotations

import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from b2b_ai.cfdi.parser import CFDIError
from b2b_ai.services.pipeline import process_file, process_batch
from b2b_ai.services.report import generate_report
from b2b_ai.tools.registry import all_tools
from b2b_ai.tools.logger import logger
from b2b_ai.api.security import allowed_upload_extension
from b2b_ai.monitoring.metrics import metrics as prom_metrics
from b2b_ai.monitoring.logger import get_logger as get_structured_logger

_structured_log = get_structured_logger("api.routes_invoices")


# -------------------------------------------------------------------------- #
# Cache TTL simple para endpoints de lectura agregados
# -------------------------------------------------------------------------- #
class _StatsCache:
    def __init__(self, ttl_seconds: float = 5.0):
        self.ttl = ttl_seconds
        self._store = {}
        self._lock = threading.Lock()

    def _key(self, dbid, tenant, version, route):
        return (dbid, route, tenant, version)

    def get(self, dbid, route, tenant, version):
        with self._lock:
            item = self._store.get((dbid, route, tenant, version))
        if item is None:
            return None
        ts, value = item
        if time.monotonic() - ts > self.ttl:
            with self._lock:
                self._store.pop((dbid, route, tenant, version), None)
            return None
        return value

    def set(self, dbid, route, tenant, version, value):
        with self._lock:
            self._store[(dbid, route, tenant, version)] = (time.monotonic(), value)

    @property
    def stats(self):
        with self._lock:
            return {"entries": len(self._store), "ttl": self.ttl}


_stats_cache = _StatsCache()


# -------------------------------------------------------------------------- #
# Local path resolution for xml_path / folder params
# -------------------------------------------------------------------------- #
def _allowed_xml_roots() -> list:
    raw = os.environ.get("B2B_LOCAL_XML_DIRS", "").strip()
    if not raw:
        return []
    roots = []
    for part in raw.split(os.pathsep if os.pathsep in raw else ":"):
        part = part.strip()
        if not part:
            continue
        try:
            resolved = Path(part).resolve(strict=False)
        except OSError:
            continue
        if not resolved.is_dir():
            import logging as _log
            _log.getLogger(__name__).warning(
                "B2B_LOCAL_XML_DIRS: skipping non-existent path: %s", part)
            continue
        # Reject paths that look like system directories
        _forbidden = ("/etc", "/sys", "/proc", "/dev", "/boot", "/usr/bin",
                      "/usr/sbin", "/bin", "/sbin", "/var/log")
        if any(str(resolved).startswith(p) for p in _forbidden):
            import logging as _log
            _log.getLogger(__name__).warning(
                "B2B_LOCAL_XML_DIRS: refusing dangerous path: %s", part)
            continue
        roots.append(resolved)
    return roots


def _resolve_local_path(candidate: str, want_dir: bool = False) -> Path:
    """Resuelve una ruta local del cliente dentro de los roots permitidos.

    Lanza HTTPException 400 si la ingesta local está desactivada, 403 si la
    ruta cae fuera de los roots y 404 si no existe. Resuelve symlinks antes de
    comparar, de modo que un enlace dentro de un root no sirve para escapar.
    """
    roots = _allowed_xml_roots()
    if not roots:
        raise HTTPException(
            status_code=400,
            detail="La ingesta por ruta local está desactivada. Suba el archivo "
                   "como multipart (campo xml_file) o configure "
                   "B2B_LOCAL_XML_DIRS en el servidor.")
    try:
        target = Path(candidate).resolve(strict=False)
    except (OSError, ValueError):
        raise HTTPException(status_code=400, detail="Ruta inválida.")
    if not any(target == r or r in target.parents for r in roots):
        raise HTTPException(
            status_code=403,
            detail="Ruta fuera de los directorios permitidos.")
    if want_dir:
        if not target.is_dir():
            raise HTTPException(status_code=404, detail="Carpeta no encontrada.")
    elif not target.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado.")
    return target


# ---- Schemas --------------------------------------------------------------- #
class ProcessRequest(BaseModel):
    xml_path: Optional[str] = None
    folder: Optional[str] = None
    tenant_id: Optional[int] = None
    tenant_name: str = ""
    tenant_rfc: str = ""


# ---- Helpers --------------------------------------------------------------- #
def _scope(info):
    """Devuelve el tenant_id efectivo a usar según la key."""
    return info.get("tenant_id")


def _strip(res):
    """Quita campos voluminosos para la respuesta JSON."""
    return {
        "archivo": res["archivo"],
        "valido": res["validacion"]["ok"],
        "requires_human_review": res["validacion"]["requires_human_review"],
        "categoria": res["clasificacion"]["categoria"],
        "confianza": res["clasificacion"]["confianza"],
        "erp_poliza": res["erp"].get("poliza"),
        "erp_status": res["erp"].get("status"),
        "insertado": res["insertado"],
        "total": res["datos"].get("total"),
        "emisor": res["datos"].get("emisor_rfc"),
        "notificacion": res["notificacion"].get("status"),
    }


def _record_business_metrics(res):
    """Incrementa métricas de negocio (invoices_processed / anomalies_detected)
    a partir del resultado del pipeline. Nunca rompe el flujo si algo falla."""
    try:
        if res.get("validacion", {}).get("ok"):
            prom_metrics.inc_invoices(1)
        n_anomalias = len(res.get("anomalias") or [])
        if n_anomalias:
            prom_metrics.inc_anomalies(n_anomalias)
    except Exception:  # noqa: BLE001
        _structured_log.exception("fallo al registrar métricas de negocio")


# -------------------------------------------------------------------------- #
# Router builder
# -------------------------------------------------------------------------- #
def build_invoices_router(db, require_api_key) -> APIRouter:
    """Build the invoices router.

    Endpoints:
        POST /api/v1/invoices/process
        GET  /api/v1/invoices
        GET  /api/v1/invoices/{invoice_id}
        GET  /api/v1/stats
        GET  /invoices        (legacy, deprecated)
        GET  /stats           (legacy, deprecated)
        POST /process         (legacy, deprecated)
    """
    router = APIRouter()

    # ---- API v1 ---- #

    @router.post("/api/v1/invoices/process",
                 summary="Procesa un CFDI (XML) por el pipeline completo.",
                 tags=["invoices"])
    async def process_invoice(
        request: Request,
        auth_info: dict = Depends(require_api_key),
    ):
        """Recibe el XML de un CFDI — como subida multipart (campo xml_file)
        o como JSON con xml_path — y devuelve el resultado del pipeline:
        validación, clasificación, póliza ERP y el id de la factura en la DB."""
        tenant = _scope(auth_info)
        content_type = request.headers.get("content-type", "")

        # 1) Multipart → archivo subido
        if "multipart/form-data" in content_type:
            form = await request.form()
            up = form.get("xml_file")
            if up is None or not getattr(up, "filename", None):
                raise HTTPException(400, "Debe enviar xml_file (multipart).")
            if not allowed_upload_extension(up.filename):
                raise HTTPException(
                    422, "Solo se aceptan archivos CFDI .xml o .pdf.")
            content = await up.read()
            if not content.strip():
                raise HTTPException(400, "Archivo XML vacío.")
            suffix = os.path.splitext(up.filename)[1] or ".xml"
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            try:
                tmp.write(content)
                tmp.close()
                try:
                    res = process_file(tmp.name, db=db, tenant_id=tenant)
                except CFDIError as e:
                    raise HTTPException(status_code=422,
                                        detail=f"CFDI inválido: {e}")
            finally:
                tmp.close()
                os.unlink(tmp.name)
            _record_business_metrics(res)
            return {"result": _strip(res)}

        # 2) JSON → xml_path (o folder)
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            raise HTTPException(400, "Body inválido. Use multipart o JSON con xml_path.")
        xml_path = (payload or {}).get("xml_path")
        if xml_path:
            safe = _resolve_local_path(str(xml_path))
            try:
                res = process_file(str(safe), db=db, tenant_id=tenant)
            except CFDIError as e:
                raise HTTPException(status_code=422,
                                    detail=f"CFDI inválido: {e}")
            _record_business_metrics(res)
            return {"result": _strip(res)}
        raise HTTPException(status_code=400,
                            detail="Debe enviar xml_file (multipart) o xml_path.")

    @router.get("/api/v1/invoices",
                summary="Lista facturas con filtros.",
                tags=["invoices"])
    def list_invoices(
        auth_info: dict = Depends(require_api_key),
        tenant_id: Optional[int] = Query(default=None),
        categoria: Optional[str] = Query(default=None),
        valido: Optional[bool] = Query(default=None),
        fecha_desde: Optional[str] = Query(default=None),
        fecha_hasta: Optional[str] = Query(default=None),
        limit: int = Query(default=100, ge=1, le=1000),
    ):
        tenant = _scope(auth_info) or tenant_id
        invoices = db.list_invoices(tenant_id=tenant, limit=limit,
                                    categoria=categoria, valido=valido,
                                    fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)
        return {"count": len(invoices), "tenant_id": tenant, "invoices": invoices}

    @router.get("/api/v1/invoices/{invoice_id}",
                summary="Detalle de una factura por id.",
                tags=["invoices"])
    def get_invoice(invoice_id: int, auth_info: dict = Depends(require_api_key)):
        tenant = _scope(auth_info)
        inv = db.get_invoice(invoice_id, tenant_id=tenant)
        if inv is None:
            raise HTTPException(status_code=404, detail="Factura no encontrada.")
        return {"invoice": inv}

    @router.get("/api/v1/stats",
                summary="Métricas agregadas (totales y por categoría).",
                tags=["stats"])
    def stats(auth_info: dict = Depends(require_api_key)):
        tenant = _scope(auth_info)
        cached = _stats_cache.get(id(db), "v1_stats", tenant, db.data_version())
        if cached is not None:
            return cached
        invoices = db.list_invoices(tenant_id=tenant)
        report = generate_report(invoices)
        stats_res = db.invoice_stats(tenant_id=tenant)
        result = {
            **stats_res,
            "tenants": db.list_tenants(),
            "audit_calls": db.count_audit(),
            "notifications": len(db.list_notifications()),
            "report": report,
            "tools_registered": [t.name for t in all_tools()],
        }
        _stats_cache.set(id(db), "v1_stats", tenant, db.data_version(), result)
        return result

    # ---- Legacy endpoints (compatibilidad, deprecated) ---- #

    @router.get("/invoices", deprecated=True,
                description="DEPRECATED: use GET /api/v1/invoices instead.")
    def invoices_legacy(tenant_id: Optional[int] = Query(default=None),
                        limit: int = Query(default=100, le=1000),
                        auth_info: dict = Depends(require_api_key)):
        tenant = _scope(auth_info) or tenant_id
        return {"count": len(db.list_invoices(tenant_id=tenant, limit=limit)),
                "invoices": db.list_invoices(tenant_id=tenant, limit=limit)}

    @router.get("/stats", deprecated=True,
                description="DEPRECATED: use GET /api/v1/stats instead.")
    def stats_legacy(auth_info: dict = Depends(require_api_key)):
        tenant = _scope(auth_info)
        cached = _stats_cache.get(id(db), "legacy_stats", tenant, db.data_version())
        if cached is not None:
            return cached
        invoices = db.list_invoices(tenant_id=tenant)
        report = generate_report(invoices)
        result = {
            "invoices_total": len(invoices),
            "tenants": db.list_tenants(),
            "audit_calls": db.count_audit(),
            "notifications": len(db.list_notifications()),
            "report": report,
            "tools_registered": [t.name for t in all_tools()],
        }
        _stats_cache.set(id(db), "legacy_stats", tenant, db.data_version(), result)
        return result

    @router.post("/process", deprecated=True,
                 description="DEPRECATED: use POST /api/v1/invoices/process instead.")
    def process_legacy(req: ProcessRequest,
                       auth_info: dict = Depends(require_api_key)):
        tenant = _scope(auth_info) or req.tenant_id
        try:
            if req.xml_path:
                safe = _resolve_local_path(str(req.xml_path))
                res = process_file(str(safe), db=db, tenant_id=tenant)
                return {"result": _strip(res)}
            if req.folder:
                safe_dir = _resolve_local_path(str(req.folder), want_dir=True)
                results = process_batch(str(safe_dir), db=db, tenant_id=tenant)
                from b2b_ai.services.pipeline import summarize
                return {"summary": summarize(results),
                        "results": [_strip(r) for r in results]}
        except CFDIError as e:
            raise HTTPException(status_code=422,
                                detail=f"CFDI inválido: {e}")
        raise HTTPException(status_code=400,
                            detail="Debe indicar xml_path o folder.")

    @router.get("/tools", deprecated=True,
                description="DEPRECATED: use GET /api/v1/tools instead.")
    def tools_legacy(auth_info: dict = Depends(require_api_key)):
        return {"tools": [t.to_dict() for t in all_tools()]}

    return router
