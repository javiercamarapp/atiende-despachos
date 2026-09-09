# -*- coding: utf-8 -*-
"""
models.py — Pydantic schemas for the Devolución de IVA module.

All models use pydantic v2 (BaseModel) with Field for descriptions.
These represent the complete data flow for IVA refund processing:
  CFDI invoices → DIOT entries → Declarations → Conciliation → Solicitud.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

from b2b_ai.cfdi.catalogs import is_valid_forma_pago, is_valid_metodo_pago


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class EstatusConciliacion(str, Enum):
    """Estado de una conciliación."""
    MATCH = "match"
    MISMATCH = "mismatch"
    MISSING = "missing"


class EstatusDevolucion(str, Enum):
    """Estatus de una solicitud de devolución ante el SAT."""
    PENDIENTE = "pendiente"
    EN_REVISION = "en_revision"
    APROBADA = "aprobada"
    RECHAZADA = "rechazada"
    PAGADA = "pagada"


class EstadoEnvioSolicitud(str, Enum):
    """Estado de congruencia de una solicitud ANTES de enviarse al SAT.

    REQ-IVA-010: distinto de `EstatusDevolucion` (que describe el ciclo de
    vida de la solicitud ya presentada ante el SAT). Este estado señala si
    la solicitud pasó la validación automática de congruencia
    DIOT↔CFDI↔declaración mensual, obligatoria cuando `monto_solicitado`
    supera $10,001.00 MXN.
    """
    LISTA_PARA_ENVIO = "lista_para_envio"
    REQUIERE_ACLARACION = "requiere_aclaracion"


class TipoFactura(str, Enum):
    """Tipo de factura CFDI."""
    INGRESO = "Ingreso"
    EGRESO = "Egreso"
    TRASLADO = "Traslado"
    NOMINA = "Nómina"
    PAGO = "Pago"


class ClasificacionIVA(str, Enum):
    """Clasificación de acreditamiento de IVA."""
    CREDITABLE_100 = "acreditable_100"
    CREDITABLE_PROPORCIONAL = "acreditable_proporcional"
    NO_CREDITABLE = "no_acreditable"


# ---------------------------------------------------------------------------
# Core schemas — FacturaCFDI
# ---------------------------------------------------------------------------

class FacturaCFDI(BaseModel):
    """Representa una factura CFDI para el proceso de devolución de IVA."""
    uuid: str = Field(..., description="UUID del CFDI (folio fiscal)")
    rfc_emisor: str = Field(..., description="RFC del emisor")
    nombre_emisor: str = Field(
        default="",
        description=(
            "Nombre o razón social del emisor/proveedor. Requerido "
            "(no vacío) para exportar el FED anexo 7/7-A (REQ-IVA-014)."
        ),
    )
    rfc_receptor: str = Field(..., description="RFC del receptor")
    fecha: str = Field(..., description="Fecha de la factura (YYYY-MM-DD)")
    subtotal: float = Field(..., description="Subtotal de la factura (sin IVA)")
    iva: float = Field(default=0.0, description="IVA trasladado")
    total: float = Field(default=0.0, description="Total de la factura")
    tipo: TipoFactura = Field(
        default=TipoFactura.INGRESO,
        description="Tipo de comprobante fiscal",
    )
    categoria: ClasificacionIVA = Field(
        default=ClasificacionIVA.CREDITABLE_100,
        description="Clasificación de acreditamiento del IVA",
    )
    banco_pago: Optional[str] = Field(
        default=None,
        description="Banco donde se efectuó el pago",
    )
    fecha_pago: Optional[str] = Field(
        default=None,
        description="Fecha en que se efectuó el pago (YYYY-MM-DD)",
    )
    proporcionalidad: float = Field(
        default=1.0,
        description="Proporción de acreditamiento (0.0 a 1.0)",
    )

    # -----------------------------------------------------------------
    # REQ-IVA-008 — campos requeridos para marcar la factura como
    # "lista para anexo 7/7-A" del trámite de devolución de IVA.
    # Son opcionales a nivel de modelo (no toda factura del periodo
    # necesita estar lista de inmediato) pero `marcar_lista_para_anexo7()`
    # exige los 4 no nulos, y `iva_acreditable_efectivamente_pagado`
    # exige `referencia_complemento_pago` (LIVA Art. 5 fracc. III).
    # -----------------------------------------------------------------
    folio_factura: Optional[str] = Field(
        default=None,
        description=(
            "Folio de la factura (serie+folio interno del emisor). "
            "Distinto del UUID/folio fiscal."
        ),
    )
    forma_pago: Optional[str] = Field(
        default=None,
        description="Clave c_FormaPago del SAT (Anexo 20), p.ej. '03' transferencia.",
    )
    metodo_pago: Optional[str] = Field(
        default=None,
        description="Clave c_MetodoPago del SAT: 'PUE' o 'PPD'.",
    )
    referencia_complemento_pago: Optional[str] = Field(
        default=None,
        description=(
            "UUID del Recibo Electrónico de Pago (REP / complemento de pago) "
            "que ampara el pago efectivo de esta factura."
        ),
    )
    concepto: Optional[str] = Field(
        default=None,
        description=(
            "Concepto de la factura (descripción de los conceptos del CFDI, "
            "p.ej. la 'Descripcion' de los nodos Concepto). Petición "
            "explícita del despacho: debe viajar junto con folio fiscal, "
            "folio de factura, fecha de pago y banco en el desglose de "
            "proveedores DIOT (sección 2 del papel de trabajo) y en el "
            "anexo FED 7/7-A exportado."
        ),
    )

    @field_validator("uuid")
    @classmethod
    def _uuid_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("uuid no puede estar vacío")
        return v.strip()

    @field_validator("rfc_emisor", "rfc_receptor")
    @classmethod
    def _rfc_upper(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("RFC no puede estar vacío")
        return v.strip().upper()

    @field_validator("subtotal", "iva", "total")
    @classmethod
    def _amount_positive(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Los montos no pueden ser negativos")
        return v

    @field_validator("folio_factura", "referencia_complemento_pago", "concepto")
    @classmethod
    def _optional_str_not_blank(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("El valor no puede ser una cadena vacía; use None si no aplica.")
        return v

    @field_validator("forma_pago")
    @classmethod
    def _forma_pago_valida(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("forma_pago no puede ser una cadena vacía; use None si no aplica.")
        if not is_valid_forma_pago(v):
            raise ValueError(
                f"forma_pago '{v}' no está en el catálogo c_FormaPago del SAT (Anexo 20)."
            )
        return v

    @field_validator("metodo_pago")
    @classmethod
    def _metodo_pago_valido(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip().upper()
        if not v:
            raise ValueError("metodo_pago no puede ser una cadena vacía; use None si no aplica.")
        if not is_valid_metodo_pago(v):
            raise ValueError(
                f"metodo_pago '{v}' no está en el catálogo c_MetodoPago del SAT "
                "(se esperaba 'PUE' o 'PPD')."
            )
        return v

    @model_validator(mode="after")
    def _folio_factura_distinto_de_uuid(self) -> "FacturaCFDI":
        if self.folio_factura is not None and self.folio_factura.strip().upper() == self.uuid.strip().upper():
            raise ValueError(
                "folio_factura no puede ser igual al uuid (folio fiscal): "
                "el folio_factura es la serie+folio interna del emisor, no el UUID del CFDI."
            )
        return self

    # -----------------------------------------------------------------
    # REQ-IVA-008 — helpers de negocio
    # -----------------------------------------------------------------

    _CAMPOS_ANEXO7 = ("folio_factura", "forma_pago", "metodo_pago", "referencia_complemento_pago")

    def campos_faltantes_anexo7(self) -> List[str]:
        """Devuelve la lista de campos requeridos para anexo 7/7-A que faltan."""
        faltantes = []
        for campo in self._CAMPOS_ANEXO7:
            valor = getattr(self, campo)
            if valor is None or not str(valor).strip():
                faltantes.append(campo)
        return faltantes

    @property
    def esta_lista_para_anexo7(self) -> bool:
        """True si la factura tiene los 4 campos requeridos por REQ-IVA-008."""
        return not self.campos_faltantes_anexo7()

    def marcar_lista_para_anexo7(self) -> bool:
        """Marca la factura como lista para el anexo 7/7-A.

        Requiere `folio_factura`, `forma_pago`, `metodo_pago` y
        `referencia_complemento_pago` no nulos/no vacíos. Lanza `ValueError`
        listando los campos faltantes en vez de marcarla como lista sin
        evidencia completa.
        """
        faltantes = self.campos_faltantes_anexo7()
        if faltantes:
            raise ValueError(
                "No se puede marcar la factura como lista para anexo 7/7-A: "
                f"faltan los campos {faltantes} (UUID {self.uuid})."
            )
        return True

    @property
    def iva_acreditable_efectivamente_pagado(self) -> float:
        """IVA acreditable 'efectivamente pagado' (LIVA Art. 5 fracc. III).

        Sin `referencia_complemento_pago` (el REP que ampara el pago) la
        factura NO cuenta como IVA acreditable efectivamente pagado, sin
        importar lo que diga `iva`/`proporcionalidad`: devuelve 0.0.
        """
        if not self.referencia_complemento_pago or not self.referencia_complemento_pago.strip():
            return 0.0
        return round(self.iva * self.proporcionalidad, 2)


# ---------------------------------------------------------------------------
# Core schemas — DIOTEntry
# ---------------------------------------------------------------------------

class DIOTFacturaDetalle(BaseModel):
    """Detalle por factura dentro del desglose de proveedores DIOT.

    Petición explícita del dueño del despacho: el desglose de proveedores
    (sección 2 del papel de trabajo) debe traer, por cada CFDI agrupado
    bajo una entrada DIOT, el concepto de la factura junto con su folio
    fiscal, folio de factura, fecha de pago y banco — no solo el UUID
    suelto que ya traía `DIOTEntry.folios_fiscales`.
    """
    folio_fiscal: str = Field(..., description="UUID del CFDI (folio fiscal)")
    folio_factura: Optional[str] = Field(
        default=None,
        description="Folio de la factura (serie+folio interno del emisor).",
    )
    concepto: Optional[str] = Field(
        default=None, description="Concepto de la factura.",
    )
    fecha_pago: Optional[str] = Field(
        default=None,
        description="Fecha en que se efectuó el pago (YYYY-MM-DD).",
    )
    banco_pago: Optional[str] = Field(
        default=None, description="Banco donde se efectuó el pago.",
    )


class DIOTEntry(BaseModel):
    """Una entrada de la DIOT agrupada por RFC tercero."""
    rfc_tercero: str = Field(..., description="RFC del tercero")
    nombre: str = Field(default="", description="Nombre o razón social")
    tipo_operacion: str = Field(default="01", description="Tipo de operación DIOT")
    monto_neto: float = Field(default=0.0, description="Monto neto (sin IVA)")
    iva_trasladado: float = Field(default=0.0, description="IVA trasladado")
    iva_acreditable: float = Field(default=0.0, description="IVA acreditable")
    folios_fiscales: List[str] = Field(
        default_factory=list,
        description="UUIDs de facturas asociadas",
    )
    facturas_detalle: List[DIOTFacturaDetalle] = Field(
        default_factory=list,
        description=(
            "Detalle por factura (folio fiscal, folio de factura, concepto, "
            "fecha de pago, banco de pago) de los CFDI agrupados bajo esta "
            "entrada DIOT. Complementa `folios_fiscales` (solo UUIDs) con "
            "los datos que el despacho pidió explícitamente para el "
            "desglose de proveedores."
        ),
    )

    @field_validator("rfc_tercero")
    @classmethod
    def _rfc_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("rfc_tercero no puede estar vacío")
        return v.strip().upper()

    @field_validator("monto_neto", "iva_trasladado", "iva_acreditable")
    @classmethod
    def _non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Los montos no pueden ser negativos")
        return v


# ---------------------------------------------------------------------------
# Core schemas — DeclaracionMensual
# ---------------------------------------------------------------------------

class DeclaracionMensual(BaseModel):
    """Declaración mensual de IVA presentada ante el SAT."""
    mes: int = Field(..., ge=1, le=12, description="Mes (1-12)")
    año: int = Field(..., ge=2014, description="Año fiscal")
    iva_cobrado: float = Field(default=0.0, description="IVA causado (cobrado en ventas)")
    iva_pagado: float = Field(default=0.0, description="IVA pagado (acreditable en compras)")
    saldo_favor: float = Field(default=0.0, description="Saldo a favor del contribuyente")
    saldo_contra: float = Field(default=0.0, description="Saldo en contra del contribuyente")

    @field_validator("iva_cobrado", "iva_pagado", "saldo_favor", "saldo_contra")
    @classmethod
    def _amount_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Los montos no pueden ser negativos")
        return v


# ---------------------------------------------------------------------------
# Conciliation schemas
# ---------------------------------------------------------------------------

class ConciliacionFacturasDIOT(BaseModel):
    """Resultado de conciliación entre una factura CFDI y la DIOT."""
    factura_uuid: str = Field(..., description="UUID de la factura")
    diot_match: bool = Field(default=False, description="¿Se encontró match en DIOT?")
    status: EstatusConciliacion = Field(
        default=EstatusConciliacion.MISSING,
        description="Estado de la conciliación",
    )
    detalles: str = Field(default="", description="Detalles de la conciliación")


class ConciliacionDIOTDeclaracion(BaseModel):
    """Resultado de conciliación entre DIOT y Declaración mensual."""
    diot_iva_total: float = Field(default=0.0, description="IVA total de DIOT")
    declaracion_iva_acreditable: float = Field(
        default=0.0,
        description="IVA acreditable declarado",
    )
    diferencia: float = Field(default=0.0, description="Diferencia entre DIOT y declaración")
    status: EstatusConciliacion = Field(
        default=EstatusConciliacion.MISSING,
        description="Estado de la conciliación",
    )


# ---------------------------------------------------------------------------
# Solicitud & Status schemas
# ---------------------------------------------------------------------------

class SolicitudDevolucion(BaseModel):
    """Solicitud de devolución de IVA ante el SAT."""
    solicitud_id: str = Field(
        default_factory=lambda: str(_uuid.uuid4()),
        description="ID único de la solicitud",
    )
    periodo: str = Field(..., description="Periodo de la devolución (YYYY-MM)")
    monto_solicitado: float = Field(..., description="Monto solicitado en devolución")
    tenant_id: Optional[str] = Field(
        default=None,
        description="Tenant al que pertenece la solicitud (aislamiento multi-tenant)",
    )
    cuenta_banco: Optional[str] = Field(default=None, description="Nombre del banco")
    clabe: Optional[str] = Field(default=None, description="CLABE interbancaria (18 dígitos)")
    documentos: List[str] = Field(
        default_factory=list,
        description="Documentos adjuntos",
    )
    status: EstatusDevolucion = Field(
        default=EstatusDevolucion.PENDIENTE,
        description="Estatus actual de la solicitud",
    )
    estado: EstadoEnvioSolicitud = Field(
        default=EstadoEnvioSolicitud.LISTA_PARA_ENVIO,
        description=(
            "Estado de congruencia previo al envío (REQ-IVA-010): "
            "'lista_para_envio' o 'requiere_aclaracion'."
        ),
    )
    motivo_aclaracion: Optional[str] = Field(
        default=None,
        description=(
            "Motivo por el que la solicitud quedó en 'requiere_aclaracion' "
            "(REQ-IVA-010): DIOT del periodo inexistente o congruencia "
            "DIOT↔CFDI↔declaración fuera de tolerancia."
        ),
    )
    created_at: Optional[str] = Field(default=None, description="Fecha de creación ISO")


class StatusDevolucion(BaseModel):
    """Estado de seguimiento de una solicitud de devolución."""
    solicitud_id: str = Field(..., description="ID de la solicitud")
    status: EstatusDevolucion = Field(
        default=EstatusDevolucion.PENDIENTE,
        description="Estatus actual",
    )
    fecha_presentacion: Optional[str] = Field(
        default=None,
        description="Fecha de presentación (YYYY-MM-DD)",
    )
    fecha_respuesta: Optional[str] = Field(
        default=None,
        description="Fecha de respuesta del SAT (YYYY-MM-DD)",
    )
    monto_aprobado: Optional[float] = Field(
        default=None,
        description="Monto aprobado por el SAT",
    )
    observaciones: Optional[str] = Field(
        default=None,
        description="Observaciones del SAT",
    )


# ---------------------------------------------------------------------------
# PapelTrabajo schema
# ---------------------------------------------------------------------------

class PapelTrabajo(BaseModel):
    """Papel de trabajo de conciliación para devolución de IVA."""
    id: str = Field(
        default_factory=lambda: str(_uuid.uuid4()),
        description="ID único del papel de trabajo (persistencia, REQ-IVA-006)",
    )
    periodo: str = Field(..., description="Periodo (YYYY-MM)")
    tenant_id: Optional[str] = Field(default=None, description="Tenant ID")
    facturas: List[FacturaCFDI] = Field(
        default_factory=list,
        description="Facturas del periodo",
    )
    diot_entries: List[DIOTEntry] = Field(
        default_factory=list,
        description="Entradas DIOT del periodo",
    )
    declaraciones: List[DeclaracionMensual] = Field(
        default_factory=list,
        description="Declaraciones mensuales",
    )
    saldo_a_favor: float = Field(default=0.0, description="Saldo a favor calculado")
    monto_solicitado: float = Field(default=0.0, description="Monto solicitado en devolución")
    status: str = Field(default="pendiente", description="Estado del papel de trabajo")
    created_at: Optional[str] = Field(default=None, description="Fecha de creación")
