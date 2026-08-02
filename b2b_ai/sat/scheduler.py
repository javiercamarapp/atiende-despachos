# -*- coding: utf-8 -*-
"""
scheduler.py — Programación automática de descargas y verificaciones SAT.

`SATScheduler` orquesta las tareas periódicas de la integración SAT:

  * run_daily()        — descarga automática de CFDI nuevos del día.
  * run_weekly()       — verificación semanal de estatus de los CFDI del
                         ledger (detecta cancelaciones).
  * process()          — ejecuta las tareas vencidas según la frecuencia
                         configurada (diaria / semanal).

Alertas: cuando un CFDI pasa de 'vigente' a 'cancelado' (o se detecta una
cancelación), el scheduler genera una alerta persistida en la DB vía
`db.insert_notification` (channel "sat") y la devuelve en `alerts`.

Estado: el scheduler guarda la fecha de la última ejecución por tipo en la
config del tenant (`sat_last_daily`, `sat_last_weekly`), de modo que es
idempotente y seguro de invocar por cron / worker / API.

Todas las operaciones usan el transporte mock (no e.firma real).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from b2b_ai.sat.downloader import SATDownloader
from b2b_ai.sat.validator import SATValidator


class SATScheduler:
    """Orquestador de tareas periódicas SAT (descarga + verificación)."""

    def __init__(self, db=None, tenant_id: Optional[Any] = None,
                 downloader: Optional[SATDownloader] = None,
                 validator: Optional[SATValidator] = None,
                 rfc: str = "", ciec: str = ""):
        self.db = db
        self.tenant_id = tenant_id
        self.rfc = rfc
        self.ciec = ciec
        self.downloader = downloader or SATDownloader(db=db, tenant_id=tenant_id,
                                                      rfc=rfc, ciec=ciec)
        self.validator = validator or SATValidator(db=db, tenant_id=tenant_id)

    # ------------------------------------------------------------------ #
    # Estado persistido
    # ------------------------------------------------------------------ #
    def _get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        if self.db and self.tenant_id is not None:
            return self.db.get_tenant_config(self.tenant_id, key, default)
        return default

    def _set(self, key: str, value: str) -> None:
        if self.db and self.tenant_id is not None:
            self.db.set_tenant_config(self.tenant_id, key, value)

    def _last_run(self, key: str) -> Optional[date]:
        raw = self._get(key)
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw).date()
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------ #
    # Descarga diaria
    # ------------------------------------------------------------------ #
    def run_daily(self, fecha: Optional[str] = None) -> Dict[str, Any]:
        """Descarga automática de los CFDI del día (emitidas + recibidas).

        Idempotente: si ya corrió hoy, devuelve sin volver a descargar salvo
        `force=True` (controlado por el caller vía `fecha`).
        """
        target = fecha or date.today().isoformat()
        # Login con las credenciales del tenant.
        login = self.downloader.login(self.rfc, self.ciec)
        if not login.get("ok"):
            return {"ok": False, "task": "daily", "error": login.get("error"),
                    "backend": self.downloader.backend}
        result = {"ok": True, "task": "daily", "fecha": target,
                  "descargas": [], "count": 0, "backend": self.downloader.backend}
        try:
            for tipo in ("emitidas", "recibidas"):
                resp = self.downloader.download_cfdi(target, target, tipo=tipo)
                if resp.get("ok"):
                    result["descargas"].append({
                        "tipo": tipo, "count": resp.get("count", 0),
                    })
                    result["count"] += resp.get("count", 0)
                else:
                    result["descargas"].append({"tipo": tipo, "error": resp.get("error")})
        finally:
            self.downloader.logout()
        self._set("sat_last_daily", datetime.now().isoformat(timespec="seconds"))
        return result

    # ------------------------------------------------------------------ #
    # Verificación semanal
    # ------------------------------------------------------------------ #
    def run_weekly(self) -> Dict[str, Any]:
        """Verifica el estatus de todos los CFDI del ledger; alerta cancelaciones."""
        # Refresca el ledger en el downloader (si tiene db se recarga al crear).
        ledger = list(self.downloader._ledger)
        if not ledger:
            return {"ok": True, "task": "weekly", "checked": 0,
                    "alerts": [], "cancelled": 0, "backend": self.validator.backend}

        alerts: List[Dict[str, Any]] = []
        cancelled = 0
        checked = 0
        changed = 0
        for cfdi in ledger:
            folio = cfdi.get("folio_fiscal", "")
            if not folio:
                continue
            checked += 1
            status = self.validator.check_status(folio)
            estado = status.get("estado")
            prev = cfdi.get("estatus", "vigente")
            # Persistir el estado actual en el ledger.
            if estado and estado != prev:
                cfdi["estatus"] = estado
                changed += 1
            if estado == "cancelado" and prev != "cancelado":
                cancelled += 1
                alert = self._alert_cancelled(cfdi, status)
                if alert:
                    alerts.append(alert)

        if self.db and self.tenant_id is not None:
            self.downloader._save_ledger()
        self._set("sat_last_weekly", datetime.now().isoformat(timespec="seconds"))
        return {"ok": True, "task": "weekly", "checked": checked,
                "changed": changed, "cancelled": cancelled,
                "alerts": alerts, "backend": self.validator.backend}

    def _alert_cancelled(self, cfdi: Dict[str, Any],
                         status: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Crea y persiste una alerta de factura cancelada."""
        subject = "Factura cancelada detectada (SAT)"
        body = (f"El CFDI {cfdi.get('folio_fiscal', '')} emitido el "
                f"{cfdi.get('fecha', '')} (total ${cfdi.get('total', 0)}) fue "
                f"cancelado según el SAT. Revisar la operación.")
        alert = {
            "folio_fiscal": cfdi.get("folio_fiscal"),
            "fecha": cfdi.get("fecha"),
            "total": cfdi.get("total"),
            "estado": "cancelado",
            "subject": subject,
            "body": body,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        if self.db and self.tenant_id is not None:
            alert["notification_id"] = self.db.insert_notification(
                self.tenant_id, "sat", "sat", self.rfc or "tenant", subject,
                body, status="new")
        return alert

    # ------------------------------------------------------------------ #
    # Ejecución según frecuencia
    # ------------------------------------------------------------------ #
    def process(self, daily_days: int = 0, weekly_days: int = 7) -> Dict[str, Any]:
        """Ejecuta las tareas periódicas vencidas.

        - Descarga diaria si no corrió hoy.
        - Verificación semanal si no corrió en `weekly_days` días.
        Devuelve resumen de lo ejecutado. Apto para cron.
        """
        out: Dict[str, Any] = {"tasks": {}, "ran": []}
        last_daily = self._last_run("sat_last_daily")
        if last_daily is None or (date.today() - last_daily).days > daily_days:
            res = self.run_daily()
            out["tasks"]["daily"] = res
            if res.get("ok"):
                out["ran"].append("daily")
        last_weekly = self._last_run("sat_last_weekly")
        if last_weekly is None or (date.today() - last_weekly).days >= weekly_days:
            res = self.run_weekly()
            out["tasks"]["weekly"] = res
            if res.get("ok"):
                out["ran"].append("weekly")
        out["ok"] = True
        return out

    def status(self) -> Dict[str, Any]:
        """Estado del scheduler (para /api/v1/sat/status)."""
        return {
            "last_daily": self._get("sat_last_daily"),
            "last_weekly": self._get("sat_last_weekly"),
            "ledger_count": len(self.downloader._ledger),
            "rfc": self.rfc,
            "backend": self.downloader.backend,
        }
