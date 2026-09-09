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

import json
import time
import uuid as _uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from b2b_ai.db.db import Database
from b2b_ai.features.alertas.deadline_engine import (
    MEXICO_HOLIDAYS_2026,
    is_business_day,
)
from b2b_ai.features.diot.models import TipoOperacion

from .models import (
    ClasificacionIVA,
    ConciliacionDIOTDeclaracion,
    ConciliacionFacturasDIOT,
    DeclaracionMensual,
    DIOTEntry,
    EstadoEnvioSolicitud,
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
# Persistencia (REQ-IVA-006)
# ---------------------------------------------------------------------------
#
# Antes, `_solicitudes`, `_status` y `_papeles_trabajo` eran dicts de
# proceso: cualquier reinicio del proceso (deploy, crash, restart de un
# worker) borraba TODAS las solicitudes de devolución de IVA ya
# presentadas, sin dejar rastro. Ahora se leen/escriben desde las tablas
# `devolucion_iva_solicitudes` y `devolucion_iva_papeles_trabajo`
# (REQ-IVA-005: `b2b_ai/db/models.py` MIGRATIONS v21 para SQLite dev/test;
# `migrations/versions/0010_devolucion_iva_persistencia.py` +
# `0011_devolucion_iva_seguimiento.py` para PostgreSQL vía Alembic).
#
# `_solicitudes`/`_status`/`_papeles_trabajo` se conservan como nombres de
# módulo (proxies sin estado propio) únicamente por compatibilidad con
# código/tests existentes que hacían `_solicitudes.clear()` para aislar
# pruebas — la fuente de verdad es siempre la tabla, nunca estos objetos.

# Tenant usado cuando el llamador no especifica uno explícito. La API de
# este módulo nunca exigió `tenant_id` (varias funciones lo reciben como
# `Optional[str] = None`); las columnas `tenant_id` de las tablas de
# REQ-IVA-005 son NOT NULL a nivel de esquema (blindaje multi-tenant),
# así que una solicitud "sin tenant" se guarda bajo este valor visible en
# vez de dejar la columna nula o inventar un tenant real.
_DEFAULT_TENANT = "SIN_TENANT"

_DEFAULT_DB: Optional[Database] = None


def _get_default_db() -> Database:
    """Base compartida (en memoria) para llamadas sin `db=` explícito.

    Reproduce, para el código/tests que no pasan `db`, el mismo
    comportamiento que tenían los dicts de módulo: un único almacén
    compartido durante la vida del proceso. Para que la persistencia
    sobreviva un reinicio real del proceso hay que pasar un
    `Database(<ruta-de-archivo-o-DSN>)` explícito (vía
    `DevolucionIVAService(db=...)` o el parámetro `db=` de cada función),
    nunca depender de este singleton en memoria.
    """
    global _DEFAULT_DB
    if _DEFAULT_DB is None:
        _DEFAULT_DB = Database(":memory:", migrate=False)
        _ensure_schema(_DEFAULT_DB)
    return _DEFAULT_DB


def _ensure_schema(db: Database) -> None:
    """Garantiza que las tablas de devolución de IVA existan (idempotente).

    En PostgreSQL el esquema lo gestiona Alembic (ver migrations/versions/
    0010_devolucion_iva_persistencia.py y 0011_devolucion_iva_seguimiento.py)
    — aquí no hacemos nada. Esta defensa cubre SQLite `:memory:` y bases
    creadas con `migrate=False` (mismo patrón que
    `document_management/service.py::_ensure_schema`).
    """
    if db._is_pg:
        return
    try:
        row = db.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='devolucion_iva_solicitudes'"
        ).fetchone()
    except Exception:  # noqa: BLE001
        return
    if row:
        return
    from b2b_ai.db.models import MIGRATIONS
    for m in MIGRATIONS:
        if m["version"] == 21:
            db.conn.executescript(m["sql"])
            db.conn.commit()
            return


class _StoreClearProxy:
    """Compat: expone `.clear()` sobre una tabla DB-backed.

    Existe solo para que código/tests preexistentes que hacían
    `_solicitudes.clear()` / `_status.clear()` (asumiendo dicts de
    proceso) sigan funcionando tal cual — ahora vacían la tabla real en
    vez de un dict. No guarda ningún estado propio: `.clear()` siempre
    opera sobre la base compartida por defecto (`_get_default_db()`),
    igual que las funciones de módulo cuando se llaman sin `db=`.
    """

    def __init__(self, table: str):
        self._table = table

    def clear(self) -> None:
        db = _get_default_db()
        _ensure_schema(db)
        db.conn.execute(f"DELETE FROM {self._table}")
        db.conn.commit()


