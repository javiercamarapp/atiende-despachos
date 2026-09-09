# -*- coding: utf-8 -*-
"""
models.py — Pydantic schemas for Income/Expense Reconciliation module.

All models use pydantic v2 (BaseModel) with Field for descriptions.
These represent bank deposits, auxiliary accounting entries, classifications,
discrepancies, IVA balance, and working papers used by despachos contables
in Mexico.
"""
from __future__ import annotations

import uuid as _uuid
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ClasificacionDeposito(str, Enum):
    """Clasificación fiscal de un depósito bancario."""
    INGRESO = "ingreso"
    FINANCIAMIENTO = "financiamiento"
    APORTACION_SOCIO = "aportacion_socio"
    GARANTIA = "garantia"
    OTRO_NO_GRAVABLE = "otro_no_gravable"


class TipoDiscrepancia(str, Enum):
    """Tipo de discrepancia fiscal o bancaria."""
    MONTO = "monto"
    FECHA = "fecha"
    CLASIFICACION = "clasificacion"
    FALTA_DOCUMENTACION = "falta_documentacion"


class Severidad(str, Enum):
    """Nivel de severidad de una discrepancia."""
    BAJA = "baja"
    MEDIA = "media"
    ALTA = "alta"
    CRITICA = "critica"


class TipoMovimientoAuxiliar(str, Enum):
    """Tipo de movimiento en auxiliar contable."""
    INGRESO = "ingreso"
    EGRESO = "egreso"
    CONSUMO = "consumo"
    ANTICIPO = "anticipo"
    DEVOLUCION = "devolucion"


def requiere_documento_soporte(clasificacion: "ClasificacionDeposito") -> bool:
    """True si la clasificación exige documento real de soporte antes de
    poder incluirse en un papel de trabajo exportable.

    Solo las clasificaciones que recaracterizan un depósito como no
    gravado por vía de la excepción del Art. 59 fracción III CFF
    (financiamiento, aportación de socio, garantía) lo requieren. INGRESO
    y OTRO_NO_GRAVABLE no. Equivalente, por diseño, a
    ``clasificacion in CLASIFICACIONES_REQUIEREN_DOCUMENTO_SOPORTE``
    (definido más abajo junto con el resto del modelo de REQ-IVA-002).
    """
    return clasificacion in (
        ClasificacionDeposito.FINANCIAMIENTO,
        ClasificacionDeposito.APORTACION_SOCIO,
        ClasificacionDeposito.GARANTIA,
    )


class EstadoCasoDeposito(str, Enum):
    """Estado de un caso de depósito evaluado para efectos de una
    devolución de IVA (REQ-IVA-011, ADR-4).

    Deliberadamente NO existe ningún valor de rechazo/negación en este
    enum. El sistema nunca puede negar ni reducir automáticamente una
    devolución de IVA solo porque un depósito clasificado como
    financiamiento/aportación de socio/garantía resulte "sospechoso"
    (sin documento de soporte o con score bajo de la regla que lo
    clasificó) — el máximo que el sistema hace por sí mismo es señalar
    el caso para revisión humana. A nivel de tipos, `CasoDepositoSospechoso`
    ni siquiera puede representar un estado "rechazada": no es una
    validación que se pueda olvidar en tiempo de ejecución.
    """
    EVIDENCIA_SUFICIENTE = "evidencia_suficiente"
    REQUIERE_REVISION_HUMANA = "requiere_revision_humana"


class OrigenClasificacion(str, Enum):
    """Origen/estado de una clasificación de depósito.

    REQ-IVA-013 / ADR-4 (docs/BLUEPRINT-AGENTES-FISCALES.md): el motor de
    reglas por regex NUNCA produce directamente ``APROBADO`` — toda
    clasificación que sale de `ClassificationEngine` nace en
    `AUTOMATICO_SUGERIDO` y solo un humano, vía
    `PATCH /clasificaciones/{id}/aprobar`, puede moverla a `APROBADO`.
    Ninguna clasificación automática de primera pasada es una
    determinación fiscal firme sin esa confirmación explícita.
    """
    AUTOMATICO_SUGERIDO = "automatico_sugerido"
    APROBADO = "aprobado"


