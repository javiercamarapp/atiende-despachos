# -*- coding: utf-8 -*-
"""
settlement_profiles.py — Perfiles de liquidación de canales de cobro/pago
(terminal de tarjeta, agregador de pagos, SPEI, cheque) para la conciliación
bancaria N-a-1 (REQ-CONC-001, ver docs/BLUEPRINT-AGENTES-FISCALES.md).

Un `SettlementProfile` describe, para un canal de cobro, la BANDA de
comisión que un agregador/banco puede descontar antes de liquidar un
depósito, y la ventana de días hábiles en la que ese depósito suele llegar
respecto a la fecha del cobro original. Esto es lo que permite, más
adelante (REQ-CONC-002 a 010), hacer "grossing-up" desde el neto
depositado en el banco hasta el bruto facturado y decidir si un conjunto
de facturas explica un depósito.

Este módulo NO decide ningún match — solo declara los perfiles y los
expone por nombre. Ningún valor aquí se usa para "inventar" un cruce:
son parámetros de banda, no resultados de conciliación.

Perfiles semilla (los 3 exigidos por REQ-CONC-001):
  - "clip"                : agregador de tarjeta Clip. Comisión 3.6%-4.3%,
                            sin meses sin intereses (sin MSI). Liquida
                            T+1 día hábil.
  - "banorte_tpv"         : terminal punto de venta Banorte. Comisión
                            1.5%-3.6%, **configurable por contrato** (el
                            rango real depende del contrato mercantil del
                            comercio con el banco — este es el rango
                            informativo de mercado, no una tasa fija).
                            Liquida en 1-2 días hábiles.
  - "spei_transferencia"  : transferencia SPEI o cheque. Sin comisión
                            (0.0%-0.0%), liquidación el mismo día hábil.
                            "cheque" es un ALIAS de este mismo perfil
                            (mismo comportamiento de liquidación: sin
                            comisión, sin ventana de días hábiles) — ver
                            `CANAL_ALIASES`. Esto mantiene exactamente 3
                            perfiles semilla, tal como pide REQ-CONC-001
                            ("verificable listando los 3 perfiles semilla
                            por nombre exacto"), en vez de duplicar un
                            cuarto perfil idéntico para "cheque".

La tasa de IVA sobre la comisión (`iva_comision`) es la tasa general de
IVA en México (16%) aplicada al monto de comisión cuando el canal SÍ
cobra comisión (clip, banorte_tpv). Para el canal sin comisión
(spei_transferencia/cheque) se deja en 0.0: no hay comisión sobre la cual
aplicar IVA.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional

# Tasa general de IVA en México, aplicada sobre la comisión de los
# agregadores/terminales que sí cobran comisión.
IVA_TASA_GENERAL = Decimal("0.16")


@dataclass(frozen=True)
class SettlementProfile:
    """Perfil de liquidación de un canal de cobro/pago.

    Los rangos de comisión (`tasa_comision_min`/`_max`) son fracciones
    (0.036 == 3.6%), no porcentajes. Los días de liquidación son días
    HÁBILES (ver `_business_days_window`, REQ-CONC-002 — no implementado
    en este requisito).
    """
    nombre: str
    tasa_comision_min: Decimal
    tasa_comision_max: Decimal
    iva_comision: Decimal
    liquidacion_dias_habiles_min: int
    liquidacion_dias_habiles_max: int
    incluye_fin_de_semana_en_lunes: bool
    notas: str = field(default="")

    def __post_init__(self) -> None:
        if self.tasa_comision_min > self.tasa_comision_max:
            raise ValueError(
                f"{self.nombre}: tasa_comision_min "
                f"({self.tasa_comision_min}) > tasa_comision_max "
                f"({self.tasa_comision_max})")
        if self.liquidacion_dias_habiles_min > self.liquidacion_dias_habiles_max:
            raise ValueError(
                f"{self.nombre}: liquidacion_dias_habiles_min "
                f"({self.liquidacion_dias_habiles_min}) > "
                f"liquidacion_dias_habiles_max "
                f"({self.liquidacion_dias_habiles_max})")

    def as_dict(self) -> Dict[str, object]:
        return {
            "nombre": self.nombre,
            "tasa_comision_min": str(self.tasa_comision_min),
            "tasa_comision_max": str(self.tasa_comision_max),
            "iva_comision": str(self.iva_comision),
            "liquidacion_dias_habiles_min": self.liquidacion_dias_habiles_min,
            "liquidacion_dias_habiles_max": self.liquidacion_dias_habiles_max,
            "incluye_fin_de_semana_en_lunes": self.incluye_fin_de_semana_en_lunes,
            "notas": self.notas,
        }


# ---------------------------------------------------------------------------
# Semillas — exactamente 3 perfiles, por nombre exacto (REQ-CONC-001).
# ---------------------------------------------------------------------------
SEED_PROFILES: Dict[str, SettlementProfile] = {
    "clip": SettlementProfile(
        nombre="clip",
        tasa_comision_min=Decimal("0.036"),
        tasa_comision_max=Decimal("0.043"),
        iva_comision=IVA_TASA_GENERAL,
        liquidacion_dias_habiles_min=1,
        liquidacion_dias_habiles_max=1,
        incluye_fin_de_semana_en_lunes=True,
        notas="Agregador de tarjeta Clip. Sin MSI (meses sin intereses). "
              "Liquida T+1 día hábil.",
    ),
    "banorte_tpv": SettlementProfile(
        nombre="banorte_tpv",
        tasa_comision_min=Decimal("0.015"),
        tasa_comision_max=Decimal("0.036"),
        iva_comision=IVA_TASA_GENERAL,
        liquidacion_dias_habiles_min=1,
        liquidacion_dias_habiles_max=2,
        incluye_fin_de_semana_en_lunes=True,
        notas="Terminal punto de venta Banorte. Tasa configurable por "
              "contrato mercantil del comercio: el rango 1.5%-3.6% es "
              "informativo de mercado, no una tasa fija universal.",
    ),
    "spei_transferencia": SettlementProfile(
        nombre="spei_transferencia",
        tasa_comision_min=Decimal("0.0"),
        tasa_comision_max=Decimal("0.0"),
        iva_comision=Decimal("0.0"),
        liquidacion_dias_habiles_min=0,
        liquidacion_dias_habiles_max=0,
        incluye_fin_de_semana_en_lunes=False,
        notas="SPEI/transferencia bancaria. Sin comisión, liquidación el "
              "mismo día hábil. 'cheque' es un alias de este perfil "
              "(ver CANAL_ALIASES).",
    ),
}

# Alias de canal -> nombre de perfil semilla. "cheque" comparte exactamente
# el mismo comportamiento de liquidación que "spei_transferencia" (sin
# comisión, sin ventana de días hábiles), así que no se duplica un cuarto
# perfil idéntico: se resuelve al mismo `SettlementProfile` vía alias.
CANAL_ALIASES: Dict[str, str] = {
    "cheque": "spei_transferencia",
}


def get_settlement_profile(nombre: str) -> Optional[SettlementProfile]:
    """Busca un perfil semilla por nombre (resolviendo alias de canal).

    Devuelve None si el nombre no corresponde a ningún perfil conocido —
    nunca inventa ni aproxima un perfil para un canal no declarado.
    """
    if not nombre:
        return None
    key = str(nombre).strip().lower()
    key = CANAL_ALIASES.get(key, key)
    return SEED_PROFILES.get(key)


def list_seed_profiles() -> List[SettlementProfile]:
    """Devuelve los perfiles semilla, en el orden en que se declararon."""
    return list(SEED_PROFILES.values())
