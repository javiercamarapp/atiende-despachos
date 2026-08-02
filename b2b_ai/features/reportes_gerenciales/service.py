# -*- coding: utf-8 -*-
"""
service.py — ReportesService: report generation, KPI calculation, cash flow, P&L, and export.

Generates monthly financial reports, KPI dashboards, cash flow analysis,
and profit & loss statements. Supports export to multiple formats.
"""
from __future__ import annotations

import csv
import io
import json
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from b2b_ai.features.reportes_gerenciales.models import (
    CashFlow,
    ExportFormat,
    KPI,
    MonthlyReport,
    ProfitLoss,
    ReportPeriod,
    TrendDirection,
)


from b2b_ai.features.compliance import (
    FiscalOutput, AuditTrail, sanitize_string, mask_rfc,
    verify_tenant_access, SafeError, SAFE_ERRORS, ManualProcessMixin,
)


class ReportesService(ManualProcessMixin):
    """Core service for management reports."""

    def __init__(self, tenant_id: str = "default"):
        super().__init__()
        self.tenant_id = tenant_id
        # In-memory stores
        self._reports: Dict[str, MonthlyReport] = {}
        self._cash_flows: Dict[str, CashFlow] = {}
        self._profit_losses: Dict[str, ProfitLoss] = {}

    # -------------------------------------------------------------------
    # Monthly report generation
    # -------------------------------------------------------------------

    def generate_monthly_report(
        self,
        tenant_id: str,
        month: int,
        year: int,
        data: Optional[Dict[str, Any]] = None,
    ) -> MonthlyReport:
        """Generate a monthly financial report.

        Parameters
        ----------
        tenant_id : str
            Tenant identifier.
        month : int
            Month (1-12).
        year : int
            Year (e.g. 2024).
        data : Optional[dict]
            Input data with revenue, expenses, etc.

        Returns
        -------
        MonthlyReport with computed KPIs.
        """
        if not 1 <= month <= 12:
            raise ValueError(f"Mes inválido: {month}. Debe ser 1-12.")

        period = f"{year}-{month:02d}"
        data = data or {}

        revenue = data.get("revenue", 0.0)
        expenses = data.get("expenses", 0.0)
        taxes_paid = data.get("taxes_paid", 0.0)
        invoices_count = data.get("invoices_count", 0)
        profit = revenue - expenses - taxes_paid

        # Generate KPIs
        kpis = self._compute_kpis(revenue, expenses, profit, taxes_paid, invoices_count, data)

        report = MonthlyReport(
            id=str(_uuid.uuid4()),
            period=period,
            tenant_id=tenant_id,
            revenue=revenue,
            expenses=expenses,
            profit=profit,
            taxes_paid=taxes_paid,
            invoices_count=invoices_count,
            kpis=kpis,
            details=data.get("details", {}),
            created_at=datetime.now().isoformat(),
        )

        # CFF Art. 89: Compliance metadata
        report.referencia_legal = "CFF Art. 89"
        report.supuesto = "Reporte gerencial mensual"
        report.requires_human_review = False
        report.escalation_path = "review_by_contador"

        self._reports[period] = report
        self.log_audit(user=tenant_id, action="generate_monthly_report", module="reportes_gerenciales", result="success", tenant_id=tenant_id)
        return report

    def _compute_kpis(
        self,
        revenue: float,
        expenses: float,
        profit: float,
        taxes_paid: float,
        invoices_count: int,
        data: Dict[str, Any],
    ) -> List[KPI]:
        """Compute KPIs from financial data."""
        kpis: List[KPI] = []

        # Ingresos mensuales
        prev_revenue = data.get("prev_revenue")
        revenue_change = None
        revenue_trend = TrendDirection.STABLE
        if prev_revenue and prev_revenue != 0:
            revenue_change = round(((revenue - prev_revenue) / abs(prev_revenue)) * 100, 2)
            revenue_trend = TrendDirection.UP if revenue_change > 0 else (
                TrendDirection.DOWN if revenue_change < 0 else TrendDirection.STABLE
            )

        kpis.append(KPI(
            name="Ingresos Mensuales",
            value=round(revenue, 2),
            unit="MXN",
            trend=revenue_trend,
            change_pct=revenue_change,
            target=data.get("revenue_target"),
            category="financial",
        ))

        # Margen bruto
        gross_margin = round((profit / revenue * 100), 2) if revenue > 0 else 0.0
        prev_margin = data.get("prev_gross_margin")
        margin_change = None
        margin_trend = TrendDirection.STABLE
        if prev_margin and prev_margin != 0:
            margin_change = round(gross_margin - prev_margin, 2)
            margin_trend = TrendDirection.UP if margin_change > 0 else (
                TrendDirection.DOWN if margin_change < 0 else TrendDirection.STABLE
            )

        kpis.append(KPI(
            name="Margen Bruto",
            value=gross_margin,
            unit="%",
            trend=margin_trend,
            change_pct=margin_change,
            target=data.get("margin_target", 20.0),
            category="financial",
        ))

        # Efectividad de facturación
        eff_rate = round((invoices_count / max(data.get("invoices_expected", invoices_count), 1)) * 100, 2)
        kpis.append(KPI(
            name="Efectividad de Facturación",
            value=eff_rate,
            unit="%",
            trend=TrendDirection.STABLE,
            target=100.0,
            category="operational",
        ))

        # Carga impositiva
        tax_burden = round((taxes_paid / revenue * 100), 2) if revenue > 0 else 0.0
        kpis.append(KPI(
            name="Carga Impositiva",
            value=tax_burden,
            unit="%",
            trend=TrendDirection.STABLE,
            target=None,
            category="compliance",
        ))

        # Gasto por factura
        cost_per_invoice = round(expenses / invoices_count, 2) if invoices_count > 0 else 0.0
        kpis.append(KPI(
            name="Gasto por Factura",
            value=cost_per_invoice,
            unit="MXN",
            trend=TrendDirection.STABLE,
            target=data.get("cost_per_invoice_target"),
            category="operational",
        ))

        return kpis

    # -------------------------------------------------------------------
    # KPI dashboard
    # -------------------------------------------------------------------

    def generate_kpi_dashboard(
        self,
        tenant_id: str,
        period: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate a KPI dashboard for a given period.

        Parameters
        ----------
        tenant_id : str
            Tenant identifier.
        period : str
            Period in YYYY-MM format.
        data : Optional[dict]
            Input data for KPI calculation.

        Returns
        -------
        Dict with KPIs, summary, and alerts.
        """
        data = data or {}
        kpis: List[KPI] = []

        # Financial KPIs
        for name, value, unit, target in [
            ("Ingresos", data.get("revenue", 0.0), "MXN", data.get("revenue_target")),
            ("Egresos", data.get("expenses", 0.0), "MXN", data.get("expense_target")),
            ("Utilidad Neta", data.get("profit", 0.0), "MXN", None),
            ("Ticket Promedio", data.get("avg_ticket", 0.0), "MXN", None),
            ("Días de Cobro", data.get("days_to_collect", 0), "days", 30),
            ("Facturas Procesadas", data.get("invoices_count", 0), "count", None),
        ]:
            kpis.append(KPI(
                name=name,
                value=round(value, 2),
                unit=unit,
                trend=TrendDirection.STABLE,
                target=target,
            ))

        # Alerts: KPIs that are below target
        alerts = []
        for kpi in kpis:
            if kpi.target is not None and kpi.unit == "%" and kpi.value < kpi.target:
                alerts.append({
                    "kpi": kpi.name,
                    "current": kpi.value,
                    "target": kpi.target,
                    "message": f"{kpi.name} está por debajo del objetivo ({kpi.value} vs {kpi.target})",
                })

        return {
            "ok": True,
            "period": period,
            "tenant_id": tenant_id,
            "kpis": [k.model_dump() for k in kpis],
            "summary": {
                "total_kpis": len(kpis),
                "alerts_count": len(alerts),
            },
            "alerts": alerts,
            "generated_at": datetime.now().isoformat(),
        }

    # -------------------------------------------------------------------
    # Cash flow
    # -------------------------------------------------------------------

    def generate_cash_flow(
        self,
        tenant_id: str,
        period: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> CashFlow:
        """Generate cash flow analysis.

        Parameters
        ----------
        tenant_id : str
            Tenant identifier.
        period : str
            Period in YYYY-MM format.
        data : Optional[dict]
            Input data with inflows, outflows, balances.

        Returns
        -------
        CashFlow with projection.
        """
        data = data or {}

        opening = data.get("opening_balance", 0.0)
        inflows = data.get("inflows", 0.0)
        outflows = data.get("outflows", 0.0)
        net = inflows - outflows
        closing = opening + net

        # Projection: simple linear projection for next 3 months
        projection = None
        if data.get("project_forward", False):
            monthly_growth = data.get("monthly_growth_rate", 0.0)
            months = data.get("projection_months", 3)
            proj_data = []
            current = closing
            for m in range(1, months + 1):
                proj_inflows = inflows * (1 + monthly_growth) ** m
                proj_outflows = outflows * (1 + monthly_growth * 0.5) ** m
                current += (proj_inflows - proj_outflows)
                proj_data.append({
                    "month_offset": m,
                    "projected_inflows": round(proj_inflows, 2),
                    "projected_outflows": round(proj_outflows, 2),
                    "projected_balance": round(current, 2),
                })
            projection = {
                "months": months,
                "monthly_growth_rate": monthly_growth,
                "projections": proj_data,
            }

        # Category breakdown
        categories = data.get("categories", {
            "ventas": inflows * 0.7 if inflows else 0,
            "servicios": inflows * 0.3 if inflows else 0,
            "nómina": outflows * 0.4 if outflows else 0,
            "proveedores": outflows * 0.3 if outflows else 0,
            "impuestos": outflows * 0.15 if outflows else 0,
            "otros": outflows * 0.15 if outflows else 0,
        })

        cash_flow = CashFlow(
            id=str(_uuid.uuid4()),
            period=period,
            tenant_id=tenant_id,
            opening_balance=opening,
            inflows=inflows,
            outflows=outflows,
            net=round(net, 2),
            closing_balance=round(closing, 2),
            projection=projection,
            categories={k: round(v, 2) for k, v in categories.items()},
            created_at=datetime.now().isoformat(),
        )

        self._cash_flows[period] = cash_flow
        return cash_flow

    # -------------------------------------------------------------------
    # Profit & Loss
    # -------------------------------------------------------------------

    def generate_profit_loss(
        self,
        tenant_id: str,
        period: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> ProfitLoss:
        """Generate Profit & Loss (Estado de Resultados).

        Parameters
        ----------
        tenant_id : str
            Tenant identifier.
        period : str
            Period in YYYY-MM format.
        data : Optional[dict]
            Input data for P&L computation.

        Returns
        -------
        ProfitLoss with computed margins.
        """
        data = data or {}

        income = data.get("income", 0.0)
        cogs = data.get("cost_of_goods_sold", 0.0)
        gross_profit = income - cogs

        op_expenses = data.get("operating_expenses", 0.0)
        operating_profit = gross_profit - op_expenses

        other_income = data.get("other_income", 0.0)
        other_expenses = data.get("other_expenses", 0.0)
        pre_tax_profit = operating_profit + other_income - other_expenses

        # ISR + IVA estimation
        isr_rate = data.get("isr_rate", 0.30)
        taxes = round(pre_tax_profit * isr_rate, 2) if pre_tax_profit > 0 else 0.0
        net_profit = pre_tax_profit - taxes
        margin_pct = round((net_profit / income * 100), 2) if income > 0 else 0.0

        # Breakdowns
        cost_breakdown = data.get("cost_breakdown", {
            "materia_prima": cogs * 0.6 if cogs else 0,
            "mano_obra": cogs * 0.25 if cogs else 0,
            "indirectos": cogs * 0.15 if cogs else 0,
        })

        expense_breakdown = data.get("expense_breakdown", {
            "nómina_admin": op_expenses * 0.35 if op_expenses else 0,
            "renta": op_expenses * 0.15 if op_expenses else 0,
            "servicios": op_expenses * 0.10 if op_expenses else 0,
            "depreciación": op_expenses * 0.10 if op_expenses else 0,
            "marketing": op_expenses * 0.10 if op_expenses else 0,
            "otros": op_expenses * 0.20 if op_expenses else 0,
        })

        pl = ProfitLoss(
            id=str(_uuid.uuid4()),
            period=period,
            tenant_id=tenant_id,
            income=round(income, 2),
            cost_of_goods_sold=round(cogs, 2),
            gross_profit=round(gross_profit, 2),
            operating_expenses=round(op_expenses, 2),
            operating_profit=round(operating_profit, 2),
            other_income=round(other_income, 2),
            other_expenses=round(other_expenses, 2),
            pre_tax_profit=round(pre_tax_profit, 2),
            taxes=taxes,
            net_profit=round(net_profit, 2),
            margin_pct=margin_pct,
            cost_breakdown={k: round(v, 2) for k, v in cost_breakdown.items()},
            expense_breakdown={k: round(v, 2) for k, v in expense_breakdown.items()},
            created_at=datetime.now().isoformat(),
        )

        self._profit_losses[period] = pl
        return pl

    # -------------------------------------------------------------------
    # Export
    # -------------------------------------------------------------------

    def export_report(
        self,
        report: Any,
        format: ExportFormat = ExportFormat.JSON,
    ) -> Any:
        """Export a report to the specified format.

        Parameters
        ----------
        report : MonthlyReport, CashFlow, or ProfitLoss
            The report to export.
        format : ExportFormat
            Target format.

        Returns
        -------
        JSON string, CSV string, or dict depending on format.
        """
        if hasattr(report, "model_dump"):
            data = report.model_dump()
        else:
            data = report

        if format == ExportFormat.JSON:
            return json.dumps(data, indent=2, ensure_ascii=False, default=str)

        elif format == ExportFormat.CSV:
            output = io.StringIO()
            writer = csv.writer(output)
            # Header
            writer.writerow(["Campo", "Valor"])
            for key, value in data.items():
                if isinstance(value, (dict, list)):
                    writer.writerow([key, json.dumps(value, ensure_ascii=False)])
                else:
                    writer.writerow([key, value])
            return output.getvalue()

        elif format == ExportFormat.PDF:
            # Simplified: return markdown that can be converted
            lines = [f"# Reporte - {data.get('period', 'N/A')}", ""]
            for key, value in data.items():
                if isinstance(value, (dict, list)):
                    lines.append(f"**{key}:**")
                    if isinstance(value, list):
                        for item in value:
                            if isinstance(item, dict):
                                lines.append(f"  - {json.dumps(item, ensure_ascii=False)}")
                            else:
                                lines.append(f"  - {item}")
                    else:
                        for k2, v2 in value.items():
                            lines.append(f"  - {k2}: {v2}")
                else:
                    lines.append(f"**{key}:** {value}")
            return "\n".join(lines)

        elif format == ExportFormat.XLSX:
            # Return a simplified dict representation for XLSX generation
            return {
                "sheets": [
                    {
                        "name": "Reporte",
                        "headers": ["Campo", "Valor"],
                        "rows": [[k, v] for k, v in data.items() if not isinstance(v, (dict, list))],
                    }
                ]
            }

        return data

    # -------------------------------------------------------------------
    # Retrieval
    # -------------------------------------------------------------------

    def get_report(self, period: str) -> Optional[MonthlyReport]:
        """Get a monthly report by period."""
        return self._reports.get(period)

    def get_cash_flow(self, period: str) -> Optional[CashFlow]:
        """Get cash flow by period."""
        return self._cash_flows.get(period)

    def get_profit_loss(self, period: str) -> Optional[ProfitLoss]:
        """Get P&L by period."""
        return self._profit_losses.get(period)

    def list_reports(self) -> List[str]:
        """List all available report periods."""
        return sorted(set(
            list(self._reports.keys())
            + list(self._cash_flows.keys())
            + list(self._profit_losses.keys())
        ))

# Alias for backward compatibility
ReportesGerencialesService = ReportesService