# Identificador del motor de reglas automático, usado como valor de
# `clasificado_por` cuando el clasificador es el `ClassificationEngine`
# (nunca una persona) — ver REQ-IVA-013.
ORIGEN_MOTOR_REGLAS = "motor_reglas_regex"

# REQ-IVA-011 / ADR-4: nota exacta que el sistema debe registrar cuando
# marca un caso de depósito sospechoso para revisión humana en vez de
# aplicar por su cuenta la presunción del Art. 59 fracción III del CFF.
NOTA_ART_59_FR_III_CFF = (
    "Art. 59 fr. III CFF exige facultades de comprobación previas (PRODECON 1/2026)"
)


class CasoDepositoSospechoso(BaseModel):
    """Evaluación de un depósito clasificado bajo la presunción del Art. 59
    fracción III CFF (financiamiento/aportación de socio/garantía) para
    efectos de una solicitud de devolución de IVA (REQ-IVA-011, ADR-4).

    El campo `estado` usa `EstadoCasoDeposito`, que a propósito no incluye
    ningún valor de rechazo: este modelo no puede representar una negación
    automática de la devolución, solo evidencia suficiente o la necesidad
    de revisión humana.
    """
    deposito_id: str = Field(default="", description="ID del depósito evaluado")
    clasificacion: ClasificacionDeposito = Field(
        ..., description="Clasificación fiscal del depósito"
    )
    confianza: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Confianza de la regla que produjo la clasificación",
    )
    documento_soporte_id: Optional[str] = Field(
        default=None,
        description=(
            "Identificador del documento de soporte real (contrato de mutuo, "
            "acta de asamblea, contrato de garantía) adjuntado a la "
            "clasificación, si existe."
        ),
    )
    estado: "EstadoCasoDeposito" = Field(
        ..., description="'evidencia_suficiente' o 'requiere_revision_humana'"
    )
    requiere_revision_humana: bool = Field(
        default=False,
        description="True si el caso debe pasar a revisión humana antes de resolverse",
    )
    nota: Optional[str] = Field(
        default=None,
        description=(
            f"Cuando `requiere_revision_humana` es True, contiene exactamente "
            f"'{NOTA_ART_59_FR_III_CFF}'."
        ),
    )


class EstadoRecaracterizacion(str, Enum):
    """Estado de la evidencia documental que soporta una recaracterización
    fiscal de un depósito (REQ-IVA-002).

    - ``VIGENTE``: la clasificación actual (incluyendo INGRESO, que no
      requiere documento) se sostiene tal como está.
    - ``REQUIERE_FORMALIZACION``: la clasificación es una recaracterización
      (financiamiento/aportación de socio/garantía) que todavía no tiene
      `documento_soporte_id`; es el estado que produce automáticamente el
      motor de reglas (`ClassificationEngine`) mientras nadie adjunta el
      contrato de mutuo, acta de asamblea o contrato de garantía real
      (REQ-IVA-003). Nunca es un error: es la sugerencia de primera pasada
      exigida por el ADR-4 (nunca aplicar la presunción del Art. 59 fr. III
      CFF por cuenta propia sin evidencia).
    - ``RECARACTERIZADO``: la recaracterización ya cuenta con
      `documento_soporte_id` real y puede considerarse formalizada.
    """
    VIGENTE = "vigente"
    REQUIERE_FORMALIZACION = "requiere_formalizacion"
    RECARACTERIZADO = "recaracterizado"


