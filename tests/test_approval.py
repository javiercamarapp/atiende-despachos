# -*- coding: utf-8 -*-
"""Tests de las reglas de aprobación (gate humano) FASE 2."""
import pytest

from b2b_ai.services.approval import ApprovalManager, DEFAULT_AUTO_THRESHOLD


def _inv(total, tipo="I", folio="FAC-1"):
    return {"folio_fiscal": folio, "total": total, "tipo": tipo,
            "emisor_rfc": "CON950820K12", "conceptos": []}


def test_umbral_por_defecto():
    assert DEFAULT_AUTO_THRESHOLD == 50000


def test_monto_bajo_umbral_auto_aprobado():
    mgr = ApprovalManager()
    ev = mgr.evaluate(_inv("1000"))
    assert ev["decision"] == "auto_approved"
    assert ev["requires_approval"] is False
    assert ev["requires_efirma"] is False
    assert mgr.can_register(_inv("1000"), ev["decision"]) is True


def test_monto_igual_al_umbral_requiere_aprobacion():
    mgr = ApprovalManager(auto_threshold=1000)
    ev = mgr.evaluate(_inv("1000"))
    assert ev["decision"] == "requires_approval"
    assert ev["requires_approval"] is True
    assert ev["requires_efirma"] is True


def test_monto_sobre_umbral_requiere_aprobacion():
    mgr = ApprovalManager()
    ev = mgr.evaluate(_inv("60000"))
    assert ev["decision"] == "requires_approval"
    assert ev["requires_approval"] is True


def test_umbral_es_inclusivo():
    mgr = ApprovalManager(auto_threshold=50000)
    assert mgr.evaluate(_inv("49999.99"))["decision"] == "auto_approved"
    assert mgr.evaluate(_inv("50000"))["decision"] == "requires_approval"


def test_pago_siempre_requiere_aprobacion_y_efirma():
    mgr = ApprovalManager()
    ev = mgr.evaluate(_inv("100", tipo="P"))
    assert ev["decision"] == "requires_approval"
    assert ev["requires_approval"] is True
    assert ev["requires_efirma"] is True


def test_pago_por_concepto_requiere_aprobacion():
    inv = {"folio_fiscal": "FAC-P", "total": "50",
           "conceptos": [{"descripcion": "Complemento de pago parcialidad"}]}
    ev = ApprovalManager().evaluate(inv)
    assert ev["decision"] == "requires_approval"
    assert ev["requires_efirma"] is True


def test_requiere_aprobacion_genera_notificacion():
    mgr = ApprovalManager(auto_threshold=1000)
    ev = mgr.evaluate(_inv("5000"))
    assert ev["notification"] is not None
    assert ev["notification"]["status"] in ("queued", "sent")
    assert "aprobacion" in ev["notification"]["message"].lower()


def test_auto_aprobado_no_notifica():
    mgr = ApprovalManager()
    ev = mgr.evaluate(_inv("100"))
    assert ev["notification"] is None


def test_notificacion_por_whatsapp_mock():
    from b2b_ai.notifications.whatsapp import MockWhatsApp
    wa = MockWhatsApp()
    mgr = ApprovalManager(auto_threshold=1000, notifier=wa)
    ev = mgr.evaluate(_inv("5000"))
    assert ev["notification"]["channel"] == "whatsapp"
    assert wa.messages  # se envió al menos un mensaje


def test_aprobacion_sin_efirma_se_bloquea():
    mgr = ApprovalManager(auto_threshold=1000)
    res = mgr.approve(_inv("5000"), responsable="Contador", efirma_ok=False)
    assert res["ok"] is False
    assert res["status"] == "blocked_efirma"


def test_aprobacion_con_efirma_ok():
    mgr = ApprovalManager(auto_threshold=1000)
    res = mgr.approve(_inv("5000"), responsable="Contador", efirma_ok=True)
    assert res["ok"] is True
    assert res["status"] == "approved"


def test_rechazo_registra_decision():
    mgr = ApprovalManager()
    res = mgr.reject(_inv("5000"), responsable="Auditor")
    assert res["status"] == "rejected"
    assert mgr.decisions  # bitácora no vacía


def test_record_decision_con_timestamp_y_responsable():
    mgr = ApprovalManager()
    rec_id = mgr.record_decision(_inv("100"), "auto_approved",
                                 "Sistema", efirma_ok=False)
    assert rec_id == 1
    rec = mgr.decisions[0]
    assert rec["responsable"] == "Sistema"
    assert rec["timestamp"]
    assert rec["decision"] == "auto_approved"


def test_can_register_solo_con_decision_aprobada():
    mgr = ApprovalManager()
    assert mgr.can_register({}, "auto_approved") is True
    assert mgr.can_register({}, "approved") is True
    assert mgr.can_register({}, "requires_approval") is False
    assert mgr.can_register({}, "blocked_efirma") is False
    assert mgr.can_register({}, "rejected") is False
