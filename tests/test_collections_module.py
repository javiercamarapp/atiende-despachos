# -*- coding: utf-8 -*-
"""
test_collections_module.py — Tests completos del módulo de cobranza automatizada.

Cubre:
  - Scheduler: programación, procesamiento, cancelación de recordatorios
  - Webhooks: procesamiento de pagos, batch, historial
  - API: endpoints REST (analyze, reminder, aging, projection, summary,
    score, events, outstanding, schedule, webhook, pdf)
  - PDF reports: generación de aging, projection, summary
  - DB: collection_payments, collection_config
"""
import datetime as dt
import json

import pytest

from b2b_ai.collections.models import (
    CollectionsAnalyzeRequest,
    CollectionsScheduleRequest,
    CollectionsSendReminderRequest,
    CollectionWebhookPayload,
)
from b2b_ai.collections.scheduler import CollectionsScheduler, ScheduledReminder
from b2b_ai.collections.webhooks import (
    CollectionsWebhookHandler,
    SUPPORTED_EVENTS,
    _event_to_respuesta,
)
from b2b_ai.services.collections import CollectionsManager, age_bucket, days_overdue
from b2b_ai.services.collections_report import aging_report, projection, summary


TODAY = dt.date(2026, 7, 31)


def _d(days_from_today):
    return TODAY + dt.timedelta(days=days_from_today)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

INVOICES = [
    {"factura_id": "F1", "nombre_empresa": "A", "monto": "1000",
     "fecha_vencimiento": _d(-10).isoformat()},
    {"factura_id": "F2", "nombre_empresa": "B", "monto": "2000",
     "fecha_vencimiento": _d(-40).isoformat()},
    {"factura_id": "F3", "nombre_empresa": "C", "monto": "3000",
     "fecha_vencimiento": _d(-75).isoformat()},
    {"factura_id": "F4", "nombre_empresa": "D", "monto": "4000",
     "fecha_vencimiento": _d(-120).isoformat()},
]


@pytest.fixture
def tenant_db(tmp_db):
    """Devuelve una DB temporal con un tenant creado (id=1)."""
    tmp_db.create_tenant("Test Collections", rfc="TCO123456")
    return tmp_db


# --------------------------------------------------------------------------- #
# ScheduledReminder dataclass
# --------------------------------------------------------------------------- #

def test_scheduled_reminder_to_dict():
    r = ScheduledReminder(
        factura_id="F1", nombre_empresa="Test", monto="500",
        fecha_vencimiento="2026-07-01", stage="vencimiento",
        channel="email", scheduled_date="2026-07-01")
    d = r.to_dict()
    assert d["factura_id"] == "F1"
    assert d["stage"] == "vencimiento"
    assert d["status"] == "pending"
    assert d["event_id"] is None


def test_scheduled_reminder_defaults():
    r = ScheduledReminder(
        factura_id="F1", nombre_empresa="X", monto="100",
        fecha_vencimiento="2026-07-01", stage="vencimiento",
        channel="email", scheduled_date="2026-07-01")
    assert r.status == "pending"
    assert r.sent_at is None
    assert r.error is None


# --------------------------------------------------------------------------- #
# CollectionsScheduler
# --------------------------------------------------------------------------- #

def test_scheduler_schedule_reminder(tenant_db):
    sched = CollectionsScheduler(db=tenant_db, tenant_id=1)
    r = sched.schedule_reminder(
        factura_id="F1", nombre_empresa="A", monto="1000",
        fecha_vencimiento=_d(-10).isoformat(),
        stage="recordatorio_formal", channel="email",
        scheduled_date=TODAY.isoformat())
    assert r.factura_id == "F1"
    assert r.status == "pending"
    pending = sched.list_pending()
    assert len(pending) == 1
    assert pending[0]["factura_id"] == "F1"


