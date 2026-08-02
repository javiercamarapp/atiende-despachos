# -*- coding: utf-8 -*-
"""
service.py — Lógica de negocio del módulo AP/AR (cuentas por pagar/cobrar).

  - APManager        : crea/lista AP records, marca pagados, aging summary.
  - ARManager        : crea/lista AR records, marca cobrados, aging summary.
  - AgingReport      : compute_aging_ap / compute_aging_ar (buckets 0-30, 31-60,
                       61-90, 90+).
  - PaymentScheduler : suggest_payment_schedule (prioriza por due_date y monto).
  - RetentionEngine  : calculate_retention (ISR 10% / IVA retenido según SAT).
  - NotasCredito     : generate_nota_credito (nota de crédito sobre un registro).

Almacenamiento en memoria (dict) con `_reset_state()` para tests, coherente con
monthly_close / compliance_tracker / pilot_tracker. La firma permite inyectar
una capa de persistencia (db) sin romper la interfaz.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from b2b_ai.features.ap_ar.models import (
    APRecord,
    APStatus,
    ARRecord,
    ARStatus,
    AgingBucketData,
    AgingReport as AgingReportModel,
    CreditNote,
    CreditNoteType,
    PaymentMethod,
    PaymentRecord,
    RetentionResult,
    RetentionType,
)


# ---------------------------------------------------------------------------
# Store en memoria (patrón monthly_close / compliance_tracker)
# ---------------------------------------------------------------------------

_ap_records: Dict[str, APRecord] = {}
_ar_records: Dict[str, ARRecord] = {}
_payments: Dict[str, PaymentRecord] = {}
_notes: Dict[str, CreditNote] = {}


def _reset_state() -> None:
    """Limpia el estado en memoria (uso en tests)."""
    _ap_records.clear()
    _ar_records.clear()
    _payments.clear()
    _notes.clear()


def _utcnow() -> datetime:
    return datetime.utcnow()


def _parse_date(value: str) -> Optional[date]:
    """Convierte una fecha YYYY-MM-DD a date; None si es inválida."""
    try:
        return datetime.strptime((value or "")[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _days_past_due(due_date: str, today: Optional[date] = None) -> int:
    """Días de vencimiento transcurridos (negativo = aún no vence)."""
    today = today or date.today()
    d = _parse_date(due_date)
    if d is None:
        return 0
    return (today - d).days


# ---------------------------------------------------------------------------
# AP Manager
# ---------------------------------------------------------------------------

class APManager:
    """Gestión de cuentas por pagar (proveedores)."""

    def __init__(self, db: Any = None):
        self.db = db

    # ------------------------------------------------------------------
    def create_ap_record(
        self,
        tenant_id: str,
        supplier_rfc: str,
        invoice_number: str,
        invoice_date: str,
        due_date: str,
        amount: float,
        supplier_name: str = "",
        payment_method: Optional[str] = None,
    ) -> APRecord:
        """Crea una cuenta por pagar."""
        if not tenant_id:
            raise ValueError("tenant_id es obligatorio")
        if amount <= 0:
            raise ValueError("amount debe ser mayor a 0")
        record = APRecord(
            tenant_id=str(tenant_id),
            supplier_rfc=supplier_rfc,
            supplier_name=supplier_name,
            invoice_number=invoice_number,
            invoice_date=invoice_date,
            due_date=due_date,
            amount=amount,
            payment_method=payment_method,
            status=APStatus.PENDING,
        )
        _ap_records[record.id] = record
        return record

    # ------------------------------------------------------------------
    def list_ap_records(
        self,
        tenant_id: str,
        status: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        supplier_rfc: Optional[str] = None,
    ) -> List[APRecord]:
        """Lista cuentas por pagar del tenant con filtros opcionales."""
        result = [
            r for r in _ap_records.values()
            if str(r.tenant_id) == str(tenant_id)
        ]
        if status:
            st = status.upper()
            result = [
                r for r in result
                if r.status.value == st or r.status.name == st
            ]
        if date_from:
            d = _parse_date(date_from)
            result = [
                r for r in result
                if _parse_date(r.invoice_date) is not None
                and _parse_date(r.invoice_date) >= d
            ]
        if date_to:
            d = _parse_date(date_to)
            result = [
                r for r in result
                if _parse_date(r.invoice_date) is not None
                and _parse_date(r.invoice_date) <= d
            ]
        if supplier_rfc:
            result = [
                r for r in result if r.supplier_rfc == supplier_rfc
            ]
        # Orden: más reciente primero.
        return sorted(
            result, key=lambda r: (r.created_at, r.id), reverse=True
        )

    # ------------------------------------------------------------------
    def get_ap_record(self, record_id: str) -> APRecord:
        """Devuelve un AP record por id; KeyError si no existe."""
        record = _ap_records.get(record_id)
        if record is None:
            raise KeyError(f"AP record no encontrado: {record_id}")
        return record

    # ------------------------------------------------------------------
    def mark_paid(
        self,
        record_id: str,
        tenant_id: str,
        amount: Optional[float] = None,
        payment_date: Optional[str] = None,
        payment_method: PaymentMethod = PaymentMethod.SPEI,
        reference: str = "",
        notes: str = "",
    ) -> APRecord:
        """Marca una cuenta por pagar como pagada (o parcial)."""
        record = self.get_ap_record(record_id)
        if str(record.tenant_id) != str(tenant_id):
            raise KeyError(f"AP record no encontrado: {record_id}")
        if record.status == APStatus.PAID:
            raise ValueError("La cuenta ya está pagada")

        pay_amount = amount if amount is not None else (record.amount - record.amount_paid)
        if pay_amount <= 0:
            raise ValueError("amount debe ser mayor a 0")

        record.amount_paid += pay_amount
        record.payment_method = payment_method.value
        record.updated_at = _utcnow()

        # Crea el registro de pago.
        payment = PaymentRecord(
            tenant_id=str(tenant_id),
            record_id=record.id,
            record_type="AP",
            amount=round(pay_amount, 2),
            payment_date=payment_date or date.today().isoformat(),
            payment_method=payment_method,
            reference=reference,
            notes=notes,
        )
        _payments[payment.id] = payment

        # Recalcula estado.
        if record.amount_paid >= record.amount - 0.005:
            record.status = APStatus.PAID
        else:
            record.status = APStatus.PARTIAL
        record.amount_paid = round(record.amount_paid, 2)
        return record

    # ------------------------------------------------------------------
    def get_aging_summary(self, tenant_id: str, today: Optional[date] = None):
        """Resumen de aging AP del tenant."""
        return AgingReport().compute_aging_ap(tenant_id, today)

    def _records_for_tenant(self, tenant_id: str) -> List[APRecord]:
        return [
            r for r in _ap_records.values()
            if str(r.tenant_id) == str(tenant_id)
        ]

    # Exposición para el scheduler / notas.
    @property
    def store(self):
        return _ap_records


# ---------------------------------------------------------------------------
# AR Manager
# ---------------------------------------------------------------------------

class ARManager:
    """Gestión de cuentas por cobrar (clientes)."""

    def __init__(self, db: Any = None):
        self.db = db

    def create_ar_record(
        self,
        tenant_id: str,
        client_rfc: str,
        invoice_number: str,
        invoice_date: str,
        due_date: str,
        amount: float,
        client_name: str = "",
        payment_method: Optional[str] = None,
    ) -> ARRecord:
        """Crea una cuenta por cobrar."""
        if not tenant_id:
            raise ValueError("tenant_id es obligatorio")
        if amount <= 0:
            raise ValueError("amount debe ser mayor a 0")
        record = ARRecord(
            tenant_id=str(tenant_id),
            client_rfc=client_rfc,
            client_name=client_name,
            invoice_number=invoice_number,
            invoice_date=invoice_date,
            due_date=due_date,
            amount=amount,
            payment_method=payment_method,
            status=ARStatus.PENDING,
        )
        _ar_records[record.id] = record
        return record

    def list_ar_records(
        self,
        tenant_id: str,
        status: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        client_rfc: Optional[str] = None,
    ) -> List[ARRecord]:
        """Lista cuentas por cobrar del tenant con filtros."""
        result = [
            r for r in _ar_records.values()
            if str(r.tenant_id) == str(tenant_id)
        ]
        if status:
            st = status.upper()
            result = [
                r for r in result
                if r.status.value == st or r.status.name == st
            ]
        if date_from:
            d = _parse_date(date_from)
            result = [
                r for r in result
                if _parse_date(r.invoice_date) is not None
                and _parse_date(r.invoice_date) >= d
            ]
        if date_to:
            d = _parse_date(date_to)
            result = [
                r for r in result
                if _parse_date(r.invoice_date) is not None
                and _parse_date(r.invoice_date) <= d
            ]
        if client_rfc:
            result = [
                r for r in result if r.client_rfc == client_rfc
            ]
        return sorted(
            result, key=lambda r: (r.created_at, r.id), reverse=True
        )

    def get_ar_record(self, record_id: str) -> ARRecord:
        """Devuelve un AR record por id; KeyError si no existe."""
        record = _ar_records.get(record_id)
        if record is None:
            raise KeyError(f"AR record no encontrado: {record_id}")
        return record

    def mark_received(
        self,
        record_id: str,
        tenant_id: str,
        amount: Optional[float] = None,
        payment_date: Optional[str] = None,
        payment_method: PaymentMethod = PaymentMethod.SPEI,
        reference: str = "",
        notes: str = "",
    ) -> ARRecord:
        """Marca una cuenta por cobrar como cobrada (o parcial)."""
        record = self.get_ar_record(record_id)
        if str(record.tenant_id) != str(tenant_id):
            raise KeyError(f"AR record no encontrado: {record_id}")
        if record.status == ARStatus.RECEIVED:
            raise ValueError("La cuenta ya está cobrada")

        pay_amount = amount if amount is not None else (record.amount - record.amount_received)
        if pay_amount <= 0:
            raise ValueError("amount debe ser mayor a 0")

        record.amount_received += pay_amount
        record.payment_method = payment_method.value
        record.updated_at = _utcnow()

        payment = PaymentRecord(
            tenant_id=str(tenant_id),
            record_id=record.id,
            record_type="AR",
            amount=round(pay_amount, 2),
            payment_date=payment_date or date.today().isoformat(),
            payment_method=payment_method,
            reference=reference,
            notes=notes,
        )
        _payments[payment.id] = payment

        if record.amount_received >= record.amount - 0.005:
            record.status = ARStatus.RECEIVED
        else:
            record.status = ARStatus.PARTIAL
        record.amount_received = round(record.amount_received, 2)
        return record

    def get_aging_summary(self, tenant_id: str, today: Optional[date] = None):
        """Resumen de aging AR del tenant."""
        return AgingReport().compute_aging_ar(tenant_id, today)

    def _records_for_tenant(self, tenant_id: str) -> List[ARRecord]:
        return [
            r for r in _ar_records.values()
            if str(r.tenant_id) == str(tenant_id)
        ]

    @property
    def store(self):
        return _ar_records


# ---------------------------------------------------------------------------
# Aging Report
# ---------------------------------------------------------------------------

class AgingReport:
    """Calcula reportes de antigüedad (aging) para AP y AR."""

    BUCKET_ORDER = ("0-30", "31-60", "61-90", "90+")

    @staticmethod
    def _bucket_for_days(days: int) -> str:
        if days <= 30:
            return "0-30"
        if days <= 60:
            return "31-60"
        if days <= 90:
            return "61-90"
        return "90+"

    @staticmethod
    def _build(
        tipo: str,
        tenant_id: str,
        records: List[Any],
        saldo_fn,
        due_fn,
        today: Optional[date],
    ) -> AgingReport:
        today = today or date.today()
        bucket_data = {
            name: {"count": 0, "monto": 0.0, "dias_sum": 0}
            for name in AgingReport.BUCKET_ORDER
        }
        total_facturas = 0
        total_monto = 0.0
        for rec in records:
            dias = _days_past_due(due_fn(rec), today)
            bucket = AgingReport._bucket_for_days(dias)
            saldo = saldo_fn(rec)
            if saldo <= 0:
                continue
            bucket_data[bucket]["count"] += 1
            bucket_data[bucket]["monto"] += saldo
            bucket_data[bucket]["dias_sum"] += max(0, dias)
            total_facturas += 1
            total_monto += saldo

        buckets = []
        for name in AgingReport.BUCKET_ORDER:
            d = bucket_data[name]
            count = d["count"]
            buckets.append(AgingBucketData(
                bucket=name,
                count=count,
                monto=round(d["monto"], 2),
                dias_promedio=round(d["dias_sum"] / count, 1) if count else 0.0,
            ))

        return AgingReportModel(
            tipo=tipo,
            tenant_id=str(tenant_id),
            buckets=buckets,
            total_facturas=total_facturas,
            total_monto=round(total_monto, 2),
        )

    def compute_aging_ap(
        self,
        tenant_id: str,
        today: Optional[date] = None,
    ) -> AgingReport:
        """Buckets de antigüedad de cuentas por pagar del tenant."""
        records = [
            r for r in _ap_records.values()
            if str(r.tenant_id) == str(tenant_id)
            and r.status not in (APStatus.PAID,)
        ]
        return self._build(
            "ap", tenant_id, records,
            saldo_fn=lambda r: r.amount - r.amount_paid,
            due_fn=lambda r: r.due_date,
            today=today,
        )

    def compute_aging_ar(
        self,
        tenant_id: str,
        today: Optional[date] = None,
    ) -> AgingReport:
        """Buckets de antigüedad de cuentas por cobrar del tenant."""
        records = [
            r for r in _ar_records.values()
            if str(r.tenant_id) == str(tenant_id)
            and r.status not in (ARStatus.RECEIVED,)
        ]
        return self._build(
            "ar", tenant_id, records,
            saldo_fn=lambda r: r.amount - r.amount_received,
            due_fn=lambda r: r.due_date,
            today=today,
        )


# ---------------------------------------------------------------------------
# Payment Scheduler
# ---------------------------------------------------------------------------

class PaymentScheduler:
    """Sugiere un calendario de pagos priorizando vencimientos y montos."""

    def suggest_payment_schedule(
        self,
        ap_records: List[APRecord],
        available_cash: float,
        today: Optional[date] = None,
        max_payments: int = 50,
    ) -> List[Dict]:
        """Sugiere pagos para un set de AP records bajo un techo de efectivo.

        Orden de prioridad:
          1. Registros vencidos (due_date < hoy) primero.
          2. Fecha de vencimiento más próxima.
          3. Monto mayor como desempate.

        Se detiene cuando se agota el efectivo o se llega a max_payments.
        """
        today = today or date.today()
        pending = [
            r for r in ap_records
            if r.status in (APStatus.PENDING, APStatus.PARTIAL)
        ]

        def _key(r: APRecord):
            days = _days_past_due(r.due_date, today)
            # Positivo = vencida (due en el pasado). Priorizar las vencidas.
            overdue = 1 if days >= 0 else 0
            remaining = r.amount - r.amount_paid
            return (-overdue, days, -remaining)

        pending.sort(key=_key)

        schedule: List[Dict] = []
        cash_left = available_cash
        for r in pending:
            if len(schedule) >= max_payments:
                break
            remaining = round(r.amount - r.amount_paid, 2)
            if remaining <= 0:
                continue
            if cash_left <= 0:
                break
            pay = min(remaining, cash_left)
            schedule.append({
                "record_id": r.id,
                "supplier_rfc": r.supplier_rfc,
                "supplier_name": r.supplier_name,
                "invoice_number": r.invoice_number,
                "due_date": r.due_date,
                "amount": remaining,
                "suggested_payment": round(pay, 2),
                "days_past_due": _days_past_due(r.due_date, today),
            })
            cash_left -= pay
        return schedule


# ---------------------------------------------------------------------------
# Retention Engine (SAT)
# ---------------------------------------------------------------------------

# Retenciones ISR/IVA según reglas SAT (tasas estándar).
# ISR: 10% sobre el monto facturado (honorarios/arrendamiento/servicios a PF).
# IVA: se retiene 2/3 del IVA trasladado (LIVA Art. 1º-A fracc. II, III y IV).
_RETENTION_RATES = {
    RetentionType.ISR_HONORARIOS: {
        "tasa": 0.10,
        "fundamento": "ISR Art. 94 fracc. II — honorarios a PF",
    },
    RetentionType.ISR_SERVICIOS_PROFESIONALES: {
        "tasa": 0.10,
        "fundamento": "ISR Art. 100 — servicios profesionales a PF",
    },
    RetentionType.ISR_ARRENDAMIENTO: {
        "tasa": 0.10,
        "fundamento": "ISR Art. 94 fracc. III — arrendamiento a PF",
    },
    RetentionType.IVA_HONORARIOS: {
        "tasa": 2.0 / 3.0,  # 2/3 del IVA trasladado
        "fundamento": "IVA Art. 1º-A fracc. IV — retención IVA honorarios",
    },
    RetentionType.IVA_ARRENDAMIENTO: {
        "tasa": 2.0 / 3.0,
        "fundamento": "IVA Art. 1º-A fracc. III — retención IVA arrendamiento",
    },
}


class RetentionEngine:
    """Calcula retenciones de ISR e IVA según reglas SAT."""

    def calculate_retention(
        self,
        invoice_amount: float,
        retention_type: RetentionType,
    ) -> RetentionResult:
        """Calcula la retención para un monto de factura.

        Para retenciones ISR, la base es el monto facturado.
        Para retenciones IVA, la base es el IVA trasladado contenido en el
        monto (monto * 16/116 cuando el monto incluye IVA) y se retiene 2/3
        de ese IVA (LIVA Art. 1º-A).
        """
        if invoice_amount <= 0:
            raise ValueError("invoice_amount debe ser mayor a 0")

        config = _RETENTION_RATES.get(retention_type)
        if config is None:
            raise ValueError(f"Tipo de retención no soportado: {retention_type}")

        if retention_type.value.startswith("iva_"):
            # IVA trasladado contenido en el monto total (16%).
            iva_trasladado = round(invoice_amount * (0.16 / 1.16), 2)
            retention = round(iva_trasladado * config["tasa"], 2)
            base = iva_trasladado
        else:
            base = invoice_amount
            retention = round(base * config["tasa"], 2)

        return RetentionResult(
            retention_type=retention_type,
            base_amount=round(base, 2),
            tasa=round(config["tasa"], 4),
            retention=retention,
            net_amount=round(invoice_amount - retention, 2),
            fundamento=config["fundamento"],
            aplica=True,
        )

    def detectar_tipo_retencion(
        self, descripcion_servicio: str
    ) -> RetentionType:
        """Heurística: detecta el tipo de retención según la descripción."""
        desc = (descripcion_servicio or "").lower()
        if any(k in desc for k in ("honorario", "consultoría", "consultoria")):
            return RetentionType.ISR_HONORARIOS
        if any(k in desc for k in ("arrendamiento", "renta")):
            return RetentionType.ISR_ARRENDAMIENTO
        if any(k in desc for k in ("servicio profesional", "servicios prof")):
            return RetentionType.ISR_SERVICIOS_PROFESIONALES
        return RetentionType.ISR_SERVICIOS_PROFESIONALES


# ---------------------------------------------------------------------------
# Notas de Crédito
# ---------------------------------------------------------------------------

class NotasCredito:
    """Genera notas de crédito sobre registros AP/AR."""

    def generate_nota_credito(
        self,
        tenant_id: str,
        original_record: Any,
        reason: str,
        amount: float,
        record_type: str = "AR",
        tipo: CreditNoteType = CreditNoteType.DEVOLUCION,
    ) -> CreditNote:
        """Genera una nota de crédito sobre un registro original.

        original_record: instancia APRecord o ARRecord (debe pertenecer al
            tenant autenticado; el router valida la propiedad antes de llamar).
        """
        if amount <= 0:
            raise ValueError("amount debe ser mayor a 0")
        if not reason.strip():
            raise ValueError("reason es obligatorio")

        note = CreditNote(
            tenant_id=str(tenant_id),
            original_record_id=original_record.id,
            original_record_type=record_type.upper(),
            reason=reason,
            amount=round(amount, 2),
            tipo=tipo,
        )
        _notes[note.id] = note
        return note

    def list_notas(
        self,
        tenant_id: str,
        record_type: Optional[str] = None,
    ) -> List[CreditNote]:
        result = [
            n for n in _notes.values() if str(n.tenant_id) == str(tenant_id)
        ]
        if record_type:
            result = [n for n in result if n.original_record_type == record_type.upper()]
        return sorted(result, key=lambda n: n.created_at, reverse=True)
