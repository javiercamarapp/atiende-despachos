# -*- coding: utf-8 -*-
"""
checklist.py — Verificación del onboarding y score 0-100.

Un onboarding NO se considera completo por haber llenado los 7 pasos: hay que
verificar contra fuentes de verdad (tenant_config, tabla users, tabla invoices)
que cada hito real se cumplió. Este módulo hace esa verificación y calcula un
score de readiness 0-100.

Chequeos:
    1. company_info     — datos de empresa completos (paso 1).
    2. erp_connected    — ERP conectado (paso 3 con credenciales o CSV).
    3. first_invoice    — primera factura procesada en la DB (paso 5 respaldado
                          por count_invoices del tenant).
    4. team_member      — al menos un miembro de equipo agregado (usuarios del
                          tenant en la DB).

Cada chequeo pesa 25 pts → score 0-100. El detalle indica QUÉ falta y cómo
resolverlo, para que la UI del wizard lo muestre.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from b2b_ai.db.tenants import TenantManager

# Pesos de cada chequeo sobre el score 0-100.
CHECK_WEIGHTS: Dict[str, int] = {
    "company_info": 25,
    "erp_connected": 25,
    "first_invoice": 25,
    "team_member": 25,
}


class OnboardingChecklist:
    """Verifica los hitos reales de onboarding y calcula el score 0-100."""

    def __init__(self, db=None, tenant_id: Optional[int] = None):
        self._tm = TenantManager(db)
        self.db = self._tm.db
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------ #
    # Lectura de datos
    # ------------------------------------------------------------------ #
    def _step(self, step: int) -> Dict[str, Any]:
        raw = self.db.get_tenant_config(self.tenant_id, f"onboarding:step:{step}")
        if not raw:
            return {}
        try:
            val = json.loads(raw)
            return val if isinstance(val, dict) else {}
        except (TypeError, ValueError):
            return {}

    def _users(self) -> List[Dict[str, Any]]:
        rows = self.db.conn.execute(
            "SELECT id, name, email FROM users WHERE tenant_id=?",
            (self.tenant_id,)).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Chequeos individuales
    # ------------------------------------------------------------------ #
    def check_company_info(self) -> Dict[str, Any]:
        s1 = self._step(1)
        ok = bool(s1.get("name") and s1.get("rfc") and s1.get("industry"))
        detail = ""
        if not ok:
            missing = [f for f in ("name", "rfc", "industry") if not s1.get(f)]
            detail = "Falta: " + ", ".join(missing)
        return {"check": "company_info", "label": "Datos de la empresa",
                "ok": ok, "detail": detail}

    def check_erp_connected(self) -> Dict[str, Any]:
        s3 = self._step(3)
        mode = s3.get("mode")
        ok = False
        if mode == "credentials":
            creds = s3.get("credentials") or {}
            ok = bool(creds.get("host") and creds.get("user"))
        elif mode == "csv":
            ok = bool(s3.get("csv_file") or s3.get("csv_path"))
        detail = ""
        if not ok:
            detail = ("Completa el paso 3 (ERP conectado por credenciales o "
                      "CSV).")
        return {"check": "erp_connected", "label": "ERP conectado",
                "ok": ok, "detail": detail}

    def check_first_invoice(self) -> Dict[str, Any]:
        # Respaldamos el paso 5 con el conteo real de facturas del tenant.
        count = self.db.count_invoices(tenant_id=self.tenant_id) or 0
        s5 = self._step(5)
        ok = count > 0 and bool(s5.get("invoice_id"))
        detail = ""
        if not ok:
            detail = ("Procesa la primera factura (paso 5); se esperan "
                      "facturas en la DB del tenant.")
        return {"check": "first_invoice", "label": "Primera factura procesada",
                "ok": ok, "detail": detail}

    def check_team_member(self) -> Dict[str, Any]:
        users = self._users()
        ok = len(users) >= 1
        detail = ""
        if not ok:
            detail = ("Invita al menos un miembro del equipo (paso 6) para "
                      "crear un usuario.")
        return {"check": "team_member", "label": "Miembro de equipo agregado",
                "ok": ok, "detail": detail, "users": len(users)}

    ALL_CHECKS = ["company_info", "erp_connected",
                  "first_invoice", "team_member"]

    # ------------------------------------------------------------------ #
    # Evaluación agregada
    # ------------------------------------------------------------------ #
    def evaluate(self) -> Dict[str, Any]:
        """Devuelve el checklist completo + score 0-100 + readiness."""
        if self.tenant_id is None:
            return {"tenant_id": None, "score": 0, "complete": False,
                    "checks": [], "missing": ["Falta tenant_id."]}
        checks = [getattr(self, f"check_{c}")() for c in self.ALL_CHECKS]
        score = sum(CHECK_WEIGHTS[c["check"]] for c in checks if c["ok"])
        missing = [c["check"] for c in checks if not c["ok"]]
        complete = score == 100
        return {
            "tenant_id": self.tenant_id,
            "score": score,
            "complete": complete,
            "missing": missing,
            "checks": checks,
        }

    # Atajos
    def score(self) -> int:
        return self.evaluate()["score"]

    def checklist(self) -> List[Dict[str, Any]]:
        return self.evaluate()["checks"]
