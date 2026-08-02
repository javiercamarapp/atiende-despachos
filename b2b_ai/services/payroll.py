# -*- coding: utf-8 -*-
"""
payroll.py — Nómina: cálculo de retenciones/prestaciones y generación de
nómina CFDI 4.0 con complemento Nomina 1.2.

Cubre: ISR (tarifa progresiva mensual/quincenal, LISR art. 96),
IMSS (trabajador: EYM + RCVA + IV + GMP, LSS arts. 105-108),
INFONAVIT (5% SBC como provisión patronal, Ley INFONAVIT art. 29-II),
Subsidio para el empleo (LISR art. 174, Decreto DOF),
PTU (10% renta gravable, LFT art. 123 fr. IX), aguinaldo (LFT art. 87),
vacaciones (LFT art. 76 reformado 1-ene-2023) y prima vacacional (LFT art. 80).

> Aviso: esta máquina PREPARA y VALIDA la nómina; el profesional determina y
> firma. No sustituye a un contador y no timbra ante el SAT. Cada salida lleva
> supuestos y la referencia legal de cada concepto. Las tasas son
> configurables y versionadas (año fiscal).
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

# ---------------------------------------------------------------------------
# Configuración fiscal (versionada)
# ---------------------------------------------------------------------------

# Tarifa ISR centralizada en fiscal_tables.py (2025 + legacy 2024)
from b2b_ai.fiscal_tables import (
    ISR_MENSUAL_2025, ISR_QUINCENAL_2025,
    SUBSIDIO_EMPLEO_MENSUAL_2025, SUBSIDIO_EMPLEO_QUINCENAL_2025,
    ISR_MENSUAL_2024,
)

def _to_str_tuples(table):
    return [(str(li), str(ls) if ls != float("inf") else None, str(cf), str(pct))
            for li, ls, cf, pct in table]

TARIFA_ISR_2024_MENSUAL = _to_str_tuples(ISR_MENSUAL_2024)

# FIS-08: Tarifa mensual ISR 2025 — tabla oficial (LISR art. 96)
TARIFA_ISR_2025_MENSUAL = _to_str_tuples(ISR_MENSUAL_2025)

# Tarifa quincenal ISR — de fiscal_tables.py (2025)
TARIFA_ISR_2024_QUINCENAL = _to_str_tuples(ISR_QUINCENAL_2025)

# Tarifa quincenal ISR — tabla oficial simplificada (LISR art. 96, Decreto DOF
# anual). Se usa cuando periodicidad='quincenal'. Nota: la tabla exacta la
# publica el SAT en el Anexo 3 de la RMF; esta tabla es la mitad de la mensual
# en cuotas fijas (los límites y porcentajes se mantienen proporcionales).
# Para máxima precisión, se recomienda usar el método de equivalencia mensual
# (calcular mensual × 2, obtener ISR mensual, dividir entre 2).

# Subsidio para el empleo — centralizado en fiscal_tables.py (2025)
SUBSIDIO_EMPLEO_MENSUAL = SUBSIDIO_EMPLEO_MENSUAL_2025

# Subsidio quincenal — de fiscal_tables.py (2025)
SUBSIDIO_EMPLEO_QUINCENAL = SUBSIDIO_EMPLEO_QUINCENAL_2025



# Cuotas/tasas de ley (configurables, con supuesto documentado).
RATES = {
    # --- IMSS Trabajador (LSS arts. 105-108, 147) ---
    # EYM: Enfermedades y Maternidad — cuota fija + excedente + prestaciones
    # dineradas + prestaciones en especie + invalidez y vida + GMP.
    # Para trabajadores del régimen obligatorio con SBC ≤ 3 UMA:
    #   cuota_fija = 20.40 * UMA_diario (art. 106 fracc. I)
    #   excedente = SBC_diario * tasa (art. 106 fracc. III-VII)
    #   prest_din = SBC_diario * tasa (art. 106 fracc. II)
    #   prest_esp = SBC_diario * tasa (art. 106 fracc. III)
    # Para simplificar, usamos la suma de tasas del trabajador publicadas por
    # el IMSS. Las tasas oficiales del IMSS (2025) son:
    "imss_trabajador_eym_cuota_fija": Decimal("0.0"),   # La cuota fija es patronal
    "imss_trabajador_enf_mat_base": Decimal("0.0025"),  # Enf. y Mat. base (art. 106 I)
    "imss_trabajador_enf_mat_prest_din": Decimal("0.0075"),  # Prest. dineradas (art. 106 II)
    "imss_trabajador_enf_mat_prest_esp": Decimal("0.00375"),  # Prest. en especie (art. 106 III)
    "imss_trabajador_enf_mat_iv": Decimal("0.00625"),  # Invalidez y Vida (art. 107)
    "imss_trabajador_rcva": Decimal("0.01125"),  # Retiro, Cesantía y Vejez (art. 108)
    # Gastos Médicos de Pensionados: tasa del trabajador (art. 109)
    "imss_trabajador_gmp": Decimal("0.00375"),
    # Total IMSS trabajador (sin excedente): se calcula sumando componentes
    # Para SBC ≤ 3 UMA, el total ≈ 0.025 + 0.00625 + 0.01125 + 0.00375
    # NOTA: Para SBC > 3 UMA hay un "excedente" adicional (art. 106 III-VII)
    # que se calcula sobre (SBC - 3*UMA_diario).
    "imss_uma_diario": Decimal("108.57"),  # UMA diaria 2025 (se actualiza cada feb)
    "imss_excedente_3uma_tasa": Decimal("0.004"),  # Tasa excedente (art. 106 fracc. III)

    # --- INFONAVIT (Ley INFONAVIT art. 29) ---
    # 5% del SBC es a cargo del PATRÓN (art. 29-II), NO del trabajador.
    # La amortización de crédito INFONAVIT (art. 29-III) es retención al
    # trabajador, pero su monto lo fija el instituto, no un porcentaje fijo.
    "infonavit_tasa": Decimal("0.0500"),  # 5% SBC — PROVISIÓN PATRONAL
    "ptu_tasa": Decimal("0.1000"),               # 10% de la renta gravable (utilidad fiscal)
    "factor_integracion": Decimal("1.0452"),     # SBC ≈ salario diario × factor (prestaciones mínimas)
    "prima_vacacional_tasa": Decimal("0.2500"),  # 25% del pago de vacaciones
    "aguinaldo_dias_ley": 15,                    # 15 días (LFT art. 87)
}

AÑO_FISCAL = 2025


def _dec(v, default=Decimal("0")):
    try:
        if v is None:
            return default
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return default


def _round2(d):
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _fmt(d):
    return str(_round2(d))


# ---------------------------------------------------------------------------
# ISR (tarifa progresiva)
# ---------------------------------------------------------------------------

def calc_isr(ingreso_gravado, tarifa=None, periodicidad="mensual"):
    """Calcula el ISR con la tarifa progresiva (LISR art. 96).

    Soporta periodicidad='mensual' y 'quincenal'. Para quincenal usa la tabla
    quincenal oficial o el método de equivalencia mensual.

    Devuelve {impuesto, ingreso_gravado, rango_aplicado, referencia}.
    """
    per = periodicidad.lower() if periodicidad else "mensual"
    if per == "quincenal":
        tabla = tarifa or TARIFA_ISR_2024_QUINCENAL
        ref_label = "quincenal"
    else:
        tabla = tarifa or TARIFA_ISR_2025_MENSUAL  # FIS-08: default 2025
        ref_label = "mensual"
    ing = _dec(ingreso_gravado)
    if ing <= 0:
        return {"impuesto": "0.00", "ingreso_gravado": _fmt(ing),
                "rango_aplicado": None, "referencia": "LISR art. 96"}
    for li, ls, cuota, pct in tabla:
        li_d = _dec(li)
        ls_d = _dec(ls) if ls is not None else None
        if ing >= li_d and (ls_d is None or ing <= ls_d):
            excedente = ing - li_d
            impuesto = _dec(cuota) + excedente * _dec(pct)
            return {
                "impuesto": _fmt(impuesto),
                "ingreso_gravado": _fmt(ing),
                "rango_aplicado": {"limite_inferior": li,
                                   "limite_superior": ls,
                                   "cuota_fija": cuota,
                                   "porcentaje_excedente": pct,
                                   "excedente": _fmt(excedente)},
                "referencia": f"LISR art. 96 (tarifa {ref_label})",
            }
    # Cae por debajo del primer rango (ingreso < 0.01) -> no aplica
    return {"impuesto": "0.00", "ingreso_gravado": _fmt(ing),
            "rango_aplicado": None, "referencia": "LISR art. 96"}


# ---------------------------------------------------------------------------
# IMSS, INFONAVIT, PTU
# ---------------------------------------------------------------------------

def calc_imss(salario_base_cotizacion, dias_pagados=30, rates=None):
    """Cuota del trabajador al IMSS (LSS arts. 105-109).

    Calcula la cuota DIARIA por cada componente y la multiplica por
    dias_pagados para obtener la retención del periodo.

    Componentes del trabajador:
    - Enfermedades y Maternidad (EYM): tasa base (art. 106 I)
    - Prestaciones dineradas (art. 106 II)
    - Prestaciones en especie (art. 106 III)
    - Invalidez y Vida (IV) (art. 107)
    - Retiro, Cesantía y Vejez (RCVA) (art. 108)
    - Gastos Médicos de Pensionados (GMP) (art. 109)
    - Excedente 3 UMA: tasa adicional sobre (SBC - 3×UMA_diario)
      cuando SBC > 3×UMA_diario (art. 106 fracc. III-VII)

    Devuelve {eym, rcva, iv, gmp, excedente, total, sbc, dias_pagados}.
    """
    r = rates or RATES
    sbc = _dec(salario_base_cotizacion)
    dias = int(dias_pagados) if dias_pagados else 30

    # FIS-3: Validate SBC > 0 and SBC >= UMA diaria (Art. 107 LSS)
    uma = r["imss_uma_diario"]
    if sbc <= Decimal("0"):
        raise ValueError(
            f"SBC ({sbc}) debe ser mayor a 0. "
            "Un empleado sin salario base de cotización no existe ante el IMSS."
        )
    if sbc < uma:
        raise ValueError(
            f"SBC ({sbc}) no puede ser menor a UMA diaria ({uma}). "
            "Art. 107 LSS: el SBC no puede ser inferior a la UMA."
        )

    # Componentes diarios del trabajador
    enf_mat_base = _round2(sbc * r["imss_trabajador_enf_mat_base"])
    enf_mat_pd = _round2(sbc * r["imss_trabajador_enf_mat_prest_din"])
    enf_mat_pe = _round2(sbc * r["imss_trabajador_enf_mat_prest_esp"])
    eym_diario = enf_mat_base + enf_mat_pd + enf_mat_pe  # subtotal EYM diario

    iv_diario = _round2(sbc * r["imss_trabajador_enf_mat_iv"])  # Invalidez y Vida
    rcva_diario = _round2(sbc * r["imss_trabajador_rcva"])  # Retiro, Cesantía y Vejez
    gmp_diario = _round2(sbc * r["imss_trabajador_gmp"])  # Gastos Médicos Pensionados

    # Excedente 3 UMA (art. 106 fracc. III): solo si SBC > 3×UMA_diario
    uma = r["imss_uma_diario"]
    excedente_diario = Decimal("0")
    if sbc > (uma * Decimal("3")):
        excedente_diario = _round2(
            (sbc - uma * Decimal("3")) * r["imss_excedente_3uma_tasa"])

    # Totales del periodo
    eym_total = _round2((eym_diario + excedente_diario) * dias)
    iv_total = _round2(iv_diario * dias)
    rcva_total = _round2(rcva_diario * dias)
    gmp_total = _round2(gmp_diario * dias)
    total = eym_total + iv_total + rcva_total + gmp_total

    return {
        "eym": _fmt(eym_total),
        "iv": _fmt(iv_total),
        "rcva": _fmt(rcva_total),
        "gmp": _fmt(gmp_total),
        "excedente_3uma": _fmt(_round2(excedente_diario * dias)),
        "total": _fmt(total),
        "sbc": _fmt(sbc),
        "dias_pagados": dias,
        "referencia": "LSS arts. 105-109 (aportaciones del trabajador, "
                       f"SBC diario × {dias} días)",
    }


def calc_infonavit(salario_base_cotizacion, tasa=None, rates=None):
    """Aportación patronal INFONAVIT (5% del SBC).

    Ley del INFONAVIT art. 29 fracc. II: el 5% del SBC es una aportación
    a cargo del PATRÓN, no del trabajador. NO se descuenta del sueldo del
    trabajador.

    La amortización de un crédito INFONAVIT (art. 29 fracc. III) es lo único
    que se puede retener al trabajador, pero su monto lo fija el instituto
    mediante aviso de retención, no un porcentaje fijo del SBC.

    Este método devuelve la aportación como provisión del patrón.
    """
    r = rates or RATES
    tasa = _dec(tasa) if tasa is not None else r["infonavit_tasa"]
    sbc = _dec(salario_base_cotizacion)
    return {
        "cuota": _fmt(_round2(sbc * tasa)),
        "tasa": str(tasa),
        "sbc": _fmt(sbc),
        "tipo": "provision_patronal",  # NO es deducción del trabajador
        "referencia": "Ley INFONAVIT art. 29-II (aportación patronal 5% SBC)",
    }


def calc_ptu(utilidad_fiscal, tasa=None, rates=None):
    """PTU: 10% de la renta gravable / utilidad fiscal (LFT art. 123 fr. IX)."""
    r = rates or RATES
    tasa = _dec(tasa) if tasa is not None else r["ptu_tasa"]
    util = _dec(utilidad_fiscal)
    return {
        "ptu": _fmt(_round2(util * tasa)),
        "tasa": str(tasa),
        "utilidad_fiscal": _fmt(util),
        "referencia": "LFT art. 123 fracc. IX (PTU 10%)",
    }


def calc_subsidio_empleo(ingreso_gravado, periodicidad="mensual"):
    """Subsidio para el empleo (LISR art. 174, Decreto DOF).

    El subsidio es de aplicación obligatoria cuando el ingreso gravado no
    excede el límite de la tabla. Se acredita contra el ISR del periodo;
    si el subsidio excede el ISR, el excedente se entrega en efectivo al
    trabajador (art. 174 LISR). En el CFDI se reporta como OtroPago
    TipoOtroPago="002" (SubsidioAlEmpleo).

    Devuelve {subsidio, isr_antes_subsidio, isr_neto, subsidio_efectivo,
    referencia}.

    NOTA: Los montos de la tabla deben actualizarse cada ejercicio fiscal
    con el decreto publicado en el DOF. Los montos corresponden al 2025.
    """
    per = periodicidad.lower() if periodicidad else "mensual"
    tabla = SUBSIDIO_EMPLEO_QUINCENAL if per == "quincenal" else SUBSIDIO_EMPLEO_MENSUAL
    ing = _dec(ingreso_gravado)
    if ing <= Decimal("0.01"):
        return {
            "subsidio": "0.00",
            "subsidio_efectivo": "0.00",
            "referencia": "LISR art. 174 (no aplica: ingreso ≤ 0.01)",
        }

    for li, ls, sub_monto in tabla:
        li_d = _dec(li)
        ls_d = _dec(ls) if ls is not None else None
        if ing >= li_d and (ls_d is None or ing <= ls_d):
            subsidio = _dec(sub_monto)
            return {
                "subsidio": _fmt(subsidio),
                "subsidio_efectivo": _fmt(subsidio),
                "referencia": f"LISR art. 174 (subsidio {per})",
            }

    return {
        "subsidio": "0.00",
        "subsidio_efectivo": "0.00",
        "referencia": "LISR art. 174 (ingreso excede límite)",
    }


# ---------------------------------------------------------------------------
# Prestaciones: aguinaldo, vacaciones, prima vacacional
# ---------------------------------------------------------------------------

def calc_aguinaldo(salario_diario, dias_trabajados=None, dias_ley=None, rates=None):
    """Aguinaldo proporcional (LFT art. 87): salario_diario × 15 días × (días/365).

    Si `dias_trabajados` es None, se asume el año completo (365 días).
    """
    r = rates or RATES
    dias_ley = dias_ley or r["aguinaldo_dias_ley"]
    sd = _dec(salario_diario)
    if dias_trabajados is None:
        return {
            "aguinaldo": _fmt(_round2(sd * dias_ley)),
            "dias": dias_ley,
            "proporcional": False,
            "referencia": "LFT art. 87 (aguinaldo ≥ 15 días)",
        }
    dt = _dec(dias_trabajados)
    # BUG-F8: Use actual days in year (366 for leap years)
    from calendar import isleap
    from datetime import date as _date
    year = _date.today().year
    dias_año = 366 if isleap(year) else 365
    monto = sd * dias_ley * (dt / Decimal(str(dias_año)))
    return {
        "aguinaldo": _fmt(_round2(monto)),
        "dias": dias_ley,
        "dias_trabajados": str(dt),
        "proporcional": True,
        "referencia": "LFT art. 87 (aguinaldo proporcional)",
    }


def dias_vacaciones(anios_trabajados):
    """Días de vacaciones por antigüedad (LFT art. 76, reformado 1-ene-2023).

    La reforma publicada en el DOF el 27-dic-2022 establece:
    - Año 1: 12 días; +2 por cada año hasta el 5.
    - A partir del SEXTO año, +2 días por cada 5 años de servicios.

    Tabla completa (LFT art. 76 vigente):
      Año  1: 12   Año  6: 22   Año 11: 24   Año 16: 26
      Año  2: 14   Año  7: 22   Año 12: 24   Año 17: 26
      Año  3: 16   Año  8: 22   Año 13: 24   Año 18: 26
      Año  4: 18   Año  9: 22   Año 14: 24   Año 19: 26
      Año  5: 20   Año 10: 22   Año 15: 24   Año 20: 26

    NOTA: El escalón abre en el SEXTO año, no en el décimo.
    El operador correcto para años ≥ 6 es: extra = ((año - 1) // 5) * 2
    """
    a = int(_dec(anios_trabajados))
    if a < 1:
        return 12
    if a <= 5:
        # Años 1-5: 12, 14, 16, 18, 20
        return 12 + 2 * (a - 1)
    # a >= 6: A partir del sexto año +2 cada 5 años
    # LFT art. 76 (reformado): el primer escalón abre en el año 6, no el 10.
    # Base: 20 días (5 años), luego 22 (6-10), 24 (11-15), 26 (16-20)...
    extra = ((a - 1) // 5) * 2
    return 20 + extra


def calc_vacaciones(salario_diario, anios_trabajados):
    """Pago de vacaciones: días × salario diario (LFT art. 76-77)."""
    dias = dias_vacaciones(anios_trabajados)
    sd = _dec(salario_diario)
    return {
        "dias": dias,
        "pago": _fmt(_round2(sd * dias)),
        "anios_trabajados": int(_dec(anios_trabajados)),
        "referencia": "LFT arts. 76-77",
    }


def calc_prima_vacacional(salario_diario, anios_trabajados, tasa=None, rates=None):
    """Prima vacacional: 25% del pago de vacaciones (LFT art. 80)."""
    r = rates or RATES
    tasa = _dec(tasa) if tasa is not None else r["prima_vacacional_tasa"]
    vac = calc_vacaciones(salario_diario, anios_trabajados)
    pago = _dec(vac["pago"])
    return {
        "prima": _fmt(_round2(pago * tasa)),
        "tasa": str(tasa),
        "pago_vacaciones": _fmt(pago),
        "dias": vac["dias"],
        "referencia": "LFT art. 80 (prima vacacional ≥ 25%)",
    }


# ---------------------------------------------------------------------------
# Nómina completa
# ---------------------------------------------------------------------------

def _sbc_desde(salario_diario, factor=None, rates=None):
    r = rates or RATES
    factor = _dec(factor) if factor is not None else r["factor_integracion"]
    return _round2(_dec(salario_diario) * factor)


def calculate_payroll(empleado, sueldo_bruto, dias_pagados=None,
                      sbc=None, percepciones_exentas=None, bono=None,
                      falta=False, periodicidad="mensual"):
    """Calcula una nómina completa (percepción + deducciones + neto).

    `empleado`: dict con al menos {salario_diario}. Campos opcionales:
        sbc (si no se pasa, se deriva con factor de integración),
        anios_trabajados (para prima vacacional opcional), nombre, rfc.

    Cambios vs versión anterior:
    - INFONAVIT 5% SBC es provisión patronal (Ley INFONAVIT art. 29-II),
      NO deducción al trabajador. Se reporta como provisión, no como
      deducción del neto.
    - IMSS se calcula por periodo (SBC diario × dias_pagados) con todos
      los componentes del trabajador (EYM + IV + RCVA + GMP).
    - Se agrega el subsidio para el empleo (LISR art. 174) cuando aplica.
    - Se soporta periodicidad quincenal para ISR y subsidio.

    Devuelve dict con percepciones, deducciones, neto y supuestos.
    """
    r = RATES
    sd = _dec(empleado.get("salario_diario"))
    sueldo = _dec(sueldo_bruto)
    exento = _dec(percepciones_exentas)
    bono_d = _dec(bono)
    sbc_d = _dec(sbc) if sbc is not None else _sbc_desde(sd, rates=r)
    dias = int(dias_pagados) if dias_pagados else 30

    gravado = sueldo + bono_d - exento
    if gravado < 0:
        gravado = Decimal("0")

    isr = calc_isr(gravado, periodicidad=periodicidad)
    imss = calc_imss(sbc_d, dias_pagados=dias, rates=r)
    # INFONAVIT es provisión patronal, NO deducción del trabajador
    infonavit = calc_infonavit(sbc_d, rates=r)

    # Subsidio para el empleo (LISR art. 174)
    isr_antes = _dec(isr["impuesto"])
    subsidio_info = calc_subsidio_empleo(gravado, periodicidad=periodicidad)
    subsidio = _dec(subsidio_info["subsidio"])
    subsidio_efectivo = _dec(subsidio_info["subsidio_efectivo"])
    # ISR neto = ISR antes del subsidio menos el subsidio (si subsidio > ISR, queda 0)
    isr_neto = max(Decimal("0"), isr_antes - subsidio)

    # INFONAVIT 5% SBC es APORTACION PATRONAL (Ley INFONAVIT art. 29-II),
    # NO deduccion al trabajador. Solo amortizacion de credito (art. 29-III)
    # se descuenta del trabajador, y su monto lo fija el instituto.
    _infonavit_patronal = infonavit["cuota"]

    percepciones = {
        "sueldo": _fmt(sueldo),
        "bono": _fmt(bono_d),
        "percepciones_exentas": _fmt(exento),
        "total_gravado": _fmt(gravado),
        "total": _fmt(sueldo + bono_d),
    }
    deducciones = {
        "isr": isr["impuesto"],
        "imss": imss["total"],
        "infonavit": "0.00",  # patronal, no deduccion al trabajador
    }
    total_ded = (_dec(isr["impuesto"]) + _dec(imss["total"]))
    # Si hay subsidio en efectivo (subsidio > ISR), se agrega al neto
    neto = _round2((sueldo + bono_d) - total_ded + subsidio_efectivo)

    return {
        "empleado": {
            "nombre": empleado.get("nombre", ""),
            "rfc": empleado.get("rfc", ""),
        },
        "salario_diario": _fmt(sd),
        "sbc": _fmt(sbc_d),
        "dias_pagados": dias,
        "periodicidad": periodicidad,
        "percepciones": percepciones,
        "deducciones": deducciones,
        "total_deducciones": _fmt(total_ded),
        "subsidio_empleo": {
            "monto": _fmt(subsidio),
            "subsidio_efectivo": _fmt(subsidio_efectivo),
            "isr_antes_subsidio": _fmt(isr_antes),
            "isr_neto": _fmt(isr_neto),
            "referencia": "LISR art. 174 (subsidio para el empleo)",
        },
        "neto_a_pagar": _fmt(neto),
        "provisiones_patron": {
            "infonavit": infonavit["cuota"],
            "infonavit_referencia": infonavit["referencia"],
            "aguinaldo": calc_aguinaldo(sd, rates=r)["aguinaldo"],
            "prima_vacacional": calc_prima_vacacional(
                sd, empleado.get("anios_trabajados", 1), rates=r)["prima"],
        },
        "supuestos": {
            "tarifa_isr": f"LISR art. 96 ({AÑO_FISCAL}, {periodicidad})",
            "imss": "LSS arts. 105-109, SBC diario × dias_pagados",
            "infonavit": "5% SBC — aportación patronal (art. 29-II Ley INFONAVIT)",
            "factor_integracion": str(r["factor_integracion"]),
            "subsidio_empleo": "LISR art. 174, Decreto DOF",
        },
        "requires_human_review": True,
        "referencia_legal": "LISR 96, 174 · LSS 105-109 · Ley INFONAVIT 29 · LFT 76-80, 87",
    }


# ---------------------------------------------------------------------------
# Generación de nómina CFDI (complemento Nomina 1.2)
# ---------------------------------------------------------------------------

def generate_payroll_cfdi(empleado, emisor, periodo, resultados=None,
                          serie="N", folio="1"):
    """Genera el XML de una nómina CFDI 4.0 (sin timbrar).

    `empleado`: {rfc, curp, nombre, salario_diario, num_seguridad_social,
                 periodicidad ('Mensual'|'Quincenal'), ...}
    `emisor`: {rfc, nombre, regimen_fiscal}
    `periodo`: {fecha_pago, fecha_inicial, fecha_final, dias_pagados}
    `resultados`: opcional, salida de `calculate_payroll`. Si no se da, se
        calcula internamente con `sueldo_bruto` del periodo.

    Devuelve una cadena XML lista para timbrar (requiere e.firma / PAC).
    """
    import xml.sax.saxutils as sx

    res = resultados or calculate_payroll(
        empleado, periodo.get("sueldo_bruto", 0),
        dias_pagados=periodo.get("dias_pagados"))
    d = res
    total = _dec(d["percepciones"]["total"])
    total_ded = _dec(d["total_deducciones"])

    emp = {
        "rfc": sx.escape(empleado.get("rfc", "")),
        "curp": sx.escape(empleado.get("curp", "")),
        "nombre": sx.escape(empleado.get("nombre", "")),
        "nss": sx.escape(empleado.get("num_seguridad_social", "")),
        "periodicidad": empleado.get("periodicidad", "Mensual"),
    }
    em = {
        "rfc": sx.escape(emisor.get("rfc", "")),
        "nombre": sx.escape(emisor.get("nombre", "")),
        "regimen": sx.escape(emisor.get("regimen_fiscal", "601")),
    }
    fechas = {k: periodo.get(k, "") for k in
              ("fecha_pago", "fecha_inicial", "fecha_final")}

    # Helper para OtroPago de subsidio (evita backslash en f-string)
    def _subsidio_otro_pago(d):
        sub_ef = _dec(d.get('subsidio_empleo', {}).get('subsidio_efectivo', '0'))
        if sub_ef is not None and sub_ef > 0:
            return f'<nomina:OtroPago TipoOtroPago="002" Clave="S001" Concepto="Subsidio para el empleo" Importe="{_fmt(sub_ef)}"/>'
        return ""

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
                  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                  xmlns:nomina="http://www.sat.gob.mx/nomina12"
                  xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
                  xsi:schemaLocation="http://www.sat.gob.mx/cfd/4 http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd
                                      http://www.sat.gob.mx/nomina12 http://www.sat.gob.mx/sitio_internet/cfd/nomina/nomina12.xsd"
                  Version="4.0" Serie="{sx.escape(serie)}" Folio="{sx.escape(str(folio))}"
                  Fecha="{fechas['fecha_pago']}"
                  FormaPago="99" MetodoPago="PUE" Moneda="MXN"
                  TipoDeComprobante="N" Exportacion="01"
                  LugarExpedicion="{sx.escape(emisor.get('lugar_expedicion', '06600'))}"
                  SubTotal="{_fmt(total)}" Total="{_fmt(_round2(total - total_ded))}">
  <cfdi:Emisor Rfc="{em['rfc']}" Nombre="{em['nombre']}" RegimenFiscal="{em['regimen']}"/>
  <cfdi:Receptor Rfc="{emp['rfc']}" Nombre="{emp['nombre']}"
                 DomicilioFiscalReceptor="{sx.escape(empleado.get('domicilio_fiscal', '06600'))}"
                 RegimenFiscalReceptor="605" UsoCFDI="CN01"/>
  <cfdi:Conceptos>
    <cfdi:Concepto ClaveProdServ="84111505" Cantidad="1" ClaveUnidad="ACT"
                   Unidad="Actividad" Descripcion="Pago de nómina"
                   ValorUnitario="{_fmt(total)}" Importe="{_fmt(total)}"
                   ObjetoImp="01"/>
  </cfdi:Conceptos>
  <cfdi:Complemento>
    <nomina:Nomina Version="1.2" TipoNomina="O"
                   FechaPago="{fechas['fecha_pago']}"
                   FechaInicialPago="{fechas['fecha_inicial']}"
                   FechaFinalPago="{fechas['fecha_final']}"
                   NumDiasPagados="{periodo.get('dias_pagados', '')}"
                   TotalPercepciones="{_fmt(total)}"
                   TotalDeducciones="{_fmt(total_ded)}"
                   TotalOtrosPagos="{_fmt(_dec(d.get('subsidio_empleo', {}).get('subsidio_efectivo', '0')))}">
      <nomina:Emisor RegistroPatronal="{sx.escape(empleado.get('registro_patronal', ''))}"/>
      <nomina:Receptor Curp="{emp['curp']}" NumSeguridadSocial="{emp['nss']}"
                       PeriodicidadPago="{emp['periodicidad']}"
                       TipoContrato="{sx.escape(empleado.get('tipo_contrato', '01'))}"
                       TipoJornada="{sx.escape(empleado.get('tipo_jornada', '01'))}"
                       TipoRegimen="{sx.escape(empleado.get('tipo_regimen', '02'))}"
                       NumEmpleado="{sx.escape(empleado.get('num_empleado', '1'))}"
                       Departamento="{sx.escape(empleado.get('departamento', ''))}"/>
      <nomina:Percepciones TotalSueldos="{_fmt(_dec(d['percepciones']['sueldo']))}"
                           TotalGravado="{_fmt(_dec(d['percepciones']['total_gravado']))}"
                           TotalExento="{_fmt(_dec(d['percepciones']['percepciones_exentas']))}">
        <nomina:Percepcion TipoPercepcion="001" Clave="P001" Concepto="Sueldos"
                           ImporteGravado="{_fmt(_dec(d['percepciones']['total_gravado']))}"
                           ImporteExento="{_fmt(_dec(d['percepciones']['percepciones_exentas']))}"/>
      </nomina:Percepciones>
      <nomina:Deducciones TotalOtrasDeducciones="{_fmt(total_ded)}">
        <nomina:Deduccion TipoDeduccion="002" Clave="D002" Concepto="ISR"
                          Importe="{d['deducciones']['isr']}"/>
        <nomina:Deduccion TipoDeduccion="001" Clave="D001" Concepto="Seguridad social"
                          Importe="{d['deducciones']['imss']}"/>
        <!-- INFONAVIT 5% SBC eliminado de deducciones del trabajador:
             es aportación patronal (Ley INFONAVIT art. 29-II).
             Solo se incluye aquí si hay amortización de crédito INFONAVIT
             activo (art. 29-III), con monto fijado por el instituto. -->
      </nomina:Deducciones>
      <!-- Subsidio para el empleo (LISR art. 174): OtroPago TipoOtroPago="002" -->
      {"" if _dec(d.get('subsidio_empleo', {}).get('subsidio_efectivo', '0')) <= 0 else '<nomina:OtrosPagos>'}
      {_subsidio_otro_pago(d)}
      {"" if _dec(d.get('subsidio_empleo', {}).get('subsidio_efectivo', '0')) <= 0 else '</nomina:OtrosPagos>'}
    </nomina:Nomina>
  </cfdi:Complemento>
</cfdi:Comprobante>
"""
    return xml