# Clasificaciones que constituyen una recaracterización fiscal del depósito
# (dejan de tratarse como ingreso gravado) y que, por lo tanto, exigen
# evidencia documental real antes de poder persistirse como determinación
# firme — ver ADR-4 en docs/BLUEPRINT-AGENTES-FISCALES.md y REQ-IVA-002.
CLASIFICACIONES_REQUIEREN_DOCUMENTO_SOPORTE = frozenset({
    ClasificacionDeposito.FINANCIAMIENTO,
    ClasificacionDeposito.APORTACION_SOCIO,
    ClasificacionDeposito.GARANTIA,
})


# ---------------------------------------------------------------------------
# Bank deposit
# ---------------------------------------------------------------------------

class DepositoBancario(BaseModel):
    """Un depósito o abono bancario para un período dado."""
    id: str = Field(default="", description="Identificador único del depósito")
    fecha: str = Field(default="", description="Fecha del depósito (YYYY-MM-DD)")
    monto: float = Field(default=0.0, description="Monto del depósito en MXN")
    descripcion: str = Field(default="", description="Descripción o concepto del depósito")
    referencia: str = Field(default="", description="Referencia bancaria o UUID de CFDI")
    banco: str = Field(default="", description="Nombre del banco")
    cuenta: str = Field(default="", description="Número de cuenta bancaria")
    es_credito: bool = Field(default=True, description="True si es abono/crédito; False si es cargo/débito")
    documento_soporte_id: Optional[str] = Field(
        default=None,
        description=(
            "FK al repositorio de documentos (contrato de mutuo, acta de "
            "asamblea, contrato de garantía) que soporta este depósito, si "
            "ya se adjuntó uno (REQ-IVA-002/003)."
        ),
    )
    fecha_documento: Optional[str] = Field(
        default=None,
        description="Fecha del documento de soporte adjunto (YYYY-MM-DD), si aplica.",
    )
    estado_recaracterizacion: EstadoRecaracterizacion = Field(
        default=EstadoRecaracterizacion.VIGENTE,
        description=(
            "Estado de la evidencia documental para este depósito. Ver "
            "`ClasificacionDepositoResult.estado_recaracterizacion` para la "
            "regla de negocio completa; a nivel de depósito es informativo."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "id": "DEP-001",
                "fecha": "2026-06-15",
                "monto": 125000.00,
                "descripcion": "Pago cliente ABC SA de CV",
                "referencia": "CFDI-ABC-001",
                "banco": "BBVA",
                "cuenta": "0123456789",
                "es_credito": True,
            }]
        }
    }


# ---------------------------------------------------------------------------
# Auxiliary accounting entry
# ---------------------------------------------------------------------------

class MovimientoAuxiliar(BaseModel):
    """Un movimiento individual dentro de una cuenta auxiliar."""
    fecha: str = Field(default="", description="Fecha del movimiento (YYYY-MM-DD)")
    concepto: str = Field(default="", description="Concepto del movimiento")
    debe: float = Field(default=0.0, ge=0, description="Monto en el debe (cargos)")
    haber: float = Field(default=0.0, ge=0, description="Monto en el haber (abonos)")
    referencia: str = Field(default="", description="Referencia del documento o CFDI")
    tipo: TipoMovimientoAuxiliar = Field(
        default=TipoMovimientoAuxiliar.INGRESO,
        description="Tipo de movimiento",
    )


class AuxiliarContable(BaseModel):
    """Una cuenta auxiliar contable con sus movimientos."""
    cuenta_id: str = Field(default="", description="Identificador de la cuenta auxiliar")
    cuenta_mayor: str = Field(default="", description="Cuenta mayor asociada")
    cuenta_auxiliar: str = Field(default="", description="Número de cuenta auxiliar")
    descripcion: str = Field(default="", description="Descripción de la cuenta")
    saldo_inicial: float = Field(default=0.0, description="Saldo inicial del período")
    movimientos: List[MovimientoAuxiliar] = Field(
        default_factory=list,
        description="Lista de movimientos de la cuenta auxiliar",
    )
    saldo_final: float = Field(default=0.0, description="Saldo final del período")


