# -*- coding: utf-8 -*-
"""
models.py — Modelos para integración de Nómina (IMSS, ISR, INFONAVIT, CFDI Nómina).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TipoNomina(str, Enum):
    """Tipo de nómina."""
    ORDINARIA = "O"
    EXTRAORDINARIA = "E"


class PeriodicidadPago(str, Enum):
    """Periodicidad de pago."""
    DIARIO = "D"
    SEMANAL = "S"
    QUINCENAL = "Q"
    MENSUAL = "M"
    BIMESTRAL = "B"


# ---------------------------------------------------------------------------
# Employee
# ---------------------------------------------------------------------------

class Empleado(BaseModel):
    """Empleado para cálculos de nómina."""
    id: str = Field(..., description="ID del empleado")
    nombre: str = Field(..., description="Nombre completo")
    rfc: str = Field(..., description="RFC del empleado")
    nss: Optional[str] = Field(default=None, description="Número de Seguridad Social")
    curp: Optional[str] = Field(default=None, description="CURP")
    salario_diario: float = Field(..., gt=0, description="Salario diario integrado")
    salario_bruto: float = Field(..., gt=0, description="Salario bruto mensual")
    salario_neto: float = Field(default=0.0, description="Salario neto (calculado)")
    banco: str = Field(default="", description="Banco")
    clabe: str = Field(default="", description="CLABE")
    departamento: str = Field(default="", description="Departamento")
    puesto: str = Field(default="", description="Puesto")
    antiguedad_anios: int = Field(default=0, description="Antigüedad en años")
    tipo_contrato: str = Field(default="indeterminado", description="Tipo de contrato")
    periodo_pago: PeriodicidadPago = Field(default=PeriodicidadPago.MENSUAL)
    cuota_fija_sindicato: float = Field(default=0.0, description="Cuota fija sindicato")
    otros_descuentos: float = Field(default=0.0, description="Otros descuentos")


# ---------------------------------------------------------------------------
# Nómina Period
# ---------------------------------------------------------------------------

class NominaPeriodo(BaseModel):
    """Periodo de nómina completo."""
    mes: int = Field(..., ge=1, le=12, description="Mes del periodo")
    anio: int = Field(..., description="Año del periodo")
    tipo: TipoNomina = Field(default=TipoNomina.ORDINARIA)
    dias_pagados: int = Field(default=30, description="Días pagados")
    empleados: List[Empleado] = Field(default_factory=list, description="Empleados del periodo")
    total_percepciones: float = Field(default=0.0, description="Total de percepciones")
    total_deducciones: float = Field(default=0.0, description="Total de deducciones")
    total_neto: float = Field(default=0.0, description="Total neto a pagar")
    total_isr: float = Field(default=0.0, description="Total ISR retenido")
    total_imss_patronal: float = Field(default=0.0, description="Total cuota patronal IMSS")
    total_imss_obrero: float = Field(default=0.0, description="Total cuota obrera IMSS")
    total_infonavit: float = Field(default=0.0, description="Total INFONAVIT")
    fecha_pago: Optional[str] = Field(default=None, description="Fecha de pago")


# ---------------------------------------------------------------------------
# Tax Calculations
# ---------------------------------------------------------------------------

class CalculoImpuestos(BaseModel):
    """Desglose de impuestos calculados para un empleado."""
    empleado_id: str = Field(default="", description="ID del empleado")
    isr: float = Field(default=0.0, description="ISR mensual")
    imss_patronal: float = Field(default=0.0, description="Cuota patronal IMSS")
    imss_obrero: float = Field(default=0.0, description="Cuota obrera IMSS")
    imss_total: float = Field(default=0.0, description="IMSS total (patronal + obrero)")
    infonavit: float = Field(default=0.0, description="Aportación INFONAVIT")
    total_cargas_sociales: float = Field(default=0.0, description="Total cargas sociales")
    total_deducciones: float = Field(default=0.0, description="Total deducciones obrero")
    salario_neto: float = Field(default=0.0, description="Salario neto")

    def calcular_totales(self) -> None:
        """Recalcula los totales."""
        self.imss_total = self.imss_patronal + self.imss_obrero
        self.total_cargas_sociales = self.imss_patronal + self.infonavit
        self.total_deducciones = self.isr + self.imss_obrero + self.infonavit


class IMSSDetalle(BaseModel):
    """Detalle de cuotas IMSS."""
    enfermedad_maternidad_patron: float = Field(default=0.0)
    enfermedad_maternidad_obrero: float = Field(default=0.0)
    invalididad_vida_patron: float = Field(default=0.0)
    invalididad_vida_obrero: float = Field(default=0.0)
    retiro_patron: float = Field(default=0.0)
    cesantia_edad_patron: float = Field(default=0.0)
    cesantia_edad_obrero: float = Field(default=0.0)
    guarderia_patron: float = Field(default=0.0)
    riesgo_trabajo_patron: float = Field(default=0.0)
    total_patron: float = Field(default=0.0)
    total_obrero: float = Field(default=0.0)


# ---------------------------------------------------------------------------
# CFDI Nómina
# ---------------------------------------------------------------------------

class CFDINomina(BaseModel):
    """CFDI de nómina generado."""
    uuid: str = Field(default="", description="UUID del CFDI")
    version: str = Field(default="4.0", description="Versión del CFDI")
    serie: str = Field(default="NOM", description="Serie")
    folio: str = Field(default="", description="Folio")
    fecha: str = Field(default="", description="Fecha de emisión")
    rfc_emisor: str = Field(default="", description="RFC del emisor")
    rfc_receptor: str = Field(default="", description="RFC del receptor")
    total: float = Field(default=0.0, description="Total del CFDI")
    status: str = Field(default="pendiente", description="Estado del timbrado")
    xml: Optional[str] = Field(default=None, description="XML del CFDI")
    fecha_timbrado: Optional[str] = Field(default=None, description="Fecha de timbrado")
    complemento_nomina: Optional[Dict[str, Any]] = Field(default=None, description="Complemento nómina 1.2")
