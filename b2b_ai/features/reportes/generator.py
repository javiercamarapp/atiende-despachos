# -*- coding: utf-8 -*-
"""
generator.py — Generadores de reportes contables profesionales.

Cada generador construye un `ReportData` con secciones, líneas y totales.
Los reportes son:

  - Balance General: activos, pasivos, capital contable con subtotales
  - Estado de Resultados: ingresos, costos, gastos, utilidad/pérdida
  - Conciliación Bancaria: transacciones conciliadas vs no conciliadas
  - Reporte de Nómina: resumen de nómina por periodo

Uso:
    report = generate_balance_general(assets=[...], liabilities=[...], equity=[...])
    report.to_dict()
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

def _fmt_money(value: Any) -> str:
    """Formatea un valor numérico como string monetario (pesos MXN)."""
    if value is None:
        return "$0.00"
    try:
        d = Decimal(str(value))
        return f"${d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"
    except (InvalidOperation, ValueError):
        return "$0.00"


def _to_decimal(value: Any) -> Decimal:
    """Convierte un valor arbitrario a Decimal."""
    if value is None:
        return Decimal("0.00")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


@dataclass
class ReportLine:
    """Una línea individual dentro de una sección del reporte."""
    concepto: str
    importe: Decimal = field(default_factory=Decimal)
    subconcepto: str = ""
    nivel: int = 0  # 0 = raíz, 1 = subcuenta, etc.

    @property
    def importe_formatted(self) -> str:
        return _fmt_money(self.importe)

    def to_dict(self) -> dict:
        return {
            "concepto": self.concepto,
            "importe": str(self.importe),
            "importe_formatted": self.importe_formatted,
            "subconcepto": self.subconcepto,
            "nivel": self.nivel,
        }


@dataclass
class ReportSection:
    """Una sección del reporte (e.g. Activos Circulantes, Pasivos)."""
    titulo: str
    lineas: list[ReportLine] = field(default_factory=list)
    subtotal: Decimal = field(default_factory=Decimal)
    subtotal_label: str = "Total"

    @property
    def subtotal_formatted(self) -> str:
        return _fmt_money(self.subtotal)

    def to_dict(self) -> dict:
        return {
            "titulo": self.titulo,
            "lineas": [l.to_dict() for l in self.lineas],
            "subtotal": str(self.subtotal),
            "subtotal_formatted": self.subtotal_formatted,
            "subtotal_label": self.subtotal_label,
        }


@dataclass
class ReportData:
    """Estructura unificada de datos de un reporte contable."""
    titulo: str
    subtitulo: str
    empresa_rfc: str = ""
    empresa_nombre: str = ""
    fecha_generacion: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    periodo_inicio: str = ""
    periodo_fin: str = ""
    secciones: list[ReportSection] = field(default_factory=list)
    totales: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "titulo": self.titulo,
            "subtitulo": self.subtitulo,
            "empresa_rfc": self.empresa_rfc,
            "empresa_nombre": self.empresa_nombre,
            "fecha_generacion": self.fecha_generacion,
            "periodo_inicio": self.periodo_inicio,
            "periodo_fin": self.periodo_fin,
            "secciones": [s.to_dict() for s in self.secciones],
            "totales": self.totales,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Generadores
# ---------------------------------------------------------------------------

def generate_balance_general(
    activos_circulantes: list[dict] | None = None,
    activos_fijos: list[dict] | None = None,
    pasivos_circulantes: list[dict] | None = None,
    pasivos_largo_plazo: list[dict] | None = None,
    capital_contable: list[dict] | None = None,
    empresa_rfc: str = "",
    empresa_nombre: str = "",
    periodo_inicio: str = "",
    periodo_fin: str = "",
) -> ReportData:
    """Genera un Balance General (Estado de Situación Financiera).

    Cada lista recibe dicts con al menos `concepto` y `importe`.

    Returns:
        ReportData con secciones Activos, Pasivos, Capital Contable
        y totales que deben cuadrar: Activos = Pasivos + Capital.
    """
    activos_circ = activos_circulantes or []
    activos_fij = activos_fijos or []
    pasivos_circ = pasivos_circulantes or []
    pasivos_lp = pasivos_largo_plazo or []
    cap_contable = capital_contable or []

    sections = []

    # Activos Circulantes
    sec_ac = ReportSection(titulo="Activos Circulantes", subtotal_label="Total Activos Circulantes")
    total_ac = Decimal("0")
    for item in activos_circ:
        importe = _to_decimal(item.get("importe", 0))
        rl = ReportLine(
            concepto=item.get("concepto", ""),
            importe=importe,
            subconcepto=item.get("subconcepto", ""),
            nivel=item.get("nivel", 0),
        )
        sec_ac.lineas.append(rl)
        total_ac += importe
    sec_ac.subtotal = total_ac
    sections.append(sec_ac)

    # Activos Fijos
    sec_af = ReportSection(titulo="Activos Fijos", subtotal_label="Total Activos Fijos")
    total_af = Decimal("0")
    for item in activos_fij:
        importe = _to_decimal(item.get("importe", 0))
        rl = ReportLine(
            concepto=item.get("concepto", ""),
            importe=importe,
            subconcepto=item.get("subconcepto", ""),
            nivel=item.get("nivel", 0),
        )
        sec_af.lineas.append(rl)
        total_af += importe
    sec_af.subtotal = total_af
    sections.append(sec_af)

    total_activos = total_ac + total_af

    # Pasivos Circulantes
    sec_pc = ReportSection(titulo="Pasivos Circulantes", subtotal_label="Total Pasivos Circulantes")
    total_pc = Decimal("0")
    for item in pasivos_circ:
        importe = _to_decimal(item.get("importe", 0))
        rl = ReportLine(
            concepto=item.get("concepto", ""),
            importe=importe,
            subconcepto=item.get("subconcepto", ""),
            nivel=item.get("nivel", 0),
        )
        sec_pc.lineas.append(rl)
        total_pc += importe
    sec_pc.subtotal = total_pc
    sections.append(sec_pc)

    # Pasivos a Largo Plazo
    sec_lp = ReportSection(titulo="Pasivos a Largo Plazo", subtotal_label="Total Pasivos a Largo Plazo")
    total_lp = Decimal("0")
    for item in pasivos_lp:
        importe = _to_decimal(item.get("importe", 0))
        rl = ReportLine(
            concepto=item.get("concepto", ""),
            importe=importe,
            subconcepto=item.get("subconcepto", ""),
            nivel=item.get("nivel", 0),
        )
        sec_lp.lineas.append(rl)
        total_lp += importe
    sec_lp.subtotal = total_lp
    sections.append(sec_lp)

    total_pasivos = total_pc + total_lp

    # Capital Contable
    sec_cc = ReportSection(titulo="Capital Contable", subtotal_label="Total Capital Contable")
    total_cc = Decimal("0")
    for item in cap_contable:
        importe = _to_decimal(item.get("importe", 0))
        rl = ReportLine(
            concepto=item.get("concepto", ""),
            importe=importe,
            subconcepto=item.get("subconcepto", ""),
            nivel=item.get("nivel", 0),
        )
        sec_cc.lineas.append(rl)
        total_cc += importe
    sec_cc.subtotal = total_cc
    sections.append(sec_cc)

    total_pasivos_capital = total_pasivos + total_cc

    totales = {
        "total_activos_circulantes": str(total_ac),
        "total_activos_fijos": str(total_af),
        "total_activos": str(total_activos),
        "total_pasivos_circulantes": str(total_pc),
        "total_pasivos_largo_plazo": str(total_lp),
        "total_pasivos": str(total_pasivos),
        "total_capital_contable": str(total_cc),
        "total_pasivos_y_capital": str(total_pasivos_capital),
        "cuadra": str(total_activos == total_pasivos_capital),
    }

    return ReportData(
        titulo="Balance General",
        subtitulo="Estado de Situación Financiera",
        empresa_rfc=empresa_rfc,
        empresa_nombre=empresa_nombre,
        periodo_inicio=periodo_inicio,
        periodo_fin=periodo_fin,
        secciones=sections,
        totales=totales,
        metadata={
            "tipo_reporte": "balance_general",
            "formato": "IFRS simplificado",
            "moneda": "MXN",
        },
    )


def generate_estado_resultados(
    ingresos: list[dict] | None = None,
    costos: list[dict] | None = None,
    gastos_operacion: list[dict] | None = None,
    gastos_administracion: list[dict] | None = None,
    otros_ingresos: list[dict] | None = None,
    impuestos: list[dict] | None = None,
    empresa_rfc: str = "",
    empresa_nombre: str = "",
    periodo_inicio: str = "",
    periodo_fin: str = "",
) -> ReportData:
    """Genera un Estado de Resultados.

    Calcula utilidad bruta, utilidad de operación, utilidad antes de impuestos
    y utilidad neta.

    Returns:
        ReportData con secciones y totales calculados.
    """
    def _sum_items(items: list[dict]) -> tuple[ReportSection, Decimal]:
        total = Decimal("0")
        sec = ReportSection(titulo="")
        for item in items:
            importe = _to_decimal(item.get("importe", 0))
            rl = ReportLine(
                concepto=item.get("concepto", ""),
                importe=importe,
                subconcepto=item.get("subconcepto", ""),
                nivel=item.get("nivel", 0),
            )
            sec.lineas.append(rl)
            total += importe
        sec.subtotal = total
        return sec, total

    sections = []
    total_ingresos = Decimal("0")
    total_costos = Decimal("0")
    total_gastos_op = Decimal("0")
    total_gastos_adm = Decimal("0")
    total_otros_ingresos = Decimal("0")
    total_impuestos = Decimal("0")

    # Ingresos
    sec_ing, total_ingresos = _sum_items(ingresos or [])
    sec_ing.titulo = "Ingresos"
    sec_ing.subtotal_label = "Total Ingresos"
    sections.append(sec_ing)

    # Costos
    sec_cos, total_costos = _sum_items(costos or [])
    sec_cos.titulo = "Costos"
    sec_cos.subtotal_label = "Total Costos"
    sections.append(sec_cos)

    utilidad_bruta = total_ingresos - total_costos

    # Gastos de Operación
    sec_go, total_gastos_op = _sum_items(gastos_operacion or [])
    sec_go.titulo = "Gastos de Operación"
    sec_go.subtotal_label = "Total Gastos de Operación"
    sections.append(sec_go)

    # Gastos de Administración
    sec_ga, total_gastos_adm = _sum_items(gastos_administracion or [])
    sec_ga.titulo = "Gastos de Administración"
    sec_ga.subtotal_label = "Total Gastos de Administración"
    sections.append(sec_ga)

    utilidad_operacion = utilidad_bruta - total_gastos_op - total_gastos_adm

    # Otros Ingresos
    sec_oi, total_otros_ingresos = _sum_items(otros_ingresos or [])
    sec_oi.titulo = "Otros Ingresos"
    sec_oi.subtotal_label = "Total Otros Ingresos"
    sections.append(sec_oi)

    utilidad_antes_impuestos = utilidad_operacion + total_otros_ingresos

    # Impuestos
    sec_imp, total_impuestos = _sum_items(impuestos or [])
    sec_imp.titulo = "Impuestos"
    sec_imp.subtotal_label = "Total Impuestos"
    sections.append(sec_imp)

    utilidad_neta = utilidad_antes_impuestos - total_impuestos

    totales = {
        "total_ingresos": str(total_ingresos),
        "total_costos": str(total_costos),
        "utilidad_bruta": str(utilidad_bruta),
        "total_gastos_operacion": str(total_gastos_op),
        "total_gastos_administracion": str(total_gastos_adm),
        "utilidad_operacion": str(utilidad_operacion),
        "total_otros_ingresos": str(total_otros_ingresos),
        "utilidad_antes_impuestos": str(utilidad_antes_impuestos),
        "total_impuestos": str(total_impuestos),
        "utilidad_neta": str(utilidad_neta),
    }

    return ReportData(
        titulo="Estado de Resultados",
        subtitulo="Resultado del Ejercicio",
        empresa_rfc=empresa_rfc,
        empresa_nombre=empresa_nombre,
        periodo_inicio=periodo_inicio,
        periodo_fin=periodo_fin,
        secciones=sections,
        totales=totales,
        metadata={
            "tipo_reporte": "estado_resultados",
            "formato": "IFRS simplificado",
            "moneda": "MXN",
        },
    )


def generate_conciliacion_bancaria(
    movimientos_banco: list[dict] | None = None,
    movimientos_contabilidad: list[dict] | None = None,
    empresa_rfc: str = "",
    empresa_nombre: str = "",
    periodo_inicio: str = "",
    periodo_fin: str = "",
    banco_nombre: str = "",
    numero_cuenta: str = "",
) -> ReportData:
    """Genera un reporte de Conciliación Bancaria.

    Clasifica movimientos en conciliados y no conciliados, y calcula
    el saldo bancario vs saldo contable.

    Args:
        movimientos_banco: lista de dicts con keys:
            - fecha, descripcion, monto, conciliado (bool)
        movimientos_contabilidad: lista de dicts con keys:
            - fecha, descripcion, monto, conciliado (bool)

    Returns:
        ReportData con secciones de movimientos conciliados/no conciliados
        y saldos reconciliados.
    """
    bancos = movimientos_banco or []
    contab = movimientos_contabilidad or []

    conciliados = []
    no_conciliados_banco = []
    no_conciliados_contab = []

    # Clasificar movimientos del banco
    for m in bancos:
        importe = _to_decimal(m.get("monto", 0))
        rl = ReportLine(
            concepto=m.get("descripcion", ""),
            importe=importe,
            subconcepto=f"Fecha: {m.get('fecha', 'N/A')}",
        )
        if m.get("conciliado", False):
            conciliados.append(rl)
        else:
            no_conciliados_banco.append(rl)

    # Clasificar movimientos de contabilidad
    for m in contab:
        importe = _to_decimal(m.get("monto", 0))
        rl = ReportLine(
            concepto=m.get("descripcion", ""),
            importe=importe,
            subconcepto=f"Fecha: {m.get('fecha', 'N/A')}",
        )
        if m.get("conciliado", False):
            conciliados.append(rl)
        else:
            no_conciliados_contab.append(rl)

    # Calcular totales
    total_conciliados = sum((r.importe for r in conciliados), Decimal("0"))
    total_no_conciliados_banco = sum((r.importe for r in no_conciliados_banco), Decimal("0"))
    total_no_conciliados_contab = sum((r.importe for r in no_conciliados_contab), Decimal("0"))

    saldo_banco = total_conciliados + total_no_conciliados_banco
    saldo_contable = total_conciliados + total_no_conciliados_contab
    diferencia = saldo_banco - saldo_contable

    sections = []

    # Movimientos Conciliados
    sec_con = ReportSection(
        titulo="Movimientos Conciliados",
        subtotal_label="Total Conciliados",
    )
    sec_con.lineas = conciliados
    sec_con.subtotal = total_conciliados
    sections.append(sec_con)

    # No Conciliados — Banco
    sec_nc_b = ReportSection(
        titulo="No Conciliados — Banco",
        subtotal_label="Total No Conciliados (Banco)",
    )
    sec_nc_b.lineas = no_conciliados_banco
    sec_nc_b.subtotal = total_no_conciliados_banco
    sections.append(sec_nc_b)

    # No Conciliados — Contabilidad
    sec_nc_c = ReportSection(
        titulo="No Conciliados — Contabilidad",
        subtotal_label="Total No Conciliados (Contabilidad)",
    )
    sec_nc_c.lineas = no_conciliados_contab
    sec_nc_c.subtotal = total_no_conciliados_contab
    sections.append(sec_nc_c)

    totales = {
        "saldo_banco": str(saldo_banco),
        "saldo_contable": str(saldo_contable),
        "total_conciliados": str(total_conciliados),
        "total_no_conciliados_banco": str(total_no_conciliados_banco),
        "total_no_conciliados_contab": str(total_no_conciliados_contab),
        "diferencia": str(diferencia),
        "conciliado": str(diferencia == Decimal("0")),
    }

    return ReportData(
        titulo="Conciliación Bancaria",
        subtitulo=f"Banco: {banco_nombre} — Cuenta: {numero_cuenta}" if banco_nombre else "Conciliación Bancaria",
        empresa_rfc=empresa_rfc,
        empresa_nombre=empresa_nombre,
        periodo_inicio=periodo_inicio,
        periodo_fin=periodo_fin,
        secciones=sections,
        totales=totales,
        metadata={
            "tipo_reporte": "conciliacion_bancaria",
            "banco": banco_nombre,
            "numero_cuenta": numero_cuenta,
            "moneda": "MXN",
        },
    )


def generate_reporte_nomina(
    empleados: list[dict] | None = None,
    empresa_rfc: str = "",
    empresa_nombre: str = "",
    periodo_inicio: str = "",
    periodo_fin: str = "",
    periodo_pago: str = "",
    tipo_nomina: str = "O",
) -> ReportData:
    """Genera un Reporte de Nómina por periodo.

    Cada empleado recibe un dict con keys:
        - nombre, rfc, salario_bruto, deducciones, percepciones_neto,
          puesto, departamento

    Calcula totales globales: nómina total, deducciones totales,
    percepciones netas totales, y por departamento.

    Returns:
        ReportData con secciones por empleado y totales globales.
    """
    emps = empleados or []

    sections = []
    total_bruto = Decimal("0")
    total_deducciones = Decimal("0")
    total_neto = Decimal("0")
    departamentos: dict[str, Decimal] = {}

    for emp in emps:
        bruto = _to_decimal(emp.get("salario_bruto", 0))
        deducciones = _to_decimal(emp.get("deducciones", 0))
        neto = bruto - deducciones
        depto = emp.get("departamento", "Sin departamento")

        rl = ReportLine(
            concepto=emp.get("nombre", ""),
            importe=neto,
            subconcepto=f"RFC: {emp.get('rfc', 'N/A')} — {emp.get('puesto', '')}",
        )

        sec = ReportSection(
            titulo=f"{emp.get('nombre', '')} — {depto}",
            subtotal_label="Neto",
        )
        sec.lineas.append(rl)
        sec.lineas.append(ReportLine(
            concepto="Salario Bruto",
            importe=bruto,
            nivel=1,
        ))
        sec.lineas.append(ReportLine(
            concepto="Deducciones",
            importe=deducciones,
            nivel=1,
        ))
        sec.subtotal = neto
        sections.append(sec)

        total_bruto += bruto
        total_deducciones += deducciones
        total_neto += neto
        departamentos[depto] = departamentos.get(depto, Decimal("0")) + neto

    # Sección de resumen por departamento
    if departamentos:
        sec_deptos = ReportSection(
            titulo="Resumen por Departamento",
            subtotal_label="Total Nómina",
        )
        for depto, total in sorted(departamentos.items()):
            sec_deptos.lineas.append(ReportLine(
                concepto=depto,
                importe=total,
            ))
        sec_deptos.subtotal = total_neto
        sections.append(sec_deptos)

    tipo_nomina_label = "Ordinaria" if tipo_nomina == "O" else "Extraordinaria" if tipo_nomina == "E" else tipo_nomina

    totales = {
        "total_empleados": str(len(emps)),
        "total_bruto": str(total_bruto),
        "total_deducciones": str(total_deducciones),
        "total_neto": str(total_neto),
        "tipo_nomina": tipo_nomina_label,
        "periodo_pago": periodo_pago,
    }

    return ReportData(
        titulo="Reporte de Nómina",
        subtitulo=f"Periodo: {periodo_pago or f'{periodo_inicio} al {periodo_fin}'}",
        empresa_rfc=empresa_rfc,
        empresa_nombre=empresa_nombre,
        periodo_inicio=periodo_inicio,
        periodo_fin=periodo_fin,
        secciones=sections,
        totales=totales,
        metadata={
            "tipo_reporte": "nomina",
            "tipo_nomina": tipo_nomina,
            "total_empleados": len(emps),
            "moneda": "MXN",
        },
    )
