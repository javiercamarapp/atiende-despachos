# -*- coding: utf-8 -*-
"""
retention_engine.py — ISR retention calculator for AP suppliers.

Calculates ISR retentions per LISR Art. 94-100:
  - Arrendamiento PF: 10% (Art. 94 fracc. III)
  - Honorarios PF: tabla Art. 96 (progressive)
  - Servicios profesionales PF: 10% sobre ingresos brutos (Art. 100)
  - Regalías nacional: 25% (Art. 178 fracc. I)
  - Regalías extranjero: 40% (Art. 178 fracc. I)
  - Subcontratación laboral: 6% (Art. 12 fracc. I, reforma 2021)
"""
from __future__ import annotations

from typing import Optional

from b2b_ai.features.ap_ar.models import RetentionResult, RetentionType


# ISR retention configuration per LISR
RETENTION_CONFIG = {
    RetentionType.ARRENDAMIENTO_PF: {
        "tasa": 0.10,
        "fundamento": "LISR Art. 94 fracc. III",
        "aplica": "PF arrendadora de bienes inmuebles",
        "es_tabla": False,
    },
    RetentionType.HONORARIOS_PF: {
        "tasa": "tabla_art_96",
        "fundamento": "LISR Art. 94 fracc. II — Tabla Art. 96",
        "aplica": "PF prestadora de servicios profesionales (honorarios)",
        "es_tabla": True,
    },
    RetentionType.SERVICIOS_PROFESIONALES: {
        "tasa": 0.10,
        "fundamento": "LISR Art. 100",
        "aplica": "PF con Actividades Empresariales",
        "es_tabla": False,
    },
    RetentionType.REGALIAS_NACIONAL: {
        "tasa": 0.25,
        "fundamento": "LISR Art. 178 fracc. I",
        "aplica": "Regalías a residentes nacionales",
        "es_tabla": False,
    },
    RetentionType.REGALIAS_EXTRANJERO: {
        "tasa": 0.40,
        "fundamento": "LISR Art. 178 fracc. I",
        "aplica": "Regalías a residentes extranjeros",
        "es_tabla": False,
    },
    RetentionType.SUBCONTRATACION: {
        "tasa": 0.06,
        "fundamento": "LISR Art. 12 fracc. I (reforma subcontratación 2021)",
        "aplica": "Subcontratación laboral (outsourcing)",
        "es_tabla": False,
    },
}

# Tabla Art. 96 LISR (simplified — monthly lower limits and rates).
# (limite_inferior, cuota_fija, tasa_sobre_excedente)
TABLA_ART_96 = [
    (0.01,       0.00,    0.0192),
    (746.05,     14.32,   0.0640),
    (6332.06,    371.84,  0.1088),
    (11128.02,   892.23,  0.1600),
    (12935.83,   1181.48, 0.1792),
    (38767.47,   5818.38, 0.2136),
    (63513.91,   11104.75, 0.2352),
    (189975.39,  40817.44, 0.3000),
    (237655.73,  55121.44, 0.3200),
    (356483.59,  93126.36, 0.3400),
    (712967.19,  214329.18, 0.3500),
]


def _is_persona_fisica(rfc: str) -> bool:
    """RFC with 13 chars = Persona Física, 12 = Persona Moral."""
    return len(rfc.strip()) == 13


def _calcular_tabla_art96(monto_mensual: float) -> float:
    """Calculate ISR retention using Art. 96 progressive table.

    Takes the monthly taxable income and returns the ISR amount.
    For simplicity, applies the monthly table directly.
    """
    if monto_mensual <= 0:
        return 0.0

    for i, (limite, cuota, tasa) in enumerate(TABLA_ART_96):
        siguiente = TABLA_ART_96[i + 1][0] if i + 1 < len(TABLA_ART_96) else float('inf')
        if monto_mensual <= siguiente:
            excedente = monto_mensual - limite
            return round(cuota + excedente * tasa, 2)

    # Above last bracket
    limite, cuota, tasa = TABLA_ART_96[-1]
    excedente = monto_mensual - limite
    return round(cuota + excedente * tasa, 2)


class RetentionEngine:
    """Calculates ISR retentions to suppliers per LISR Art. 94-100."""

    def calcular_retencion(
        self,
        proveedor_rfc: str,
        tipo_servicio: RetentionType,
        monto_factura: float,
    ) -> RetentionResult:
        """Calculate ISR retention for a given supplier invoice.

        Args:
            proveedor_rfc: Supplier RFC (13 chars = PF, 12 = PM).
            tipo_servicio: Type of service/retention.
            monto_factura: Invoice subtotal (before IVA).

        Returns:
            RetentionResult with calculated retention details.
        """
        es_pf = _is_persona_fisica(proveedor_rfc)

        if not es_pf:
            return RetentionResult(
                proveedor_rfc=proveedor_rfc,
                monto_factura=monto_factura,
                monto_neto=monto_factura,
                es_pf=False,
                aplica_retencion=False,
                motivo="Persona Moral — no aplica retención ISR a PM",
            )

        config = RETENTION_CONFIG.get(tipo_servicio)
        if config is None:
            return RetentionResult(
                proveedor_rfc=proveedor_rfc,
                tipo_retencion=tipo_servicio,
                monto_factura=monto_factura,
                monto_neto=monto_factura,
                es_pf=True,
                aplica_retencion=False,
                motivo=f"Tipo de servicio '{tipo_servicio}' no sujeto a retención",
            )

        if config["es_tabla"]:
            retencion = _calcular_tabla_art96(monto_factura)
        else:
            retencion = round(monto_factura * config["tasa"], 2)

        monto_neto = round(monto_factura - retencion, 2)

        return RetentionResult(
            proveedor_rfc=proveedor_rfc,
            tipo_retencion=tipo_servicio,
            tasa=config["tasa"] if not config["es_tabla"] else 0.0,
            fundamento=config["fundamento"],
            monto_factura=monto_factura,
            retencion=retencion,
            monto_neto=monto_neto,
            es_pf=True,
            aplica_retencion=True,
            motivo=config["aplica"],
        )

    def detectar_tipo_retencion(
        self, proveedor_rfc: str, descripcion_servicio: str
    ) -> Optional[RetentionType]:
        """Heuristic detection of retention type from service description."""
        desc = descripcion_servicio.lower()

        if any(kw in desc for kw in ("arrendamiento", "renta", "renta inmueble")):
            return RetentionType.ARRENDAMIENTO_PF
        if any(kw in desc for kw in ("honorario", "consultoría", "consultoria")):
            return RetentionType.HONORARIOS_PF
        if any(kw in desc for kw in ("regalía", "regalia", "royalty", "licencia")):
            return RetentionType.REGALIAS_NACIONAL
        if any(kw in desc for kw in ("subcontra", "outsourcing", "terceriz")):
            return RetentionType.SUBCONTRATACION
        if any(kw in desc for kw in ("servicio profesional", "servicios prof")):
            return RetentionType.SERVICIOS_PROFESIONALES

        return RetentionType.SERVICIOS_PROFESIONALES  # Default for PF