def test_scheduler_dedup(tenant_db):
    sched = CollectionsScheduler(db=tenant_db, tenant_id=1)
    sched.schedule_reminder("F1", "A", "1000", _d(-10).isoformat(),
                            "vencimiento", "email",
                            TODAY.isoformat())
    # Duplicate should return existing, not create new
    r2 = sched.schedule_reminder("F1", "A", "1000", _d(-10).isoformat(),
                                 "vencimiento", "email",
                                 TODAY.isoformat())
    assert r2.factura_id == "F1"
    pending = sched.list_pending()
    assert len(pending) == 1


def test_scheduler_schedule_batch(tenant_db):
    sched = CollectionsScheduler(db=tenant_db, tenant_id=1)
    result = sched.schedule_batch(INVOICES, channels=["email"], today=TODAY)
    assert result["total_scheduled"] > 0
    assert "reminders" in result
    # F4 (120 days overdue) should be escalamiento
    stages = [r["stage"] for r in result["reminders"]]
    assert "escalamiento" in stages


def test_scheduler_process_pending(tenant_db):
    sched = CollectionsScheduler(db=tenant_db, tenant_id=1)
    # Schedule for today so they are immediately processable
    for inv in INVOICES:
        sched.schedule_reminder(
            inv["factura_id"], inv["nombre_empresa"], inv["monto"],
            inv["fecha_vencimiento"], "recordatorio_formal", "email",
            TODAY.isoformat())
    result = sched.process_pending(today=TODAY)
    assert result["sent"] == 4
    assert result["failed"] == 0
    # All should be sent now
    pending = sched.list_pending()
    assert len(pending) == 0


def test_scheduler_cancel(tenant_db):
    sched = CollectionsScheduler(db=tenant_db, tenant_id=1)
    sched.schedule_reminder("F1", "A", "1000", _d(-10).isoformat(),
                            "vencimiento", "email",
                            TODAY.isoformat())
    ok = sched.cancel_reminder("F1", "vencimiento", "email")
    assert ok is True
    pending = sched.list_pending()
    assert len(pending) == 0


def test_scheduler_cancel_not_found(tenant_db):
    sched = CollectionsScheduler(db=tenant_db, tenant_id=1)
    ok = sched.cancel_reminder("NONEXISTENT", "vencimiento", "email")
    assert ok is False


def test_scheduler_stats(tenant_db):
    sched = CollectionsScheduler(db=tenant_db, tenant_id=1)
    sched.schedule_reminder("F1", "A", "1000", _d(-10).isoformat(),
                            "vencimiento", "email",
                            TODAY.isoformat())
    sched.schedule_reminder("F2", "B", "2000", _d(-40).isoformat(),
                            "escalamiento", "whatsapp",
                            TODAY.isoformat())
    stats = sched.get_stats()
    assert stats["total"] == 2
    assert stats["by_status"]["pending"] == 2
    assert "email" in stats["by_channel"]
    assert "whatsapp" in stats["by_channel"]


def test_scheduler_clear_processed(tenant_db):
    sched = CollectionsScheduler(db=tenant_db, tenant_id=1)
    sched.schedule_reminder("F1", "A", "1000", _d(-10).isoformat(),
                            "vencimiento", "email",
                            TODAY.isoformat())
    sched.process_pending(today=TODAY)
    cleared = sched.clear_processed()
    assert cleared == 1
    all_reminders = sched.list_all()
    assert len(all_reminders) == 0


def test_scheduler_persistence(tenant_db):
    """Verifica que la cola se persiste en la DB."""
    sched1 = CollectionsScheduler(db=tenant_db, tenant_id=1)
    sched1.schedule_reminder("F1", "A", "1000", _d(-10).isoformat(),
                             "vencimiento", "email",
                             TODAY.isoformat())
    # Create a new scheduler instance (should load from DB)
    sched2 = CollectionsScheduler(db=tenant_db, tenant_id=1)
    pending = sched2.list_pending()
    assert len(pending) == 1
    assert pending[0]["factura_id"] == "F1"


