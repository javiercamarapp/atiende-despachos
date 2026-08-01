# -*- coding: utf-8 -*-
"""
accounting.py — Contabilidad electrónica: catálogo de cuentas (CUC), balanza
de comprobación y envío XML al SAT (mock).

Cubre los entregables de la contabilidad electrónica del enterprise MVP:
  - Catálogo de cuentas estándar (estructura tipo SAT / Código Agrupador).
  - Balanza de comprobación agregada desde facturas (cargos/abonos/saldos).
  - Envío de la balanza al SAT (mock: genera el XML y un acuse de recepción
    simulado; la presentación real exige e.firma / software del SAT).

> Aviso: prepara y valida; el profesional presenta ante el SAT. La
> presentación real está fuera de alcance (requiere e.firma y el servicio
> oficial de contabilidad electrónica).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

# ---------------------------------------------------------------------------
# Catálogo de cuentas (CUC — estructura simplificada tipo SAT)
# ---------------------------------------------------------------------------

# (codigo, descripcion, nivel, tipo) — tipo: D=deudora, A=acreedora
CATALOGO_CUENTAS = [
    ("1000", "ACTIVO", 1, "D"),
    ("1100", "ACTIVO CIRCULANTE", 2, "D"),
    ("1101", "BANCOS", 3, "D"),
    ("1102", "CLIENTES", 3, "D"),
    ("1103", "IVA ACREDITABLE", 3, "D"),
    ("1104", "INVENTARIOS", 3, "D"),
    ("1200", "ACTIVO FIJO", 2, "D"),
    ("1201", "MOBILIARIO Y EQUIPO", 3, "D"),
    ("1202", "EQUIPO DE COMPUTO", 3, "D"),
    ("1300", "ACTIVOS DIFERIDOS", 2, "D"),
    ("2000", "PASIVO", 1, "A"),
    ("2100", "PASIVO CIRCULANTE", 2, "A"),
    ("2101", "PROVEEDORES", 3, "A"),
    ("2102", "ACREEDORES DIVERSOS", 3, "A"),
    ("2103", "IVA ACREDITABLE POR TRASLADAR", 3, "A"),
    ("2104", "IMPUESTOS POR PAGAR", 3, "A"),
    ("2200", "PASIVO A LARGO PLAZO", 2, "A"),
    ("2300", "PASIVO DIFERIDO", 2, "A"),
    ("3000", "CAPITAL CONTABLE", 1, "A"),
    ("3100", "CAPITAL SOCIAL", 2, "A"),
    ("3200", "RESULTADOS ACUMULADOS", 2, "A"),
    ("4000", "INGRESOS", 1, "A"),
    ("4100", "INGRESOS POR SERVICIOS", 2, "A"),
    ("4200", "OTROS INGRESOS", 2, "A"),
    ("5000", "COSTOS", 1, "D"),
    ("5100", "COSTO DE VENTAS", 2, "D"),
    ("6000", "GASTOS", 1, "D"),
    ("6100", "GASTOS DE OPERACION", 2, "D"),
    ("6101", "SUELDOS Y SALARIOS", 3, "D"),
    ("6102", "GASTOS ADMINISTRATIVOS", 3, "D"),
    ("6103", "GASTOS FINANCIEROS", 3, "D"),
    ("6200", "GASTOS NO DEDUCIBLES", 2, "D"),
]

# Mapeo de categoría de factura -> cuenta contable (regla simple).
CATEGORIA_A_CUENTA = {
    "gasto_operativo": "6102",   # GASTOS ADMINISTRATIVOS
    "inversion": "1202",          # EQUIPO DE COMPUTO (inversión/activo)
    "activo_fijo": "1201",        # MOBILIARIO Y EQUIPO
    "nomina": "6101",             # SUELDOS Y SALARIOS
    "ingreso": "4100",            # INGRESOS POR SERVICIOS
    "venta": "4100",
    "servicios": "4100",
    "costo": "5100",              # COSTO DE VENTAS
    "impuestos": "2104",          # IMPUESTOS POR PAGAR
    "desconocido": "6102",
}


def _dec(v, default=Decimal("0")):
    try:
        if v is None or v == "":
            return default
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return default


def _round2(d):
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _fmt(d):
    return str(_round2(d))


def get_catalogo():
    """Devuelve el catálogo de cuentas."""
    return [{"codigo": c, "descripcion": d, "nivel": n, "tipo": t}
            for c, d, n, t in CATALOGO_CUENTAS]


def find_account(codigo):
    """Busca una cuenta por código. Devuelve dict o None."""
    for c, d, n, t in CATALOGO_CUENTAS:
        if c == str(codigo):
            return {"codigo": c, "descripcion": d, "nivel": n, "tipo": t}
    return None


def cuenta_para_categoria(categoria):
    """Resuelve la cuenta contable para una categoría de factura."""
    cat = (categoria or "desconocido").lower()
    return CATEGORIA_A_CUENTA.get(cat, "6102")


def _periodo(fecha):
    return str(fecha)[:7] if fecha else ""


# ---------------------------------------------------------------------------
# Balanza de comprobación
# ---------------------------------------------------------------------------

def build_balance(invoices, period=None, tenant_id=None):
    """Construye la balanza de comprobación desde facturas.

    invoices: lista de dicts con {fecha, total, categoria, tenant_id, valido}.
    period: 'YYYY-MM' opcional para filtrar.
    tenant_id: opcional para filtrar.

    Agrupa por cuenta (según la categoría). Para cuentas deudoras el total va
    a `cargo`; para acreedoras (ingresos) a `abono`. Devuelve la balanza con
    totales, saldo y el resultado del chequeo de equilibrio.
    """
    rows = [r for r in invoices]
    if period:
        rows = [r for r in rows if _periodo(r.get("fecha")) == period]
    if tenant_id is not None:
        rows = [r for r in rows if str(r.get("tenant_id")) == str(tenant_id)]

    # Acumular por cuenta
    agrupado = defaultdict(lambda: {"cargo": Decimal("0"), "abono": Decimal("0"),
                                    "count": 0})
    for r in rows:
        total = _dec(r.get("total"))
        if total == 0:
            continue
        cuenta = cuenta_para_categoria(r.get("categoria"))
        if not find_account(cuenta):
            continue
        acc = agrupado[cuenta]
        acc["count"] += 1
        cuenta_tipo = find_account(cuenta)["tipo"]
        if cuenta_tipo == "D":
            acc["cargo"] += total
        else:
            acc["abono"] += total

    # Líneas de balanza
    lineas = []
    for codigo in sorted(agrupado):
        acc = agrupado[codigo]
        acct = find_account(codigo)
        cargo = acc["cargo"]
        abono = acc["abono"]
        # Saldo = deudor (cargo-abono) o acreedor (abono-cargo) según naturaleza
        if acct["tipo"] == "D":
            saldo = cargo - abono
            naturaleza = "deudor"
        else:
            saldo = abono - cargo
            naturaleza = "acreedor"
        lineas.append({
            "cuenta": codigo,
            "descripcion": acct["descripcion"],
            "nivel": acct["nivel"],
            "tipo": acct["tipo"],
            "cargo": _fmt(cargo),
            "abono": _fmt(abono),
            "saldo": _fmt(saldo),
            "naturaleza": naturaleza,
            "movimientos": acc["count"],
        })

    total_cargo = sum(_dec(l["cargo"]) for l in lineas)
    total_abono = sum(_dec(l["abono"]) for l in lineas)
    balanceado = total_cargo == total_abono

    return {
        "periodo": period,
        "tenant_id": tenant_id,
        "cuentas": len(lineas),
        "movimientos": sum(l["movimientos"] for l in lineas),
        "total_cargo": _fmt(total_cargo),
        "total_abono": _fmt(total_abono),
        "balanceado": balanceado,
        "lineas": lineas,
    }


def build_balanza_from_entries(entries, period=None):
    """Balanza genérica desde movimientos {cuenta, cargo, abono}."""
    agrupado = defaultdict(lambda: {"cargo": Decimal("0"), "abono": Decimal("0")})
    for e in entries:
        cta = e.get("cuenta")
        if not cta:
            continue
        agrupado[cta]["cargo"] += _dec(e.get("cargo"))
        agrupado[cta]["abono"] += _dec(e.get("abono"))
    lineas = []
    for cta in sorted(agrupado):
        acct = find_account(cta) or {"descripcion": "Cuenta", "tipo": "D", "nivel": 3}
        cargo = agrupado[cta]["cargo"]
        abono = agrupado[cta]["abono"]
        saldo = (cargo - abono) if acct["tipo"] == "D" else (abono - cargo)
        naturaleza = "deudor" if acct["tipo"] == "D" else "acreedor"
        lineas.append({
            "cuenta": cta, "descripcion": acct["descripcion"],
            "cargo": _fmt(cargo), "abono": _fmt(abono),
            "saldo": _fmt(saldo), "naturaleza": naturaleza,
        })
    total_cargo = sum(_dec(l["cargo"]) for l in lineas)
    total_abono = sum(_dec(l["abono"]) for l in lineas)
    return {
        "periodo": period,
        "cuentas": len(lineas),
        "total_cargo": _fmt(total_cargo),
        "total_abono": _fmt(total_abono),
        "balanceado": total_cargo == total_abono,
        "lineas": lineas,
    }


# ---------------------------------------------------------------------------
# Envío XML al SAT (mock)
# ---------------------------------------------------------------------------

def build_balanza_xml(balanza, ejercicio, mes, tipo_envio="B", rfc="",
                      razon_social=""):
    """Genera el XML de balanza de comprobación (formato SAT, simplificado).

    tipo_envio: 'B' = balanza de comprobación, 'C' = catálogo de cuentas.
    """
    import xml.sax.saxutils as sx

    def esc(v):
        return sx.escape(str(v or ""))

    hoy = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    mes_s = str(mes).zfill(2)
    lineas_xml = "\n".join(
        f"""      <ct:Cuenta NumCta="{esc(l['cuenta'])}"
                   SaldoIni="{esc(l.get('saldo_inicial', '0.00'))}"
                   Debe="{esc(l['cargo'])}"
                   Haber="{esc(l['abono'])}"
                   SaldoFin="{esc(l['saldo'])}"/>"""
        for l in balanza.get("lineas", []))
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Rep:Repositorio xmlns:Rep="http://www.sat.gob.mx/esquemas/repositorio/1"
                 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                 xsi:schemaLocation="http://www.sat.gob.mx/esquemas/repositorio/1 http://www.sat.gob.mx/esquemas/repositorio/1/repositorio.xsd"
                 Version="1.1">
  <Rep:Solicitud>
    <Rep:Rfc>{esc(rfc)}</Rep:Rfc>
    <Rep:Ejercicio>{esc(ejercicio)}</Rep:Ejercicio>
    <Rep:Mes>{esc(mes_s)}</Rep:Mes>
    <Rep:TipoEnvio>{esc(tipo_envio)}</Rep:TipoEnvio>
    <Rep:Balance>
      <ct:Balanza xmlns:ct="http://www.sat.gob.mx/esquemas/ContabilidadE/1_1/BalanzaComprobacion"
                  Version="1.1" TipoEnvio="{esc(tipo_envio)}"
                  RFC="{esc(rfc)}" Mes="{esc(mes_s)}"
                  Anio="{esc(ejercicio)}"
                  FechaModificacion="{hoy}"
                  Sello="{''}" noCertificado="{''}" Certificado="{''}">
{lineas_xml}
      </ct:Balanza>
    </Rep:Balance>
  </Rep:Solicitud>
</Rep:Repositorio>
"""
    return xml


def send_balance_to_sat(balanza, ejercicio, mes, rfc="", razon_social="",
                        tipo_envio="B", mock=True):
    """Envía la balanza de comprobación al SAT (MOCK).

    En modo mock devuelve un acuse simulado con folio y estatus 'Aceptado'.
    La presentación real exige e.firma y el servicio oficial del SAT
    (contabilidad electrónica) — fuera de alcance del MVP.
    """
    if mock:
        import uuid
        folio = str(uuid.uuid4())
        hoy = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        xml = build_balanza_xml(balanza, ejercicio, mes, tipo_envio, rfc,
                                razon_social)
        return {
            "estatus": "Aceptado",
            "folio": folio,
            "fecha_envio": hoy,
            "ejercicio": ejercicio,
            "mes": mes,
            "tipo_envio": tipo_envio,
            "xml_generado": xml,
            "rfc": rfc,
            "razon_social": razon_social,
            "mock": True,
            "nota": "Acuse simulado. La presentación real requiere e.firma.",
        }
    raise NotImplementedError("Envío real al SAT no implementado (requiere "
                              "e.firma / servicio oficial).")
