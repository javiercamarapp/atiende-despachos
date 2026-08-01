# -*- coding: utf-8 -*-
"""
payroll.py — Nómina: cálculo de retenciones/prestaciones y generación de
nómina CFDI 4.0 con complemento Nomina 1.2.

Cubre: ISR (tarifa progresiva mensual, LISR art. 96), IMSS (trabajador),
INFONAVIT (5% SBC), PTU (10% renta gravable, LFT art. 123 fr. IX), aguinaldo
(LFT art. 87), vacaciones (LFT art. 76-77) y prima vacacional (LFT art. 80).

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

# Tarifa mensual ISR — LISR art. 96 (año fiscal 2025).
# (limite_inferior, limite_superior, cuota_fija, porcentaje_excedente)
TARIFA_ISR_2025_MENSUAL = [
    ("0.01", "746.04", "0.00", "0.0192"),
    ("746.05", "6332.05", "14.32", "0.0640"),
    ("6332.06", "11128.01", "371.83", "0.1088"),
    ("11128.02", "12935.82", "893.63", "0.1600"),
    ("12935.83", "15487.71", "1182.88", "0.1792"),
    ("15487.72", "31236.49", "1640.18", "0.2136"),
    ("31236.50", "49233.00", "5004.12", "0.2352"),
    ("49233.01", "93993.90", "9236.89", "0.3000"),
    ("93993.91", "125325.20", "22665.17", "0.3200"),
    ("125325.21", "375975.61", "32691.18", "0.3400"),
    ("375975.62", None, "117912.32", "0.3500"),
]

# Cuotas/tasas de ley (configurables, con supuesto documentado).
RATES = {
    "imss_trabajador_eym": Decimal("0.01125"),   # Enfermedad y Maternidad (trabajador) aprox.
    "imss_trabajador_rcva": Decimal("0.01125"),  # Retiro, Cesantía y Vejez (trabajador) aprox.
    "imss_total_trabajador": Decimal("0.0175"),  # Simplificación para el resumen (≈ EYM + RCVA)
    "infonavit_tasa": Decimal("0.0500"),         # 5% del SBC
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
    """Calcula el ISR con la tarifa progresiva mensual (LISR art. 96).

    Devuelve {impuesto, ingreso_gravado, rango_aplicado, referencia}.
    """
    tarifa = tarifa or TARIFA_ISR_2025_MENSUAL
    ing = _dec(ingreso_gravado)
    if ing <= 0:
        return {"impuesto": "0.00", "ingreso_gravado": _fmt(ing),
                "rango_aplicado": None, "referencia": "LISR art. 96"}
    for li, ls, cuota, pct in tarifa:
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
                "referencia": "LISR art. 96 (tarifa mensual)",
            }
    # Cae por debajo del primer rango (ingreso < 0.01) -> no aplica
    return {"impuesto": "0.00", "ingreso_gravado": _fmt(ing),
            "rango_aplicado": None, "referencia": "LISR art. 96"}


# ---------------------------------------------------------------------------
# IMSS, INFONAVIT, PTU
# ---------------------------------------------------------------------------

def calc_imss(salario_base_cotizacion, rates=None):
    """Cuota del trabajador al IMSS (aprox. EYM + RCVA).

    Devuelve {eym, rcva, total, sbc}. Supuesto: porcentajes configurables.
    """
    r = rates or RATES
    sbc = _dec(salario_base_cotizacion)
    eym = _round2(sbc * r["imss_trabajador_eym"])
    rcva = _round2(sbc * r["imss_trabajador_rcva"])
    return {
        "eym": _fmt(eym),
        "rcva": _fmt(rcva),
        "total": _fmt(eym + rcva),
        "sbc": _fmt(sbc),
        "referencia": "LSS (aportaciones del trabajador)",
    }


def calc_infonavit(salario_base_cotizacion, tasa=None, rates=None):
    """Cuota INFONAVIT (5% del SBC)."""
    r = rates or RATES
    tasa = _dec(tasa) if tasa is not None else r["infonavit_tasa"]
    sbc = _dec(salario_base_cotizacion)
    return {
        "cuota": _fmt(_round2(sbc * tasa)),
        "tasa": str(tasa),
        "sbc": _fmt(sbc),
        "referencia": "Ley INFONAVIT (5% SBC)",
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
    monto = sd * dias_ley * (dt / Decimal("365"))
    return {
        "aguinaldo": _fmt(_round2(monto)),
        "dias": dias_ley,
        "dias_trabajados": str(dt),
        "proporcional": True,
        "referencia": "LFT art. 87 (aguinaldo proporcional)",
    }


def dias_vacaciones(anios_trabajados):
    """Días de vacaciones por antigüedad (LFT art. 76-77).

    Año 1: 12 días; +2 por cada año hasta 20; después +2 cada 5 años.
    """
    a = int(_dec(anios_trabajados))
    if a < 1:
        return 12
    if a <= 4:
        return 12 + 2 * (a - 1)
    # a >= 5: base 20 días + incremento cada 5 años
    extra = ((a - 5) // 5) * 2
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
                      falta=False):
    """Calcula una nómina completa (percepción + deducciones + neto).

    `empleado`: dict con al menos {salario_diario}. Campos opcionales:
        sbc (si no se pasa, se deriva con factor de integración),
        anios_trabajados (para prima vacacional opcional), nombre, rfc.

    Devuelve dict con percepciones, deducciones, neto y supuestos.
    """
    r = RATES
    sd = _dec(empleado.get("salario_diario"))
    sueldo = _dec(sueldo_bruto)
    exento = _dec(percepciones_exentas)
    bono_d = _dec(bono)
    sbc_d = _dec(sbc) if sbc is not None else _sbc_desde(sd, rates=r)

    gravado = sueldo + bono_d - exento
    if gravado < 0:
        gravado = Decimal("0")

    isr = calc_isr(gravado)
    imss = calc_imss(sbc_d, rates=r)
    infonavit = calc_infonavit(sbc_d, rates=r)

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
        "infonavit": infonavit["cuota"],
    }
    total_ded = (_dec(isr["impuesto"]) + _dec(imss["total"])
                 + _dec(infonavit["cuota"]))
    neto = _round2((sueldo + bono_d) - total_ded)

    return {
        "empleado": {
            "nombre": empleado.get("nombre", ""),
            "rfc": empleado.get("rfc", ""),
        },
        "salario_diario": _fmt(sd),
        "sbc": _fmt(sbc_d),
        "dias_pagados": dias_pagados,
        "percepciones": percepciones,
        "deducciones": deducciones,
        "total_deducciones": _fmt(total_ded),
        "neto_a_pagar": _fmt(neto),
        "provisiones": {
            "aguinaldo": calc_aguinaldo(sd, rates=r)["aguinaldo"],
            "prima_vacacional": calc_prima_vacacional(
                sd, empleado.get("anios_trabajados", 1), rates=r)["prima"],
        },
        "supuestos": {
            "tarifa_isr": f"LISR art. 96 ({AÑO_FISCAL})",
            "imss": "aportaciones del trabajador (EYM + RCVA)",
            "infonavit": "5% SBC",
            "factor_integracion": str(r["factor_integracion"]),
        },
        "requires_human_review": True,
        "referencia_legal": "LISR 96 · LSS · Ley INFONAVIT · LFT 76-80, 87",
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
                   TotalDeducciones="{_fmt(total_ded)}">
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
        <nomina:Deduccion TipoDeduccion="003" Clave="D003" Concepto="INFONAVIT"
                          Importe="{d['deducciones']['infonavit']}"/>
      </nomina:Deducciones>
    </nomina:Nomina>
  </cfdi:Complemento>
</cfdi:Comprobante>
"""
    return xml
