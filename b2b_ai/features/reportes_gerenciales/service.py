# -*- coding: utf-8 -*-
"""
service.py — Servicio de Reportes Gerenciales.

Genera reportes financieros mensuales, dashboards de KPIs,
análisis de flujo de efectivo y estados de resultados.
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any, Optional

from b2b_ai.features.reportes_gerenciales.models import (
    CashFlow,
    KPI,
    MonthlyReport,
)


def generate_monthly_report(tenant_id: int,
                            month: int,
                            year: int,
                            revenue: float = 0.0,
                            cost_of_goods: float = 0.0,
                            operating_expenses: float = 0.0,
                            taxes: float = 0.0,
                            previous_revenue: float = 0.0,
                            cash_flow: Optional[CashFlow] = None) -> MonthlyReport:
    """Genera un reporte financiero mensual.

    Calcula márgenes, KPIs y genera un resumen ejecutivo.
    """
    gross_profit = revenue - cost_of_goods
    ebitda = gross_profit - operating_expenses
    net_profit = ebitda - taxes

    period = f"{year}-{month:02d}"

    # KPIs
    kpis = []

    # Margen bruto
    mg = (gross_profit / revenue * 100) if revenue > 0 else 0
    kpis.append(KPI(
        name="Margen Bruto",
        value=round(mg, 2),
        unit="%",
        target=40.0,
        trend="up" if mg >= 40 else "down",
    ))

    # Margen neto
    mn = (net_profit / revenue * 100) if revenue > 0 else 0
    kpis.append(KPI(
        name="Margen Neto",
        value=round(mn, 2),
        unit="%",
        target=15.0,
        trend="up" if mn >= 15 else "down",
    ))

    # Variación de ingresos
    if previous_revenue > 0:
        rev_var = ((revenue - previous_revenue) / previous_revenue) * 100
    else:
        rev_var = 0.0
    kpis.append(KPI(
        name="Variación de Ingresos",
        value=round(rev_var, 2),
        unit="%",
        target=5.0,
        trend="up" if rev_var >= 0 else "down",
        delta_pct=round(rev_var, 2),
    ))

    # EBITDA
    kpis.append(KPI(
        name="EBITDA",
        value=round(ebitda, 2),
        unit="MXN",
        target=0.0,
        trend="up" if ebitda > 0 else "down",
    ))

    # Resumen ejecutivo
    if net_profit > 0:
        summary = (
            f"Periodo {period}: Ingresos ${revenue:,.2f}, "
            f"utilidad neta ${net_profit:,.2f} (margen {mn:.1f}%). "
            f"{'Crecimiento positivo.' if rev_var > 0 else 'Ingresos a la baja.'}"
        )
    else:
        summary = (
            f"Periodo {period}: Ingresos ${revenue:,.2f}, "
            f"pérdida neta ${abs(net_profit):,.2f}. "
            f"Se requiere revisión de gastos."
        )

    return MonthlyReport(
        period=period,
        tenant_id=tenant_id,
        revenue=round(revenue, 2),
        cost_of_goods=round(cost_of_goods, 2),
        gross_profit=round(gross_profit, 2),
        operating_expenses=round(operating_expenses, 2),
        ebitda=round(ebitda, 2),
        taxes=round(taxes, 2),
        net_profit=round(net_profit, 2),
        kpis=kpis,
        cash_flow=cash_flow,
        summary=summary,
    )


def generate_kpi_dashboard(tenant_id: int,
                           period: str,
                           metrics: Optional[dict] = None) -> list[KPI]:
    """Genera un dashboard de KPIs clave.

    Acepta métricas personalizadas o genera KPIs por defecto.
    """
    metrics = metrics or {}
    kpis = []

    # Revenue per employee
    employees = metrics.get("employees", 1)
    revenue = metrics.get("revenue", 0)
    rpe = revenue / employees if employees > 0 else 0
    kpis.append(KPI(name="Ingresos por Empleado", value=round(rpe, 2), unit="MXN"))

    # Collection rate
    billed = metrics.get("billed", 0)
    collected = metrics.get("collected", 0)
    cr = (collected / billed * 100) if billed > 0 else 0
    kpis.append(KPI(name="Tasa de Cobro", value=round(cr, 2), unit="%"))

    # DSO (Days Sales Outstanding)
    ar = metrics.get("accounts_receivable", 0)
    daily_rev = revenue / 30 if revenue > 0 else 1
    dso = ar / daily_rev if daily_rev > 0 else 0
    kpis.append(KPI(name="DSO (Días de Cobro)", value=round(dso, 1), unit="días"))

    # Operating expense ratio
    opex = metrics.get("operating_expenses", 0)
    oer = (opex / revenue * 100) if revenue > 0 else 0
    kpis.append(KPI(name="Ratio de Gastos Operativos", value=round(oer, 2), unit="%"))

    # Cash runway
    cash = metrics.get("cash_balance", 0)
    monthly_burn = metrics.get("monthly_burn", 1)
    runway = cash / monthly_burn if monthly_burn > 0 else 0
    kpis.append(KPI(
        name="Cash Runway (meses)",
        value=round(runway, 1),
        target=6.0,
        trend="up" if runway >= 6 else "down",
    ))

    return kpis


def generate_cash_flow(tenant_id: int,
                       period: str,
                       inflows: float = 0.0,
                       outflows: float = 0.0,
                       beginning_balance: float = 0.0,
                       details: Optional[dict] = None) -> CashFlow:
    """Genera un análisis de flujo de efectivo."""
    net = inflows - outflows
    ending = beginning_balance + net
    # Proyección simple: misma tasa neta
    projection = ending + net

    return CashFlow(
        period=period,
        inflows=round(inflows, 2),
        outflows=round(outflows, 2),
        net=round(net, 2),
        beginning_balance=round(beginning_balance, 2),
        ending_balance=round(ending, 2),
        projection_next_month=round(projection, 2),
        details=details or {},
    )


def generate_profit_loss(tenant_id: int,
                         period: str,
                         revenue: float = 0.0,
                         cost_of_goods: float = 0.0,
                         operating_expenses: float = 0.0,
                         other_income: float = 0.0,
                         taxes: float = 0.0,
                         depreciation: float = 0.0,
                         interest: float = 0.0) -> MonthlyReport:
    """Genera un Estado de Resultados (P&L) detallado.

    Incluye desglose de gastos de operación y otros ingresos.
    """
    gross = revenue - cost_of_goods
    operating_income = gross - operating_expenses - depreciation
    ebit = operating_income + other_income - interest
    ebitda = gross - operating_expenses
    net = ebit - taxes

    # KPIs del P&L
    kpis = []
    if revenue > 0:
        kpis.append(KPI(
            name="EBIT",
            value=round(ebit, 2),
            unit="MXN",
            trend="up" if ebit > 0 else "down",
        ))
        kpis.append(KPI(
            name="Depreciación/Aмортизación",
            value=round(depreciation, 2),
            unit="MXN",
        ))
        kpis.append(KPI(
            name="Costo Financiero",
            value=round(interest, 2),
            unit="MXN",
        ))

    period_label = period
    return MonthlyReport(
        period=period_label,
        tenant_id=tenant_id,
        revenue=round(revenue, 2),
        cost_of_goods=round(cost_of_goods, 2),
        gross_profit=round(gross, 2),
        operating_expenses=round(operating_expenses, 2),
        ebitda=round(ebitda, 2),
        taxes=round(taxes, 2),
        net_profit=round(net, 2),
        kpis=kpis,
        summary=f"P&L {period}: Utilidad neta ${net:,.2f}",
    )


def export_report(report: MonthlyReport, format: str = "json") -> str:
    """Exporta un reporte en el formato solicitado (json, csv, html).

    Returns:
        String con el contenido del reporte.
    """
    data = report.to_dict()

    if format == "json":
        return json.dumps(data, indent=2, ensure_ascii=False)

    elif format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        # Header
        writer.writerow(["Concepto", "Monto"])
        writer.writerow(["Periodo", data["period"]])
        writer.writerow(["Ingresos", data["revenue"]])
        writer.writerow(["Costo de Ventas", data["cost_of_goods"]])
        writer.writerow(["Utilidad Bruta", data["gross_profit"]])
        writer.writerow(["Gastos Operativos", data["operating_expenses"]])
        writer.writerow(["EBITDA", data["ebitda"]])
        writer.writerow(["Impuestos", data["taxes"]])
        writer.writerow(["Utilidad Neta", data["net_profit"]])
        # KPIs
        for kpi in data["kpis"]:
            writer.writerow([f"KPI: {kpi['name']}", f"{kpi['value']} {kpi['unit']}"])
        return output.getvalue()

    elif format == "html":
        rows = ""
        for kpi in data["kpis"]:
            color = "#22c55e" if kpi["trend"] == "up" else "#ef4444" if kpi["trend"] == "down" else "#94a3b8"
            rows += f"""
            <tr>
                <td>{kpi['name']}</td>
                <td style="text-align:right">{kpi['value']:.2f} {kpi['unit']}</td>
                <td style="color:{color};text-align:center">{kpi['trend'].upper()}</td>
            </tr>"""
        return f"""<!DOCTYPE html>