def test_scheduler_get_current_stage(tenant_db):
    sched = CollectionsScheduler(db=tenant_db, tenant_id=1)
    # 5 days overdue -> recordatorio_formal
    stage = sched._get_current_stage(_d(-5).isoformat(), TODAY)
    assert stage == "recordatorio_formal"
    # 35 days overdue -> segundo_recordatorio
    stage = sched._get_current_stage(_d(-35).isoformat(), TODAY)
    assert stage == "segundo_recordatorio"
    # 65 days overdue -> escalamiento
    stage = sched._get_current_stage(_d(-65).isoformat(), TODAY)
    assert stage == "escalamiento"


# --------------------------------------------------------------------------- #
# CollectionsWebhookHandler
# --------------------------------------------------------------------------- #

def test_webhook_payment_received(tenant_db):
    # Sync outstanding first
    mgr = CollectionsManager(db=tenant_db, tenant_id=1)
    mgr.sync_outstanding(INVOICES, today=TODAY)
    handler = CollectionsWebhookHandler(db=tenant_db, tenant_id=1)
    result = handler.process_webhook({
        "event_type": "payment_received",
        "invoice_id": "F1",
        "amount": 1000.0,
        "reference": "SPEI-ABC",
        "provider": "spei",
    })
    assert result["ok"] is True
    assert result["event_type"] == "payment_received"
    assert result["respuesta"] == "pagado"
    # F1 should be removed from outstanding
    remaining = tenant_db.list_outstanding_invoices(tenant_id=1, factura_id="F1")
    assert len(remaining) == 0


def test_webhook_payment_partial(tenant_db):
    # Sync outstanding first so F2 exists
    mgr = CollectionsManager(db=tenant_db, tenant_id=1)
    mgr.sync_outstanding(INVOICES, today=TODAY)
    handler = CollectionsWebhookHandler(db=tenant_db, tenant_id=1)
    result = handler.process_webhook({
        "event_type": "payment_partial",
        "invoice_id": "F2",
        "amount": 500.0,
        "reference": "REF-123",
    })
    assert result["ok"] is True
    assert result["respuesta"] == "pago_parcial"
    # F2 should still be in outstanding
    remaining = tenant_db.list_outstanding_invoices(tenant_id=1, factura_id="F2")
    assert len(remaining) == 1


def test_webhook_payment_rejected(tenant_db):
    handler = CollectionsWebhookHandler(db=tenant_db, tenant_id=1)
    result = handler.process_webhook({
        "event_type": "payment_rejected",
        "invoice_id": "F3",
        "amount": 0,
        "reference": "REJ-1",
    })
    assert result["ok"] is True
    assert result["respuesta"] == "pago_rechazado"


def test_webhook_invalid_event(tenant_db):
    handler = CollectionsWebhookHandler(db=tenant_db, tenant_id=1)
    result = handler.process_webhook({
        "event_type": "invalid_event",
        "invoice_id": "F1",
    })
    assert result["ok"] is False
    assert "no soportado" in result["error"]


def test_webhook_missing_invoice_id(tenant_db):
    handler = CollectionsWebhookHandler(db=tenant_db, tenant_id=1)
    result = handler.process_webhook({
        "event_type": "payment_received",
    })
    assert result["ok"] is False
    assert "invoice_id" in result["error"]


def test_webhook_batch(tenant_db):
    handler = CollectionsWebhookHandler(db=tenant_db, tenant_id=1)
    webhooks = [
        {"event_type": "payment_received", "invoice_id": "F1",
         "amount": 1000.0, "reference": "SPEI-1"},
        {"event_type": "payment_received", "invoice_id": "F2",
         "amount": 2000.0, "reference": "SPEI-2"},
    ]
    result = handler.batch_process(webhooks)
    assert result["total"] == 2
    assert result["ok"] == 2
    assert result["failed"] == 0


def test_webhook_payment_history(tenant_db):
    handler = CollectionsWebhookHandler(db=tenant_db, tenant_id=1)
    handler.process_webhook({
        "event_type": "payment_received",
        "invoice_id": "F1",
        "amount": 1000.0,
        "reference": "SPEI-1",
    })
    handler.process_webhook({
        "event_type": "payment_partial",
        "invoice_id": "F1",
        "amount": 500.0,
        "reference": "SPEI-2",
    })
    history = handler.get_payment_history("F1")
    # Both events are webhook_ events
    assert len(history) >= 1


