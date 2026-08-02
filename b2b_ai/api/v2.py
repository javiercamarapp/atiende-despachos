# -*- coding: utf-8 -*-
"""
v2.py — API v2 enterprise: multi-tenant robusto (Billion Company).

Agrega a /api/v1 los endpoints de escala:

    POST /api/v2/batch         procesamiento masivo de CFDI (≤1000/lote),
                               síncrono o async (job + polling).
    GET  /api/v2/batch/{id}    estado/resultado de un lote async.
    GET  /api/v2/analytics     analytics avanzado por tenant (cache TTL).
    POST /api/v2/webhooks      registrar webhooks por evento.
    GET  /api/v2/webhooks      listar suscripciones.
    DELETE /api/v2/webhooks/{id}
    GET  /api/v2/audit         log completo de auditoría por tenant.
    POST /api/v2/export        exportar a CSV/XLSX/PDF.
    GET  /api/v2/usage         uso del tenant (calls, facturas).
    GET  /api/v2/health        health detallado (db, pool, cache).
    GET/POST /api/v2/tenants   admin: listar / crear (key de servicio).
    POST /api/v2/tenants/{id}/block   bloquear tenant.
    POST /api/v2/tenants/{id}/unblock
    PATCH /api/v2/tenants/{id} configurar.
    GET  /api/v2/tenants/{id}/usage    uso de un tenant (admin).

Seguridad / aislamiento:
  - TODA ruta v2 exige API key y opera SIEMPRE sobre el tenant de la key
    (nunca acepta `tenant_id` del cliente para leer datos de otro tenant).
  - Rate limiting POR TENANT (independiente del por-IP de /api/v1).
  - Usage tracking: cada llamada incrementa api_calls; cada factura del
    batch incrementa invoices_processed.
  - Los endpoints de admin requieren la key de servicio (tenant_id=None)
    o que el tenant administre su propio recurso.

La app lo monta con `build_v2_router(db, require_api_key, auth)`.
"""
from __future__ import annotations

import threading
import time
import uuid
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

from fastapi import (APIRouter, Depends, HTTPException, Query)
from fastapi.responses import Response
from pydantic import BaseModel, Field

from b2b_ai.db.db import Database
from b2b_ai.db.pool import ConnectionPool
from b2b_ai.services.analytics import build_analytics, TTLCache
from b2b_ai.services.exporter import export
from b2b_ai.services.pipeline import process_file
from b2b_ai.db.tenants import TenantManager
from b2b_ai.api import webhooks as wh

MAX_BATCH = 1000


# ==========================================================================
# Schemas
# ==========================================================================
class BatchRequest(BaseModel):
    """Lote de CFDI. Acepta rutas a XML o una carpeta. `async_` (alias
    "async") ejecuta el lote en background y devuelve un job para polling."""
    paths: list = []
    folder: str = ""
    async_: Optional[bool] = Field(default=False, alias="async")
    webhook: bool = False
    model_config = {"populate_by_name": True}


class WebhookRegister(BaseModel):
    url: str
    events: list = ["invoice_processed"]


class ExportRequest(BaseModel):
    format: str = "csv"           # csv | xlsx | pdf
    scope: str = "invoices"       # invoices | audit
    title: str = "Export"
    periodo: Optional[str] = None
    desde: Optional[str] = None
    hasta: Optional[str] = None
    limit: int = Field(default=1000, ge=1, le=10000)


class TenantConfigRequest(BaseModel):
    config: dict = {}


# ==========================================================================
# Store de jobs async (en memoria, single-node MVP)
# ==========================================================================
_JOBS: dict = {}
_JOBS_LOCK = threading.Lock()


def _new_job(tenant_id):
    job_id = uuid.uuid4().hex[:12]
    with _JOBS_LOCK:
        _JOBS[job_id] = {"id": job_id, "tenant_id": tenant_id,
                         "status": "running", "created_at": datetime.now()
                         .isoformat(timespec="seconds"),
                         "summary": None, "results": None}
    return job_id


def _finish_job(job_id, summary, results):
    with _JOBS_LOCK:
        if job_id in _JOBS:
            _JOBS[job_id]["status"] = "completed"
            _JOBS[job_id]["summary"] = summary
            _JOBS[job_id]["results"] = results


def _get_job(job_id):
    with _JOBS_LOCK:
        return _JOBS.get(job_id)


