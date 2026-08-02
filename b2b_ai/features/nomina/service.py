# -*- coding: utf-8 -*-
"""
service.py — Lógica de negocio del módulo de Nómina (payroll).

Clases:
  - NominaManager          : alta, listado, validación, pago y anulación de nóminas.
  - NominaValidator        : validación de RFC, periodos, montos y duplicados.
  - PayrollCalculator      : cálculo de ISR (Tabla Art. 96 LISR), IMSS y neto.
  - PayrollSummaryGenerator: resumen agregado por periodo + exportación CSV.

Almacenamiento: en memoria (dict) con `_reset_state()` para tests, coherente
con el patrón de bank_feeds / vencimientos / monthly_close. Todos los
registros llevan `tenant_id`; todas las operaciones de escritura/lectura
filtran por tenant para garantizar el aislamiento multi-tenant.

Los cálculos de ISR reutilizan la Tabla del Art. 96 de la LISR (límite
inferior, cuota fija, tasa sobre excedente) — la misma usada por
`ap_ar/retention_engine.py`. El IMSS usa tasas simplificadas documentadas.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from b2b_ai.features.nomina.models import (
    NominaConcept,
    NominaRecord,
    NominaRecordCreate,
    NominaStatus,
    PayrollSummary,
)


# ---------------------------------------------------------------------------
# Store en memoria (patrón bank_feeds / monthly_close)
# ---------------------------------------------------------------------------

_records: Dict[str, NominaRecord] = {}
_concepts: Dict[str, NominaConcept] = {}
# nomina_id -> concept_ids (índice de pertenencia)
_record_concepts: Dict[str, List[str]] = {}


def _reset_state() -> None:
    """Limpia el estado en memoria (uso en tests)."""
    _records.clear()
    _concepts.clear()
    _record_concepts.clear()


def _utcnow() -> datetime:
    return datetime.utcnow()


def _to_decimal(value: Any, default: float = 0.0) -> Decimal:
    """Convierte a Decimal de forma segura."""
    try:
        return Decimal(str(value or default))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(str(default))


# ---------------------------------------------------------------------------
# Tabla ISR Art. 96 LISR (mensual) — límite inferior, cuota fija, tasa
# ---------------------------------------------------------------------------

# Reutiliza los mismos valores que ap_ar/retention_engine.py (Tabla Art. 96).
TABLA_ART_96 = [
    (0.01,       0.00,     0.0192),
    (746.05,     14.32,    0.0640),
    (6332.06,    371.84,   0.1088),
    (11128.02,   892.23,   0.1600),
    (12935.83,   1181.48,  0.1792),
    (38767.47,   5818.38,  0.2136),
    (63513.91,   11104.75, 0.2352),
    (189975.39,  40817.44, 0.3000),
    (237655.73,  55121.44, 0.3200),
    (356483.59,  93126.36, 0.3400),
    (712967.19,  214329.18, 0.3500),
]

# Factores de periodo para anualizar/prorratear la tabla mensual.
# La tabla Art. 96 es mensual; para otros periodos se prorratea el resultado.
PERIOD_FACTOR_DAYS = {
    "01": 7,    # Semanal
    "02": 15,   # Quincenal
    "03": 30,   # Mensual (base de la tabla)
    "04": 60,   # Bimestral
}

# Tasas simplificadas de IMSS (documentadas, para el MVP):
#   - IMSS obrero: cuota obrera sobre salario (aprox. 2.725%)
#   - IMSS patrón: cuota patronal sobre salario (aprox. 20.4%)
IMSS_EMPLOYEE_RATE = 0.02725
IMSS_EMPLOYER_RATE = 0.2040


# ---------------------------------------------------------------------------
# NominaValidator
# ---------------------------------------------------------------------------

class NominaValidator:
    """Validación de RFC, periodos, montos y duplicados de nómina."""

    @staticmethod
    def validate_rfc_format(rfc: str) -> Optional[str]:
        """Valida el formato del RFC (Persona Física = 13 chars, PM = 12).

        Returns:
            None si es válido, o un mensaje de error.
        """
        rfc = (rfc or "").strip().upper()
        if not rfc:
            return "RFC vacío o ausente."
        # RFC PF: 4 letras + 6 dígitos + 3 homoclave = 13.
        # RFC PM: 3 letras + 6 dígitos + 3 homoclave = 12.
        import re
        if re.match(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$", rfc):
            return None
        return f"RFC '{rfc}' no tiene un formato válido."

    @staticmethod
    def validate_period(period_start: str, period_end: str) -> Optional[str]:
        """Valida que el periodo sea YYYY-MM-DD y que inicio <= fin.

        Returns:
            None si es válido, o un mensaje de error.
        """
        try:
            start = date.fromisoformat((period_start or "").strip())
            end = date.fromisoformat((period_end or "").strip())
        except (ValueError, TypeError):
            return "Periodo inválido (se espera YYYY-MM-DD)."
        if start > end:
            return "period_start no puede ser posterior a period_end."
        return None

    @staticmethod
    def validate_amounts(record: NominaRecordCreate) -> Optional[str]:
        """Valida que los montos no sean negativos.

        Returns:
            None si es válido, o un mensaje de error.
        """
        for field in ("base_salary", "overtime_pay", "bonuses", "deductions"):
            val = getattr(record, field, 0.0)
            if val is not None and val < 0:
                return f"{field} no puede ser negativo."
        return None

    @classmethod
    def check_duplicate_period(cls, tenant_id: str, rfc: str,
                               period_start: str, period_end: str,
                               exclude_id: Optional[str] = None) -> bool:
        """True si ya existe un registro del mismo empleado en el periodo.

        Evita nóminas duplicadas para el mismo RFC y periodo solapado.
        """
        target_start = _parse_date(period_start)
        target_end = _parse_date(period_end)
        if target_start is None or target_end is None:
            return False
        for rec in _records.values():
            if exclude_id and rec.id == exclude_id:
                continue
            if str(rec.tenant_id or "") != str(tenant_id or ""):
                continue
            if rec.employee_rfc.strip().upper() != (rfc or "").strip().upper():
                continue
            r_start = _parse_date(rec.period_start)
            r_end = _parse_date(rec.period_end)
            if r_start is None or r_end is None:
                continue
            # Solapamiento: los periodos se intersectan
            if target_start <= r_end and target_end >= r_start:
                return True
        return False


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# PayrollCalculator
# ---------------------------------------------------------------------------

class PayrollCalculator:
    """Cálculo de ISR, IMSS y neto a pagar."""

    @staticmethod
    def calculate_isr(income: float, period: str = "03") -> float:
        """Calcula la retención de ISR usando la Tabla del Art. 96 LISR.

        La tabla es mensual. Para un periodo distinto (semanal/quincenal/
        bimestral) se prorratea: se ajusta el ingreso al equivalente mensual,
        se aplica la tabla y se prorratea el ISR al periodo original.

        Args:
            income: Ingreso gravable del periodo.
            period: Código SAT de periodicidad (01 semanal, 02 quincenal,
                    03 mensual, 04 bimestral). Default mensual.

        Returns:
            ISR retenido redondeado a 2 decimales.
        """
        if income is None or income <= 0:
            return 0.0
        factor_days = PERIOD_FACTOR_DAYS.get(str(period), 30)
        # Equivalente mensual del ingreso del periodo
        monthly_equiv = income * (30.0 / factor_days)
        isr_monthly = _calcular_tabla_art96(monthly_equiv)
        # Prorratear al periodo original
        return round(isr_monthly * (factor_days / 30.0), 2)

    @staticmethod
    def calculate_imss(salary: float) -> Dict[str, float]:
        """Calcula aportaciones IMSS (obrero y patrón) sobre el salario.

        Tasas simplificadas (ver constantes IMSS_*_RATE). Retorna dict con
        `imss_employer` y `imss_employee`.
        """
        sal = max(float(salary or 0.0), 0.0)
        return {
            "imss_employer": round(sal * IMSS_EMPLOYER_RATE, 2),
            "imss_employee": round(sal * IMSS_EMPLOYEE_RATE, 2),
        }

    @classmethod
    def calculate_net_pay(cls, gross: float, deductions: float,
                          period: str = "03") -> Dict[str, float]:
        """Calcula el neto a pagar dado el bruto y las deducciones.

        Deduce ISR e IMSS obrero sobre el bruto además de las deducciones
        explícitas. Retorna dict con `isr`, `imss_employer`, `imss_employee`
        y `net_pay`.
        """
        gross = max(float(gross or 0.0), 0.0)
        deductions = max(float(deductions or 0.0), 0.0)
        isr = cls.calculate_isr(gross, period)
        imss = cls.calculate_imss(gross)
        net_pay = round(gross - deductions - isr - imss["imss_employee"], 2)
        return {
            "isr": isr,
            "imss_employer": imss["imss_employer"],
            "imss_employee": imss["imss_employee"],
            "net_pay": net_pay,
        }


def _calcular_tabla_art96(monto_mensual: float) -> float:
    """Aplica la Tabla Art. 96 LISR a un monto mensual (progresiva)."""
    monto = float(monto_mensual or 0.0)
    if monto <= 0:
        return 0.0
    for i, (limite, cuota, tasa) in enumerate(TABLA_ART_96):
        siguiente = TABLA_ART_96[i + 1][0] if i + 1 < len(TABLA_ART_96) else float('inf')
        if monto <= siguiente:
            excedente = monto - limite
            return round(cuota + excedente * tasa, 2)
    limite, cuota, tasa = TABLA_ART_96[-1]
    return round(cuota + (monto - limite) * tasa, 2)


# ---------------------------------------------------------------------------
# NominaManager
# ---------------------------------------------------------------------------

class NominaManager:
    """Gestión de registros de nómina: alta, listado, validación, pago, anulación."""

    def __init__(self, db: Any = None):
        self.db = db
        self.validator = NominaValidator()
        self.calculator = PayrollCalculator()

    # ------------------------------------------------------------------
    # Alta
    # ------------------------------------------------------------------
    def create_nomina_record(
        self,
        tenant_id: str,
        data: NominaRecordCreate,
        auto_calculate: bool = True,
    ) -> NominaRecord:
        """Crea un registro de nómina para un empleado y tenant.

        Valida formato, periodo, montos y duplicado de periodo. Si
        `auto_calculate` es True, calcula ISR, IMSS y neto.
        """
        tenant_id = str(tenant_id or "")
        if not tenant_id:
            raise ValueError("tenant_id es obligatorio")

        rfc_err = self.validator.validate_rfc_format(data.employee_rfc)
        if rfc_err:
            raise ValueError(rfc_err)
        period_err = self.validator.validate_period(data.period_start, data.period_end)
        if period_err:
            raise ValueError(period_err)
        amount_err = self.validator.validate_amounts(data)
        if amount_err:
            raise ValueError(amount_err)
        if self.validator.check_duplicate_period(
            tenant_id, data.employee_rfc, data.period_start, data.period_end
        ):
            raise ValueError(
                f"Ya existe una nómina para {data.employee_rfc} en el periodo "
                f"{data.period_start} a {data.period_end}."
            )

        gross = round(data.base_salary + data.overtime_pay + data.bonuses, 2)
        if auto_calculate:
            calc = self.calculator.calculate_net_pay(gross, data.deductions)
            isr = calc["isr"]
            imss_employer = calc["imss_employer"]
            imss_employee = calc["imss_employee"]
            net_pay = calc["net_pay"]
        else:
            isr = 0.0
            imss_employer = 0.0
            imss_employee = 0.0
            net_pay = round(gross - data.deductions, 2)

        record = NominaRecord(
            tenant_id=tenant_id,
            employee_rfc=data.employee_rfc,
            employee_name=data.employee_name,
            employee_id=data.employee_id,
            period_start=data.period_start,
            period_end=data.period_end,
            base_salary=data.base_salary,
            overtime_pay=data.overtime_pay,
            bonuses=data.bonuses,
            deductions=data.deductions,
            isr_retention=isr,
            imss_employer=imss_employer,
            imss_employee=imss_employee,
            net_pay=net_pay,
            status=NominaStatus.DRAFT,
            payment_date=data.payment_date,
        )
        _records[record.id] = record
        return record

    # ------------------------------------------------------------------
    # Lectura
    # ------------------------------------------------------------------
    def get_record(self, record_id: str, tenant_id: str) -> NominaRecord:
        """Devuelve un registro SOLO si pertenece al tenant."""
        rec = _records.get(record_id)
        if rec is None:
            raise KeyError(f"Nómina no encontrada: {record_id}")
        if str(rec.tenant_id or "") != str(tenant_id or ""):
            raise KeyError(f"Nómina no encontrada: {record_id}")
        return rec

    def list_records(
        self,
        tenant_id: str,
        period: Optional[str] = None,
        employee: Optional[str] = None,
        status: Optional[NominaStatus] = None,
    ) -> List[NominaRecord]:
        """Lista nóminas del tenant con filtros opcionales.

        `period` acepta 'YYYY-MM' (coincide con period_start) o 'YYYY-MM-DD'
        a 'YYYY-MM-DD' (coincide exacto). `employee` filtra por RFC o nombre
        (case-insensitive).
        """
        tenant_id = str(tenant_id or "")
        results: List[NominaRecord] = []
        for rec in _records.values():
            if str(rec.tenant_id or "") != tenant_id:
                continue
            if period:
                period = period.strip()
                if not (rec.period_start.startswith(period)
                        or rec.period_end.startswith(period)
                        or period in (rec.period_start, rec.period_end)):
                    continue
            if employee:
                employee = employee.strip().upper()
                if (employee not in rec.employee_rfc.upper()
                        and employee not in rec.employee_name.upper()
                        and employee not in rec.employee_id.upper()):
                    continue
            if status:
                if rec.status != status:
                    continue
            results.append(rec)
        results.sort(key=lambda r: (r.period_start, r.employee_name))
        return results

    def get_concepts(self, record_id: str, tenant_id: str) -> List[NominaConcept]:
        """Lista los conceptos de un registro (verificado por tenant)."""
        self.get_record(record_id, tenant_id)
        ids = _record_concepts.get(record_id, [])
        return [_concepts[i] for i in ids if i in _concepts]

    def add_concept(self, record_id: str, tenant_id: str,
                    concept: NominaConcept) -> NominaConcept:
        """Agrega un concepto a un registro (verificado por tenant)."""
        self.get_record(record_id, tenant_id)
        concept = concept.model_copy(update={
            "nomina_id": record_id,
            "tenant_id": str(tenant_id),
        })
        _concepts[concept.id] = concept
        _record_concepts.setdefault(record_id, []).append(concept.id)
        return concept

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------
    def validate_payroll(self, record_id: str, tenant_id: str) -> NominaRecord:
        """Valida una nómina (DRAFT -> VALIDATED). No se puede pagar una no validada."""
        rec = self.get_record(record_id, tenant_id)
        if rec.status == NominaStatus.VOIDED:
            raise ValueError("No se puede validar una nómina anulada.")
        rec.status = NominaStatus.VALIDATED
        rec.updated_at = _utcnow()
        _records[record_id] = rec
        return rec

    def mark_paid(self, record_id: str, tenant_id: str,
                  payment_date: Optional[str] = None) -> NominaRecord:
        """Marca una nómina como pagada (debe estar VALIDATED)."""
        rec = self.get_record(record_id, tenant_id)
        if rec.status == NominaStatus.VOIDED:
            raise ValueError("No se puede pagar una nómina anulada.")
        if rec.status != NominaStatus.VALIDATED:
            raise ValueError(
                f"La nómina debe estar VALIDATED para pagarse (estado: {rec.status.value})."
            )
        rec.status = NominaStatus.PAID
        rec.payment_date = payment_date or date.today().isoformat()
        rec.updated_at = _utcnow()
        _records[record_id] = rec
        return rec

    def void_payroll(self, record_id: str, tenant_id: str) -> NominaRecord:
        """Anula una nómina (solo si no está PAID)."""
        rec = self.get_record(record_id, tenant_id)
        if rec.status == NominaStatus.PAID:
            raise ValueError("No se puede anular una nómina ya pagada.")
        rec.status = NominaStatus.VOIDED
        rec.updated_at = _utcnow()
        _records[record_id] = rec
        return rec


# ---------------------------------------------------------------------------
# PayrollSummaryGenerator
# ---------------------------------------------------------------------------

class PayrollSummaryGenerator:
    """Genera resúmenes agregados de nómina por periodo/tenant."""

    def generate_summary(self, tenant_id: str, period: str) -> PayrollSummary:
        """Agrega las nóminas de un periodo (YYYY-MM) para el tenant.

        Solo considera registros no VOIDED (los anulados se excluyen de los
        totales). Si `period` es 'YYYY-MM', incluye nóminas cuyo period_start
        empieza con ese mes.
        """
        tenant_id = str(tenant_id or "")
        period = period.strip()
        summary = PayrollSummary(period=period, tenant_id=tenant_id)
        total_gross = 0.0
        total_deductions = 0.0
        total_isr = 0.0
        total_imss = 0.0
        total_net = 0.0
        count = 0
        for rec in _records.values():
            if str(rec.tenant_id or "") != tenant_id:
                continue
            if not (rec.period_start.startswith(period)
                    or rec.period_end.startswith(period)
                    or period in (rec.period_start, rec.period_end)):
                continue
            if rec.status == NominaStatus.VOIDED:
                continue
            total_gross += rec.total_gross
            total_deductions += rec.total_deductions
            total_isr += rec.isr_retention
            total_imss += rec.imss_employer + rec.imss_employee
            total_net += rec.net_pay
            count += 1
        summary.total_employees = count
        summary.total_gross = round(total_gross, 2)
        summary.total_deductions = round(total_deductions, 2)
        summary.total_isr = round(total_isr, 2)
        summary.total_imss = round(total_imss, 2)
        summary.total_net = round(total_net, 2)
        return summary

    def export_to_csv(self, tenant_id: str, period: str) -> str:
        """Exporta las nóminas del periodo a CSV (retorna el contenido).

        Incluye cabecera y una fila por nómina (excluye VOIDED).
        """
        tenant_id = str(tenant_id or "")
        period = period.strip()
        headers = [
            "id", "tenant_id", "employee_rfc", "employee_name", "employee_id",
            "period_start", "period_end", "base_salary", "overtime_pay",
            "bonuses", "deductions", "isr_retention", "imss_employer",
            "imss_employee", "net_pay", "status", "payment_date",
        ]
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=headers)
        writer.writeheader()
        for rec in _records.values():
            if str(rec.tenant_id or "") != tenant_id:
                continue
            if not (rec.period_start.startswith(period)
                    or rec.period_end.startswith(period)
                    or period in (rec.period_start, rec.period_end)):
                continue
            if rec.status == NominaStatus.VOIDED:
                continue
            row = rec.to_dict()
            writer.writerow({k: row.get(k, "") for k in headers})
        return buffer.getvalue()
