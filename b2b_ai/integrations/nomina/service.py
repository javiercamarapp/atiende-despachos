# -*- coding: utf-8 -*-
"""
service.py — Servicio completo de Nómina con cálculos de ISR, IMSS, INFONAVIT.

Calcula nómina, genera CFDI de nómina y recibo individual para cada empleado.
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.integrations.nomina.adapter import NominaAdapter
from b2b_ai.integrations.nomina.models import (
    CalculoImpuestos,
    CFDINomina,
    Empleado,
    IMSSDetalle,
    NominaPeriodo,
    PeriodicidadPago,
    TipoNomina,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tablas ISR 2026 (Mensual)
# ---------------------------------------------------------------------------

_ISR_TABLA = [
    (0.01, 5_541.66, 0.00, 0.00),
    (5_541.67, 47_071.37, 0.00, 0.00),
    (47_071.38, 87_472.49, 0.30, 16_623.41),
    (87_472.50, 103_376.40, 0.32, 34_746.75),
    (103_376.41, 124_262.27, 0.34, 56_813.74),
    (124_262.28, 250_000.00, 0.35, 69_274.90),
    (250_000.01, 750_000.00, 0.37, 119_274.90),
    (750_000.01, float('inf'), 0.39, 349_274.90),
]


def _calcular_isr(salario_gravable: float) -> float:
    """Calcula el ISR mensual con tabla progresiva."""
    if salario_gravable <= 0:
        return 0.0
    for lim_inf, lim_sup, tasa, cuota_fija in _ISR_TABLA:
        if lim_inf <= salario_gravable <= lim_sup:
            isr = (salario_gravable - lim_inf) * tasa + cuota_fija
            return max(0.0, isr)
    lim_inf, _, tasa, cuota_fija = _ISR_TABLA[-1]
    isr = (salario_gravable - lim_inf) * tasa + cuota_fija
    return max(0.0, isr)


def _calcular_imss(salario_diario: float) -> IMSSDetalle:
    """Calcula las cuotas del IMSS (patronal + obrero).

    Cuotas simplificadas 2026:
    - Enfermedades y maternidad: 0.40% obrero, 20.40% patronal
    - Invalidez y vida: 0.625% obrero, 1.75% patronal
    - Retiro: 2.00% patronal
    - Cesantía: 1.125% obrero, 3.150% patronal
    - Guardarantía: 0.125% patronal
    - Riesgo de trabajo: 0.50% patronal (riesgo promedio)
    """
    base = salario_diario * 30  # salario mensual integrado

    # Obrero
    enm_obrero = base * 0.0040
    inv_obrero = base * 0.00625
    ces_obrero = base * 0.01125
    total_obrero = enm_obrero + inv_obrero + ces_obrero

    # Patronal
    enm_patron = base * 0.2040
    inv_patron = base * 0.0175
    ret_patron = base * 0.02
    ces_patron = base * 0.03150
    guar_patron = base * 0.00125
    riesgo_patron = base * 0.0050
    total_patron = enm_patron + inv_patron + ret_patron + ces_patron + guar_patron + riesgo_patron

    return IMSSDetalle(
        enfermedad_maternidad_patron=round(enm_patron, 2),
        enfermedad_maternidad_obrero=round(enm_obrero, 2),
        invalididad_vida_patron=round(inv_patron, 2),
        invalididad_vida_obrero=round(inv_obrero, 2),
        retiro_patron=round(ret_patron, 2),
        cesantia_edad_patron=round(ces_patron, 2),
        cesantia_edad_obrero=round(ces_obrero, 2),
        guarderia_patron=round(guar_patron, 2),
        riesgo_trabajo_patron=round(riesgo_patron, 2),
        total_patron=round(total_patron, 2),
        total_obrero=round(total_obrero, 2),
    )


def _calcular_infonavit(salario_diario: float) -> float:
    """Calcula la aportación al INFONAVIT (5% del salario integrado)."""
    base = salario_diario * 30
    return round(base * 0.05, 2)


# ---------------------------------------------------------------------------
# NominaService
# ---------------------------------------------------------------------------

class NominaService(NominaAdapter):
    """Servicio completo de nómina.

    Calcula ISR, IMSS (patronal + obrero) e INFONAVIT, genera CFDI de nómina
    y recibo individual para cada empleado.
    """

    def __init__(self):
        super().__init__(name="nomina_service")

    def calcular_isr(self, salario_bruto: float) -> float:
        """Calcula el ISR mensual."""
        return _calcular_isr(salario_bruto)

    def calcular_imss(self, salario_diario: float) -> IMSSDetalle:
        """Calcula las cuotas del IMSS."""
        return _calcular_imss(salario_diario)

    def calcular_infonavit(self, salario_diario: float) -> float:
        """Calcula la aportación al INFONAVIT."""
        return _calcular_infonavit(salario_diario)

    def calcular_impuestos_empleado(
        self,
        salario_bruto: float,
        salario_diario: float = 0.0,
        deducciones_extras: float = 0.0,
    ) -> CalculoImpuestos:
        """Calcula todos los impuestos de un empleado.

        Args:
            salario_bruto: Salario bruto mensual.
            salario_diario: Salario diario (si es 0, se calcula como bruto/30).
            deducciones_extras: Otras deducciones (sindicato, préstamos, etc.)

        Returns:
            CalculoImpuestos con el desglose completo.
        """
        if salario_diario <= 0:
            salario_diario = salario_bruto / 30 if salario_bruto > 0 else 0

        isr = _calcular_isr(salario_bruto)
        imss = _calcular_imss(salario_diario)
        infonavit = _calcular_infonavit(salario_diario)

        total_deducciones = isr + imss.total_obrero + infonavit + deducciones_extras
        salario_neto = max(0, salario_bruto - total_deducciones)

        calculo = CalculoImpuestos(
            isr=round(isr, 2),
            imss_patronal=imss.total_patron,
            imss_obrero=imss.total_obrero,
            imss_total=round(imss.total_patron + imss.total_obrero, 2),
            infonavit=infonavit,
            total_cargas_sociales=round(imss.total_patron + infonavit, 2),
            total_deducciones=round(total_deducciones, 2),
            salario_neto=round(salario_neto, 2),
        )

        return calculo

    def calcular_nomina(
        self,
        empleados: List[Empleado],
        periodo: Dict[str, Any],
    ) -> NominaPeriodo:
        """Calcula la nómina completa para un periodo.

        Args:
            empleados: Lista de empleados.
            periodo: {"mes": 1, "anio": 2026, "dias_pagados": 30}

        Returns:
            NominaPeriodo con todos los cálculos.
        """
        mes = periodo.get("mes", 1)
        anio = periodo.get("anio", 2026)
        dias_pagados = periodo.get("dias_pagados", 30)

        total_percepciones = 0.0
        total_deducciones = 0.0
        total_isr = 0.0
        total_imss_patronal = 0.0
        total_imss_obrero = 0.0
        total_infonavit = 0.0

        for emp in empleados:
            calculo = self.calcular_impuestos_empleado(
                salario_bruto=emp.salario_bruto,
                salario_diario=emp.salario_diario,
                deducciones_extras=emp.cuota_fija_sindicato + emp.otros_descuentos,
            )
            emp.salario_neto = calculo.salario_neto

            total_percepciones += emp.salario_bruto
            total_deducciones += calculo.total_deducciones
            total_isr += calculo.isr
            total_imss_patronal += calculo.imss_patronal
            total_imss_obrero += calculo.imss_obrero
            total_infonavit += calculo.infonavit

        nomina = NominaPeriodo(
            mes=mes,
            anio=anio,
            tipo=TipoNomina.ORDINARIA,
            dias_pagados=dias_pagados,
            empleados=empleados,
            total_percepciones=round(total_percepciones, 2),
            total_deducciones=round(total_deducciones, 2),
            total_neto=round(total_percepciones - total_deducciones, 2),
            total_isr=round(total_isr, 2),
            total_imss_patronal=round(total_imss_patronal, 2),
            total_imss_obrero=round(total_imss_obrero, 2),
            total_infonavit=round(total_infonavit, 2),
        )

        logger.info(
            f"Nómina calculada: {len(empleados)} empleados, "
            f"total neto: ${nomina.total_neto:,.2f}"
        )
        return nomina

    def generar_cfdi_nomina(self, nomina_data: Dict[str, Any]) -> CFDINomina:
        """Genera un CFDI de Nómina 1.2 en formato dict (mock XML).

        En producción, esto generaría un XML real con Timbrado SAT.
        """
        uuid_cfdi = str(_uuid.uuid4())
        emisor = nomina_data.get("emisor", {})
        receptor = nomina_data.get("receptor", {})
        period = nomina_data.get("period", {})
        taxes = nomina_data.get("taxes", {})

        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        complemento = {
            "Nomina12:Nomina": {
                "Version": "1.2",
                "TipoNomina": nomina_data.get("tipo_nomina", "O"),
                "FechaPago": f"{period.get('anio', 2026)}-{period.get('mes', 1):02d}-01",
                "FechaInicialPago": f"{period.get('anio', 2026)}-{period.get('mes', 1):02d}-01",
                "FechaFinalPago": f"{period.get('anio', 2026)}-{period.get('mes', 1):02d}-28",
                "NumDiasPagados": str(period.get("dias_pagados", 30)),
                "Percepciones": {
                    "TotalSueldos": str(round(nomina_data.get("subtotal", 0), 2)),
                },
                "Deducciones": {
                    "TotalOtrasDeducciones": str(round(
                        taxes.get("isr", 0) + taxes.get("imss_obrero", 0), 2
                    )),
                    "TotalRetenciones": str(round(taxes.get("isr", 0), 2)),
                },
            },
        }

        return CFDINomina(
            uuid=uuid_cfdi,
            version="4.0",
            serie="NOM",
            folio=uuid_cfdi[:8].upper(),
            fecha=now,
            rfc_emisor=emisor.get("rfc", ""),
            rfc_receptor=receptor.get("rfc", ""),
            total=round(nomina_data.get("total", 0), 2),
            status="timbrado",
            xml=f"<cfdi:Comprobante UUID='{uuid_cfdi}' Version='4.0' ...>",
            fecha_timbrado=now,
            complemento_nomina=complemento,
        )
