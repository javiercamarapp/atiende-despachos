# -*- coding: utf-8 -*-
"""
routes.py — FastAPI router for the Intelligent Alerts Engine API.

Endpoints:
    GET  /api/v1/alerts              — List alerts (with filters)
    GET  /api/v1/alerts/{id}         — Get alert detail
    POST /api/v1/alerts/{id}/acknowledge  — Acknowledge an alert
    POST /api/v1/alerts/{id}/dismiss      — Dismiss an alert
    GET  /api/v1/alerts/rules        — List alert rules
    POST /api/v1/alerts/rules        — Create an alert rule
    GET  /api/v1/alerts/stats        — Alert statistics by severity/type
    DELETE /api/v1/alerts/{id}       — Delete an alert
    GET  /api/v1/alerts/{id}/history — Alert history / audit trail
    POST /api/v1/alerts/evaluate     — Evaluate data against rules

The router is built with `build_alertas_router(db, require_api_key)`
following the project pattern.
"""
from __future__ import annotations

from typing import Any, List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from b2b_ai.features.alertas.models import (
    Alert,
    AlertConfig,
    AlertHistory,
    AlertRule,
    AlertSeverity,
    AlertStatus,
    AlertType,
)
from b2b_ai.features.alertas.engine import AlertEngine, evaluate_rules
from b2b_ai.features.alertas.store import AlertStore


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class AcknowledgeRequest(BaseModel):
    """Request to acknowledge an alert."""
    user: Optional[str] = Field(default=None, description="User acknowledging the alert")


class DismissRequest(BaseModel):
    """Request to dismiss an alert."""
    user: Optional[str] = Field(default=None, description="User dismissing the alert")


class CreateRuleRequest(BaseModel):
    """Request to create an alert rule."""
    name: str = Field(..., description="Rule name")
    type: str = Field(..., description="Rule type: threshold, anomaly, due_date, volume, reconciliation, custom")
    enabled: bool = Field(default=True, description="Whether the rule is active")
    condition: str = Field(default="gt", description="Comparison operator: gt, gte, lt, lte, eq, neq, between")
    threshold_value: Optional[float] = Field(default=None, description="Threshold value")
    threshold_value_max: Optional[float] = Field(default=None, description="Upper bound for between")
    multiplier: Optional[float] = Field(default=None, description="Multiplier for anomaly rules")
    days_before_due: Optional[int] = Field(default=None, description="Days before due for due_date rules")
    volume_limit: Optional[int] = Field(default=None, description="Limit for volume rules")
    field_path: Optional[str] = Field(default=None, description="Dot-separated field path")
    severity: str = Field(default="warning", description="Severity: info, warning, critical")
    message_template: str = Field(default="", description="Message template")
    tenant_id: Optional[int] = Field(default=None, description="Tenant scope")
    metadata: dict = Field(default_factory=dict, description="Extra parameters")


class EvaluateRequest(BaseModel):
    """Request to evaluate data against rules."""
    data: dict = Field(..., description="Data to evaluate")
    rules: List[dict] = Field(default_factory=list, description="Rules to evaluate against")
    historical_values: Optional[dict] = Field(default=None, description="Historical values for anomaly detection")
    reference_date: Optional[str] = Field(default=None, description="Reference date for due_date rules")
    tenant_id: Optional[int] = Field(default=None, description="Tenant scope")


# ---------------------------------------------------------------------------
# Router builder
# ---------------------------------------------------------------------------

