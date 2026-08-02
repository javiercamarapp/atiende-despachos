# -*- coding: utf-8 -*-
"""routes_arco.py — LFPDPPP ARCO rights endpoints (Acceso, Rectificación,
Cancelación, Oposición).

Extracted from app.py to reduce monolith size.
"""
from __future__ import annotations

import json as _json
import logging

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel


logger = logging.getLogger(__name__)


class ARCORequest(BaseModel):
    """Solicitud ARCO según LFPDPPP Art. 28-35."""
    email: str
    nombre_completo: str = ""
    tipo_solicitud: str  # "acceso" | "rectificacion" | "cancelacion" | "oposicion"
    descripcion: str = ""
    datos_a_modificar: dict | None = None  # Para rectificación
    identificacion_tipo: str = ""  # IFE, INE, pasaporte
    identificacion_ref: str = ""


def build_arco_router(db, require_api_key) -> APIRouter:
    """Build the ARCO rights router.

    Endpoints:
        POST /api/v1/arco/solicitud          — submit ARCO request (public)
        GET  /api/v1/arco/estatus/{email}     — check ARCO status (public)
        GET  /api/v1/arco/datos/{email}       — access personal data (public)
        POST /api/v1/arco/cancelacion/{email} — cancel/delete data (public)
    """
    router = APIRouter(tags=["arco"])

    def _require_tenant(auth_info: dict) -> Optional[str]:
        """Return the tenant_id from the authenticated API key, or None if
        the system is single-tenant. Multi-tenant authorization: the data
        being accessed MUST belong to the API key's tenant.
        """
        return (auth_info or {}).get("tenant_id")

    def _resolve_user(email: str, auth_info: dict):
        """Get the client user for an email scoped to the API key's tenant."""
        tenant_id = _require_tenant(auth_info)
        user = db.get_client_user_by_email(email, tenant_id=tenant_id)
        if user is None:
            raise HTTPException(
                404, "No se encontraron datos para ese email.")
        return user, tenant_id

    @router.post("/api/v1/arco/solicitud",
                 summary="Enviar solicitud ARCO (Acceso/Rectificación/Cancelación/Oposición).",
                 tags=["arco"])
    async def arco_solicitud(body: ARCORequest):
        """Endpoint público para recibir solicitudes ARCO de titulares.

        LFPDPPP Art. 29: el responsable debe registrar cada solicitud
        y responder en un plazo máximo de 20 días hábiles.
        """
        logger.info(
            "ARCO solicitud recibida: tipo=%s email=%s",
            body.tipo_solicitud, body.email)

        valid_types = {"acceso", "rectificacion", "cancelacion", "oposicion"}
        if body.tipo_solicitud not in valid_types:
            raise HTTPException(
                400, f"tipo_solicitud inválido. Valores: {valid_types}")

        db.log_call(
            "arco", "solicitud",
            entity="arco_request",
            entity_id=body.email,
            payload={
                "tipo": body.tipo_solicitud,
                "email": body.email,
                "nombre": body.nombre_completo,
                "descripcion": body.descripcion,
            },
            status="received",
        )

        return {
            "status": "received",
            "mensaje": (
                f"Solicitud ARCO ({body.tipo_solicitud}) recibida. "
                "Recibirás respuesta en un plazo máximo de 20 días hábiles "
                "conforme al Art. 29 LFPDPPP."),
            "referencia": f"ARCO-{body.tipo_solicitud[:3].upper()}",
            "plazo_dias_habiles": 20,
        }

    @router.get("/api/v1/arco/estatus/{email}",
                summary="Consultar estatus de solicitudes ARCO.",
                tags=["arco"])
    async def arco_estatus(email: str, auth_info: dict = Depends(require_api_key)):
        """Devuelve las solicitudes ARCO registradas para un email."""
        rows = db.conn.execute(
            "SELECT entity_id, payload, status, ts FROM audit_log "
            "WHERE entity = 'arco_request' AND entity_id = ? "
            "ORDER BY ts DESC LIMIT 20",
            (email,),
        ).fetchall()
        solicitudes = []
        for r in rows:
            payload = {}
            try:
                payload = _json.loads(r["payload"]) if r["payload"] else {}
            except Exception:
                pass
            solicitudes.append({
                "tipo": payload.get("tipo", ""),
                "email": r["entity_id"],
                "estado": r["status"],
                "fecha": r["ts"],
            })
        return {
            "email": email,
            "solicitudes": solicitudes,
            "total": len(solicitudes),
        }

    @router.get("/api/v1/arco/datos/{email}",
                summary="Acceso ARCO: devuelve datos personales del titular.",
                tags=["arco"])
    async def arco_acceso(email: str, auth_info: dict = Depends(require_api_key)):
        """Acceso ARCO — LFPDPPP Art. 28: devuelve todos los datos
        personales que el responsable tiene del titular."""
        user, _tenant_id = _resolve_user(email, auth_info)

        db.log_call(
            "arco", "acceso",
            entity="arco_request",
            entity_id=email,
            payload={"tipo": "acceso"},
            status="processed",
        )

        datos = {k: v for k, v in dict(user).items()
                 if k != "password_hash"}
        return {
            "titular": email,
            "datos_personales": datos,
            "finalidades": [
                "Prestación del servicio de automatización contable y fiscal",
                "Cumplimiento de obligaciones fiscales",
                "Soporte técnico",
            ],
            "referencia_legal": "LFPDPPP Art. 28 (derecho de acceso)",
        }

    @router.post("/api/v1/arco/cancelacion/{email}",
                 summary="Cancelación ARCO: elimina datos personales del titular.",
                 tags=["arco"])
    async def arco_cancelacion(email: str, auth_info: dict = Depends(require_api_key)):
        """Cancelación ARCO — LFPDPPP Art. 33: eliminar datos personales.

        Nota: Se conservan datos con obligación legal de retención
        (CFDI, contabilidad electrónica — CFF Art. 82-89, 5 años).
        """
        user, _tenant_id = _resolve_user(email, auth_info)

        user_id = user.get("id")
        logger.warning(
            "ARCO cancelación solicitada para %s (user_id=%s) — "
            "Se eliminarán datos no retenidos por ley.", email, user_id)

        # Actually delete personal data
        deleted_count = 0
        try:
            db.delete_client_user(user_id)
            deleted_count = 1
        except Exception as e:
            logger.error("Error deleting client user %s: %s", user_id, e)
            raise HTTPException(500, f"Error eliminando datos: {e}")

        # Anonymize audit log entries for this email
        try:
            db.conn.execute(
                "UPDATE audit_log SET payload = '{\"anonymized\": true}' "
                "WHERE entity_id = ? AND entity IN ('arco_request', 'client_user')",
                (email,))
            db.conn.commit()
        except Exception as e:
            logger.warning("Could not anonymize audit log for %s: %s", email, e)

        db.log_call(
            "arco", "cancelacion",
            entity="arco_request",
            entity_id=email,
            payload={"tipo": "cancelacion", "deleted_user_id": user_id},
            status="completed",
        )

        return {
            "status": "completed",
            "deleted_records": deleted_count,
            "mensaje": (
                f"Datos personales de {email} eliminados. "
                "Se conservan CFDI y registros contables con obligación "
                "legal de retención (CFF Art. 82-89, mínimo 5 años)."),
            "referencia_legal": (
                "LFPDPPP Art. 33 (derecho de cancelación), "
                "CFF Art. 82 (conservación fiscal)"),
            "datos_retenidos": [
                "CFDIs procesados (CFF Art. 82, 5 años)",
                "Registros de contabilidad electrónica",
                "Bitácora de auditoría (CFF Art. 89)",
            ],
        }

    return router