# `_status` vive en las mismas filas que `_solicitudes` (una solicitud y
# su seguimiento son 1:1) — limpiar cualquiera de los dos vacía la tabla.
_solicitudes = _StoreClearProxy("devolucion_iva_solicitudes")
_status = _StoreClearProxy("devolucion_iva_solicitudes")
_papeles_trabajo = _StoreClearProxy("devolucion_iva_papeles_trabajo")


def _fetch_solicitud_row(db: Database, solicitud_id: str):
    return db.conn.execute(
        "SELECT * FROM devolucion_iva_solicitudes WHERE id = ?",
        (solicitud_id,),
    ).fetchone()


def _row_to_solicitud(row: Any) -> SolicitudDevolucion:
    return SolicitudDevolucion(
        solicitud_id=row["id"],
        periodo=row["periodo"],
        monto_solicitado=row["monto_solicitado"],
        tenant_id=row["tenant_id"],
        cuenta_banco=row["cuenta_banco"],
        clabe=row["clabe"],
        documentos=json.loads(row["documentos"] or "[]"),
        status=EstatusDevolucion(row["status"]),
        estado=(
            EstadoEnvioSolicitud(row["estado"])
            if row["estado"] else EstadoEnvioSolicitud.LISTA_PARA_ENVIO
        ),
        motivo_aclaracion=row["motivo_aclaracion"],
        created_at=row["created_at"],
    )


def _row_to_status(row: Any) -> StatusDevolucion:
    return StatusDevolucion(
        solicitud_id=row["id"],
        status=EstatusDevolucion(row["status"]),
        fecha_presentacion=row["fecha_presentacion"],
        fecha_respuesta=row["fecha_respuesta"],
        monto_aprobado=row["monto_aprobado"],
        observaciones=row["observaciones"],
    )


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
        # For DIOT of compras, we group by RFC proveedor (rfc_emisor).
        # tipo_operacion must be a real code from the shared DIOT catalog
        # (b2b_ai.features.diot.models.TipoOperacion) — "01" is not a
        # valid SAT DIOT tipo de operación and was a hardcoded invention.
        # REQ-IVA-017 tracks verifying this shared catalog against the
        # official SAT/RMF source (Anexo 19); until then this is the best
        # available real code for a standard gravada purchase.
        key = (f.rfc_emisor, TipoOperacion.GASTOS_GENERAL.value)
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

# REQ-IVA-010: por encima de este monto, exigir congruencia DIOT↔CFDI↔
# declaración mensual antes de dejar la solicitud lista para envío.
UMBRAL_CONGRUENCIA_MONTO = 10001.00  # MXN

# REQ-IVA-010: tolerancia absoluta de redondeo (NO porcentual, a diferencia
# de `validate_diot_consistency`/`validate_declaration_consistency` que
# usan un margen relativo del 5% para advertencias generales).
TOLERANCIA_CONGRUENCIA_MXN = 1.00  # MXN