<html>
<head><title>Reporte {data['period']}</title>
<style>body{{font-family:sans-serif;margin:2em}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ddd;padding:8px}}th{{background:#1e293b;color:white}}</style></head>
<body>
<h1>Reporte Gerencial — {data['period']}</h1>
<table>
<tr><th>Concepto</th><th style="text-align:right">Monto</th></tr>
<tr><td>Ingresos</td><td style="text-align:right">${data['revenue']:,.2f}</td></tr>
<tr><td>Costo de Ventas</td><td style="text-align:right">${data['cost_of_goods']:,.2f}</td></tr>
<tr><td>Utilidad Bruta</td><td style="text-align:right">${data['gross_profit']:,.2f}</td></tr>
<tr><td>Gastos Operativos</td><td style="text-align:right">${data['operating_expenses']:,.2f}</td></tr>
<tr><td>EBITDA</td><td style="text-align:right">${data['ebitda']:,.2f}</td></tr>
<tr><td>Impuestos</td><td style="text-align:right">${data['taxes']:,.2f}</td></tr>
<tr><td><strong>Utilidad Neta</strong></td><td style="text-align:right"><strong>${data['net_profit']:,.2f}</strong></td></tr>
</table>
<h2>KPIs</h2>
<table><tr><th>Indicador</th><th>Valor</th><th>Tendencia</th></tr>
{rows}</table>
<p>{data['summary']}</p>
</body></html>"""

    else:
        raise ValueError(f"Formato no soportado: {format}. Use: json, csv, html")
