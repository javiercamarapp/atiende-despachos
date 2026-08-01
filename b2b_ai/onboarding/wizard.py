# -*- coding: utf-8 -*-
"""
wizard.py — OnboardingWizard: asistente de alta de un nuevo cliente (tenant).

Orquesta el flujo de onboarding en 7 pasos y persiste el progreso en la tabla
`tenant_config` (claves `onboarding:step:N` y `onboarding:state`), de modo que
el progreso sobrevive entre requests y es por-tenant.

Pasos:
    1. company_info      — nombre, RFC, industria.
    2. erp_selection     — CONTPAQi | Aspel | Other.
    3. erp_connection    — credenciales ERP o subida de CSV.
    4. account_catalog   — catálogo de cuentas.
    5. first_invoice     — primera factura procesada.
    6. team_invites      — invitaciones de equipo (crea usuarios).
    7. subscription_plan — plan de facturación.

Cada paso valida su `data` antes de persistir. El wizard NO autoevalúa el
cierre: la verificación y el score los calcula OnboardingChecklist (checklist.py).
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from b2b_ai.db.tenants import TenantManager, TenantNotFoundError

# Orden canónico de los pasos (1..7).
STEP_ORDER: List[int] = [1, 2, 3, 4, 5, 6, 7]

# Claves legibles de cada paso (para la API / UI).
STEP_NAMES: Dict[int, str] = {
    1: "company_info",
    2: "erp_selection",
    3: "erp_connection",
    4: "account_catalog",
    5: "first_invoice",
    6: "team_invites",
    7: "subscription_plan",
}

STEP_TITLES: Dict[int, str] = {
    1: "Información de la empresa",
    2: "Selección de ERP",
    3: "Conexión del ERP",
    4: "Catálogo de cuentas",
    5: "Primera factura",
    6: "Invitaciones de equipo",
    7: "Plan de suscripción",
}

# ERP soportados en el paso 2 (case-insensitive; se normalizan a mayúscula).
ERP_OPTIONS: List[str] = ["CONTPAQi", "ASPEL", "OTHER"]

# Planes válidos en el paso 7 (coinciden con billing.pricing.PLANS).
PLAN_OPTIONS: List[str] = ["starter", "growth", "enterprise"]

# Claves de tenant_config donde se guarda el estado.
_CFG_STATE = "onboarding:state"      # JSON: {current_step, complete}
_CFG_STEP = "onboarding:step:{}"     # JSON: data del paso N

# Datos mínimos obligatorios por paso (para validación).
_STEP_REQUIRED: Dict[int, List[str]] = {
    1: ["name", "rfc", "industry"],
    2: ["erp"],
    3: [],  # depende de modo (credentials | csv) — se valida en _validate_step3
    4: [],  # se acepta catálogo o plantilla; se valida en _validate_step4
    5: ["invoice_id"],
    6: ["invites"],
    7: ["plan"],
}


class OnboardingError(Exception):
    """Error de validación o estado del wizard de onboarding."""


class OnboardingWizard:
    """Wizard de onboarding por pasos, persistido en tenant_config."""

    def __init__(self, db=None, tenant_id: Optional[int] = None):
        self._tm = TenantManager(db)
        self.db = self._tm.db
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------ #
    # Persistencia / estado
    # ------------------------------------------------------------------ #
    def _ensure_tenant(self) -> None:
        """Valida que el tenant exista; si no, lanza TenantNotFoundError."""
        if self.tenant_id is None:
            raise OnboardingError("Falta tenant_id: el onboarding es por cliente.")
        self._tm.get_tenant(self.tenant_id)  # lanza TenantNotFoundError

    def _load_state(self) -> Dict[str, Any]:
        raw = self.db.get_tenant_config(self.tenant_id, _CFG_STATE)
        if not raw:
            return {"current_step": 1, "complete": False}
        try:
            state = json.loads(raw)
        except (TypeError, ValueError):
            return {"current_step": 1, "complete": False}
        return {
            "current_step": int(state.get("current_step", 1) or 1),
            "complete": bool(state.get("complete", False)),
        }

    def _save_state(self, current_step: int, complete: bool = False) -> None:
        self.db.set_tenant_config(
            self.tenant_id, _CFG_STATE,
            json.dumps({"current_step": current_step, "complete": complete}))

    def _step_key(self, step: int) -> str:
        return _CFG_STEP.format(step)

    def _load_step(self, step: int) -> Optional[Dict[str, Any]]:
        raw = self.db.get_tenant_config(self.tenant_id, self._step_key(step))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------ #
    # Validación por paso
    # ------------------------------------------------------------------ #
    @staticmethod
    def _require(data: Dict[str, Any], fields: List[str]) -> None:
        for f in fields:
            if not data.get(f):
                raise OnboardingError(f"Falta el campo obligatorio: {f}")

    def _validate_step1(self, data: Dict[str, Any]) -> None:
        self._require(data, ["name", "rfc", "industry"])
        rfc = str(data["rfc"]).strip()
        if len(rfc) < 12:
            raise OnboardingError("RFC inválido: debe tener al menos 12 caracteres.")

    def _validate_step2(self, data: Dict[str, Any]) -> None:
        erp_in = str(data.get("erp", "")).strip()
        # Comparación case-insensitive; CONTPAQi se guarda con su grafía
        # canónica (la "i" final es minúscula en la marca).
        by_key = {opt.upper(): opt for opt in ERP_OPTIONS}
        if erp_in.upper() not in by_key:
            raise OnboardingError(
                f"ERP inválido: {erp_in!r}. Opciones: "
                + ", ".join(ERP_OPTIONS) + ".")
        data["erp"] = by_key[erp_in.upper()]  # normaliza

    def _validate_step3(self, data: Dict[str, Any]) -> None:
        mode = data.get("mode", "")
        if mode == "credentials":
            creds = data.get("credentials") or {}
            missing = [k for k in ("host", "user", "password") if not creds.get(k)]
            if missing:
                raise OnboardingError(
                    "Credenciales incompletas. Faltan: " + ", ".join(missing))
        elif mode == "csv":
            if not (data.get("csv_file") or data.get("csv_path")):
                raise OnboardingError(
                    "Modo CSV requiere csv_file (o csv_path).")
        else:
            raise OnboardingError(
                "Conexión ERP requiere mode='credentials' o 'csv'.")

    def _validate_step4(self, data: Dict[str, Any]) -> None:
        catalog = data.get("catalog")
        template = data.get("template")
        if not catalog and not template:
            raise OnboardingError(
                "Catálogo de cuentas requiere 'catalog' (lista) o 'template'.")
        if catalog is not None and not isinstance(catalog, list):
            raise OnboardingError("'catalog' debe ser una lista de cuentas.")

    def _validate_step5(self, data: Dict[str, Any]) -> None:
        self._require(data, ["invoice_id"])

    def _validate_step6(self, data: Dict[str, Any]) -> None:
        invites = data.get("invites")
        if not isinstance(invites, list) or not invites:
            raise OnboardingError(
                "Equipo requiere 'invites' (lista de {name, email}).")

    def _validate_step7(self, data: Dict[str, Any]) -> None:
        plan = str(data.get("plan", "")).strip().lower()
        if plan not in PLAN_OPTIONS:
            raise OnboardingError(
                f"Plan inválido: {data.get('plan')!r}. Opciones: "
                + ", ".join(PLAN_OPTIONS) + ".")
        data["plan"] = plan  # normaliza

    _VALIDATORS = {
        1: _validate_step1, 2: _validate_step2, 3: _validate_step3,
        4: _validate_step4, 5: _validate_step5, 6: _validate_step6,
        7: _validate_step7,
    }

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #
    def status(self) -> Dict[str, Any]:
        """Estado actual del onboarding: paso en curso, completados, cierre."""
        self._ensure_tenant()
        state = self._load_state()
        completed = [
            s for s in STEP_ORDER
            if self._load_step(s) is not None
        ]
        return {
            "tenant_id": self.tenant_id,
            "current_step": state["current_step"],
            "complete": state["complete"],
            "steps": {STEP_NAMES[s]: STEP_TITLES[s] for s in STEP_ORDER},
            "completed_steps": [STEP_NAMES[s] for s in completed],
            "next_step": STEP_NAMES.get(state["current_step"]),
        }

    def get_step(self, step: int) -> Dict[str, Any]:
        """Devuelve el data de un paso (vacío si no está completado)."""
        self._ensure_tenant()
        if step not in STEP_ORDER:
            raise OnboardingError(f"Paso inválido: {step} (usa 1..7).")
        return {
            "step": step,
            "name": STEP_NAMES[step],
            "title": STEP_TITLES[step],
            "complete": self._load_step(step) is not None,
            "data": self._load_step(step) or {},
        }

    def set_step(self, step: int, data: Dict[str, Any],
                 advance: bool = True) -> Dict[str, Any]:
        """Valida, persiste el paso y (por defecto) avanza el wizard.

        Si el paso ya se había completado, se reemplaza su data. El paso en
        curso avanza al siguiente únicamente si `step == current_step` (o si
        es un repaso de un paso anterior). El paso 7 marca complete=True.
        """
        self._ensure_tenant()
        if step not in STEP_ORDER:
            raise OnboardingError(f"Paso inválido: {step} (usa 1..7).")
        if not isinstance(data, dict):
            raise OnboardingError("El data del paso debe ser un objeto JSON.")
        data = dict(data)
        self._VALIDATORS[step](self, data)  # lanza OnboardingError si es inválido

        # Persiste el data del paso.
        self.db.set_tenant_config(self.tenant_id, self._step_key(step),
                                  json.dumps(data, ensure_ascii=False))

        if advance:
            # Recalcula el paso en curso: el primero (en orden) que aún no
            # tiene data. Esto tolera completar pasos fuera de orden y nunca
            # regresa a un paso ya hecho. Si todos están completos, cierra.
            nxt = None
            for s in STEP_ORDER:
                if self._load_step(s) is None:
                    nxt = s
                    break
            complete = nxt is None
            self._save_state(nxt or STEP_ORDER[-1], complete)

        return self.status()

    def complete(self) -> Dict[str, Any]:
        """Marca el onboarding como completo (el score lo da el checklist)."""
        self._ensure_tenant()
        missing = [s for s in STEP_ORDER if self._load_step(s) is None]
        if missing:
            raise OnboardingError(
                "Onboarding incompleto: faltan los pasos "
                + ", ".join(str(s) for s in missing) + ".")
        self._save_state(STEP_ORDER[-1], complete=True)
        return self.status()

    def create_team_users(self) -> int:
        """Crea los usuarios del paso 6 (team_invites) en el tenant.

        Idempotente por (email): los emails ya existentes no se duplican.
        Devuelve el número de usuarios creados.
        """
        self._ensure_tenant()
        invites = self._load_step(6) or {}
        created = 0
        existing = {u["email"] for u in self._list_users()}
        for inv in invites.get("invites", []):
            email = (inv.get("email") or "").strip()
            if not email or email in existing:
                continue
            self.db.create_user(self.tenant_id, inv.get("name") or email,
                                email, inv.get("role") or "contador")
            existing.add(email)
            created += 1
        return created

    def _list_users(self) -> List[Dict[str, Any]]:
        """Usuarios del tenant (consulta directa, no expuesta por db.py)."""
        rows = self.db.conn.execute(
            "SELECT id, name, email, role FROM users WHERE tenant_id=?",
            (self.tenant_id,)).fetchall()
        return [dict(r) for r in rows]