def validar_congruencia_diot_cfdi_declaracion(
    periodo: str,
    facturas: Optional[List[FacturaCFDI]] = None,
    diot_entries: Optional[List[DIOTEntry]] = None,
    declaraciones: Optional[List[DeclaracionMensual]] = None,
    tolerancia: float = TOLERANCIA_CONGRUENCIA_MXN,
) -> Dict[str, Any]:
    """REQ-IVA-010 — Congruencia de totales agrupados DIOT↔CFDI↔declaración.

    Compara, para el `periodo` dado, el IVA acreditable agregado de:
      - Facturas CFDI del periodo (``f.iva * f.proporcionalidad``).
      - Entradas DIOT (``iva_acreditable``) — se asume que el llamador ya
        entrega las entradas correspondientes al periodo (mismo patrón que
        el resto del módulo: la DIOT no trae su propio campo de periodo).
      - Declaración mensual del periodo (``iva_pagado``, que el modelo
        `DeclaracionMensual` documenta como "IVA pagado / acreditable en
        compras").

    No existe DIOT del periodo cuando ``diot_entries`` es vacío o ``None``
    — en ese caso el resultado nunca es congruente, sin importar los demás
    totales.

    Returns
    -------
    dict con, entre otros: ``diot_existe``, ``diferencia_maxima`` y
    ``congruente`` (True solo si hay DIOT del periodo Y la diferencia
    máxima entre los tres totales no excede ``tolerancia`` MXN).
    """
    facturas = facturas or []
    diot_entries = diot_entries or []
    declaraciones = declaraciones or []

    diot_existe = len(diot_entries) > 0

    total_cfdi = round(
        sum(
            f.iva * f.proporcionalidad
            for f in facturas
            if not periodo or (f.fecha and f.fecha[:7] == periodo)
        ),
        2,
    )
    total_diot = round(sum(e.iva_acreditable for e in diot_entries), 2)

    declaraciones_periodo = [
        d for d in declaraciones
        if not periodo or f"{d.año:04d}-{d.mes:02d}" == periodo
    ]
    declaracion_existe = len(declaraciones_periodo) > 0
    total_declaracion = round(sum(d.iva_pagado for d in declaraciones_periodo), 2)

    diferencia_cfdi_diot = round(abs(total_cfdi - total_diot), 2)
    diferencia_diot_declaracion = round(abs(total_diot - total_declaracion), 2)
    diferencia_maxima = round(max(diferencia_cfdi_diot, diferencia_diot_declaracion), 2)

    congruente = diot_existe and diferencia_maxima <= tolerancia

    return {
        "periodo": periodo,
        "diot_existe": diot_existe,
        "declaracion_existe": declaracion_existe,
        "total_cfdi_iva_acreditable": total_cfdi,
        "total_diot_iva_acreditable": total_diot,
        "total_declaracion_iva_pagado": total_declaracion,
        "diferencia_cfdi_diot": diferencia_cfdi_diot,
        "diferencia_diot_declaracion": diferencia_diot_declaracion,
        "diferencia_maxima": diferencia_maxima,
        "tolerancia": tolerancia,
        "congruente": congruente,
    }


