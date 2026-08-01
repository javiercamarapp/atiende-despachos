# -*- coding: utf-8 -*-
"""
Comprehensive tests for b2b_ai/services/pipeline.py
Covers: ensure_tenant, _tool, process_file, process_batch, summarize
"""
from __future__ import annotations

import os
import tempfile
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch, PropertyMock, call

import pytest

from b2b_ai.services.pipeline import ensure_tenant, _tool, process_file, process_batch, summarize
from b2b_ai.tools.logger import ToolCallLogger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeDB:
    """Minimal in-memory DB mock for pipeline tests."""
    def __init__(self):
        self._tenants = []
        self._invoices = []
        self._notifications = []
        self._audit = []

    def list_tenants(self):
        return self._tenants

    def create_tenant(self, name, rfc=""):
        tid = len(self._tenants) + 1
        self._tenants.append({"id": tid, "name": name, "rfc": rfc})
        return tid

    def insert_invoice(self, tenant_id, datos, clasif, validacion, erp=None):
        inv_id = len(self._invoices) + 1
        self._invoices.append({"id": inv_id, "tenant_id": tenant_id})
        return inv_id, True

    def list_invoices(self, tenant_id=None, limit=200):
        return [i for i in self._invoices if tenant_id is None or i.get("tenant_id") == tenant_id][:limit]

    def insert_notification(self, tenant_id, event, channel, to, subject, message, status="sent"):
        self._notifications.append({"tenant_id": tenant_id, "event": event, "status": status})

    def log_call(self, tool_name, action, entity, entity_id, payload, status, tenant_id):
        return len(self._audit) + 1


class FakeLogger:
    """Minimal logger mock."""
    def __init__(self):
        self.calls = []

    def set_db(self, db):
        pass

    def log(self, tool_name, action, entity="", entity_id="", payload=None, status="ok", tenant_id=None):
        self.calls.append({"tool_name": tool_name, "status": status})
        return len(self.calls)


# ---------------------------------------------------------------------------
# ensure_tenant
# ---------------------------------------------------------------------------

class TestEnsureTenant:
    def test_returns_explicit_tenant_id(self):
        db = FakeDB()
        result = ensure_tenant(db, tenant_id=42)
        assert result == 42

    def test_returns_first_existing_tenant(self):
        db = FakeDB()
        db.create_tenant("Existing", "RFC1")
        result = ensure_tenant(db)
        assert result == 1

    def test_creates_new_tenant_when_none_exist(self):
        db = FakeDB()
        result = ensure_tenant(db, name="New Tenant", rfc="ABC")
        assert result == 1
        tenants = db.list_tenants()
        assert len(tenants) == 1
        assert tenants[0]["name"] == "New Tenant"

    def test_creates_default_tenant(self):
        db = FakeDB()
        result = ensure_tenant(db)
        assert result == 1
        assert db.list_tenants()[0]["name"] == "Despacho Demo"


# ---------------------------------------------------------------------------
# _tool
# ---------------------------------------------------------------------------

class TestTool:
    @patch("b2b_ai.services.pipeline.call_tool")
    def test_tool_success(self, mock_call):
        mock_call.return_value = {"ok": True}
        logger = FakeLogger()
        result = _tool("parse_cfdi", logger, tenant_id=1, xml_path="/tmp/test.xml")
        assert result == {"ok": True}
        assert mock_call.called
        assert logger.calls[-1]["status"] == "ok"

    @patch("b2b_ai.services.pipeline.call_tool")
    def test_tool_error_reraises(self, mock_call):
        mock_call.side_effect = KeyError("Tool no registrada")
        logger = FakeLogger()
        with pytest.raises(KeyError):
            _tool("nonexistent_tool", logger, tenant_id=1)
        assert logger.calls[-1]["status"] == "error"

    @patch("b2b_ai.services.pipeline.call_tool")
    def test_tool_logs_payload(self, mock_call):
        mock_call.return_value = {"result": "data"}
        logger = FakeLogger()
        _tool("parse_cfdi", logger, tenant_id=1, xml_path="/tmp/x.xml")
        assert logger.calls[-1]["tool_name"] == "parse_cfdi"

    @patch("b2b_ai.services.pipeline.call_tool")
    def test_tool_logs_error_payload(self, mock_call):
        mock_call.side_effect = ValueError("bad input")
        logger = FakeLogger()
        with pytest.raises(ValueError):
            _tool("parse_cfdi", logger, tenant_id=1, xml_path="/tmp/x.xml")
        assert "error" in logger.calls[-1]["status"]


