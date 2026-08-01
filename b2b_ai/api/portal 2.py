# -*- coding: utf-8 -*-
"""
portal.py — Portal del cliente (FASE 5): los clientes del despacho contable
suben facturas CFDI (XML/PDF) desde el navegador, sin API key.

Auth: sesión por token opaco. El login valida email+password con bcrypt y
devuelve un token que el frontend manda en `Authorization: Bearer <token>`.
Cada sesión se liga a un `client_user` y por tanto a un `tenant_id`: TODA
consulta de facturas/estadísticas se filtra por ese tenant (multi-tenant).

Upload: se procesa de forma asíncrona (hilo en segundo plano) a través del
pipeline existente (`process_file`), para que el portal pueda mostrar el
progreso en tiempo real vía GET /portal/invoices/{job_id}/status (polling
cada ~2s). Los jobs en vuelo viven en memoria (JobStore); una vez terminado,
la factura queda persistida en la DB y el status se resuelve desde ahí.
"""
from __future__ import annotations

import os
import re
import secrets
import tempfile
import threading
import uuid
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel

from b2b_ai.services.pipeline import process_file

SESSION_TTL_DAYS = 30
_PORTAL_STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "static", "portal.html")


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
class PortalLogin(BaseModel):
    email: str
    password: str
    tenant_id: Optional[int] = None


class PortalMagicLink(BaseModel):
    email: str


class PortalTokenRequest(BaseModel):
    token: str


# --------------------------------------------------------------------------
# Password helpers (bcrypt)
# --------------------------------------------------------------------------
def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"),
                         bcrypt.gensalt(rounds=12)).decode("utf-8")


def _check_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"),
                              password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def _expires() -> str:
    return (datetime.now() + timedelta(days=SESSION_TTL_DAYS)).isoformat(
        timespec="seconds")


# --------------------------------------------------------------------------
# JobStore: trabajos de procesamiento en vuelo (async upload + polling)
# --------------------------------------------------------------------------
class _JobStore:
    def __init__(self):
        self._jobs = {}
        self._lock = threading.Lock()

    def new(self):
        job_id = uuid.uuid4().hex
        with self._lock:
            self._jobs[job_id] = {
                "id": job_id, "status": "processing", "message": "En cola…",
                "invoice_id": None, "result": None, "error": None,
                "tenant_id": None,
            }
        return job_id

    def get(self, job_id):
        with self._lock:
            return dict(self._jobs[job_id]) if job_id in self._jobs else None

    def set(self, job_id, **fields):
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(fields)

    def cleanup(self, max_age_s=3600):
        cutoff = datetime.now() - timedelta(seconds=max_age_s)
        with self._lock:
            dead = [j for j, v in self._jobs.items()
                    if v["status"] != "processing" and v.get("done_at")
                    and v["done_at"] < cutoff]
            for j in dead:
                self._jobs.pop(j, None)


JOBS = _JobStore()


# --------------------------------------------------------------------------
# Auth dependency
# --------------------------------------------------------------------------
def _extract_token(
    authorization: Optional[str] = Header(default=None),
    x_portal_token: Optional[str] = Header(default=None),
) -> Optional[str]:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return x_portal_token


def _require_user(db):
    def dep(token: Optional[str] = Depends(_extract_token)):
        if not token:
            raise HTTPException(status_code=401,
                                detail="Se requiere sesión (Bearer token).")
        session = db.get_portal_session(token)
        if session is None:
            raise HTTPException(status_code=401,
                                detail="Sesión inválida o caducada.")
        return {"token": token, **session}
    return dep


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _iso_from_ms(ts):
    """Convierte timestamp con milisegundos (SQLite CURRENT_TIMESTAMP) en
    YYYY-MM-DDTHH:MM:SS para comparaciones consistentes."""
    return (ts.split(".")[0] if ts else "") or ""