def preparar_solicitud(
    periodo: str,
    saldo: Dict[str, Any],
    cuenta_banco: Optional[str] = None,
    clabe: Optional[str] = None,
    documentos: Optional[List[str]] = None,
    tenant_id: Optional[str] = None,
    facturas: Optional[List[FacturaCFDI]] = None,
    diot_entries: Optional[List[DIOTEntry]] = None,
    declaraciones: Optional[List[DeclaracionMensual]] = None,
) -> SolicitudDevolucion:
    """Prepare a refund request for submission to SAT.

    Validates inputs and creates a SolicitudDevolucion.

    REQ-IVA-010: cuando ``monto_solicitado`` supera
    ``UMBRAL_CONGRUENCIA_MONTO`` ($10,001.00 MXN), corre automáticamente
    la validación de congruencia DIOT↔CFDI↔declaración mensual
    (`validar_congruencia_diot_cfdi_declaracion`). Si la DIOT del periodo
    no existe o la diferencia entre los totales agrupados supera
    ``TOLERANCIA_CONGRUENCIA_MXN`` ($1.00 MXN de redondeo), la solicitud
    se crea con ``estado=EstadoEnvioSolicitud.REQUIERE_ACLARACION`` en vez
    de ``LISTA_PARA_ENVIO`` — nunca se bloquea la creación de la solicitud
    ni se reduce el monto automáticamente (ADR-4): solo se marca para
    revisión humana antes de enviarse al SAT.
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

    monto_redondeado = round(monto, 2)

    estado = EstadoEnvioSolicitud.LISTA_PARA_ENVIO
    motivo_aclaracion: Optional[str] = None

    if monto_redondeado > UMBRAL_CONGRUENCIA_MONTO:
        congruencia = validar_congruencia_diot_cfdi_declaracion(
            periodo,
            facturas=facturas,
            diot_entries=diot_entries,
            declaraciones=declaraciones,
        )
        if not congruencia["congruente"]:
            estado = EstadoEnvioSolicitud.REQUIERE_ACLARACION
            if not congruencia["diot_existe"]:
                motivo_aclaracion = (
                    f"No existe DIOT registrada para el periodo {periodo}; "
                    "no se puede validar la congruencia requerida para "
                    f"montos superiores a ${UMBRAL_CONGRUENCIA_MONTO:,.2f} MXN."
                )
            else:
                motivo_aclaracion = (
                    "Diferencia de congruencia DIOT↔CFDI↔declaración de "
                    f"${congruencia['diferencia_maxima']:.2f} MXN supera la "
                    f"tolerancia de ${congruencia['tolerancia']:.2f} MXN "
                    f"(periodo {periodo})."
                )

    now = _now_iso()
    solicitud = SolicitudDevolucion(
        periodo=periodo,
        monto_solicitado=monto_redondeado,
        tenant_id=tenant_id,
        cuenta_banco=cuenta_banco,
        clabe=clabe,
        documentos=documentos or [],
        status=EstatusDevolucion.PENDIENTE,
        estado=estado,
        motivo_aclaracion=motivo_aclaracion,
        created_at=now,
    )

    return solicitud


# ---------------------------------------------------------------------------
# REQ-IVA-016 — Plazo de resolución (Art. 22 CFF)
# ---------------------------------------------------------------------------
#
# El SAT debe resolver una solicitud de devolución de IVA dentro de 40 días
# hábiles contados a partir de la presentación de la solicitud (Art. 22,
# quinto párrafo, CFF); el plazo se reduce a 20 días hábiles cuando el
# contribuyente dictamina sus estados financieros por contador público
# registrado, o garantiza el interés fiscal (mismo artículo).
#
# "Días hábiles" excluye sábados, domingos y el calendario oficial de días
# inhábiles del SAT (Art. 12 CFF: los plazos no corren en los días en que
# las oficinas de la autoridad fiscal permanezcan cerradas). Este módulo
# reutiliza el mismo calendario oficial (`MEXICO_HOLIDAYS_2026`) que ya usa
# `b2b_ai.features.alertas.deadline_engine` para el resto de los plazos
# fiscales del sistema, en vez de mantener un segundo calendario paralelo
# que pudiera desincronizarse de esa fuente.
DIAS_HABILES_PLAZO_RESOLUCION = 40
DIAS_HABILES_PLAZO_RESOLUCION_CON_DICTAMEN_O_GARANTIA = 20


def _parse_fecha(fecha: "str | date") -> date:
    """Acepta tanto `date` como texto ISO (`YYYY-MM-DD`)."""
    if isinstance(fecha, date):
        return fecha
    if isinstance(fecha, datetime):
        return fecha.date()
    return datetime.strptime(str(fecha)[:10], "%Y-%m-%d").date()


def sumar_dias_habiles(
    fecha_inicio: "str | date",
    num_dias_habiles: int,
    holidays: Optional[List[Tuple[int, int]]] = None,
) -> date:
    """Avanza `num_dias_habiles` días hábiles a partir de `fecha_inicio`.

    `fecha_inicio` se EXCLUYE del conteo (Art. 12 CFF: los plazos empiezan a
    correr a partir del día siguiente a aquel en que surta efectos la
    notificación/presentación); solo cuentan como "día hábil" los días que
    no son sábado, domingo, ni parte del calendario oficial de días
    inhábiles del SAT (`is_business_day` de
    `b2b_ai.features.alertas.deadline_engine`, con `MEXICO_HOLIDAYS_2026`
    por defecto).

    Una solicitud presentada un jueves da como resultado una fecha 40 días
    HÁBILES después (saltando fines de semana y días inhábiles), nunca 40
    días naturales.
    """
    if num_dias_habiles < 0:
        raise ValueError("num_dias_habiles no puede ser negativo.")

    dia = _parse_fecha(fecha_inicio)
    contados = 0
    while contados < num_dias_habiles:
        dia += timedelta(days=1)
        if is_business_day(dia, holidays):
            contados += 1
    return dia


def calcular_fecha_limite_resolucion(
    fecha_presentacion: "str | date",
    hay_dictamen_o_garantia: bool = False,
    holidays: Optional[List[Tuple[int, int]]] = None,
) -> date:
    """REQ-IVA-016 — Fecha límite para que el SAT resuelva (Art. 22 CFF).

    40 días hábiles desde `fecha_presentacion`; 20 días hábiles si
    `hay_dictamen_o_garantia=True` (dictamen de contador público registrado
    o garantía del interés fiscal). Solo cuenta días hábiles — ver
    `sumar_dias_habiles`.
    """
    dias = (
        DIAS_HABILES_PLAZO_RESOLUCION_CON_DICTAMEN_O_GARANTIA
        if hay_dictamen_o_garantia
        else DIAS_HABILES_PLAZO_RESOLUCION
    )
    return sumar_dias_habiles(fecha_presentacion, dias, holidays=holidays)


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

def registrar_solicitud(
    solicitud: SolicitudDevolucion, db: Optional[Database] = None,
) -> SolicitudDevolucion:
    """Store a refund request.

    REQ-IVA-006: persistido en la tabla `devolucion_iva_solicitudes`, no en
    un dict de proceso — sobrevive un reinicio del proceso entre el alta
    (este `registrar_solicitud`) y una consulta posterior
    (`consultar_status`/`generar_reporte_seguimiento`) desde una instancia
    nueva de `DevolucionIVAService`/`Database` apuntando al mismo archivo.
    """
    database = db or _get_default_db()
    _ensure_schema(database)

    tenant_key = solicitud.tenant_id or _DEFAULT_TENANT
    fecha_presentacion = (
        solicitud.created_at[:10] if solicitud.created_at else None
    )

    database.conn.execute(
        """INSERT INTO devolucion_iva_solicitudes
           (id, tenant_id, periodo, monto_solicitado, cuenta_banco, clabe,
            documentos, status, estado, motivo_aclaracion,
            fecha_presentacion, fecha_respuesta, monto_aprobado,
            observaciones, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            solicitud.solicitud_id,
            tenant_key,
            solicitud.periodo,
            solicitud.monto_solicitado,
            solicitud.cuenta_banco,
            solicitud.clabe,
            json.dumps(solicitud.documentos),
            solicitud.status.value,
            solicitud.estado.value,
            solicitud.motivo_aclaracion,
            fecha_presentacion,
            None,
            None,
            None,
            solicitud.created_at,
        ),
    )
    database.conn.commit()

    return solicitud


