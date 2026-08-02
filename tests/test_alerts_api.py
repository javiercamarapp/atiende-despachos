# -*- coding: utf-8 -*-
"""Tests for the alerts API: list (with date range), deadlines, acknowledge,
and stats."""
import json

import pytest
from fastapi.testclient import TestClient

from b2b_ai.db.db import Database
from b2b_ai.api.app import create_app

API_KEY = "alerts-api-test-key"


@pytest.fixture
def client(tmp_path):
    db = Database(str(tmp_path / "alerts_api.db"))
    db.create_tenant("Alerts API Tenant")
    db.create_api_key(1, "alerts-api", API_KEY)
    app = create_app(db)
    return TestClient(app), db


def _auth():
    return {"X-API-Key": API_KEY}


class TestListAlerts:
    def test_list_empty(self, client):
        c, _ = client
        r = c.get("/api/v1/alerts", headers=_auth())
        assert r.status_code == 200
        assert r.json()["count"] == 0

    def test_list_filters_severity(self, client):
        c, _ = client
        # Create a critical alert via the evaluate endpoint
        c.post("/api/v1/alerts/evaluate", json={
            "data": {"total": 75000, "entity_type": "invoice", "entity_id": "INV-1"},
            "rules": [{
                "name": "High amount", "type": "threshold",
                "threshold_value": 50000, "field_path": "total",
                "severity": "critical",
            }],
        }, headers=_auth())
        r = c.get("/api/v1/alerts", params={"severity": "critical"}, headers=_auth())
        assert r.status_code == 200
        assert r.json()["count"] == 1
        assert r.json()["alerts"][0]["severity"] == "critical"

    def test_list_invalid_severity_422(self, client):
        c, _ = client
        r = c.get("/api/v1/alerts", params={"severity": "bogus"}, headers=_auth())
        assert r.status_code == 422

    def test_list_date_range(self, client):
        c, _ = client
        c.post("/api/v1/alerts/evaluate", json={
            "data": {"total": 75000, "entity_type": "invoice", "entity_id": "INV-1"},
            "rules": [{
                "name": "High amount", "type": "threshold",
                "threshold_value": 50000, "field_path": "total",
                "severity": "warning",
            }],
        }, headers=_auth())
        # created_at is today; a future date range should exclude it
        r = c.get("/api/v1/alerts", params={
            "date_from": "2030-01-01T00:00:00Z",
            "date_to": "2030-12-31T23:59:59Z",
        }, headers=_auth())
        assert r.json()["count"] == 0
        # an inclusive today range should include it
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        r2 = c.get("/api/v1/alerts", params={
            "date_from": "2000-01-01T00:00:00Z",
            "date_to": today,
        }, headers=_auth())
        assert r2.json()["count"] == 1


class TestDeadlines:
    def test_deadlines_default(self, client):
        c, _ = client
        r = c.get("/api/v1/alerts/deadlines", headers=_auth())
        assert r.status_code == 200
        data = r.json()
        assert "deadlines" in data
        assert data["days"] == 30

    def test_deadlines_with_companies(self, client):
        c, _ = client
        companies = json.dumps([{"rfc": "ABC123456XYZ", "name": "Empresa Test"}])
        r = c.get("/api/v1/alerts/deadlines", params={
            "days": 120, "companies": companies,
        }, headers=_auth())
        assert r.status_code == 200
        data = r.json()
        assert data["count"] > 0
        dl = data["deadlines"][0]
        assert "obligation_code" in dl
        assert "due_date" in dl
        assert dl["company_rfc"] == "ABC123456XYZ"

    def test_deadlines_invalid_companies_422(self, client):
        c, _ = client
        r = c.get("/api/v1/alerts/deadlines", params={"companies": "{not-json"},
                                                     headers=_auth())
        assert r.status_code == 422


class TestAcknowledge:
    def test_acknowledge_alert(self, client):
        c, _ = client
        c.post("/api/v1/alerts/evaluate", json={
            "data": {"total": 75000, "entity_type": "invoice", "entity_id": "INV-1"},
            "rules": [{
                "name": "High amount", "type": "threshold",
                "threshold_value": 50000, "field_path": "total",
            }],
        }, headers=_auth())
        listed = c.get("/api/v1/alerts", headers=_auth()).json()["alerts"]
        alert_id = listed[0]["id"]
        r = c.post(f"/api/v1/alerts/{alert_id}/acknowledge",
                   json={"user": "test-user"}, headers=_auth())
        assert r.status_code == 200
        assert r.json()["alert"]["status"] == "acknowledged"
        assert r.json()["alert"]["acknowledged_by"] == "test-user"

    def test_acknowledge_missing_404(self, client):
        c, _ = client
        r = c.post("/api/v1/alerts/nonexistent/acknowledge", json={},
                   headers=_auth())
        assert r.status_code == 404


class TestStats:
    def test_stats_shape(self, client):
        c, _ = client
        c.post("/api/v1/alerts/evaluate", json={
            "data": {"total": 75000, "entity_type": "invoice", "entity_id": "INV-1"},
            "rules": [{
                "name": "High amount", "type": "threshold",
                "threshold_value": 50000, "field_path": "total",
                "severity": "critical",
            }],
        }, headers=_auth())
        r = c.get("/api/v1/alerts/stats", headers=_auth())
        assert r.status_code == 200
        data = r.json()
        assert "total" in data
        assert "by_severity" in data
        assert data["by_severity"].get("critical", 0) == 1