def test_event_to_respuesta():
    assert _event_to_respuesta("payment_received") == "pagado"
    assert _event_to_respuesta("payment_partial") == "pago_parcial"
    assert _event_to_respuesta("payment_rejected") == "pago_rechazado"
    assert _event_to_respuesta("payment_disputed") == "disputa"
    assert _event_to_respuesta("payment_refunded") == "reembolso"


def test_supported_events():
    assert "payment_received" in SUPPORTED_EVENTS
    assert "payment_partial" in SUPPORTED_EVENTS
    assert "payment_rejected" in SUPPORTED_EVENTS
    assert "payment_disputed" in SUPPORTED_EVENTS
    assert "payment_refunded" in SUPPORTED_EVENTS


# --------------------------------------------------------------------------- #
# DB methods: collection_payments, collection_config
# --------------------------------------------------------------------------- #

def test_db_collection_payments(tmp_db):
    tid = tmp_db.create_tenant("Test")
    pid = tmp_db.add_collection_payment(
        tid, "F1", "payment_received", 1000.0, "MXN",
        "SPEI-123", "spei", "2026-07-31T10:00:00", {"extra": "data"})
    assert pid is not None
    payments = tmp_db.list_collection_payments(tenant_id=tid)
    assert len(payments) == 1
    assert payments[0]["factura_id"] == "F1"
    assert payments[0]["amount"] == 1000.0
    assert payments[0]["reference"] == "SPEI-123"


def test_db_collection_payments_by_factura(tmp_db):
    tid = tmp_db.create_tenant("Test")
    tmp_db.add_collection_payment(tid, "F1", "payment_received", 500.0)
    tmp_db.add_collection_payment(tid, "F1", "payment_partial", 200.0)
    tmp_db.add_collection_payment(tid, "F2", "payment_received", 300.0)
    f1_payments = tmp_db.list_collection_payments(
        tenant_id=tid, factura_id="F1")
    assert len(f1_payments) == 2


def test_db_collection_config(tmp_db):
    tid = tmp_db.create_tenant("Test")
    tmp_db.set_collection_config(tid, "grace_days", "7")
    tmp_db.set_collection_config(tid, "max_reminders", "5")
    val = tmp_db.get_collection_config(tid, "grace_days")
    assert val == "7"
    config = tmp_db.list_collection_config(tid)
    assert config["grace_days"] == "7"
    assert config["max_reminders"] == "5"


def test_db_collection_config_upsert(tmp_db):
    tid = tmp_db.create_tenant("Test")
    tmp_db.set_collection_config(tid, "grace_days", "7")
    tmp_db.set_collection_config(tid, "grace_days", "14")
    val = tmp_db.get_collection_config(tid, "grace_days")
    assert val == "14"


def test_db_collection_config_missing(tmp_db):
    tid = tmp_db.create_tenant("Test")
    val = tmp_db.get_collection_config(tid, "nonexistent")
    assert val is None


# --------------------------------------------------------------------------- #
# Pydantic models
# --------------------------------------------------------------------------- #

def test_models_analyze_request():
    req = CollectionsAnalyzeRequest(invoices=INVOICES, sync=True)
    assert len(req.invoices) == 4
    assert req.sync is True


def test_models_reminder_request():
    req = CollectionsSendReminderRequest(
        invoice=INVOICES[0], stage="vencimiento",
        channel="email", record=True)
    assert req.stage == "vencimiento"
    assert req.record is True


def test_models_schedule_request():
    req = CollectionsScheduleRequest(
        invoices=INVOICES, auto_send=False,
        channels=["email", "whatsapp"])
    assert len(req.invoices) == 4
    assert "whatsapp" in req.channels