def _as_csv(invoices) -> str:
    """Serializa facturas a CSV (UTF-8). El frontend usa el nombre del archivo
    como cabecera, por eso aquí sin BOM (se añade en el cliente)."""
    import csv
    import io
    cols = ["id", "fecha", "tipo", "serie", "folio", "folio_fiscal",
            "emisor_rfc", "emisor_nombre", "receptor_rfc", "subtotal", "iva",
            "total", "moneda", "categoria", "confianza", "valido", "status",
            "issues", "archivo"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for inv in invoices:
        w.writerow([inv.get(c, "") for c in cols])
    return buf.getvalue()


# --------------------------------------------------------------------------
# Router
# --------------------------------------------------------------------------
def build_portal_router(db):
    router = APIRouter(prefix="/portal", tags=["portal"])
    require_user = _require_user(db)

    # ---- Auth ------------------------------------------------------------
    @router.post("/auth/login")
    def portal_login(body: PortalLogin):
        """Autentica un cliente por email+password (bcrypt) y devuelve un
        token de sesión multi-tenant."""
        email = (body.email or "").strip().lower()
        password = body.password or ""
        if not email or not password:
            raise HTTPException(status_code=422,
                                detail="email y password son obligatorios.")
        user = db.get_client_user_by_email(email, tenant_id=body.tenant_id)
        if user is None or not _check_password(password, user["password_hash"]):
            raise HTTPException(status_code=401,
                                detail="Credenciales inválidas.")
        token = _new_token()
        db.create_portal_session(user["id"], token, _expires())
        return {
            "token": token,
            "user": {"id": user["id"], "email": user["email"],
                     "name": user["name"], "role": user["role"]},
            "tenant_id": user["tenant_id"],
            "expires_at": _expires(),
        }

    @router.post("/auth/magic-link")
    def portal_magic_link(body: PortalMagicLink, request: Request):
        """Emite una sesión sin password y la 'envía' por email (mock para el
        MVP: se registra en notifications y se devuelve dev_token para que el
        SPA continúe en desarrollo)."""
        email = (body.email or "").strip().lower()
        if not email:
            raise HTTPException(status_code=422, detail="email es obligatorio.")
        user = db.get_client_user_by_email(email)
        if user is None:
            # No revelamos si el email existe (evita enumeración de cuentas),
            # pero en modo dev devolvemos un ok genérico.
            raise HTTPException(status_code=404,
                                detail="No hay una cuenta con ese email.")
        token = _new_token()
        db.create_portal_session(user["id"], token, _expires())
        # Mock de envío: guardamos la notificación (canal email).
        try:
            db.insert_notification(
                user["tenant_id"], "portal_magic_link", "email",
                email, "Tu enlace de acceso al portal B&B AI",
                "Portal: usa el token para iniciar sesión. "
                f"(dev_token: {token})", status="sent")
        except Exception:  # noqa: BLE001
            pass
        return {
            "ok": True,
            "message": "Te enviamos un enlace de acceso por email.",
            "dev_token": token,
            "expires_at": _expires(),
        }

    @router.post("/auth/confirm")
    def portal_confirm(body: PortalTokenRequest):
        """Valida un token (magic link) y devuelve la sesión activa."""
        session = db.get_portal_session(body.token)
        if session is None:
            raise HTTPException(status_code=401, detail="Token inválido.")
        u = session["user"]
        return {
            "token": body.token,
            "user": {"id": u["id"], "email": u["email"],
                     "name": u["name"], "role": u["role"]},
            "tenant_id": session["tenant_id"],
        }

    @router.post("/auth/logout")
    def portal_logout(user: dict = Depends(require_user)):
        db.delete_portal_session(user["token"])
        return {"ok": True}

    @router.get("/auth/me")
    def portal_me(user: dict = Depends(require_user)):
        u = user["user"]
        return {"user": {"id": u["id"], "email": u["email"],
                         "name": u["name"], "role": u["role"]},
                "tenant_id": user["tenant_id"]}

    # ---- Invoices --------------------------------------------------------
    @router.get("/invoices")
    def portal_invoices(
        user: dict = Depends(require_user),
        categoria: Optional[str] = Query(default=None),
        estado: Optional[str] = Query(default=None),
        fecha_desde: Optional[str] = Query(default=None),
        fecha_hasta: Optional[str] = Query(default=None),
        valido: Optional[bool] = Query(default=None),
        limit: int = Query(default=200, ge=1, le=1000),
    ):
        """Lista las facturas del tenant autenticado con filtros."""
        tenant = user["tenant_id"]
        estado_lower = estado.strip().lower() if estado else None
        invoices = db.list_invoices(
            tenant_id=tenant, limit=limit, categoria=categoria,
            valido=valido, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)
        # El filtro por `estado` se hace en memoria porque DB no tiene columna
        # dedicada más allá de `status` (procesado / pending_approval).
        if estado_lower:
            invoices = [i for i in invoices
                        if (i.get("status") or "").lower() == estado_lower
                        or (estado_lower == "anomalia"
                            and i.get("requires_human_review"))
                        or (estado_lower == "valida" and i.get("valido"))
                        or (estado_lower == "invalida" and not i.get("valido"))]
        return {"count": len(invoices), "tenant_id": tenant,
                "invoices": invoices}

    @router.get("/invoices/{job_or_id}/status")
    def portal_invoice_status(job_or_id: str,
                              user: dict = Depends(require_user)):
        """Estado de procesamiento. Acepta un job_id (procesamiento en vuelo)
        o un invoice_id ya persistido."""
        tenant = user["tenant_id"]
        job = JOBS.get(job_or_id)
        if job is not None:
            if job.get("tenant_id") not in (None, tenant):
                raise HTTPException(status_code=403,
                                    detail="Acceso denegado.")
            payload = {"job_id": job["id"], "status": job["status"],
                       "message": job["message"]}
            if job["status"] == "done":
                payload["invoice_id"] = job["invoice_id"]
                payload["result"] = job["result"]
            if job["status"] == "error":
                payload["error"] = job["error"]
            return payload
        # No es un job en vuelo → buscar por invoice id (scoped por tenant).
        try:
            invoice_id = int(job_or_id)
        except ValueError:
            raise HTTPException(status_code=404,
                                detail="Job o factura no encontrado.")
        inv = db.get_invoice(invoice_id, tenant_id=tenant)
        if inv is None:
            raise HTTPException(status_code=404, detail="Factura no encontrada.")
        return {
            "invoice_id": inv["id"], "status": "procesado",
            "result": {
                "archivo": inv["archivo"], "valido": inv["valido"],
                "categoria": inv["categoria"], "confianza": inv["confianza"],
                "total": inv["total"], "emisor": inv["emisor_rfc"],
                "requires_human_review": inv["requires_human_review"],
                "erp_status": inv["erp_status"],
            },
        }

    @router.post("/invoices/upload")
    async def portal_upload(request: Request,
                            user: dict = Depends(require_user)):
        """Sube CFDI (XML/PDF) y lo procesa por el pipeline en segundo plano.
        Devuelve job_id para que el portal haga polling del estado."""
        tenant = user["tenant_id"]
        content_type = request.headers.get("content-type", "")
        if "multipart/form-data" not in content_type:
            raise HTTPException(
                400, "Debe enviar el archivo (multipart/form-data).")
        form = await request.form()
        up = form.get("file") or form.get("xml_file")
        if up is None or not getattr(up, "filename", None):
            raise HTTPException(400, "Debe enviar un archivo (campo `file`).")
        content = await up.read()
        if not content.strip():
            raise HTTPException(400, "Archivo vacío.")
        name = up.filename or ""
        if not re.search(r"\.(xml|pdf)$", name, re.IGNORECASE):
            raise HTTPException(422, "Solo se aceptan archivos XML o PDF.")

        suffix = os.path.splitext(name)[1] or ".xml"
        job_id = JOBS.new()
        JOBS.set(job_id, tenant_id=tenant, message="Subiendo archivo…")

        def _run():
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            tmp.write(content)
            tmp.close()
            try:
                JOBS.set(job_id, message="Validando y clasificando CFDI…")
                res = process_file(tmp.name, db=db, tenant_id=tenant)
                inv_id = res.get("invoice_id")
                JOBS.set(job_id, status="done", invoice_id=inv_id,
                         result=_strip(res), message="Procesado correctamente.",
                         done_at=datetime.now())
            except Exception as e:  # noqa: BLE001
                JOBS.set(job_id, status="error", error=str(e),
                         message="Error al procesar.", done_at=datetime.now())
            finally:
                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return {"ok": True, "job_id": job_id,
                "status": "processing", "filename": name}

    @router.get("/invoices/export.csv")
    def portal_export(
        user: dict = Depends(require_user),
        categoria: Optional[str] = Query(default=None),
        fecha_desde: Optional[str] = Query(default=None),
        fecha_hasta: Optional[str] = Query(default=None),
    ):
        """Exporta el historial del tenant a CSV."""
        tenant = user["tenant_id"]
        invoices = db.list_invoices(tenant_id=tenant, categoria=categoria,
                                    fecha_desde=fecha_desde,
                                    fecha_hasta=fecha_hasta)
        return _csv_response(_as_csv(invoices))

    # ---- Dashboard -------------------------------------------------------
    @router.get("/dashboard/stats")
    def portal_stats(user: dict = Depends(require_user)):
        """Métricas del tenant autenticado."""
        tenant = user["tenant_id"]
        invoices = db.list_invoices(tenant_id=tenant)
        stats = db.invoice_stats(tenant_id=tenant)
        total = stats["total_facturas"]
        anomalias = sum(1 for i in invoices if i.get("requires_human_review"))
        procesadas = sum(1 for i in invoices if (i.get("status")
                                                 or "") == "procesado")
        por_categoria = stats["por_categoria"]
        return {
            "total_facturas": total,
            "monto_total": stats["monto_total"],
            "iva_total": stats["iva_total"],
            "anomalias": anomalias,
            "procesadas": procesadas,
            "pendientes": total - procesadas,
            "por_categoria": por_categoria,
            "ultima_actividad": max(
                (_iso_from_ms(i.get("procesado_en") or i.get("created_at"))
                 for i in invoices), default=None),
        }

    @router.get("/", include_in_schema=False)
    def portal_index():
        """Servir el SPA del portal desde el mismo origen."""
        if not os.path.isfile(_PORTAL_STATIC):
            raise HTTPException(404, "Portal SPA no disponible.")
        from fastapi.responses import FileResponse
        return FileResponse(_PORTAL_STATIC)

    return router


def _strip(res):
    """Resumen ligero del resultado del pipeline para el frontend."""
    return {
        "archivo": res.get("archivo"),
        "valido": res["validacion"].get("ok"),
        "requires_human_review": res["validacion"].get("requires_human_review"),
        "categoria": res["clasificacion"].get("categoria"),
        "confianza": res["clasificacion"].get("confianza"),
        "erp_status": res["erp"].get("status"),
        "insertado": res.get("insertado"),
        "total": res["datos"].get("total"),
        "emisor": res["datos"].get("emisor_rfc"),
        "fecha": res["datos"].get("fecha"),
    }


def _csv_response(csv_data):
    from fastapi import Response
    return Response(
        content="\ufeff" + csv_data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 "attachment; filename=\"facturas_portal.csv\""},
    )