# ---------------------------------------------------------------------------
# process_file
# ---------------------------------------------------------------------------

def _make_fake_tools():
    """Return a dict of mock functions for each pipeline tool."""
    parse = MagicMock(return_value={
        "folio_fiscal": "uuid-1234",
        "emisor_nombre": "Proveedor SA",
        "emisor_rfc": "ABC010101",
        "total": "1000.00",
        "fecha": "2026-07-01",
        "conceptos": [{"descripcion": "Servicio"}],
        "claves_prod_serv": [],
        "tipo": "I",
    })
    validate = MagicMock(return_value={"ok": True, "issues": [], "warnings": []})
    classify = MagicMock(return_value={"categoria": "gasto_operativo", "confianza": 0.9, "razon": "test"})
    anomalies = MagicMock(return_value={"anomalias": [], "nivel": "normal"})
    approval = MagicMock(return_value={"decision": "auto_approved"})
    register = MagicMock(return_value={"ok": True, "poliza": "POL-1", "status": "registered"})
    notification = MagicMock(return_value={"status": "sent", "subject": "Test", "message": "Body"})
    pii = MagicMock(return_value={"rfc_found": 0, "curp_found": 0})
    return {
        "parse_cfdi": parse,
        "validate_cfdi": validate,
        "classify_expense": classify,
        "detect_anomalies": anomalies,
        "evaluate_approval": approval,
        "register_erp": register,
        "send_notification": notification,
        "detect_pii": pii,
    }


class TestProcessFile:
    @patch("b2b_ai.api.security.detect_pii", return_value={"rfc_found": 0})
    @patch("b2b_ai.services.pipeline.call_tool")
    @patch("b2b_ai.services.pipeline.EmailSender")
    def test_process_file_auto_approved(self, mock_email, mock_call, mock_pii):
        fake_tools = _make_fake_tools()
        mock_call.side_effect = lambda name, **kw: fake_tools[name](**kw)
        db = FakeDB()
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
            f.write(b"<cfdi/>")
            xml_path = f.name
        try:
            result = process_file(xml_path, db=db)
            assert result["archivo"].endswith(".xml")
            assert result["validacion"]["ok"] is True
            assert result["clasificacion"]["categoria"] == "gasto_operativo"
            assert result["insertado"] is True
            assert result["notificacion"]["status"] == "sent"
            assert result["invoice_id"] is not None
        finally:
            os.unlink(xml_path)

    @patch("b2b_ai.api.security.detect_pii", return_value={"rfc_found": 1})
    @patch("b2b_ai.services.pipeline.call_tool")
    @patch("b2b_ai.services.pipeline.EmailSender")
    def test_process_file_pending_approval(self, mock_email, mock_call, mock_pii):
        fake_tools = _make_fake_tools()
        fake_tools["evaluate_approval"] = MagicMock(return_value={"decision": "needs_review"})
        mock_call.side_effect = lambda name, **kw: fake_tools[name](**kw)
        db = FakeDB()
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
            f.write(b"<cfdi/>")
            xml_path = f.name
        try:
            result = process_file(xml_path, db=db)
            assert result["erp"]["status"] == "pending_approval"
            assert result["aprobacion"]["decision"] == "needs_review"
        finally:
            os.unlink(xml_path)

    @patch("b2b_ai.api.security.detect_pii", return_value={})
    @patch("b2b_ai.services.pipeline.call_tool")
    @patch("b2b_ai.services.pipeline.EmailSender")
    def test_process_file_rejected(self, mock_email, mock_call, mock_pii):
        fake_tools = _make_fake_tools()
        fake_tools["evaluate_approval"] = MagicMock(return_value={"decision": "rejected"})
        mock_call.side_effect = lambda name, **kw: fake_tools[name](**kw)
        db = FakeDB()
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
            f.write(b"<cfdi/>")
            xml_path = f.name
        try:
            result = process_file(xml_path, db=db)
            assert result["erp"]["status"] == "pending_approval"
            assert "rejected" in result["erp"]["decision"].lower() or "Rejected" in result["erp"]["message"]
        finally:
            os.unlink(xml_path)

    @patch("b2b_ai.api.security.detect_pii", return_value={})
    @patch("b2b_ai.services.pipeline.call_tool")
    @patch("b2b_ai.services.pipeline.EmailSender")
    def test_process_file_notification_error_handled(self, mock_email, mock_call, mock_pii):
        fake_tools = _make_fake_tools()
        fake_tools["send_notification"] = MagicMock(side_effect=Exception("SMTP down"))
        mock_call.side_effect = lambda name, **kw: fake_tools[name](**kw)
        db = FakeDB()
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
            f.write(b"<cfdi/>")
            xml_path = f.name
        try:
            result = process_file(xml_path, db=db)
            assert result["notificacion"]["status"] == "error"
            assert "SMTP down" in result["notificacion"]["message"]
        finally:
            os.unlink(xml_path)

    @patch("b2b_ai.api.security.detect_pii", return_value={})
    @patch("b2b_ai.services.pipeline.call_tool")
    @patch("b2b_ai.services.pipeline.EmailSender")
    def test_process_file_returns_pii(self, mock_email, mock_call, mock_pii):
        fake_tools = _make_fake_tools()
        mock_call.side_effect = lambda name, **kw: fake_tools[name](**kw)
        db = FakeDB()
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
            f.write(b"<cfdi/>")
            xml_path = f.name
        try:
            result = process_file(xml_path, db=db)
            assert "pii" in result
        finally:
            os.unlink(xml_path)

    @patch("b2b_ai.api.security.detect_pii", return_value={})
    @patch("b2b_ai.services.pipeline.call_tool")
    @patch("b2b_ai.services.pipeline.EmailSender")
    def test_process_file_validacion_not_ok_sends_rejection_notification(self, mock_email, mock_call, mock_pii):
        """When validation fails, the pipeline now sends a rejection notification
        (invoice_rejected event) instead of skipping."""
        fake_tools = _make_fake_tools()
        fake_tools["validate_cfdi"] = MagicMock(return_value={"ok": False, "issues": [], "warnings": []})
        mock_call.side_effect = lambda name, **kw: fake_tools[name](**kw)
        db = FakeDB()
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
            f.write(b"<cfdi/>")
            xml_path = f.name
        try:
            result = process_file(xml_path, db=db)
            assert result["notificacion"]["status"] == "sent"
            assert result["erp"]["status"] == "rejected_invalid_cfdi"
        finally:
            os.unlink(xml_path)

    @patch("b2b_ai.api.security.detect_pii", return_value={})
    @patch("b2b_ai.services.pipeline.call_tool")
    def test_process_file_no_explicit_db(self, mock_call, mock_pii):
        fake_tools = _make_fake_tools()
        mock_call.side_effect = lambda name, **kw: fake_tools[name](**kw)
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
            f.write(b"<cfdi/>")
            xml_path = f.name
        try:
            result = process_file(xml_path)
            # When no db is passed, process_file creates a default Database()
            # so tenant_id will be assigned (not None)
            assert "tenant_id" in result
            # insertado depends on real DB; just verify the pipeline ran
            assert result["validacion"]["ok"] is True
            assert result["clasificacion"]["categoria"] == "gasto_operativo"
        finally:
            os.unlink(xml_path)