# ---------------------------------------------------------------------------
# Deposit classification result
# ---------------------------------------------------------------------------

class ClasificacionDepositoResult(BaseModel):
    """Resultado de la clasificación de un depósito bancario."""
    id: str = Field(
        default_factory=lambda: str(_uuid.uuid4()),
        description="Identificador único de esta clasificación (usado por PATCH /clasificaciones/{id}/aprobar)",
    )
    tenant_id: Optional[str] = Field(default=None, description="Tenant ID propietario de la clasificación")
    deposito_id: str = Field(default="", description="ID del depósito clasificado")
    clasificacion: ClasificacionDeposito = Field(
        ...,
        description="Clasificación fiscal del depósito",
    )
    confianza: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Nivel de confianza de la clasificación (0-1)",
    )
    razon: str = Field(default="", description="Razón o justificación de la clasificación")
    articulo_cff: Optional[str] = Field(
        default=None,
        description="Artículo del CFF aplicable (si aplica)",
    )
    requires_human_review: bool = Field(
        default=False,
        description="Si la clasificación requiere revisión humana",
    )
    origen: OrigenClasificacion = Field(
        default=OrigenClasificacion.AUTOMATICO_SUGERIDO,
        description=(
            "Estado de confirmación de la clasificación. El motor de reglas por "
            "regex SIEMPRE produce 'automatico_sugerido'; solo pasa a 'aprobado' "
            "vía PATCH /clasificaciones/{id}/aprobar confirmado por un humano "
            "(REQ-IVA-013, ADR-4: ninguna clasificación automática de primera "
            "pasada es una determinación fiscal firme sin revisión humana)."
        ),
    )
    clasificado_por: Optional[str] = Field(
        default=None,
        description=(
            "Quién produjo esta clasificación. Para clasificaciones no triviales "
            "(financiamiento/aportación_socio/garantía) queda registrado con el "
            "identificador del motor automático (ver ORIGEN_MOTOR_REGLAS); nunca "
            "queda vacío en ese caso."
        ),
    )
    clasificado_en: Optional[str] = Field(
        default=None,
        description=(
            "Timestamp ISO 8601 de cuándo se produjo la clasificación. Obligatorio "
            "(no None) para clasificaciones no triviales (financiamiento/"
            "aportación_socio/garantía)."
        ),
    )
    aprobado_por: Optional[str] = Field(
        default=None,
        description="Identificador del humano que confirmó la clasificación vía PATCH /clasificaciones/{id}/aprobar",
    )
    aprobado_en: Optional[str] = Field(
        default=None,
        description="Timestamp ISO 8601 de la aprobación humana",
    )
    documento_soporte_id: Optional[str] = Field(
        default=None,
        description=(
            "FK al repositorio de documentos (contrato de mutuo, acta de "
            "asamblea, contrato de garantía) que soporta esta clasificación "
            "(REQ-IVA-002/003). Obligatorio y no nulo para poder persistir "
            "una clasificación FINANCIAMIENTO, APORTACION_SOCIO o GARANTIA — "
            "ver `puede_persistirse()`/`assert_puede_persistirse()`."
        ),
    )
    fecha_documento: Optional[str] = Field(
        default=None,
        description="Fecha del documento de soporte adjunto (YYYY-MM-DD), si aplica.",
    )
    estado_recaracterizacion: EstadoRecaracterizacion = Field(
        default=EstadoRecaracterizacion.VIGENTE,
        description=(
            "Estado de la evidencia documental de esta recaracterización. "
            "Se autoasigna a 'requiere_formalizacion' cuando la clasificación "
            "es financiamiento/aportación_socio/garantía y todavía no hay "
            "`documento_soporte_id` — nunca se acepta que ese caso se declare "
            "'vigente' o 'recaracterizado' sin evidencia real (ADR-4)."
        ),
    )

    @model_validator(mode="after")
    def _aplicar_regla_evidencia_documental(self) -> "ClasificacionDepositoResult":
        """REQ-IVA-002 / ADR-4: nunca aceptar como cerrada (`vigente` o
        `recaracterizado`) una recaracterización (financiamiento/aportación
        de socio/garantía) sin `documento_soporte_id` real.

        Esto NO bloquea la sugerencia automática de primera pasada que
        produce `ClassificationEngine` (REQ-IVA-013/ADR-4: esa sugerencia
        debe poder generarse siempre, sin documento, para que un humano la
        revise) — solo evita que el propio modelo declare, sin evidencia,
        que el caso ya está `vigente` o `recaracterizado`. Quien de verdad
        necesita bloquear la persistencia final debe usar
        `puede_persistirse()` / `assert_puede_persistirse()`.
        """
        requiere_evidencia = self.clasificacion in CLASIFICACIONES_REQUIEREN_DOCUMENTO_SOPORTE
        tiene_documento = bool(self.documento_soporte_id)

        if requiere_evidencia and not tiene_documento:
            estado_declarado_explicitamente = "estado_recaracterizacion" in self.model_fields_set
            if estado_declarado_explicitamente and self.estado_recaracterizacion != EstadoRecaracterizacion.REQUIERE_FORMALIZACION:
                raise ValueError(
                    f"La clasificación '{self.clasificacion.value}' no tiene "
                    f"documento_soporte_id; no puede declararse "
                    f"estado_recaracterizacion="
                    f"'{self.estado_recaracterizacion.value}' sin evidencia "
                    f"documental real (contrato de mutuo, acta de asamblea o "
                    f"contrato de garantía) — Art. 59 fracción III CFF, ADR-4."
                )
            # Sugerencia automática sin documento todavía: queda marcada
            # explícitamente como pendiente de formalización, nunca como
            # determinación fiscal firme.
            self.estado_recaracterizacion = EstadoRecaracterizacion.REQUIERE_FORMALIZACION

        return self

    def puede_persistirse(self) -> bool:
        """True si esta clasificación puede persistirse como determinación
        firme: toda clasificación FINANCIAMIENTO/APORTACION_SOCIO/GARANTIA
        exige `documento_soporte_id` no nulo (REQ-IVA-002)."""
        requiere_evidencia = self.clasificacion in CLASIFICACIONES_REQUIEREN_DOCUMENTO_SOPORTE
        return (not requiere_evidencia) or bool(self.documento_soporte_id)