def build_alertas_router(
    db: Any = None,
    require_api_key: Any = None,
    store: Optional[AlertStore] = None,
) -> APIRouter:
    """Construct the alerts API router.

    Parameters
    ----------
    db : Database instance (unused for now; alerts are in-memory).
    require_api_key : FastAPI dependency for auth.
    store : AlertStore instance (for testing; defaults to shared instance).
    """
    auth_dep = require_api_key or (lambda: None)
    shared_store = store or AlertStore()
    engine = AlertEngine(store=shared_store)

    router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])

    def _scope(auth_info) -> Optional[int]:
        return auth_info.get("tenant_id") if auth_info else None

    # -- List alerts --------------------------------------------------------
    @router.get(
        "",
        summary="List alerts with optional filters.",
        response_model=None,
    )
    def list_alerts(
        auth_info: dict = Depends(auth_dep),
        severity: Optional[str] = Query(default=None, description="Filter by severity"),
        type: Optional[str] = Query(default=None, description="Filter by type"),
        status: Optional[str] = Query(default=None, description="Filter by status"),
        limit: int = Query(default=100, ge=1, le=1000, description="Max results"),
        offset: int = Query(default=0, ge=0, description="Offset for pagination"),
    ) -> dict:
        tenant = _scope(auth_info)
        sev = AlertSeverity(severity) if severity else None
        typ = AlertType(type) if type else None
        stat = AlertStatus(status) if status else None
        alerts = shared_store.list_alerts(
            tenant_id=tenant,
            severity=sev,
            alert_type=typ,
            status=stat,
            limit=limit,
            offset=offset,
        )
        return {
            "count": len(alerts),
            "tenant_id": tenant,
            "alerts": [a.model_dump() for a in alerts],
        }

    # -- Get alert detail ---------------------------------------------------
    @router.get(
        "/{alert_id}",
        summary="Get alert detail by ID.",
        response_model=None,
    )
    def get_alert(
        alert_id: str,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        alert = shared_store.get_alert(alert_id)
        if alert is None:
            raise HTTPException(status_code=404, detail="Alert not found.")
        return {"alert": alert.model_dump()}

    # -- Acknowledge --------------------------------------------------------
    @router.post(
        "/{alert_id}/acknowledge",
        summary="Acknowledge an alert.",
        response_model=None,
    )
    def acknowledge_alert(
        alert_id: str,
        req: AcknowledgeRequest = AcknowledgeRequest(),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        result = shared_store.acknowledge_alert(alert_id, user=req.user)
        if result is None:
            raise HTTPException(status_code=404, detail="Alert not found.")
        return {"ok": True, "alert": result.model_dump()}

    # -- Dismiss ------------------------------------------------------------
    @router.post(
        "/{alert_id}/dismiss",
        summary="Dismiss an alert.",
        response_model=None,
    )
    def dismiss_alert(
        alert_id: str,
        req: DismissRequest = DismissRequest(),
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        result = shared_store.dismiss_alert(alert_id, user=req.user)
        if result is None:
            raise HTTPException(status_code=404, detail="Alert not found.")
        return {"ok": True, "alert": result.model_dump()}

    # -- Delete -------------------------------------------------------------
    @router.delete(
        "/{alert_id}",
        summary="Permanently delete an alert.",
        response_model=None,
    )
    def delete_alert(
        alert_id: str,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        deleted = shared_store.delete_alert(alert_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Alert not found.")
        return {"ok": True, "deleted": alert_id}

    # -- Alert history / audit trail ----------------------------------------
    @router.get(
        "/{alert_id}/history",
        summary="Get history / audit trail for an alert.",
        response_model=None,
    )
    def alert_history(
        alert_id: str,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        alert = shared_store.get_alert(alert_id)
        if alert is None:
            raise HTTPException(status_code=404, detail="Alert not found.")
        history = shared_store.get_history(alert_id)
        return {
            "alert_id": alert_id,
            "count": len(history),
            "history": [h.model_dump() for h in history],
        }

    # -- List rules ---------------------------------------------------------
    @router.get(
        "/rules",
        summary="List alert rules.",
        response_model=None,
    )
    def list_rules(
        auth_info: dict = Depends(auth_dep),
        enabled_only: bool = Query(default=False, description="Only enabled rules"),
    ) -> dict:
        tenant = _scope(auth_info)
        rules = shared_store.list_rules(tenant_id=tenant, enabled_only=enabled_only)
        return {"count": len(rules), "rules": rules}

    # -- Create rule --------------------------------------------------------
    @router.post(
        "/rules",
        summary="Create an alert rule.",
        response_model=None,
    )
    def create_rule(
        req: CreateRuleRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        import uuid
        rule_id = str(uuid.uuid4())[:8]
        now = datetime.utcnow().isoformat() + "Z"
        rule_data = {
            "id": rule_id,
            "name": req.name,
            "type": req.type,
            "enabled": req.enabled,
            "condition": req.condition,
            "threshold_value": req.threshold_value,
            "threshold_value_max": req.threshold_value_max,
            "multiplier": req.multiplier,
            "days_before_due": req.days_before_due,
            "volume_limit": req.volume_limit,
            "field_path": req.field_path,
            "severity": req.severity,
            "message_template": req.message_template,
            "tenant_id": req.tenant_id,
            "metadata": req.metadata,
            "created_at": now,
        }
        shared_store.save_rule(rule_id, rule_data)
        return {"ok": True, "rule": rule_data}

    # -- Stats --------------------------------------------------------------
    @router.get(
        "/stats",
        summary="Alert statistics by severity and type.",
        response_model=None,
    )
    def alert_stats(
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        tenant = _scope(auth_info)
        return shared_store.stats(tenant_id=tenant)

    # -- Evaluate data against rules ----------------------------------------
    @router.post(
        "/evaluate",
        summary="Evaluate data against rules and return new alerts.",
        response_model=None,
    )
    def evaluate_data(
        req: EvaluateRequest,
        auth_info: dict = Depends(auth_dep),
    ) -> dict:
        # Convert rule dicts to AlertRule objects
        alert_rules: List[AlertRule] = []
        for r in req.rules:
            try:
                ar = AlertRule(**r)
                alert_rules.append(ar)
            except Exception:
                continue

        new_alerts = engine.evaluate(
            data=req.data,
            rules=alert_rules,
            historical_values=req.historical_values,
            reference_date=req.reference_date,
            tenant_id=req.tenant_id or _scope(auth_info),
        )
        return {
            "count": len(new_alerts),
            "alerts": [a.model_dump() for a in new_alerts],
        }

    return router