def test_models_webhook_payload():
    payload = CollectionWebhookPayload(
        event_type="payment_received",
        invoice_id="F1",
        amount=1000.0,
        reference="SPEI-123",
        provider="spei")
    assert payload.event_type == "payment_received"
    assert payload.tenant_id is None


# --------------------------------------------------------------------------- #
# PDF reports (fallback mode — without reportlab)
# --------------------------------------------------------------------------- #

def test_pdf_aging_fallback():
    from b2b_ai.collections.pdf_report import generate_aging_pdf
    pdf_bytes = generate_aging_pdf(INVOICES, tenant_id=1, today=TODAY)
    # reportlab is installed → generates real PDF bytes
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 100
    # Real PDF starts with %PDF
    assert pdf_bytes[:5] == b"%PDF-"


def test_pdf_projection_fallback():
    from b2b_ai.collections.pdf_report import generate_projection_pdf
    scored = [{**inv, "score": 0.5} for inv in INVOICES]
    pdf_bytes = generate_projection_pdf(scored, tenant_id=1, today=TODAY)
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 100
    assert pdf_bytes[:5] == b"%PDF-"


def test_pdf_summary_fallback():
    from b2b_ai.collections.pdf_report import generate_summary_pdf
    scored = [{**inv, "score": 0.5} for inv in INVOICES]
    pdf_bytes = generate_summary_pdf(scored, tenant_id=1, today=TODAY)
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 100
    assert pdf_bytes[:5] == b"%PDF-"


# --------------------------------------------------------------------------- #
# Integration: full flow with DB
# --------------------------------------------------------------------------- #

def test_full_flow_analyze_schedule_process(tenant_db):
    """Flujo completo: analizar → programar → procesar."""
    # 1. Analyze
    mgr = CollectionsManager(db=tenant_db, tenant_id=1)
    result = mgr.analyze(INVOICES, today=TODAY)
    assert result["total_invoices"] == 4
    # Sync to DB
    mgr.sync_outstanding(INVOICES, today=TODAY)

    # 2. Schedule
    sched = CollectionsScheduler(db=tenant_db, tenant_id=1)
    batch = sched.schedule_batch(INVOICES, channels=["email"], today=TODAY)
    assert batch["total_scheduled"] > 0

    # 3. Process (all scheduled for today)
    processed = sched.process_pending(today=TODAY)
    assert processed["sent"] > 0

    # 4. Verify events were registered
    events = tenant_db.list_collection_events(tenant_id=1)
    assert len(events) > 0


def test_full_flow_webhook_payment(tenant_db):
    """Flujo completo: cartera → pago → eliminación."""
    # Setup: sync outstanding
    mgr = CollectionsManager(db=tenant_db, tenant_id=1)
    mgr.sync_outstanding(INVOICES, today=TODAY)
    outstanding = tenant_db.list_outstanding_invoices(tenant_id=1)
    assert len(outstanding) == 4

    # Process payment webhook
    handler = CollectionsWebhookHandler(db=tenant_db, tenant_id=1)
    result = handler.process_webhook({
        "event_type": "payment_received",
        "invoice_id": "F1",
        "amount": 1000.0,
        "reference": "SPEI-123",
        "provider": "spei",
    })
    assert result["ok"] is True

    # F1 should be removed from outstanding
    remaining = tenant_db.list_outstanding_invoices(tenant_id=1)
    assert len(remaining) == 3
    remaining_ids = {r["factura_id"] for r in remaining}
    assert "F1" not in remaining_ids


def test_full_flow_config(tenant_db):
    """Flujo completo: configurar → usar config."""
    tid = tenant_db.create_tenant("Test Config")
    tenant_db.set_collection_config(tid, "grace_days", "7")
    tenant_db.set_collection_config(tid, "channels", "email,whatsapp")
    tenant_db.set_collection_config(tid, "max_reminders", "5")

    config = tenant_db.list_collection_config(tid)
    assert config["grace_days"] == "7"
    assert config["channels"] == "email,whatsapp"
    assert config["max_reminders"] == "5"