def assert_puede_persistirse(clasificacion: ClasificacionDepositoResult) -> None:
    """Punto de aplicación explícito de REQ-IVA-002: levanta `ValueError` si
    `clasificacion` es FINANCIAMIENTO, APORTACION_SOCIO o GARANTIA y no tiene
    `documento_soporte_id` no nulo. Debe invocarse antes de cualquier
    escritura a un almacenamiento persistente (BD, papel de trabajo
    exportable) de una `ClasificacionDepositoResult`.
    """
    if not clasificacion.puede_persistirse():
        raise ValueError(
            f"La clasificación de depósito '{clasificacion.deposito_id}' "
            f"('{clasificacion.clasificacion.value}') no puede persistirse "
            f"sin documento_soporte_id no nulo (contrato de mutuo, acta de "
            f"asamblea o contrato de garantía) — Art. 59 fracción III CFF, "
            f"ADR-4 (docs/BLUEPRINT-AGENTES-FISCALES.md)."
        )


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

class ConciliacionIngresosEgresos(BaseModel):
    """Resultado de la conciliación entre depósitos bancarios y auxiliares contables."""
    periodo: str = Field(default="", description="Período conciliado (YYYY-MM)")
    tenant_id: Optional[str] = Field(default=None, description="Tenant ID")
    depositos: List[DepositoBancario] = Field(
        default_factory=list,
        description="Depósitos del período",
    )
    auxiliares: List[AuxiliarContable] = Field(
        default_factory=list,
        description="Auxiliares contables del período",
    )
    clasificaciones: List[ClasificacionDepositoResult] = Field(
        default_factory=list,
        description="Clasificaciones de depósitos",
    )
    discrepancias: List["DiscrepanciaFiscal"] = Field(
        default_factory=list,
        description="Discrepancias detectadas",
    )
    saldo_bancario: float = Field(default=0.0, description="Saldo bancario total")
    saldo_contable: float = Field(default=0.0, description="Saldo contable total")
    diferencia: float = Field(default=0.0, description="Diferencia entre saldo bancario y contable")