def consultar_status(
    solicitud_id: str, db: Optional[Database] = None,
) -> Optional[StatusDevolucion]:
    """Check the status of a refund request (leído desde DB, REQ-IVA-006)."""
    database = db or _get_default_db()
    _ensure_schema(database)
    row = _fetch_solicitud_row(database, solicitud_id)
    if not row:
        return None
    return _row_to_status(row)


def generar_reporte_seguimiento(
    solicitud_id: str, db: Optional[Database] = None,
) -> Optional[Dict[str, Any]]:
    """Generate a status report for a refund request.

    Returns a structured dict with all tracking information, leído desde
    la tabla `devolucion_iva_solicitudes` (REQ-IVA-006).
    """
    database = db or _get_default_db()
    _ensure_schema(database)
    row = _fetch_solicitud_row(database, solicitud_id)
    if not row:
        return None

    solicitud = _row_to_solicitud(row)
    status = _row_to_status(row)

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
    db: Optional[Database] = None,
) -> Optional[StatusDevolucion]:
    """Update the status of a refund request (persistido, REQ-IVA-006)."""
    database = db or _get_default_db()
    _ensure_schema(database)
    row = _fetch_solicitud_row(database, solicitud_id)
    if not row:
        return None

    new_fecha_respuesta = fecha_respuesta if fecha_respuesta else row["fecha_respuesta"]
    new_monto_aprobado = (
        monto_aprobado if monto_aprobado is not None else row["monto_aprobado"]
    )
    new_observaciones = observaciones if observaciones else row["observaciones"]

    # Both StatusDevolucion.status and SolicitudDevolucion.status son la
    # misma columna `status` en esta tabla (siempre se mantuvieron en
    # sincronía en la versión anterior en memoria).
    database.conn.execute(
        """UPDATE devolucion_iva_solicitudes
           SET status = ?, fecha_respuesta = ?, monto_aprobado = ?,
               observaciones = ?
           WHERE id = ?""",
        (
            nuevo_status.value,
            new_fecha_respuesta,
            new_monto_aprobado,
            new_observaciones,
            solicitud_id,
        ),
    )
    database.conn.commit()

    updated_row = _fetch_solicitud_row(database, solicitud_id)
    return _row_to_status(updated_row)


