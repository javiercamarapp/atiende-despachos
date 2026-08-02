# -*- coding: utf-8 -*-
"""
anomaly_detector.py — Transaction anomaly detection for Likida AI Enterprise.

Detects common anomalies in CFDI / invoice transactions:
  - Duplicate CFDI (same UUID, or same emisor+folio+amount within a window)
  - Amounts outside the historical range (z-score / percentile)
  - Invoices not stamped (timbre) within >24h
  - Sequential gaps in UUIDs / folio series

Severity model: critical / warning / info.
Thresholds are configurable per tenant via `AnomalyThresholds`.

This module is ADDITIVE. It depends only on .models for the canonical
Alert model and severity enums. No existing module is modified.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from statistics import mean, stdev
from typing import Dict, List, Optional, Sequence

from b2b_ai.features.alertas.models import Alert, AlertSeverity, AlertType


# ---------------------------------------------------------------------------
# Thresholds (per tenant)
# ---------------------------------------------------------------------------

@dataclass
class AnomalyThresholds:
    """Configurable detection thresholds.

    `dup_window_hours`      : CFDI considered duplicate if within this window.
    `range_stdev_mult`      : amount flagged out-of-range if beyond this many
                              standard deviations from the historical mean.
    `range_min_history`     : minimum historical samples before range checks.
    `max_stamp_hours`       : invoices not stamped within this many hours.
    `uuid_pattern`          : regex matching a sequential UUID/series fragment
                              (the trailing digits used for gap detection).
    """
    dup_window_hours: int = 72
    range_stdev_mult: float = 2.5
    range_min_history: int = 3
    max_stamp_hours: int = 24
    uuid_tail_digits: int = 6

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "AnomalyThresholds":
        if not data:
            return cls()
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in allowed})


# ---------------------------------------------------------------------------
# Anomaly result / alert builders
# ---------------------------------------------------------------------------

def _anomaly_alert_id(detector: str, entity: str, kind: str) -> str:
    raw = f"anomaly:{detector}:{entity}:{kind}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# AnomalyDetector
# ---------------------------------------------------------------------------

class AnomalyDetector:
    """Detect anomalies in a batch of CFDI / invoice transactions.

    Usage
    -----
        detector = AnomalyDetector()
        alerts = detector.detect(invoices, tenant_id=1)
    """

    def __init__(
        self,
        thresholds: Optional[AnomalyThresholds] = None,
        tenant_thresholds: Optional[Dict[int, AnomalyThresholds]] = None,
        now: Optional[datetime] = None,
    ):
        self.default_thresholds = thresholds or AnomalyThresholds()
        self.tenant_thresholds = tenant_thresholds or {}
        self._now = now or datetime.now(timezone.utc)

    # -- Config -----------------------------------------------------------

    def thresholds_for(self, tenant_id: Optional[int]) -> AnomalyThresholds:
        if tenant_id is not None and tenant_id in self.tenant_thresholds:
            return self.tenant_thresholds[tenant_id]
        return self.default_thresholds

    # -- Main entry point ---------------------------------------------------

    def detect(
        self,
        invoices: Sequence[dict],
        historical_amounts: Optional[Sequence[float]] = None,
        tenant_id: Optional[int] = None,
    ) -> List[Alert]:
        """Run all detectors over a batch of invoices.

        Each invoice dict may contain:
            uuid / folio_fiscal / folio  : CFDI UUID or folio
            emisor_rfc / rfc_emisor      : issuer RFC
            receptor_rfc / rfc_receptor  : recipient RFC
            total / monto / amount       : invoice total
            totales_total                : (CONTPAQi style) invoice total
            fecha / fecha_emision        : issue date (ISO)
            fecha_timbrado               : stamp date (ISO)
            estatus / status             : 'timbrado' | 'pendiente' | ...
        """
        thr = self.thresholds_for(tenant_id)
        items = list(invoices)
        alerts: List[Alert] = []

        alerts.extend(self.detect_duplicates(items, tenant_id, thr))
        alerts.extend(
            self.detect_out_of_range(items, historical_amounts, tenant_id, thr)
        )
        alerts.extend(self.detect_unstamped(items, tenant_id, thr))
        alerts.extend(self.detect_uuid_gaps(items, tenant_id, thr))
        return alerts

    # -- 1. Duplicate CFDI ---------------------------------------------------

    def detect_duplicates(
        self,
        invoices: Sequence[dict],
        tenant_id: Optional[int] = None,
        thr: Optional[AnomalyThresholds] = None,
    ) -> List[Alert]:
        thr = thr or self.thresholds_for(tenant_id)
        window = timedelta(hours=thr.dup_window_hours)
        alerts: List[Alert] = []
        seen: Dict[str, dict] = {}

        for inv in invoices:
            uuid = self._uuid(inv)
            if not uuid:
                continue
            key = uuid
            if key in seen:
                first = seen[key]
                ts1 = self._parse_date(self._issue_date(first))
                ts2 = self._parse_date(self._issue_date(inv))
                if ts1 and ts2 and abs(ts2 - ts1) <= window:
                    alerts.append(self._alert(
                        "duplicate_uuid", inv, tenant_id,
                        AlertSeverity.CRITICAL,
                        f"CFDI duplicado: UUID {uuid} ya registrado "
                        f"({self._detail(inv)}).",
                        kind="duplicate",
                    ))
            else:
                seen[key] = inv

        # Also detect logical duplicates: same emisor+receptor+amount+window
        logical: Dict[tuple, dict] = {}
        for inv in invoices:
            uuid = self._uuid(inv)
            emisor = self._emisor(inv)
            total = self._amount(inv)
            if not emisor or total is None:
                continue
            lkey = (emisor, self._receptor(inv), round(total, 2))
            ts = self._parse_date(self._issue_date(inv))
            if lkey in logical and ts:
                prev = logical[lkey]
                pts = self._parse_date(self._issue_date(prev))
                if pts and abs(ts - pts) <= window:
                    alerts.append(self._alert(
                        "duplicate_logical", inv, tenant_id,
                        AlertSeverity.WARNING,
                        f"Factura probablemente duplicada: mismo emisor, "
                        f"receptor y monto ({total:,.2f}) dentro de "
                        f"{thr.dup_window_hours}h.",
                        kind="duplicate",
                    ))
            else:
                logical[lkey] = inv
        return alerts

    # -- 2. Amount out of historical range ------------------------------------

    def detect_out_of_range(
        self,
        invoices: Sequence[dict],
        historical_amounts: Optional[Sequence[float]] = None,
        tenant_id: Optional[int] = None,
        thr: Optional[AnomalyThresholds] = None,
    ) -> List[Alert]:
        thr = thr or self.thresholds_for(tenant_id)
        hist = [float(x) for x in (historical_amounts or []) if x is not None]
        if len(hist) < thr.range_min_history:
            return []

        mu = mean(hist)
        try:
            sd = stdev(hist)
        except ValueError:
            sd = 0.0
        if sd == 0:
            return []

        alerts: List[Alert] = []
        for inv in invoices:
            total = self._amount(inv)
            if total is None:
                continue
            z = (total - mu) / sd
            if abs(z) >= thr.range_stdev_mult:
                sev = (
                    AlertSeverity.CRITICAL if abs(z) >= thr.range_stdev_mult * 1.6
                    else AlertSeverity.WARNING
                )
                alerts.append(self._alert(
                    "amount_out_of_range", inv, tenant_id, sev,
                    f"Monto fuera de rango histórico: {total:,.2f} "
                    f"(z={z:+.2f}, media={mu:,.2f}, ±{thr.range_stdev_mult}σ).",
                    kind="amount",
                ))
        return alerts

    # -- 3. Unstamped invoices > max hours ------------------------------------

    def detect_unstamped(
        self,
        invoices: Sequence[dict],
        tenant_id: Optional[int] = None,
        thr: Optional[AnomalyThresholds] = None,
    ) -> List[Alert]:
        thr = thr or self.thresholds_for(tenant_id)
        cutoff = timedelta(hours=thr.max_stamp_hours)
        alerts: List[Alert] = []
        now = self._now

        for inv in invoices:
            if self._is_stamped(inv):
                continue
            issued = self._parse_date(self._issue_date(inv))
            if issued is None:
                continue
            elapsed = now - issued
            if elapsed > cutoff:
                hours = int(elapsed.total_seconds() // 3600)
                sev = (
                    AlertSeverity.CRITICAL if elapsed > cutoff * 3
                    else AlertSeverity.WARNING
                )
                alerts.append(self._alert(
                    "uninvoiced_stamp", inv, tenant_id, sev,
                    f"Factura sin timbrar por >{thr.max_stamp_hours}h "
                    f"(hace {hours}h): {self._detail(inv)}.",
                    kind="stamp",
                ))
        return alerts

    # -- 4. Sequential gaps in UUID / folio tail --------------------------------

    def detect_uuid_gaps(
        self,
        invoices: Sequence[dict],
        tenant_id: Optional[int] = None,
        thr: Optional[AnomalyThresholds] = None,
    ) -> List[Alert]:
        thr = thr or self.thresholds_for(tenant_id)
        # Group by emisor + (fixed prefix) + date, then look for numeric gaps.
        groups: Dict[tuple, List[int]] = defaultdict(list)
        for inv in invoices:
            uuid = self._uuid(inv)
            emisor = self._emisor(inv) or "?"
            if not uuid:
                continue
            tail = self._numeric_tail(uuid, thr.uuid_tail_digits)
            if tail is None:
                continue
            prefix = uuid[:-thr.uuid_tail_digits]
            key = (emisor, prefix)
            groups[key].append(tail)

        alerts: List[Alert] = []
        for (emisor, prefix), seq in groups.items():
            seq = sorted(set(seq))
            if len(seq) < 2:
                continue
            for i in range(1, len(seq)):
                gap = seq[i] - seq[i - 1]
                if gap > 1:
                    sev = (
                        AlertSeverity.CRITICAL if gap > 10
                        else AlertSeverity.WARNING
                    )
                    alerts.append(self._alert(
                        "uuid_gap", {}, tenant_id, sev,
                        f"Salto secuencial en UUIDs de {emisor}: "
                        f"{seq[i-1]:0{thr.uuid_tail_digits}d} → "
                        f"{seq[i]:0{thr.uuid_tail_digits}d} "
                        f"(gap de {gap}).",
                        kind="gap",
                        entity=self._entity_id_for_gap(emisor, prefix),
                    ))
        return alerts

    # -- Alert builder ---------------------------------------------------------

    def _alert(
        self,
        detector: str,
        inv: dict,
        tenant_id: Optional[int],
        severity: AlertSeverity,
        message: str,
        kind: str = "anomaly",
        entity: Optional[str] = None,
    ) -> Alert:
        entity_id = entity or self._detail(inv) or "unknown"
        return Alert(
            id=_anomaly_alert_id(detector, entity_id, kind),
            rule_id=f"anomaly:{detector}",
            rule_name=detector,
            type=AlertType.ANOMALY,
            severity=severity,
            status="active",
            title=message.split(":")[0],
            message=message,
            entity_type="invoice",
            entity_id=entity_id,
            tenant_id=tenant_id,
            metadata={
                "detector": detector,
                "invoice": self._entity_id_for_gap(
                    self._emisor(inv) or "", self._uuid(inv) or ""),
            },
        )

    # -- Field extractors (tolerant of several naming conventions) ------------

    @staticmethod
    def _uuid(inv: dict) -> Optional[str]:
        for k in ("uuid", "folio_fiscal", "folio", "UUID"):
            v = inv.get(k)
            if v:
                return str(v)
        return None

    @staticmethod
    def _emisor(inv: dict) -> Optional[str]:
        for k in ("emisor_rfc", "rfc_emisor", "emisor"):
            v = inv.get(k)
            if v:
                return str(v)
        return None

    @staticmethod
    def _receptor(inv: dict) -> Optional[str]:
        for k in ("receptor_rfc", "rfc_receptor", "receptor"):
            v = inv.get(k)
            if v:
                return str(v)
        return None

    @staticmethod
    def _amount(inv: dict) -> Optional[float]:
        for k in ("total", "monto", "amount", "totales_total"):
            v = inv.get(k)
            if v is not None:
                try:
                    return float(v)
                except (ValueError, TypeError):
                    continue
        return None

    @staticmethod
    def _issue_date(inv: dict) -> Optional[str]:
        for k in ("fecha", "fecha_emision", "fecha_emisión", "fecha_timbrado"):
            v = inv.get(k)
            if v:
                return str(v)
        return None

    @staticmethod
    def _is_stamped(inv: dict) -> bool:
        for k in ("estatus", "status", "timbrado"):
            v = inv.get(k)
            if v is None:
                continue
            if isinstance(v, str) and v.lower() in ("timbrado", "stamped", "vigente"):
                return True
            if isinstance(v, bool):
                return v
        # If a stamp date exists, treat as stamped
        if inv.get("fecha_timbrado"):
            return True
        return False

    @staticmethod
    def _parse_date(s: Optional[str]) -> Optional[datetime]:
        if not s:
            return None
        from dateutil import parser as _dup
        try:
            dt = _dup.parse(str(s))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError, OverflowError):
            return None

    @staticmethod
    def _numeric_tail(uuid: str, digits: int) -> Optional[int]:
        tail = uuid[-digits:]
        if not tail.isdigit():
            return None
        return int(tail)

    @staticmethod
    def _entity_id_for_gap(emisor: str, prefix: str) -> str:
        raw = f"{emisor}:{prefix}".strip(":")
        return raw or "series"

    def _detail(self, inv: dict) -> str:
        return self._uuid(inv) or self._emisor(inv) or str(inv)[:24]