# ---------------------------------------------------------------------------
# Fiscal discrepancy
# ---------------------------------------------------------------------------

class DiscrepanciaFiscal(BaseModel):
    """Una discrepancia detectada en la conciliación fiscal."""
    tipo: TipoDiscrepancia = Field(..., description="Tipo de discrepancia")
    deposito_id: Optional[str] = Field(default=None, description="ID del depósito relacionado")
    auxiliar_id: Optional[str] = Field(default=None, description="ID del auxiliar relacionado")
    monto_afectado: float = Field(default=0.0, description="Monto afectado por la discrepancia")
    descripcion: str = Field(default="", description="Descripción de la discrepancia")
    severidad: Severidad = Field(
        default=Severidad.MEDIA,
        description="Nivel de severidad",
    )
    resuelta: bool = Field(default=False, description="Si la discrepancia ya fue resuelta")


# ---------------------------------------------------------------------------
# IVA balance
# ---------------------------------------------------------------------------

class BalanceIVA(BaseModel):
    """Balance de IVA para un período fiscal."""
    iva_cobrado: float = Field(default=0.0, description="IVA cobrado a clientes")
    iva_pagado: float = Field(default=0.0, description="IVA pagado a proveedores")
    iva_acreditable: float = Field(default=0.0, description="IVA acreditable (pagado - cobrado)")
    saldo_favor: float = Field(default=0.0, description="Saldo a favor (IVA pagado > cobrado)")
    saldo_contra: float = Field(default=0.0, description="Saldo en contra (IVA cobrado > pagado)")
    declarado: float = Field(default=0.0, description="Monto declarado en la declaración SAT")
    discrepancia: float = Field(default=0.0, description="Discrepancia entre cálculo y declaración")


# ---------------------------------------------------------------------------
# Working paper
# ---------------------------------------------------------------------------

class SeccionResumen(BaseModel):
    """Sección de resumen del papel de trabajo."""
    titulo: str = Field(default="", description="Título de la sección")
    contenido: str = Field(default="", description="Contenido de la sección")
    total_depositos: int = Field(default=0, description="Total de depósitos analizados")
    total_auxiliares: int = Field(default=0, description="Total de auxiliares analizados")


class PapelTrabajoConciliacion(BaseModel):
    """Papel de trabajo de conciliación de ingresos y egresos."""
    periodo: str = Field(default="", description="Período del papel de trabajo (YYYY-MM)")
    tenant_id: Optional[str] = Field(default=None, description="Tenant ID")
    resumen: List[SeccionResumen] = Field(
        default_factory=list,
        description="Secciones de resumen",
    )
    clasificaciones: List[ClasificacionDepositoResult] = Field(
        default_factory=list,
        description="Clasificaciones de depósitos",
    )
    discrepancias: List[DiscrepanciaFiscal] = Field(
        default_factory=list,
        description="Discrepancias detectadas",
    )
    balanceiva: List[BalanceIVA] = Field(
        default_factory=list,
        description="Balances de IVA",
    )
    conclusiones: List[str] = Field(
        default_factory=list,
        description="Conclusiones del análisis",
    )
    requires_human_review: bool = Field(
        default=False,
        description="Si el papel de trabajo requiere revisión humana",
    )
    created_at: Optional[str] = Field(
        default=None,
        description="Fecha de creación ISO format",
    )