# ---------------------------------------------------------------------------
# process_batch
# ---------------------------------------------------------------------------

class TestProcessBatch:
    @patch("b2b_ai.api.security.detect_pii", return_value={})
    @patch("b2b_ai.services.pipeline.call_tool")
    @patch("b2b_ai.services.pipeline.EmailSender")
    def test_batch_empty_folder(self, mock_email, mock_call, mock_pii):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = process_batch(tmpdir)
            assert results == []

    @patch("b2b_ai.api.security.detect_pii", return_value={})
    @patch("b2b_ai.services.pipeline.call_tool")
    @patch("b2b_ai.services.pipeline.EmailSender")
    def test_batch_multiple_files(self, mock_email, mock_call, mock_pii):
        fake_tools = _make_fake_tools()
        mock_call.side_effect = lambda name, **kw: fake_tools[name](**kw)
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(3):
                with open(os.path.join(tmpdir, f"inv{i}.xml"), "w") as f:
                    f.write(f"<cfdi>{i}</cfdi>")
            results = process_batch(tmpdir)
            assert len(results) == 3
            for r in results:
                assert "archivo" in r

    @patch("b2b_ai.api.security.detect_pii", return_value={})
    @patch("b2b_ai.services.pipeline.call_tool")
    @patch("b2b_ai.services.pipeline.EmailSender")
    def test_batch_custom_pattern(self, mock_email, mock_call, mock_pii):
        fake_tools = _make_fake_tools()
        mock_call.side_effect = lambda name, **kw: fake_tools[name](**kw)
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "a.xml"), "w") as f:
                f.write("<cfdi>a</cfdi>")
            with open(os.path.join(tmpdir, "b.txt"), "w") as f:
                f.write("not xml")
            results = process_batch(tmpdir, pattern="*.xml")
            assert len(results) == 1


