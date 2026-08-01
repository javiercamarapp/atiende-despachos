# -*- coding: utf-8 -*-
"""
checklist.py — Verificación del onboarding y score 0-100.

Un onboarding NO se considera completo por haber llenado los 5 pasos: hay que
verificar contra fuentes de verdad (tenant_config, tabla users, tabla invoices)
que cada hito real se cumplió. Este módulo hace esa verificación y calcula un
score de readiness 0-100.

Chequeos:
    1. company_profile  — datos de empresa completos (paso 1).
    2. sat_credentials  — CIEC configurado (paso 2).
    3. erp_connected    — ERP conectado (paso 3 con credenciales o CSV).
    4. billing_plan     — plan seleccionado (paso 4).
    5. first_cfdi       — primer CFDI procesado (paso 5 respaldado
                          por count_invoices del tenant).

Cada chequeo pesa 20 pts → score 0-100. El detalle indica QUÉ falta y cómo
resolverlo, para que la UI del wizard lo muestre.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from b2b_ai.db.tenants import TenantManager

# Pesos de cada chequeo sobre el score 0-100.
CHECK_WEIGHTS: Dict[str, int] = {
    "company_profile": 20,
    "sat_credentials": 20,
    "erp_connected": 20,
    "billing_plan": 20,
    "first_cfdi": 20,
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
        raw = self.db.get_tenant_config(
            self.tenant_id, f"onboarding:step:{step}")
        if not raw:
            return {}
        try:
            val = json.loads(raw)
            return val if isinstance(val, dict) else {}
        except (TypeError, ValueError):
            return {}

    # ------------------------------------------------------------------ #
    # Chequeos individuales
    # ------------------------------------------------------------------ #
    def check_company_profile(self) -> Dict[str, Any]:
        s1 = self._step(1)
        ok = bool(
            s1.get("name") and s1.get("rfc")
            and s1.get("address") and s1.get("contact_name")
            and s1.get("contact_email"))
        detail = ""
        if not ok:
            missing = [f for f in ("name", "rfc", "address",
                                   "contact_name", "contact_email")
                       if not s1.get(f)]
            detail = "Falta: " + ", ".join(missing)
        return {"check": "company_profile", "label": "Perfil de la empresa",
                "ok": ok, "detail": detail}

    def check_sat_credentials(self) -> Dict[str, Any]:
        s2 = self._step(2)
        ciec = s2.get("ciec", "")
        ok = bool(ciec and len(ciec) >= 6)
        detail = ""
        if not ok:
            detail = "Configura el CIEC del SAT (paso 2)."
        return {"check": "sat_credentials", "label": "Credenciales SAT",
                "ok": ok, "detail": detail}

    def check_erp_connected(self) -> Dict[str, Any]:
        s3 = self._step(3)
        erp = s3.get("erp", "")
        ok = False
        if erp.lower() == "csv":
            ok = bool(s3.get("csv_file") or s3.get("csv_path"))
        elif erp.lower() in ("contpaqi", "aspel"):
            creds = s3.get("credentials") or {}
            ok = bool(creds.get("host") and creds.get("user"))
        detail = ""
        if not ok:
            detail = ("Conecta tu ERP (paso 3): ContPAQi, Aspel, "
                      "o importación CSV.")
        return {"check": "erp_connected", "label": "ERP conectado",
                "ok": ok, "detail": detail}

    def check_billing_plan(self) -> Dict[str, Any]:
        s4 = self._step(4)
        plan = s4.get("plan", "")
        ok = plan in ("basico", "profesional", "enterprise")
        detail = ""
        if not ok:
            detail = "Selecciona un plan de facturación (paso 4)."
        return {"check": "billing_plan", "label": "Plan de facturación",
                "ok": ok, "detail": detail}

    def check_first_cfdi(self) -> Dict[str, Any]:
        s5 = self._step(5)
        # Respaldamos el paso 5 con el conteo real de facturas del tenant.
        count = self.db.count_invoices(tenant_id=self.tenant_id) or 0
        ok = count > 0 and bool(s5.get("cfdi_xml"))
        detail = ""
        if not ok:
            detail = ("Sube un CFDI de prueba (paso 5); se esperan "
                      "facturas en la DB del tenant.")
        return {"check": "first_cfdi", "label": "Primer CFDI procesado",
                "ok": ok, "detail": detail, "invoice_count": count}

    ALL_CHECKS = [
        "company_profile", "sat_credentials", "erp_connected",
        "billing_plan", "first_cfdi",
    ]

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
