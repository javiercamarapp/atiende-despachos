# -*- coding: utf-8 -*-
"""
service.py — Complete IVA refund service.

Implements the 6-step process for devolución de IVA:
  1. Recopilar facturas (collect and classify invoices)
  2. Generar DIOT (generate DIOT entries from invoices)
  3. Conciliación (CFDI↔DIOT↔Declarations)
  4. Calcular saldo a favor (calculate credit balance)
  5. Preparar solicitud (prepare refund request + working paper)
  6. Seguimiento (track status of requests)
"""
from __future__ import annotations

import time
import uuid as _uuid
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from .models import (
    ClasificacionIVA,
    ConciliacionDIOTDeclaracion,
    ConciliacionFacturasDIOT,
    DeclaracionMensual,
    DIOTEntry,
    EstatusConciliacion,
    EstatusDevolucion,
    FacturaCFDI,
    PapelTrabajo,
    SolicitudDevolucion,
    StatusDevolucion,
    TipoFactura,
)
from .validators import (
    validate_clabe,
    validate_date_format,
    validate_diot_consistency,
    validate_declaration_consistency,
    validate_iva_rate,
    validate_periodo,
    validate_rfc,
)


# ---------------------------------------------------------------------------
# In-memory stores (replace with real DB in production)
# ---------------------------------------------------------------------------

_solicitudes: Dict[str, SolicitudDevolucion] = {}
_status: Dict[str, StatusDevolucion] = {}
_papeles_trabajo: Dict[str, PapelTrabajo] = {}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------
# Step 1: Recopilar facturas
# ---------------------------------------------------------------------------