def listar_solicitudes(
    tenant_id: Optional[str] = None, db: Optional[Database] = None,
) -> List[Dict[str, Any]]:
    """List refund requests, filtered by tenant when `tenant_id` is given.

    Cuando se pasa `tenant_id`, únicamente se devuelven las solicitudes
    cuyo `tenant_id` coincide exactamente (comparado a nivel de SQL, no en
    Python sobre un dict) — nunca se exponen solicitudes de otros tenants
    (aislamiento multi-tenant, REQ-IVA-007). Leído desde
    `devolucion_iva_solicitudes` (REQ-IVA-006).
    """
    database = db or _get_default_db()
    _ensure_schema(database)

    if tenant_id is not None:
        rows = database.conn.execute(
            "SELECT * FROM devolucion_iva_solicitudes WHERE tenant_id = ? "
            "ORDER BY created_at",
            (tenant_id,),
        ).fetchall()
    else:
        rows = database.conn.execute(
            "SELECT * FROM devolucion_iva_solicitudes ORDER BY created_at"
        ).fetchall()

    results = []
    for row in rows:
        results.append({
            "solicitud_id": row["id"],
            "tenant_id": row["tenant_id"],
            "periodo": row["periodo"],
            "monto_solicitado": row["monto_solicitado"],
            "status": row["status"],
            "fecha_presentacion": row["fecha_presentacion"],
            "monto_aprobado": row["monto_aprobado"],
            "created_at": row["created_at"],
        })
    return results


