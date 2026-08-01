# -*- coding: utf-8 -*-
"""
electronica_routes.py — Endpoints FastAPI para el workflow de contabilidad
electrónica SAT (generate package, hash, status, transition, summary).

Endpoints:
    POST /contabilidad/electronica/package      — Genera paquete XML del mes.
    POST /contabilidad/electronica/hash         — Calcula hash SHA-1 (SAT).
    GET  /contabilidad/electronica/status/{id}  — Estado del paquete.
    POST /contabilidad/electronica/transition   — Avanza el estado del paquete.
    GET  /contabilidad/electronica/summary/{id} — Resumen mensual del paquete.

El router se construye con `build_electronica_router()` para inyectar DB y
dependencias de auth en tests.  Los endpoints operan sobre un almacén
en memoria (paquetes generados en la sesión) — persistencia real depende
del caller que use ContabilidadElectronica con db=.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from b2b_ai.services.catalogo_cuentas import CatalogoCuentas
from b2b_ai.services.contabilidad_electronica import (
    ContabilidadElectronica,
    ESTADOS,
    ESTADO_INICIAL,
)


# ---------------------------------------------------------------------------
# In-memory store  (keyed by package_id)
# ---------------------------------------------------------------------------
_packages: Dict[str, Dict[str, Any]] = {}


def _store_package(package_id: str, pkg: Dict[str, Any],
                   mgr: ContabilidadElectronica) -> None:
    """Persiste un paquete en el almacén en memoria."""
    _packages[package_id] = {
        "package_id": package_id,
        "paquete": pkg,
        "estado": mgr.estado_actual(),
    }


def _get_package(package_id: str) -> Dict[str, Any]:
    """Devuelve el paquete o lanza 404."""
    pkg = _packages.get(package_id)
    if pkg is None:
        raise HTTPException(
            status_code=404,
            detail=f"Paquete {package_id} no encontrado.",
        )
    return pkg


def clear_packages() -> None:
    """Limpia el almacén (útil en tests)."""
    _packages.clear()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AsientoSchema(BaseModel):
    """Un asiento contable para generar el paquete."""
    cuenta: str
    debe: str = "0"
    haber: str = "0"
    fecha: str = ""


class PackageRequest(BaseModel):
    """Parámetros para generar el paquete de contabilidad electrónica."""
    rfc: str = ""
    razon_social: str = ""
    ejercicio: int = Field(default_factory=lambda: __import__("datetime").datetime.now().year)
    mes: int = Field(default=1, ge=1, le=12)
    asientos: List[AsientoSchema]
    saldos_iniciales: Optional[Dict[str, str]] = None


class HashRequest(BaseModel):
    """Contenido en texto para calcular SHA-1."""
    content: str = Field(..., description="Texto a hashear (se codifica a UTF-8).")


class TransitionRequest(BaseModel):
    """Solicita una transición de estado para un paquete."""
    package_id: str
    target_state: str = Field(
        ...,
        description="Estado destino: listo_para_timbrar, timbrado o enviado.",
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def build_electronica_router() -> APIRouter:
    """Devuelve un APIRouter con endpoints /contabilidad/electronica/*.

    Sigue el patrón `build_*_router()` del proyecto.  No requiere auth
    por ser flujo de trabajo local (sin persistencia externa).
    """
    router = APIRouter(
        prefix="/contabilidad/electronica",
        tags=["contabilidad-electronica"],
    )

    # ---- POST /package ---------------------------------------------------
    @router.post(
        "/package",
        summary="Genera el paquete de contabilidad electrónica del mes.",
        response_model=None,
    )
    def generate_package_endpoint(req: PackageRequest):
        """Genera un paquete de contabilidad electrónica SAT para el período
        dado, incluyendo catálogo de cuentas, balanza de comprobación y sus
        hashes SHA-1.  Devuelve el paquete completo con un `package_id`
        único para consultas posteriores.
        """
        try:
            catalogo = CatalogoCuentas()
            mgr = ContabilidadElectronica(
                catalogo=catalogo,
                rfc=req.rfc,
                razon_social=req.razon_social,
                ejercicio=req.ejercicio,
                mes=req.mes,
            )
            asientos = [a.model_dump() for a in req.asientos]
            paquete = mgr.generar_paquete(
                asientos,
                saldos_iniciales=req.saldos_iniciales,
            )
            package_id = uuid.uuid4().hex[:12]
            _store_package(package_id, paquete, mgr)
            return {
                "ok": True,
                "package_id": package_id,
                "periodo": paquete["periodo"],
                "estado": paquete["estado"],
                "catalogo_cuentas": paquete["catalogo"]["cuentas"],
                "catalogo_sha1": paquete["catalogo"]["sha1"],
                "balanza_cuadrada": paquete["balanza"]["cuadrada"],
                "balanza_sha1": paquete["balanza"]["sha1"],
                "generado_en": paquete["generado_en"],
            }
        except (ValueError, TypeError) as e:
            raise HTTPException(
                status_code=422,
                detail=f"Error generando paquete: {type(e).__name__}: {e}",
            )

    # ---- POST /hash ------------------------------------------------------
    @router.post(
        "/hash",
        summary="Calcula el hash SHA-1 de un contenido (requisito SAT).",
        response_model=None,
    )
    def calculate_hash_endpoint(req: HashRequest):
        """Calcula el hash SHA-1 en hexadecimal del contenido enviado.
        El SAT exige SHA-1 como checksum del archivo de catálogo/balanza.
        """
        sha1 = ContabilidadElectronica.calcular_hash_sha1(
            req.content.encode("utf-8")
        )
        return {"ok": True, "sha1": sha1, "length": len(req.content)}

    # ---- GET /status/{package_id} ----------------------------------------
    @router.get(
        "/status/{package_id}",
        summary="Obtiene el estado de un paquete de contabilidad electrónica.",
        response_model=None,
    )
    def get_status_endpoint(package_id: str):
        """Devuelve el estado actual de un paquete previamente generado."""
        pkg = _get_package(package_id)
        paquete = pkg["paquete"]
        return {
            "ok": True,
            "package_id": package_id,
            "estado": pkg["estado"],
            "periodo": paquete.get("periodo"),
            "rfc": paquete.get("rfc"),
            "generado_en": paquete.get("generado_en"),
        }

    # ---- POST /transition ------------------------------------------------
    @router.post(
        "/transition",
        summary="Avanza el estado de un paquete de contabilidad electrónica.",
        response_model=None,
    )
    def transition_state_endpoint(req: TransitionRequest):
        """Transita el paquete al estado indicado.

        Transiciones válidas:
          borrador → listo_para_timbrar → timbrado → enviado
        """
        pkg = _get_package(req.package_id)
        current = pkg["estado"]

        # Validar que el target_state sea un estado válido
        if req.target_state not in ESTADOS:
            raise HTTPException(
                status_code=422,
                detail=f"Estado inválido: {req.target_state!r}. "
                       f"Estados válidos: {list(ESTADOS)}",
            )

        # Validar la transición
        valid_transitions = {
            "borrador": "listo_para_timbrar",
            "listo_para_timbrar": "timbrado",
            "timbrado": "enviado",
        }
        expected_next = valid_transitions.get(current)
        if expected_next is None:
            raise HTTPException(
                status_code=409,
                detail=f"El paquete ya está en estado terminal: {current!r}.",
            )
        if req.target_state != expected_next:
            raise HTTPException(
                status_code=422,
                detail=f"Transición inválida: {current!r} → {req.target_state!r}. "
                       f"El siguiente estado esperado es: {expected_next!r}.",
            )

        # Ejecutar la transición
        try:
            paquete = pkg["paquete"]
            mgr = ContabilidadElectronica(
                catalogo=CatalogoCuentas(),
                rfc=paquete.get("rfc", ""),
                ejercicio=paquete.get("ejercicio"),
                mes=paquete.get("mes"),
            )
            mgr.estado = current

            if req.target_state == "listo_para_timbrar":
                mgr.marcar_listo_para_timbrar()
            elif req.target_state == "timbrado":
                mgr.marcar_timbrado()
            elif req.target_state == "enviado":
                mgr.marcar_enviado()

            pkg["estado"] = mgr.estado_actual()
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

        return {
            "ok": True,
            "package_id": req.package_id,
            "estado_anterior": current,
            "estado_nuevo": pkg["estado"],
        }

    # ---- GET /summary/{package_id} ---------------------------------------
    @router.get(
        "/summary/{package_id}",
        summary="Resumen mensual de contabilidad electrónica.",
        response_model=None,
    )
    def get_summary_endpoint(package_id: str):
        """Devuelve el resumen mensual (totales debe/haber, cuentas,
        si cuadra) de un paquete previamente generado.
        """
        pkg = _get_package(package_id)
        paquete = pkg["paquete"]

        mgr = ContabilidadElectronica(
            catalogo=CatalogoCuentas(),
            rfc=paquete.get("rfc", ""),
            razon_social=paquete.get("razon_social", ""),
            ejercicio=paquete.get("ejercicio"),
            mes=paquete.get("mes"),
        )
        mgr.estado = pkg["estado"]
        mgr._paquete = paquete

        resumen = mgr.generar_resumen_mensual(paquete=paquete)
        resumen["package_id"] = package_id
        return {"ok": True, "summary": resumen}

    return router