# ---------------------------------------------------------------------------
# summarize
# ---------------------------------------------------------------------------

class TestSummarize:
    def test_summarize_valid_results(self):
        results = [
            {"validacion": {"ok": True}, "insertado": True, "clasificacion": {"categoria": "gasto_operativo"}},
            {"validacion": {"ok": True}, "insertado": False, "clasificacion": {"categoria": "nomina"}},
            {"validacion": {"ok": False}, "insertado": False, "clasificacion": {"categoria": "desconocido"}},
        ]
        s = summarize(results)
        assert s["procesadas"] == 3
        assert s["validas"] == 2
        assert s["con_observaciones"] == 1
        assert s["insertadas"] == 1
        assert s["por_categoria"]["gasto_operativo"] == 1

    def test_summarize_empty(self):
        s = summarize([])
        assert s["procesadas"] == 0
        assert s["validas"] == 0
        assert s["insertadas"] == 0

    def test_summarize_all_valid(self):
        results = [
            {"validacion": {"ok": True}, "insertado": True, "clasificacion": {"categoria": "gasto_operativo"}},
            {"validacion": {"ok": True}, "insertado": True, "clasificacion": {"categoria": "gasto_operativo"}},
        ]
        s = summarize(results)
        assert s["validas"] == 2
        assert s["con_observaciones"] == 0
        assert s["por_categoria"]["gasto_operativo"] == 2

    def test_summarize_all_invalid(self):
        results = [
            {"validacion": {"ok": False}, "insertado": False, "clasificacion": {"categoria": "desconocido"}},
        ]
        s = summarize(results)
        assert s["validas"] == 0
        assert s["con_observaciones"] == 1


# ---------------------------------------------------------------------------
# Integration: process_file end-to-end
# ---------------------------------------------------------------------------

class TestPipelineIntegration:
    @patch("b2b_ai.api.security.detect_pii", return_value={"rfc_found": 2})
    @patch("b2b_ai.services.pipeline.call_tool")
    @patch("b2b_ai.services.pipeline.EmailSender")
    def test_full_pipeline_all_keys(self, mock_email, mock_call, mock_pii):
        """Verify process_file returns all expected keys."""
        fake_tools = _make_fake_tools()
        mock_call.side_effect = lambda name, **kw: fake_tools[name](**kw)
        db = FakeDB()
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
            f.write(b"<cfdi/>")
            xml_path = f.name
        try:
            result = process_file(xml_path, db=db)
            expected_keys = {"archivo", "datos", "validacion", "clasificacion", "anomalias",
                             "aprobacion", "erp", "invoice_id", "insertado", "tenant_id",
                             "notificacion", "pii", "efos_69b", "sat_status"}
            assert expected_keys == set(result.keys())
        finally:
            os.unlink(xml_path)

    @patch("b2b_ai.api.security.detect_pii", return_value={})
    @patch("b2b_ai.services.pipeline.call_tool")
    @patch("b2b_ai.services.pipeline.EmailSender")
    def test_pipeline_creates_tenant_if_none(self, mock_email, mock_call, mock_pii):
        fake_tools = _make_fake_tools()
        mock_call.side_effect = lambda name, **kw: fake_tools[name](**kw)
        db = FakeDB()
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
            f.write(b"<cfdi/>")
            xml_path = f.name
        try:
            result = process_file(xml_path, db=db)
            assert result["tenant_id"] is not None
            assert len(db.list_tenants()) == 1
        finally:
            os.unlink(xml_path)

    @patch("b2b_ai.api.security.detect_pii", return_value={})
    @patch("b2b_ai.services.pipeline.call_tool")
    @patch("b2b_ai.services.pipeline.EmailSender")
    def test_pipeline_with_existing_tenant(self, mock_email, mock_call, mock_pii):
        fake_tools = _make_fake_tools()
        mock_call.side_effect = lambda name, **kw: fake_tools[name](**kw)
        db = FakeDB()
        existing = db.create_tenant("Existing", "EX")
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
            f.write(b"<cfdi/>")
            xml_path = f.name
        try:
            result = process_file(xml_path, db=db, tenant_id=existing)
            assert result["tenant_id"] == existing
        finally:
            os.unlink(xml_path)