def registrar_papel_trabajo(
    papel: PapelTrabajo, db: Optional[Database] = None,
) -> PapelTrabajo:
    """Persist a working paper (REQ-IVA-006).

    Upsert por (tenant_id, periodo): recalcular el papel de trabajo de un
    periodo ya existente lo reemplaza, en vez de acumular versiones
    obsoletas del mismo periodo.
    """
    database = db or _get_default_db()
    _ensure_schema(database)

    tenant_key = papel.tenant_id or _DEFAULT_TENANT
    # `created_at` es NOT NULL en la tabla (todas las filas persistidas
    # necesitan una fecha de creación real); `generar_papel_trabajo()` ya
    # lo rellena, pero un `PapelTrabajo` construido a mano (tests, u otro
    # llamador) puede dejarlo en None — se completa aquí en vez de
    # rechazar el registro.
    created_at = papel.created_at or _now_iso()
    facturas_json = json.dumps([f.model_dump() for f in papel.facturas])
    diot_json = json.dumps([e.model_dump() for e in papel.diot_entries])
    declaraciones_json = json.dumps([d.model_dump() for d in papel.declaraciones])

    existing = database.conn.execute(
        "SELECT id FROM devolucion_iva_papeles_trabajo "
        "WHERE tenant_id = ? AND periodo = ?",
        (tenant_key, papel.periodo),
    ).fetchone()

    if existing:
        database.conn.execute(
            """UPDATE devolucion_iva_papeles_trabajo
               SET facturas = ?, diot_entries = ?, declaraciones = ?,
                   saldo_a_favor = ?, monto_solicitado = ?, status = ?,
                   created_at = ?
               WHERE id = ?""",
            (
                facturas_json, diot_json, declaraciones_json,
                papel.saldo_a_favor, papel.monto_solicitado, papel.status,
                created_at, existing["id"],
            ),
        )
    else:
        database.conn.execute(
            """INSERT INTO devolucion_iva_papeles_trabajo
               (id, tenant_id, periodo, facturas, diot_entries,
                declaraciones, saldo_a_favor, monto_solicitado, status,
                created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                papel.id, tenant_key, papel.periodo,
                facturas_json, diot_json, declaraciones_json,
                papel.saldo_a_favor, papel.monto_solicitado, papel.status,
                created_at,
            ),
        )
    database.conn.commit()
    return papel


def obtener_papel_trabajo(
    periodo: str,
    tenant_id: Optional[str] = None,
    db: Optional[Database] = None,
) -> Optional[PapelTrabajo]:
    """Retrieve a persisted working paper by (periodo, tenant_id).

    REQ-IVA-006: leído desde `devolucion_iva_papeles_trabajo`, no desde un
    dict de proceso.
    """
    database = db or _get_default_db()
    _ensure_schema(database)
    tenant_key = tenant_id or _DEFAULT_TENANT

    row = database.conn.execute(
        "SELECT * FROM devolucion_iva_papeles_trabajo "
        "WHERE tenant_id = ? AND periodo = ?",
        (tenant_key, periodo),
    ).fetchone()
    if not row:
        return None

    return PapelTrabajo(
        id=row["id"],
        periodo=row["periodo"],
        tenant_id=(row["tenant_id"] if row["tenant_id"] != _DEFAULT_TENANT else None),
        facturas=[FacturaCFDI(**f) for f in json.loads(row["facturas"] or "[]")],
        diot_entries=[DIOTEntry(**e) for e in json.loads(row["diot_entries"] or "[]")],
        declaraciones=[
            DeclaracionMensual(**d) for d in json.loads(row["declaraciones"] or "[]")
        ],
        saldo_a_favor=row["saldo_a_favor"],
        monto_solicitado=row["monto_solicitado"],
        status=row["status"],
        created_at=row["created_at"],
    )


# ---------------------------------------------------------------------------
# Service class — wraps module-level functions for router use
# ---------------------------------------------------------------------------

class DevolucionIVAService:
    """High-level service class wrapping all IVA refund operations.

    Used by the FastAPI router. Delegates to module-level functions.

    REQ-IVA-006: acepta un `Database` explícito (SQLite con ruta de
    archivo, o PostgreSQL) para que la persistencia de solicitudes/status/
    papeles de trabajo sobreviva un reinicio del proceso. Sin `db=`
    explícito usa la base compartida en memoria del módulo (mismo
    comportamiento histórico para código/tests que no pasan `db`).
    """

    def __init__(self, db: Optional[Database] = None):
        self.db = db if db is not None else _get_default_db()
        _ensure_schema(self.db)

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
        tenant_id: Optional[str] = None,
        facturas: Optional[List[dict | FacturaCFDI]] = None,
        diot_entries: Optional[List[dict | DIOTEntry]] = None,
        declaraciones: Optional[List[dict | DeclaracionMensual]] = None,
    ) -> SolicitudDevolucion:
        f_typed = self._coerce_facturas(facturas)
        d_typed = self._coerce_diot(diot_entries)
        decl_typed = self._coerce_declaraciones(declaraciones)
        return preparar_solicitud(
            periodo,
            saldo,
            cuenta_banco,
            clabe,
            tenant_id=tenant_id,
            facturas=f_typed,
            diot_entries=d_typed,
            declaraciones=decl_typed,
        )

    def registrar(self, solicitud: SolicitudDevolucion) -> SolicitudDevolucion:
        return registrar_solicitud(solicitud, db=self.db)

    def consultar_status(self, solicitud_id: str) -> Optional[StatusDevolucion]:
        return consultar_status(solicitud_id, db=self.db)

    def generar_reporte(self, solicitud_id: str) -> Optional[Dict[str, Any]]:
        return generar_reporte_seguimiento(solicitud_id, db=self.db)

    def actualizar_status(
        self,
        solicitud_id: str,
        nuevo_status: EstatusDevolucion,
        fecha_respuesta: Optional[str] = None,
        monto_aprobado: Optional[float] = None,
        observaciones: Optional[str] = None,
    ) -> Optional[StatusDevolucion]:
        return actualizar_status(
            solicitud_id, nuevo_status,
            fecha_respuesta=fecha_respuesta,
            monto_aprobado=monto_aprobado,
            observaciones=observaciones,
            db=self.db,
        )

    def listar(self, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return listar_solicitudes(tenant_id=tenant_id, db=self.db)

    def generar_papel_trabajo(
        self,
        periodo: str,
        facturas: List[dict | FacturaCFDI],
        diot_entries: List[dict | DIOTEntry],
        declaraciones: List[dict | DeclaracionMensual],
        saldo: float,
        monto: float,
        tenant_id: Optional[str] = None,
    ) -> PapelTrabajo:
        f_typed = self._coerce_facturas(facturas)
        d_typed = self._coerce_diot(diot_entries)
        decl_typed = self._coerce_declaraciones(declaraciones)
        return generar_papel_trabajo(
            periodo, f_typed, d_typed, decl_typed, saldo, monto,
            tenant_id=tenant_id,
        )

    def registrar_papel_trabajo(self, papel: PapelTrabajo) -> PapelTrabajo:
        return registrar_papel_trabajo(papel, db=self.db)

    def obtener_papel_trabajo(
        self, periodo: str, tenant_id: Optional[str] = None,
    ) -> Optional[PapelTrabajo]:
        return obtener_papel_trabajo(periodo, tenant_id=tenant_id, db=self.db)

    def calcular_fecha_limite_resolucion(
        self,
        fecha_presentacion: "str | date",
        hay_dictamen_o_garantia: bool = False,
    ) -> date:
        """REQ-IVA-016 — ver `calcular_fecha_limite_resolucion` de módulo."""
        return calcular_fecha_limite_resolucion(
            fecha_presentacion, hay_dictamen_o_garantia=hay_dictamen_o_garantia,
        )

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
