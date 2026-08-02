# -*- coding: utf-8 -*-
"""
service.py — ClientReportService: lógica de negocio de reportes PDF para clientes.

Responsabilidades:
  1. Recopilar datos de los módulos existentes (DIOT, declaraciones, conciliación,
     nómina, contabilidad electrónica) para el tenant/período solicitado.
  2. Delegar la generación del PDF al PDFReportGenerator.
  3. Persistir (en memoria) el registro ClientReport con metadata y ruta del archivo.
  4. Mantener el historial de reportes generados.
  5. Gestionar las programaciones de reportes automáticos.

El servicio sigue el patrón de los módulos del piloto: store en memoria, métodos
que reciben tenant_id + período, y uso de ManualProcessMixin de compliance.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from b2b_ai.features.client_reports.generator import PDFReportGenerator
from b2b_ai.features.client_reports.models import (
    ClientReport,
    ReportSchedule,
    ReportStatus,
    ReportType,
    ScheduleFrequency,
)
from b2b_ai.features.compliance import ManualProcessMixin


# ---------------------------------------------------------------------------
# Helpers de acceso a datos de los módulos existentes (best-effort)
# ---------------------------------------------------------------------------

def _load_diot_data(tenant_id: str, year: int, month: int) -> Dict[str, Any]:
    """Recopila datos DIOT del módulo existente (si está disponible)."""
    try:
        from b2b_ai.features.diot.service import DIOTService
        from b2b_ai.features.diot.models import DIOTPeriod
        # El DIOT es trimestral; calculamos el trimestre del mes.
        quarter = ((month - 1) // 3) + 1
        period = DIOTPeriod(year=year, quarter=quarter)
        svc = DIOTService()
        declaration = svc.get_declaration(tenant_id, period)
        if declaration:
            summary = declaration.to_dict().get("summary", {})
            records = [
                r.to_dict() if hasattr(r, "to_dict") else dict(r)
                for r in (declaration.records or [])
            ]
            return {
                "summary": summary,
                "records": records,
                "quarter": quarter,
            }
    except Exception:
        # Datos no disponibles: devolver vacío para que el PDF se genere igual.
        pass
    return {"summary": {}, "records": []}


def _load_iva_data(tenant_id: str, year: int, month: int) -> Dict[str, Any]:
    """Recopila datos de IVA del módulo declaraciones (si está disponible)."""
    try:
        from b2b_ai.features.declaraciones.service import DeclaracionesService
        from b2b_ai.features.declaraciones.models import DeclaracionType
        svc = DeclaracionesService()
        if hasattr(svc, "get_declaraciones_by_tenant"):
            decls = svc.get_declaraciones_by_tenant(
                tenant_id, tipo=DeclaracionType.IVA
            )
            period = f"{year:04d}-{month:02d}"
            for d in decls:
                if getattr(d, "periodo", "") == period and getattr(d, "data", None):
                    return dict(d.data)
    except Exception:
        pass
    return {}


def _load_isr_data(tenant_id: str, year: int, month: int) -> Dict[str, Any]:
    """Recopila datos de ISR provisional del módulo declaraciones."""
    try:
        from b2b_ai.features.declaraciones.service import DeclaracionesService
        from b2b_ai.features.declaraciones.models import DeclaracionType
        svc = DeclaracionesService()
        if hasattr(svc, "get_declaraciones_by_tenant"):
            decls = svc.get_declaraciones_by_tenant(
                tenant_id, tipo=DeclaracionType.ISR_PROVISIONAL
            )
            period = f"{year:04d}-{month:02d}"
            for d in decls:
                if getattr(d, "periodo", "") == period and getattr(d, "data", None):
                    return dict(d.data)
    except Exception:
        pass
    return {}


def _load_conciliacion_data(
    tenant_id: str, account_id: str, year: int, month: int
) -> Dict[str, Any]:
    """Recopila datos de conciliación del módulo existente."""
    try:
        from b2b_ai.features.conciliacion.service import ConciliationService
        svc = ConciliationService()
        if hasattr(svc, "get_report"):
            report = svc.get_report(tenant_id, account_id, f"{year}-{month:02d}")
            if report:
                return report
        if hasattr(svc, "generate_report"):
            # Recuperar desde store de reportes si está accesible.
            pass
    except Exception:
        pass
    return {}


def _load_nomina_data(tenant_id: str, year: int, month: int) -> Dict[str, Any]:
    """Recopila datos de nómina del módulo existente."""
    try:
        from b2b_ai.features.nomina_completa.service import NominaCompletaService
        svc = NominaCompletaService()
        if hasattr(svc, "get_summary"):
            data = svc.get_summary(tenant_id, year, month)
            if data:
                return data
    except Exception:
        pass
    return {}


def _load_balanza_data(tenant_id: str, year: int, month: int) -> List[Dict[str, Any]]:
    """Recopila cuentas de la balanza del módulo contabilidad electrónica."""
    try:
        from b2b_ai.features.contabilidad_electronica.service import (
            ContabilidadElectronicaService,
        )
        svc = ContabilidadElectronicaService()
        if hasattr(svc, "get_balanza"):
            balanza = svc.get_balanza(tenant_id, year, month)
            if balanza:
                return balanza.get("cuentas", [])
    except Exception:
        pass
    return []


# ---------------------------------------------------------------------------
# Servicio principal
# ---------------------------------------------------------------------------

class ClientReportService(ManualProcessMixin):
    """Lógica de negocio de los reportes PDF para clientes del despacho."""

    def __init__(
        self,
        generator: Optional[PDFReportGenerator] = None,
        output_dir: str = "reports/client_reports",
    ) -> None:
        super().__init__()
        self.generator = generator or PDFReportGenerator()
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._reports: Dict[str, ClientReport] = {}
        self._schedules: Dict[str, ReportSchedule] = {}

    # ------------------------------------------------------------------
    # Persistencia del archivo PDF
    # ------------------------------------------------------------------

    def _save_pdf(self, report_type: ReportType, period: str, pdf_bytes: bytes) -> str:
        """Guarda el PDF en disco y devuelve la ruta absoluta."""
        safe_type = report_type.value
        file_name = f"{safe_type}_{period}.pdf"
        file_path = self.output_dir / file_name
        file_path.write_bytes(pdf_bytes)
        return str(file_path)

    def _register(
        self,
        report_type: ReportType,
        tenant_id: str,
        period: str,
        file_path: str,
        metadata: Dict[str, Any],
        account_id: Optional[str] = None,
        title: str = "",
    ) -> ClientReport:
        """Crea y almacena el registro ClientReport."""
        report = ClientReport(
            report_type=report_type,
            tenant_id=tenant_id,
            period=period,
            account_id=account_id,
            title=title or report_type.label,
            file_name=Path(file_path).name,
            file_path=file_path,
            metadata=metadata,
        )
        self._reports[report.id] = report
        return report

    # ------------------------------------------------------------------
    # Generadores públicos
    # ------------------------------------------------------------------

    def generate_monthly_tax_summary(
        self,
        tenant_id: str,
        year: int,
        month: int,
        tenant_name: str = "",
        tenant_rfc: str = "",
    ) -> ClientReport:
        """Genera el resumen fiscal mensual (IVA + ISR) y lo registra."""
        iva = _load_iva_data(tenant_id, year, month)
        isr = _load_isr_data(tenant_id, year, month)
        pdf = self.generator.generate_monthly_tax_summary(
            tenant_id=tenant_id, year=year, month=month,
            tenant_name=tenant_name, tenant_rfc=tenant_rfc,
            iva=iva, isr=isr,
        )
        period = f"{year}-{month:02d}"
        path = self._save_pdf(ReportType.MONTHLY_TAX, period, pdf)
        return self._register(
            ReportType.MONTHLY_TAX, tenant_id, period, path,
            {"iva": iva, "isr": isr, "despacho": self.generator.despacho_info()},
            title="Resumen Fiscal Mensual",
        )

    def generate_diot_report(
        self,
        tenant_id: str,
        year: int,
        month: int,
        tenant_name: str = "",
        tenant_rfc: str = "",
    ) -> ClientReport:
        """Genera el resumen DIOT del trimestre que incluye el mes."""
        data = _load_diot_data(tenant_id, year, month)
        pdf = self.generator.generate_diot_report(
            tenant_id=tenant_id, year=year, month=month,
            tenant_name=tenant_name, tenant_rfc=tenant_rfc,
            summary=data.get("summary", {}), records=data.get("records", []),
        )
        period = f"{year}-{month:02d}"
        path = self._save_pdf(ReportType.DIOT_SUMMARY, period, pdf)
        return self._register(
            ReportType.DIOT_SUMMARY, tenant_id, period, path,
            {"summary": data.get("summary", {}),
             "records_count": len(data.get("records", [])),
             "quarter": data.get("quarter"),
             "despacho": self.generator.despacho_info()},
            title="Resumen DIOT",
        )

    def generate_conciliacion_report(
        self,
        tenant_id: str,
        account_id: str,
        year: int,
        month: int,
        tenant_name: str = "",
        tenant_rfc: str = "",
    ) -> ClientReport:
        """Genera el reporte de conciliación bancaria por cuenta/período."""
        conc = _load_conciliacion_data(tenant_id, account_id, year, month)
        pdf = self.generator.generate_conciliacion_report(
            tenant_id=tenant_id, account_id=account_id, year=year, month=month,
            tenant_name=tenant_name, tenant_rfc=tenant_rfc,
            conciliacion=conc,
        )
        period = f"{year}-{month:02d}"
        path = self._save_pdf(ReportType.CONCILIACION, period, pdf)
        return self._register(
            ReportType.CONCILIACION, tenant_id, period, path,
            {"account_id": account_id, "conciliacion": conc,
             "despacho": self.generator.despacho_info()},
            account_id=account_id,
            title=f"Conciliación {account_id or 'Bancaria'}",
        )

    def generate_nomina_summary(
        self,
        tenant_id: str,
        year: int,
        month: int,
        tenant_name: str = "",
        tenant_rfc: str = "",
    ) -> ClientReport:
        """Genera el resumen de nómina del período."""
        nom = _load_nomina_data(tenant_id, year, month)
        pdf = self.generator.generate_nomina_summary(
            tenant_id=tenant_id, year=year, month=month,
            tenant_name=tenant_name, tenant_rfc=tenant_rfc,
            nomina=nom,
        )
        period = f"{year}-{month:02d}"
        path = self._save_pdf(ReportType.NOMINA_SUMMARY, period, pdf)
        return self._register(
            ReportType.NOMINA_SUMMARY, tenant_id, period, path,
            {"nomina": nom, "despacho": self.generator.despacho_info()},
            title="Resumen de Nómina",
        )

    def generate_balanza(
        self,
        tenant_id: str,
        year: int,
        month: int,
        tenant_name: str = "",
        tenant_rfc: str = "",
    ) -> ClientReport:
        """Genera la balanza de comprobación del período."""
        cuentas = _load_balanza_data(tenant_id, year, month)
        pdf = self.generator.generate_balanza(
            tenant_id=tenant_id, year=year, month=month,
            tenant_name=tenant_name, tenant_rfc=tenant_rfc,
            cuentas=cuentas,
        )
        period = f"{year}-{month:02d}"
        path = self._save_pdf(ReportType.BALANZA, period, pdf)
        return self._register(
            ReportType.BALANZA, tenant_id, period, path,
            {"cuentas_count": len(cuentas),
             "despacho": self.generator.despacho_info()},
            title="Balanza de Comprobación",
        )

    # ------------------------------------------------------------------
    # Historial
    # ------------------------------------------------------------------

    def list_history(
        self,
        tenant_id: Optional[str] = None,
        report_type: Optional[ReportType] = None,
        limit: int = 50,
    ) -> List[ClientReport]:
        """Devuelve el historial de reportes generados (ordenados por fecha)."""
        reports = list(self._reports.values())
        if tenant_id:
            reports = [r for r in reports if r.tenant_id == tenant_id]
        if report_type:
            reports = [r for r in reports if r.report_type == report_type]
        reports.sort(key=lambda r: r.generated_at, reverse=True)
        return reports[:limit]

    def get_report(self, report_id: str) -> Optional[ClientReport]:
        """Recupera un reporte por su id."""
        return self._reports.get(report_id)

    def read_pdf(self, report_id: str) -> Optional[bytes]:
        """Lee los bytes del PDF de un reporte generado."""
        report = self._reports.get(report_id)
        if not report:
            return None
        try:
            return Path(report.file_path).read_bytes()
        except OSError:
            return None

    # ------------------------------------------------------------------
    # Programación automática
    # ------------------------------------------------------------------

    def schedule_report(
        self,
        report_type: ReportType,
        tenant_id: str,
        frequency: ScheduleFrequency = ScheduleFrequency.MONTHLY,
        recipients: Optional[List[str]] = None,
    ) -> ReportSchedule:
        """Programa la generación automática de un tipo de reporte."""
        schedule = ReportSchedule(
            report_type=report_type,
            tenant_id=tenant_id,
            frequency=frequency,
            recipients=recipients or [],
        )
        self._schedules[schedule.id] = schedule
        return schedule

    def list_schedules(
        self, tenant_id: Optional[str] = None
    ) -> List[ReportSchedule]:
        """Lista las programaciones activas."""
        schedules = list(self._schedules.values())
        if tenant_id:
            schedules = [s for s in schedules if s.tenant_id == tenant_id]
        return schedules

    def cancel_schedule(self, schedule_id: str) -> bool:
        """Cancela (desactiva) una programación."""
        schedule = self._schedules.get(schedule_id)
        if not schedule:
            return False
        schedule.active = False
        return True