# ==========================================================================
# Rate limiting por tenant
# ==========================================================================
class TenantRateLimiter:
    """Ventana deslizante por tenant: `limit` llamadas por `window` seg."""

    def __init__(self, window: float = 60.0):
        self.window = window
        self._hits: dict = {}

    def allow(self, tenant_id, limit: int) -> bool:
        now = time.monotonic()
        bucket = self._hits.setdefault(tenant_id, [])
        bucket[:] = [t for t in bucket if t > now - self.window]
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True

    def reset(self, tenant_id=None):
        if tenant_id is None:
            self._hits.clear()
        else:
            self._hits.pop(tenant_id, None)

    @property
    def stats(self):
        return {"tenants": len(self._hits)}


# ==========================================================================
# Entrega de webhooks (mock-safe por defecto; inyectable en tests)
# ==========================================================================
def default_post(url, payload, timeout=15):
    """Entrega mock-safe: registra la entrega sin salir a la red (MVP).
    En producción, apuntar a wh.default_post (urllib real)."""
    return 200


def _deliver_events(db, tenant_id, event, payload, post=None):
    """Entrega `event` a todas las suscripciones del tenant, con bitácora.
    Devuelve lista de resultados de entrega por suscripción."""
    post = post or default_post
    subs = db.list_webhook_subscriptions(tenant_id=tenant_id, event=event)
    out = []
    for s in subs:
        delivery_id = db.record_webhook_delivery(
            tenant_id, event, s["url"], payload)
        res = wh.retry_deliver(s["url"], payload, post=post)
        now = datetime.now().isoformat(timespec="seconds") if res["ok"] else None
        db.update_webhook_delivery(
            delivery_id, res["attempts"], res["last_status"],
            res.get("last_error", ""), completed_at=now)
        out.append({"subscription_id": s["id"], "url": s["url"], **res})
    return out