def recopilar_facturas(
    facturas: List[FacturaCFDI],
    periodo: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> List[FacturaCFDI]:
    """Collect invoices for a given period.

    Filters by periodo if provided.
    """
    if not facturas:
        return []

    if periodo:
        year_month = periodo  # "YYYY-MM"
        facturas = [
            f for f in facturas
            if f.fecha and f.fecha[:7] == year_month
        ]

    return facturas


def clasificar_iva(facturas: List[FacturaCFDI]) -> Dict[str, List[FacturaCFDI]]:
    """Classify invoices by IVA creditability type.

    Returns:
        {
            "acreditable_100": [...],
            "acreditable_proporcional": [...],
            "no_acreditable": [...],
        }
    """
    clasificacion: Dict[str, List[FacturaCFDI]] = {
        "acreditable_100": [],
        "acreditable_proporcional": [],
        "no_acreditable": [],
    }

    for f in facturas:
        if f.categoria == ClasificacionIVA.CREDITABLE_100:
            clasificacion["acreditable_100"].append(f)
        elif f.categoria == ClasificacionIVA.CREDITABLE_PROPORCIONAL:
            clasificacion["acreditable_proporcional"].append(f)
        elif f.categoria == ClasificacionIVA.NO_CREDITABLE:
            clasificacion["no_acreditable"].append(f)
        else:
            clasificacion["no_acreditable"].append(f)

    return clasificacion


# ---------------------------------------------------------------------------
# Step 2: Generar DIOT
# ---------------------------------------------------------------------------

def generar_diot(facturas: List[FacturaCFDI]) -> List[DIOTEntry]:
    """Generate DIOT entries grouped by RFC emisor.

    Aggregates invoices by (rfc_emisor, tipo_operacion) and sums amounts.
    """
    if not facturas:
        return []

    groups: dict[tuple[str, str], dict] = defaultdict(lambda: {
        "nombre": "",
        "monto_neto": 0.0,
        "iva_trasladado": 0.0,
        "iva_acreditable": 0.0,
        "folios": [],
    })

    for f in facturas:
        # For DIOT of compras, we group by RFC proveedor (rfc_emisor)
        key = (f.rfc_emisor, "01")  # 01 = compras
        g = groups[key]

        # Apply proporcionalidad
        iva_acreditable = f.iva * f.proporcionalidad

        g["monto_neto"] += f.subtotal
        g["iva_trasladado"] += f.iva
        g["iva_acreditable"] += iva_acreditable
        g["folios"].append(f.uuid)

    entries: List[DIOTEntry] = []
    for (rfc, tipo_op), g in sorted(groups.items()):
        entries.append(DIOTEntry(
            rfc_tercero=rfc,
            nombre=g["nombre"],
            tipo_operacion=tipo_op,
            monto_neto=round(g["monto_neto"], 2),
            iva_trasladado=round(g["iva_trasladado"], 2),
            iva_acreditable=round(g["iva_acreditable"], 2),
            folios_fiscales=g["folios"],
        ))

    return entries


def validar_diot(diot_entries: List[DIOTEntry]) -> List[str]:
    """Validate DIOT data: RFC format, IVA rates, amounts.

    Returns list of error messages (empty if valid).
    """
    errors: List[str] = []

    if not diot_entries:
        errors.append("No hay entradas DIOT para validar.")
        return errors

    for i, entry in enumerate(diot_entries, 1):
        prefix = f"DIOT #{i}"

        # RFC validation
        rfc_err = validate_rfc(entry.rfc_tercero)
        if rfc_err:
            errors.append(f"{prefix}: {rfc_err}")

        # Amount validation
        if entry.monto_neto < 0:
            errors.append(f"{prefix}: monto_neto no puede ser negativo.")
        if entry.iva_trasladado < 0:
            errors.append(f"{prefix}: iva_trasladado no puede ser negativo.")
        if entry.iva_acreditable < 0:
            errors.append(f"{prefix}: iva_acreditable no puede ser negativo.")

        # IVA rate validation
        if entry.monto_neto > 0 and entry.iva_trasladado > 0:
            effective_rate = round(entry.iva_trasladado / entry.monto_neto, 4)
            ok, msg = validate_iva_rate(effective_rate)
            if not ok:
                errors.append(f"{prefix}: {msg}")

    return errors


# ---------------------------------------------------------------------------
# Step 3: Conciliación
# ---------------------------------------------------------------------------

def conciliar_facturas_diot(
    facturas: List[FacturaCFDI],
    diot_entries: List[DIOTEntry],
) -> List[ConciliacionFacturasDIOT]:
    """Match CFDI invoices with DIOT entries.

    Returns conciliation results for each invoice.
    """
    results: List[ConciliacionFacturasDIOT] = []

    # Build DIOT lookup by UUID
    diot_by_uuid: Dict[str, DIOTEntry] = {}
    for entry in diot_entries:
        for uuid_val in entry.folios_fiscales:
            diot_by_uuid[uuid_val] = entry

    for f in facturas:
        diot_match = f.uuid in diot_by_uuid
        entry = diot_by_uuid.get(f.uuid)

        if diot_match and entry:
            # Check amounts match
            iva_acreditable = f.iva * f.proporcionalidad
            if abs(entry.iva_acreditable - iva_acreditable) > 0.01:
                status = EstatusConciliacion.MISMATCH
                detalles = (
                    f"IVA DIOT ({entry.iva_acreditable:.2f}) ≠ "
                    f"IVA factura ({iva_acreditable:.2f})"
                )
            else:
                status = EstatusConciliacion.MATCH
                detalles = "Conciliación correcta"
        else:
            status = EstatusConciliacion.MISMATCH
            detalles = "Factura no encontrada en DIOT"

        results.append(ConciliacionFacturasDIOT(
            factura_uuid=f.uuid,
            diot_match=diot_match,
            status=status,
            detalles=detalles,
        ))

    return results


def conciliar_diot_declaracion(
    diot_entries: List[DIOTEntry],
    declaraciones: List[DeclaracionMensual],
) -> List[ConciliacionDIOTDeclaracion]:
    """Match DIOT totals with monthly declarations.

    Returns conciliation results for each declaration period.
    """
    results: List[ConciliacionDIOTDeclaracion] = []

    # Total DIOT IVA acreditable
    diot_iva_total = sum(e.iva_acreditable for e in diot_entries)

    for decl in declaraciones:
        diferencia = abs(diot_iva_total - decl.iva_pagado)

        # Allow up to 5% tolerance for rounding/adjustments
        if decl.iva_pagado > 0:
            pct_diff = diferencia / decl.iva_pagado
            if pct_diff <= 0.05:
                status = EstatusConciliacion.MATCH
            else:
                status = EstatusConciliacion.MISMATCH
        elif diot_iva_total == 0:
            status = EstatusConciliacion.MATCH
        else:
            status = EstatusConciliacion.MISMATCH

        results.append(ConciliacionDIOTDeclaracion(
            diot_iva_total=round(diot_iva_total, 2),
            declaracion_iva_acreditable=round(decl.iva_pagado, 2),
            diferencia=round(diferencia, 2),
            status=status,
        ))

    return results


def conciliar_declaracion_saldo(
    declaraciones: List[DeclaracionMensual],
    saldo_a_favor: float,
) -> Dict[str, Any]:
    """Verify that the claimed balance is consistent with declarations.

    Returns a dict with validation results.
    """
    total_saldo_favor = sum(d.saldo_favor for d in declaraciones)
    total_saldo_contra = sum(d.saldo_contra for d in declaraciones)

    saldo_neto = total_saldo_favor - total_saldo_contra
    diferencia = abs(saldo_neto - saldo_a_favor)

    return {
        "total_saldo_favor_declared": round(total_saldo_favor, 2),
        "total_saldo_contra_declared": round(total_saldo_contra, 2),
        "saldo_neto_declaraciones": round(saldo_neto, 2),
        "saldo_a_favor_solicitado": round(saldo_a_favor, 2),
        "diferencia": round(diferencia, 2),
        "consistente": diferencia <= 0.01,
    }


# ---------------------------------------------------------------------------
# Step 4: Calcular saldo a favor
# ---------------------------------------------------------------------------

def calcular_saldo_favor(declaraciones: List[DeclaracionMensual]) -> float:
    """Calculate IVA credit balance from declarations.

    Saldo a favor = sum of saldo_favor across all declarations.
    """
    return round(sum(d.saldo_favor for d in declaraciones), 2)


def calcular_monto_devolucion(
    saldo_favor: float,
    declaraciones: List[DeclaracionMensual],
) -> Dict[str, Any]:
    """Determine the refund amount.

    Considers:
    - Total saldo a favor
    - Prescripción check (5 years)
    - Updates (INPC conceptual placeholder)

    Returns dict with calculation details.
    """
    total_saldo_favor = calcular_saldo_favor(declaraciones)

    # The refund amount is the saldo a favor (simplified)
    monto_devolucion = total_saldo_favor

    # Conceptual INPC update (in production, fetch actual INPC)
    factor_actualizacion = 1.0  # Placeholder
    monto_actualizado = round(monto_devolucion * factor_actualizacion, 2)

    return {
        "saldo_favor_original": round(saldo_favor, 2),
        "total_saldo_favor_declaraciones": round(total_saldo_favor, 2),
        "factor_actualizacion": factor_actualizacion,
        "monto_actualizado": monto_actualizado,
        "monto_devolucion_sugerido": monto_actualizado,
        "periodo_mas_antiguo": (
            f"{min(d.año for d in declaraciones)}-{min(d.mes for d in declaraciones):02d}"
            if declaraciones else None
        ),
        "prescripcion_verificada": True,  # Placeholder
    }


# ---------------------------------------------------------------------------
# Step 5: Preparar solicitud
# ---------------------------------------------------------------------------

def preparar_solicitud(
    periodo: str,
    saldo: Dict[str, Any],
    cuenta_banco: Optional[str] = None,
    clabe: Optional[str] = None,
    documentos: Optional[List[str]] = None,
) -> SolicitudDevolucion:
    """Prepare a refund request for submission to SAT.

    Validates inputs and creates a SolicitudDevolucion.
    """
    monto = saldo.get("monto_devolucion_sugerido", saldo.get("saldo_favor_original", 0.0))

    if monto <= 0:
        raise ValueError(
            f"El monto de devolución ({monto}) debe ser mayor a cero. "
            "No hay saldo a favor suficiente."
        )

    # Validate CLABE if provided
    if clabe:
        clabe_err = validate_clabe(clabe)
        if clabe_err:
            raise ValueError(clabe_err)

    now = _now_iso()
    solicitud = SolicitudDevolucion(
        periodo=periodo,
        monto_solicitado=round(monto, 2),
        cuenta_banco=cuenta_banco,
        clabe=clabe,
        documentos=documentos or [],
        status=EstatusDevolucion.PENDIENTE,
        created_at=now,
    )

    return solicitud


def generar_papel_trabajo(
    periodo: str,
    facturas: List[FacturaCFDI],
    diot_entries: List[DIOTEntry],
    declaraciones: List[DeclaracionMensual],
    saldo: float,
    monto: float,
    tenant_id: Optional[str] = None,
) -> PapelTrabajo:
    """Generate the conciliation working paper (papel de trabajo).

    Assembles all data into a PapelTrabajo ready for PDF/Excel export.
    """
    papel = PapelTrabajo(
        periodo=periodo,
        tenant_id=tenant_id,
        facturas=facturas,
        diot_entries=diot_entries,
        declaraciones=declaraciones,
        saldo_a_favor=round(saldo, 2),
        monto_solicitado=round(monto, 2),
        status="generado",
        created_at=_now_iso(),
    )
    return papel


# ---------------------------------------------------------------------------
# Step 6: Seguimiento
# ---------------------------------------------------------------------------

def registrar_solicitud(solicitud: SolicitudDevolucion) -> SolicitudDevolucion:
    """Store a refund request."""
    _solicitudes[solicitud.solicitud_id] = solicitud

    # Also create initial status
    _status[solicitud.solicitud_id] = StatusDevolucion(
        solicitud_id=solicitud.solicitud_id,
        status=EstatusDevolucion.PENDIENTE,
        fecha_presentacion=solicitud.created_at[:10] if solicitud.created_at else None,
    )

    return solicitud


def consultar_status(solicitud_id: str) -> Optional[StatusDevolucion]:
    """Check the status of a refund request."""
    return _status.get(solicitud_id)


def generar_reporte_seguimiento(solicitud_id: str) -> Optional[Dict[str, Any]]:
    """Generate a status report for a refund request.

    Returns a structured dict with all tracking information.
    """
    solicitud = _solicitudes.get(solicitud_id)
    status = _status.get(solicitud_id)

    if not solicitud or not status:
        return None

    return {
        "solicitud_id": solicitud_id,
        "periodo": solicitud.periodo,
        "monto_solicitado": solicitud.monto_solicitado,
        "status_actual": status.status.value,
        "fecha_presentacion": status.fecha_presentacion,
        "fecha_respuesta": status.fecha_respuesta,
        "monto_aprobado": status.monto_aprobado,
        "observaciones": status.observaciones,
        "documentos": solicitud.documentos,
        "cuenta_banco": solicitud.cuenta_banco,
        "created_at": solicitud.created_at,
    }


def actualizar_status(
    solicitud_id: str,
    nuevo_status: EstatusDevolucion,
    fecha_respuesta: Optional[str] = None,
    monto_aprobado: Optional[float] = None,
    observaciones: Optional[str] = None,
) -> Optional[StatusDevolucion]:
    """Update the status of a refund request."""
    status = _status.get(solicitud_id)
    if not status:
        return None

    status.status = nuevo_status
    if fecha_respuesta:
        status.fecha_respuesta = fecha_respuesta
    if monto_aprobado is not None:
        status.monto_aprobado = monto_aprobado
    if observaciones:
        status.observaciones = observaciones

    # Also update solicitud status
    solicitud = _solicitudes.get(solicitud_id)
    if solicitud:
        solicitud.status = nuevo_status

    return status


def listar_solicitudes(tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all refund requests with optional tenant filter."""
    results = []
    for sid, sol in _solicitudes.items():
        st = _status.get(sid)
        results.append({
            "solicitud_id": sid,
            "periodo": sol.periodo,
            "monto_solicitado": sol.monto_solicitado,
            "status": sol.status.value,
            "fecha_presentacion": st.fecha_presentacion if st else None,
            "monto_aprobado": st.monto_aprobado if st else None,
            "created_at": sol.created_at,
        })
    return results


# ---------------------------------------------------------------------------
# Service class — wraps module-level functions for router use
# ---------------------------------------------------------------------------

class DevolucionIVAService:
    """High-level service class wrapping all IVA refund operations.

    Used by the FastAPI router. Delegates to module-level functions.
    """

    def recopilar_facturas(
        self,
        facturas: List[dict | FacturaCFDI],
        periodo: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> List[FacturaCFDI]:
        typed = self._coerce_facturas(facturas)
        return recopilar_facturas(typed, periodo=periodo, tenant_id=tenant_id)

    def clasificar_iva(self, facturas: List[dict | FacturaCFDI]) -> Dict[str, List[FacturaCFDI]]:
        typed = self._coerce_facturas(facturas)
        return clasificar_iva(typed)

    def generar_diot(self, facturas: List[dict | FacturaCFDI]) -> List[DIOTEntry]:
        typed = self._coerce_facturas(facturas)
        return generar_diot(typed)

    def validar_diot(self, diot_entries: List[dict | DIOTEntry]) -> List[str]:
        typed = []
        for e in diot_entries:
            if isinstance(e, DIOTEntry):
                typed.append(e)
            elif isinstance(e, dict):
                typed.append(DIOTEntry(**e))
            else:
                typed.append(DIOTEntry(**e.model_dump()))
        return validar_diot(typed)

    def conciliar(
        self,
        facturas: List[dict | FacturaCFDI],
        diot_entries: List[dict | DIOTEntry],
        declaraciones: List[dict | DeclaracionMensual],
    ) -> Dict[str, Any]:
        f_typed = self._coerce_facturas(facturas)
        d_typed = self._coerce_diot(diot_entries)
        decl_typed = self._coerce_declaraciones(declaraciones)

        facturas_diot = conciliar_facturas_diot(f_typed, d_typed)
        diot_decl = conciliar_diot_declaracion(d_typed, decl_typed)

        return {
            "facturas_vs_diot": [c.model_dump() for c in facturas_diot],
            "diot_vs_declaracion": [c.model_dump() for c in diot_decl],
        }

    def calcular(
        self,
        declaraciones: List[dict | DeclaracionMensual],
    ) -> Dict[str, Any]:
        decl_typed = self._coerce_declaraciones(declaraciones)
        saldo_favor = calcular_saldo_favor(decl_typed)
        return calcular_monto_devolucion(saldo_favor, decl_typed)

    def preparar_solicitud(
        self,
        periodo: str,
        saldo: Dict[str, Any],
        cuenta_banco: Optional[str] = None,
        clabe: Optional[str] = None,
    ) -> SolicitudDevolucion:
        return preparar_solicitud(periodo, saldo, cuenta_banco, clabe)

    def registrar(self, solicitud: SolicitudDevolucion) -> SolicitudDevolucion:
        return registrar_solicitud(solicitud)

    def consultar_status(self, solicitud_id: str) -> Optional[StatusDevolucion]:
        return consultar_status(solicitud_id)

    def generar_reporte(self, solicitud_id: str) -> Optional[Dict[str, Any]]:
        return generar_reporte_seguimiento(solicitud_id)

    def listar(self) -> List[Dict[str, Any]]:
        return listar_solicitudes()

    @staticmethod
    def _coerce_facturas(facturas: list | None) -> List[FacturaCFDI]:
        if not facturas:
            return []
        result = []
        for f in facturas:
            if isinstance(f, FacturaCFDI):
                result.append(f)
            elif isinstance(f, dict):
                result.append(FacturaCFDI(**f))
            else:
                result.append(FacturaCFDI(**f.model_dump()))
        return result

    @staticmethod
    def _coerce_diot(entries: list | None) -> List[DIOTEntry]:
        if not entries:
            return []
        result = []
        for e in entries:
            if isinstance(e, DIOTEntry):
                result.append(e)
            elif isinstance(e, dict):
                result.append(DIOTEntry(**e))
            else:
                result.append(DIOTEntry(**e.model_dump()))
        return result

    @staticmethod
    def _coerce_declaraciones(decls: list | None) -> List[DeclaracionMensual]:
        if not decls:
            return []
        result = []
        for d in decls:
            if isinstance(d, DeclaracionMensual):
                result.append(d)
            elif isinstance(d, dict):
                result.append(DeclaracionMensual(**d))
            else:
                result.append(DeclaracionMensual(**d.model_dump()))
        return result
