# -*- coding: utf-8 -*-
"""
models.py — Pydantic schemas for the Admin Dashboard API.

All models use pydantic v2 (BaseModel) with Field for descriptions.
These are response schemas — the service layer populates them from
raw DB data.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ClientSummary(BaseModel):
    """Summary of a single client (tenant) for the admin dashboard."""

    id: int = Field(..., description="Tenant ID")
    name: str = Field(..., description="Client / despacho name")
    rfc: str = Field(default="", description="RFC fiscal del cliente")
    active: bool = Field(default=True, description="Whether the client is active")
    invoice_count: int = Field(default=0, description="Total invoices processed")
    monto_total: float = Field(default=0.0, description="Total MXN processed")
    api_calls: int = Field(default=0, description="Total API calls")
    created_at: Optional[str] = Field(default=None, description="Registration date")
    last_activity: Optional[str] = Field(default=None, description="Last activity timestamp")


class DailyMetric(BaseModel):
    """A single day's usage metric."""

    date: str = Field(..., description="Date (YYYY-MM-DD)")
    count: int = Field(default=0, description="Number of items (invoices, calls, etc.)")
    total_amount: float = Field(default=0.0, description="Total amount for the day")


class SystemHealth(BaseModel):
    """System health overview for the admin dashboard."""

    status: str = Field(default="healthy", description="Overall status: healthy/degraded/degraded")
    api_uptime_pct: float = Field(default=100.0, description="API uptime percentage (last 24h)")
    total_invoices: int = Field(default=0, description="Total invoices in DB")
    total_tenants: int = Field(default=0, description="Total tenants registered")
    db_size_mb: float = Field(default=0.0, description="Database size in MB")
    queue_depth: int = Field(default=0, description="Pending items in processing queue")
    error_rate_24h: float = Field(default=0.0, description="Error rate in last 24 hours (0-1)")
    last_check: str = Field(default="", description="Timestamp of last health check")
    details: dict = Field(default_factory=dict, description="Additional health details")


class UsageMetrics(BaseModel):
    """Usage metrics for the admin dashboard."""

    total_api_calls: int = Field(default=0, description="Total API calls across all tenants")
    total_invoices_processed: int = Field(default=0, description="Total invoices processed")
    cfdi_daily: List[DailyMetric] = Field(default_factory=list, description="CFDIs processed per day (last 30d)")
    avg_processing_time_sec: float = Field(default=0.0, description="Average invoice processing time (seconds)")
    llm_calls: int = Field(default=0, description="Total LLM calls made")
    error_rate: float = Field(default=0.0, description="Current error rate (0-1)")
    period_start: str = Field(default="", description="Metrics period start date")
    period_end: str = Field(default="", description="Metrics period end date")


class RevenueReport(BaseModel):
    """Revenue report for the admin dashboard."""

    mrr: float = Field(default=0.0, description="Monthly Recurring Revenue (MXN)")
    arr: float = Field(default=0.0, description="Annual Recurring Revenue (MXN)")
    total_revenue: float = Field(default=0.0, description="Total revenue to date (MXN)")
    active_subscriptions: int = Field(default=0, description="Number of active subscriptions")
    churn_rate: float = Field(default=0.0, description="Monthly churn rate (0-1)")
    avg_revenue_per_client: float = Field(default=0.0, description="Average revenue per active client (MXN)")
    plan_breakdown: dict = Field(default_factory=dict, description="Revenue breakdown by plan")
    period_start: str = Field(default="", description="Report period start")
    period_end: str = Field(default="", description="Report period end")


class DashboardOverview(BaseModel):
    """Top-level overview for the admin dashboard."""

    total_clients: int = Field(default=0, description="Total registered clients")
    active_clients: int = Field(default=0, description="Active clients (with invoices in last 30d)")
    revenue_mrr: float = Field(default=0.0, description="Monthly Recurring Revenue (MXN)")
    cfdi_count_month: int = Field(default=0, description="CFDIs processed this month")
    total_invoices: int = Field(default=0, description="All-time invoice count")
    total_revenue: float = Field(default=0.0, description="All-time revenue (MXN)")
    system_status: str = Field(default="healthy", description="System status")
    last_updated: str = Field(default="", description="Timestamp of this snapshot")