# ==========================================================================
# Router
# ==========================================================================
def build_v2_router(db: Database, require_api_key, auth=None):
    # Use the main Database connection for queries (supports both SQLite and PG).
    # The old ConnectionPool was SQLite-only and broke on PostgreSQL.
    class _DBPool:
        """Thin adapter that delegates to Database.conn for raw queries."""
        def run(self, sql, params=None):
            try:
                if params:
                    cur = db.conn.execute(sql, params)
                else:
                    cur = db.conn.execute(sql)
                cols = [d[0] for d in cur.description] if cur.description else []
                return [dict(zip(cols, row)) for row in cur.fetchall()]
            except Exception:
                return []

        @property
        def stats(self):
            return {
                "backend": "postgresql" if getattr(db, "_is_pg", False) else "sqlite",
                "active": 1,
                "healthy": True,
            }
    pool = _DBPool()
    cache = TTLCache(ttl_seconds=float(
        _get_env("B2B_V2_CACHE_TTL", "30")))
    rl = TenantRateLimiter()
    tm = TenantManager(db)
    router = APIRouter(prefix="/api/v2", tags=["enterprise"])

    # --- Dependencias compartidas ---------------------------------------
    def _tenant(auth_info: dict):
        """Valida el tenant autenticado, cuenta la llamada y lo devuelve."""
        tid = auth_info.get("tenant_id")
        if tid is None:
            raise HTTPException(
                422, "Este endpoint requiere una API key de tenant.")
        row = db.get_tenant_by_id(tid)
        if row is None or row.get("blocked"):
            raise HTTPException(403, "Tenant bloqueado o inexistente.")
        db.increment_usage(tid, api_calls=1)
        return tid

    def _tenant_rate_limit(auth_info: dict = Depends(require_api_key)):
        tid = auth_info.get("tenant_id")
        if tid is None:
            return
        limit = int(db.get_tenant_config(tid, "rate_limit_per_min", 300) or 300)
        if not rl.allow(tid, limit):
            raise HTTPException(
                429, "Rate limit por tenant excedido. Reduce el ritmo.",
                headers={"Retry-After": str(int(rl.window))})

    def _require_admin(auth_info: dict, target_tid):
        """Admin: key de servicio (tenant None) o el propio tenant."""
        tid = auth_info.get("tenant_id")
        if tid is None:            # key de servicio → admin global
            return
        if tid == target_tid:      # self-service
            return
        raise HTTPException(403, "No autorizado para administrar otro tenant.")

    def _result_summary(res):
        """Compacta un resultado de process_file para la respuesta."""
        return {
            "archivo": res["archivo"],
            "valido": res["validacion"]["ok"],
            "requires_human_review": res["validacion"]
            .get("requires_human_review"),
            "categoria": res["clasificacion"]["categoria"],
            "confianza": res["clasificacion"]["confianza"],
            "erp_poliza": res["erp"].get("poliza"),
            "erp_status": res["erp"].get("status"),
            "insertado": res["insertado"],
            "total": res["datos"].get("total"),
            "emisor": res["datos"].get("emisor_rfc"),
            "invoice_id": res["invoice_id"],
        }

    # --- /batch -----------------------------------------------------------
    def _resolve_path_safe(candidate: str, want_dir: bool = False) -> str:
        """Validate a local path against B2B_LOCAL_XML_DIRS (same as app.py)."""
        from pathlib import Path as _Path
        raw = os.environ.get("B2B_LOCAL_XML_DIRS", "").strip()
        if not raw:
            raise HTTPException(
                status_code=400,
                detail="La ingesta por ruta local está desactivada. "
                       "Suba el archivo como multipart o configure "
                       "B2B_LOCAL_XML_DIRS en el servidor.")
        roots = []
        for part in raw.split(os.pathsep if os.pathsep in raw else ":"):
            part = part.strip()
            if part:
                try:
                    roots.append(_Path(part).resolve(strict=False))
                except OSError:
                    continue
        if not roots:
            raise HTTPException(
                status_code=400,
                detail="La ingesta por ruta local está desactivada.")
        try:
            target = _Path(candidate).resolve(strict=False)
        except (OSError, ValueError):
            raise HTTPException(status_code=400, detail="Ruta inválida.")
        if not any(target == r or r in target.parents for r in roots):
            raise HTTPException(
                status_code=403,
                detail="Ruta fuera de los directorios permitidos.")
        if want_dir:
            if not target.is_dir():
                raise HTTPException(status_code=404,
                                    detail="Carpeta no encontrada.")
        elif not target.is_file():
            raise HTTPException(status_code=404,
                                detail="Archivo no encontrado.")
        return str(target)

    def _process_batch_items(tenant_id, paths, folder, webhook, job_id=None,
                             dbx=None):
        from collections import Counter
        dbx = dbx or db
        raw = []
        for p in paths:
            raw.append(_process_one(tenant_id, p, dbx))
        if folder:
            import glob
            for f in sorted(glob.glob(folder + "/*.xml")):
                raw.append(_process_one(tenant_id, f, dbx))
        ok = sum(1 for r in raw
                 if r.get("validacion", {}).get("ok"))
        inserted = sum(1 for r in raw if r.get("insertado"))
        cats = Counter(r.get("clasificacion", {}).get("categoria", "desconocido")
                       for r in raw if "clasificacion" in r)
        summary = {
            "procesadas": len(raw),
            "validas": ok,
            "con_observaciones": len(raw) - ok,
            "insertadas": inserted,
            "por_categoria": dict(cats),
            "errores": sum(1 for r in raw if "error" in r),
        }
        dbx.increment_usage(tenant_id,
                            invoices_processed=summary["procesadas"])
        deliveries = []
        if webhook:
            deliveries = _deliver_events(
                dbx, tenant_id, "invoice_processed",
                {"batch": job_id, "summary": summary})
        results = [
            _result_summary(r) if "validacion" in r
            else {"archivo": r.get("archivo"), "valido": False,
                  "error": r.get("error")}
            for r in raw
        ]
        return {"summary": summary, "results": results,
                "webhook_deliveries": deliveries}

    def _process_one(tenant_id, path, dbx=None):
        dbx = dbx or db
        try:
            return process_file(path, db=dbx, tenant_id=tenant_id)
        except Exception as e:  # noqa: BLE001 — una factura no rompe el lote
            return {"archivo": path.split("/")[-1], "error": str(e)}

    @router.post("/batch", summary="Procesa hasta 1000 CFDI en lote.")
    def batch(req: BatchRequest,
              auth_info: dict = Depends(require_api_key),
              _rl: None = Depends(_tenant_rate_limit)):
        tenant = _tenant(auth_info)
        paths = list(req.paths or [])
        if not paths and not req.folder:
            raise HTTPException(400, "Indica paths o folder.")
        # Check batch size limit BEFORE path validation so the 422
        # is returned even when paths are outside allowed dirs.
        if not req.folder and len(paths) > MAX_BATCH:
            raise HTTPException(422, f"Máximo {MAX_BATCH} por lote.")
        # Validate all paths against B2B_LOCAL_XML_DIRS
        validated_paths = []
        for p in paths:
            validated_paths.append(_resolve_path_safe(p))
        if req.folder:
            validated_folder = _resolve_path_safe(req.folder, want_dir=True)
        else:
            validated_folder = None
        if not req.folder:
            total = len(validated_paths)
        else:
            import glob
            assert validated_folder is not None
            total = len(validated_paths) + len(glob.glob(validated_folder + "/*.xml"))
            if total > MAX_BATCH:
                raise HTTPException(422, f"Máximo {MAX_BATCH} por lote.")

        if req.async_:
            job_id = _new_job(tenant)
            t = threading.Thread(
                target=lambda: _run_job(job_id, tenant, validated_paths, validated_folder,
                                        req.webhook),
                daemon=True)
            t.start()
            return {"accepted": True, "job_id": job_id, "total": total,
                    "status": "running"}
        out = _process_batch_items(tenant, validated_paths, validated_folder, req.webhook)
        return {**out, "usage": db.get_usage(tenant)}

    def _run_job(job_id, tenant_id, paths, folder, webhook):
        # Conexión dedicada al hilo: evita compartir la conexión principal
        # (sqlite no permite transacciones concurrentes sobre un mismo conn).
        dbx = Database(db.path, migrate=False)
        try:
            out = _process_batch_items(tenant_id, paths, folder, webhook,
                                       job_id=job_id, dbx=dbx)
            _finish_job(job_id, out["summary"], out["results"])
        except Exception as e:  # noqa: BLE001
            with _JOBS_LOCK:
                if job_id in _JOBS:
                    _JOBS[job_id]["status"] = "error"
                    _JOBS[job_id]["error"] = str(e)
        finally:
            dbx.close()

    @router.get("/batch/{job_id}",
                summary="Estado y resultado de un lote async.")
    def batch_status(job_id: str,
                     auth_info: dict = Depends(require_api_key)):
        tenant = _tenant(auth_info)
        job = _get_job(job_id)
        if job is None or job["tenant_id"] != tenant:
            raise HTTPException(404, "Lote no encontrado.")
        return {k: job[k] for k in
                ("id", "tenant_id", "status", "created_at",
                 "summary", "results", "error") if k in job}

    # --- /analytics --------------------------------------------------------
    @router.get("/analytics",
                summary="Analytics avanzado por tenant (cache TTL).")
    def analytics(periodo: Optional[str] = Query(default=None),
                  desde: Optional[str] = Query(default=None),
                  hasta: Optional[str] = Query(default=None),
                  auth_info: dict = Depends(require_api_key),
                  _rl: None = Depends(_tenant_rate_limit)):
        tenant = _tenant(auth_info)
        ckey = ("analytics", tenant, periodo, desde, hasta)

        def _compute():
            invoices = pool.run(
                "SELECT * FROM invoices WHERE tenant_id=?",
                (tenant,))
            return build_analytics(invoices, periodo=periodo,
                                   desde=desde, hasta=hasta)
        value, hit = cache.get_or_compute(ckey, _compute)
        return {"tenant_id": tenant, "cached": hit, "data": value}

    # --- /webhooks ---------------------------------------------------------
    @router.post("/webhooks",
                 summary="Registra webhooks para eventos del tenant.")
    def register_webhook(req: WebhookRegister,
                         auth_info: dict = Depends(require_api_key)):
        tenant = _tenant(auth_info)
        if not req.url.startswith(("http://", "https://")):
            raise HTTPException(422, "URL inválida.")
        if not req.events:
            raise HTTPException(422, "Indica al menos un evento.")
        created = []
        for ev in req.events:
            sid = db.create_webhook_subscription(tenant, ev, req.url)
            created.append({"id": sid, "event": ev, "url": req.url})
        db.log_call("webhook", "register", entity="webhook_subscription",
                    entity_id=str(tenant), payload={"events": req.events,
                                                    "url": req.url},
                    status="ok", tenant_id=tenant)
        return {"ok": True, "tenant_id": tenant, "subscriptions": created}

    @router.get("/webhooks",
                summary="Lista las suscripciones de webhook del tenant.")
    def list_webhooks(event: Optional[str] = Query(default=None),
                      auth_info: dict = Depends(require_api_key)):
        tenant = _tenant(auth_info)
        return {"tenant_id": tenant,
                "subscriptions": db.list_webhook_subscriptions(
                    tenant_id=tenant, event=event)}

    @router.delete("/webhooks/{subscription_id}",
                   summary="Elimina una suscripción de webhook.")
    def delete_webhook(subscription_id: int,
                       auth_info: dict = Depends(require_api_key)):
        tenant = _tenant(auth_info)
        if not db.delete_webhook_subscription(subscription_id,
                                              tenant_id=tenant):
            raise HTTPException(404, "Suscripción no encontrada.")
        db.log_call("webhook", "delete", entity="webhook_subscription",
                    entity_id=str(subscription_id), status="ok",
                    tenant_id=tenant)
        return {"ok": True, "deleted": subscription_id}

    # --- /audit ------------------------------------------------------------
    @router.get("/audit", summary="Log completo de auditoría por tenant.")
    def audit(tool: Optional[str] = Query(default=None),
              action: Optional[str] = Query(default=None),
              entity: Optional[str] = Query(default=None),
              desde: Optional[str] = Query(default=None),
              hasta: Optional[str] = Query(default=None),
              limit: int = Query(default=100, ge=1, le=5000),
              offset: int = Query(default=0, ge=0),
              auth_info: dict = Depends(require_api_key)):
        tenant = _tenant(auth_info)
        rows = pool.run(
            "SELECT * FROM audit_log WHERE tenant_id=? "
            "ORDER BY id DESC LIMIT ? OFFSET ?",
            (tenant, limit, offset))
        if tool:
            rows = [r for r in rows if r["tool_name"] == tool]
        if action:
            rows = [r for r in rows if r["action"] == action]
        if entity:
            rows = [r for r in rows if r["entity"] == entity]
        if desde:
            rows = [r for r in rows if (r.get("created_at") or "") >= desde]
        if hasta:
            rows = [r for r in rows if (r.get("created_at") or "") <= hasta]
        return {"count": len(rows), "limit": limit, "offset": offset,
                "audit": rows}

    # --- /export -----------------------------------------------------------
    @router.post("/export", summary="Exporta datos a CSV/XLSX/PDF.")
    def export_data(req: ExportRequest,
                    auth_info: dict = Depends(require_api_key),
                    _rl: None = Depends(_tenant_rate_limit)):
        tenant = _tenant(auth_info)
        if req.scope == "invoices":
            rows = pool.run(
                "SELECT * FROM invoices WHERE tenant_id=? "
                "ORDER BY id DESC LIMIT ?", (tenant, req.limit))
        elif req.scope == "audit":
            rows = pool.run(
                "SELECT * FROM audit_log WHERE tenant_id=? "
                "ORDER BY id DESC LIMIT ?", (tenant, req.limit))
        else:
            raise HTTPException(422, "scope debe ser 'invoices' o 'audit'.")
        try:
            data, media = export(rows, req.format, title=req.title)
        except ValueError as e:
            raise HTTPException(422, str(e))
        ext = req.format if req.format != "xlsx" else "xlsx"
        filename = f"{req.scope}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"
        return Response(content=data, media_type=media,
                        headers={"Content-Disposition":
                                 f'attachment; filename="{filename}"'})

    # --- /usage ------------------------------------------------------------
    @router.get("/usage", summary="Uso del tenant (calls, facturas).")
    def my_usage(auth_info: dict = Depends(require_api_key),
                 _rl: None = Depends(_tenant_rate_limit)):
        tenant = _tenant(auth_info)
        return {"tenant_id": tenant, "usage": db.get_usage(tenant)}

    # --- /health -----------------------------------------------------------
    @router.get("/health", summary="Health detallado del servicio.")
    def health_v2(auth_info: dict = Depends(require_api_key)):
        tenant = _tenant(auth_info)
        return {
            "status": "ok",
            "service": "b2b-ai-v2",
            "schema_version": db.schema_version(),
            "tenants": len(db.list_tenants()),
            "invoices": db.count_invoices(tenant_id=tenant),
            "connection_pool": pool.stats,
            "cache": cache.stats,
            "rate_limiter": rl.stats,
            "async_jobs": len(_JOBS),
        }

    # --- Tenant admin ------------------------------------------------------
    @router.get("/tenants", summary="Lista tenants + uso (admin).")
    def admin_list_tenants(auth_info: dict = Depends(require_api_key)):
        _require_admin(auth_info, target_tid=None)
        tenants = db.list_tenants()
        usage = {u["tenant_id"]: u for u in db.get_all_usage()}
        for t in tenants:
            u = usage.get(t["id"])
            t["usage"] = ({"api_calls": u["api_calls"],
                           "invoices_processed": u["invoices_processed"]}
                          if u else {"api_calls": 0, "invoices_processed": 0})
        return {"tenants": tenants}

    @router.post("/tenants", summary="Onboarding de un tenant (admin).")
    def admin_create_tenant(req: TenantConfigRequest,
                            name: str = Query(...),
                            rfc: str = Query(default=""),
                            auth_info: dict = Depends(require_api_key)):
        _require_admin(auth_info, target_tid=None)
        out = tm.onboard_tenant(name, rfc=rfc, **{
            k: v for k, v in req.config.items()
            if k in ("erp_type", "plantilla_contable", "notif_channel",
                     "notif_recipient", "webhook_url",
                     "policy_human_review")})
        return {"ok": True, "tenant": {
            "id": out["id"], "name": out["name"], "rfc": out["rfc"],
            "config": out["config"]}}

    @router.post("/tenants/{tid}/block",
                 summary="Bloquea un tenant (deja de poder autenticarse).")
    def admin_block(tid: int,
                    auth_info: dict = Depends(require_api_key)):
        _require_admin(auth_info, target_tid=tid)
        if db.get_tenant_by_id(tid) is None:
            raise HTTPException(404, "Tenant no encontrado.")
        db.set_tenant_blocked(tid, True)
        rl.reset(tid)
        return {"ok": True, "tenant_id": tid, "blocked": True}

    @router.post("/tenants/{tid}/unblock",
                 summary="Desbloquea un tenant.")
    def admin_unblock(tid: int,
                      auth_info: dict = Depends(require_api_key)):
        _require_admin(auth_info, target_tid=tid)
        if db.get_tenant_by_id(tid) is None:
            raise HTTPException(404, "Tenant no encontrado.")
        db.set_tenant_blocked(tid, False)
        return {"ok": True, "tenant_id": tid, "blocked": False}

    @router.patch("/tenants/{tid}",
                  summary="Configura un tenant (admin).")
    def admin_config(tid: int, req: TenantConfigRequest,
                     auth_info: dict = Depends(require_api_key)):
        _require_admin(auth_info, target_tid=tid)
        if db.get_tenant_by_id(tid) is None:
            raise HTTPException(404, "Tenant no encontrado.")
        cfg = tm.set_config(tid, **req.config)
        return {"ok": True, "tenant_id": tid, "config": cfg}

    @router.get("/tenants/{tid}/usage",
                summary="Uso de un tenant (admin).")
    def admin_usage(tid: int,
                    auth_info: dict = Depends(require_api_key)):
        _require_admin(auth_info, target_tid=tid)
        if db.get_tenant_by_id(tid) is None:
            raise HTTPException(404, "Tenant no encontrado.")
        return {"tenant_id": tid, "usage": db.get_usage(tid)}

    # --- /retention (politica de retencion de datos) ------------------------
    @router.post("/retention/purge",
                 summary="Aplica la política de retención de datos (admin).")
    def admin_retention_purge(days: Optional[int] = Query(default=None),
                              auth_info: dict = Depends(require_api_key)):
        """Ejecuta enforce_retention(days): borra audit_log, webhooks,
        notificaciones y sesiones del portal más viejos que `days` días.
        Solo para la key de servicio (tenant_id=None). Las facturas
        (datos fiscales) NO se tocan."""
        if auth_info.get("tenant_id") is not None:
            raise HTTPException(403, "Solo la key de servicio.")
        removed = db.enforce_retention(days=days)
        db.log_call("retention", "purge", entity="retention",
                    payload={"days": days, "removed": removed}, status="ok")
        return {"ok": True, "days": days or int(
            os.environ.get("B2B_RETENTION_DAYS", "365") or "365"),
            "removed": removed}

    return router


def _get_env(key, default):
    import os
    return os.environ.get(key, default)
