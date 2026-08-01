# -*- coding: utf-8 -*-
"""
wizard.py — OnboardingWizard: asistente de alta de un nuevo cliente (tenant).

Orquesta el flujo de onboarding en 5 pasos y persiste el progreso en la tabla
`tenant_config` (claves `onboarding:step:N` y `onboarding:state`), de modo que
el progreso sobrevive entre requests y es por-tenant.

Pasos:
    1. company_profile   — RFC, nombre, dirección, contacto.
    2. sat_credentials   — CIEC y e.firma del SAT.
    3. erp_connection    — selección y conexión del ERP (ContPAQi / Aspel / CSV).
    4. billing_plan      — plan de facturación (Básico / Profesional / Enterprise).
    5. first_cfdi        — prueba de subida de primer CFDI.

Cada paso valida su `data` antes de persistir. El wizard NO autoevalúa el
cierre: la verificación y el score los calcula OnboardingChecklist (checklist.py).
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from b2b_ai.db.tenants import TenantManager, TenantNotFoundError

# Orden canónico de los pasos (1..5).
STEP_ORDER: List[int] = [1, 2, 3, 4, 5]

# Claves legibles de cada paso (para la API / UI).
STEP_NAMES: Dict[int, str] = {
    1: "company_profile",
    2: "sat_credentials",
    3: "erp_connection",
    4: "billing_plan",
    5: "first_cfdi",
}

STEP_TITLES: Dict[int, str] = {
    1: "Perfil de la empresa",
    2: "Credenciales SAT",
    3: "Conexión del ERP",
    4: "Plan de facturación",
    5: "Prueba de CFDI",
}

# Descripción de cada paso (para UI / CLI).
STEP_DESCRIPTIONS: Dict[int, str] = {
    1: "Datos fiscales y de contacto de la empresa: RFC, nombre legal, dirección y contacto.",
    2: "Configuración de credenciales ante el SAT: CIEC y e.firma (certificado + llave privada).",
    3: "Selecciona y conecta tu sistema ERP: ContPAQi, Aspel, o importación CSV.",
    4: "Elige el plan de facturación mensual que mejor se adapte a tu despacho.",
    5: "Sube un CFDI de prueba para validar que el sistema procesa correctamente.",
}

# ERP soportados en el paso 3 (case-insensitive; se normalizan a grafía canónica).
ERP_OPTIONS: List[str] = ["ContPAQi", "Aspel", "CSV"]

# Planes válidos en el paso 4 — coinciden con billing.pricing.PLANS.
PLAN_OPTIONS: List[str] = ["basico", "profesional", "enterprise"]

# Detalle de planes (precios MXN/mes).
PLAN_DETAILS: Dict[str, Dict[str, Any]] = {
    "basico": {
        "key": "basico",
        "name": "Básico",
        "price_mxn": 4900.0,
        "cfdi_limit": 500,
        "description": "Hasta 500 CFDI/mes — para despachos pequeños",
    },
    "profesional": {
        "key": "profesional",
        "name": "Profesional",
        "price_mxn": 12000.0,
        "cfdi_limit": 2000,
        "description": "Hasta 2,000 CFDI/mes — para despachos medianos",
    },
    "enterprise": {
        "key": "enterprise",
        "name": "Enterprise",
        "price_mxn": 48000.0,
        "cfdi_limit": None,
        "description": "Sin límite de CFDI — para grandes despachos",
    },
}

# Claves de tenant_config donde se guarda el estado.
_CFG_STATE = "onboarding:state"      # JSON: {current_step, complete}
_CFG_STEP = "onboarding:step:{}"     # JSON: data del paso N

# Datos mínimos obligatorios por paso (para validación rápida).
_STEP_REQUIRED: Dict[int, List[str]] = {
    1: ["name", "rfc", "address", "contact_name", "contact_email"],
    2: ["ciec"],
    3: ["erp"],
    4: ["plan"],
    5: ["cfdi_xml"],  # contenido XML o ruta del archivo
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
        """Company profile: RFC, nombre, dirección, contacto."""
        self._require(data, ["name", "rfc", "address", "contact_name", "contact_email"])
        from b2b_ai.common.rfc import is_valid_rfc
        rfc = str(data["rfc"]).strip()
        if not is_valid_rfc(rfc):
            raise OnboardingError(
                f"RFC inválido: {rfc!r}. Debe ser un RFC válido de persona física "
                "(13 chars) o moral (12 chars) del SAT.")
        # Normalizar RFC a mayúsculas
        data["rfc"] = rfc.upper()
        # Validar email de contacto
        contact_email = str(data["contact_email"]).strip()
        if "@" not in contact_email or "." not in contact_email:
            raise OnboardingError(
                f"Email de contacto inválido: {contact_email!r}.")
        data["contact_email"] = contact_email.lower()

    def _validate_step2(self, data: Dict[str, Any]) -> None:
        """SAT credentials: CIEC obligatorio, e.firma opcional."""
        self._require(data, ["ciec"])
        ciec = str(data["ciec"]).strip()
        # CIEC del SAT: 6 caracteres alfanuméricos
        if len(ciec) < 6:
            raise OnboardingError(
                "CIEC inválido: debe tener al menos 6 caracteres alfanuméricos.")
        data["ciec"] = ciec
        # e.firma es opcional pero si se prove, validar campos mínimos.
        # Soporta tanto formato anidado {"efirma": {"certificado": ...}}
        # como formato plano {"efirma_certificado": ..., "efirma_llave": ...}.
        efirma = data.get("efirma")
        if isinstance(efirma, dict):
            missing = [k for k in ("certificado", "llave_privada")
                       if not efirma.get(k)]
            if missing:
                raise OnboardingError(
                    "e.firma incompleta. Faltan: " + ", ".join(missing))
        else:
            # Formato plano: e.firma_certificado / e.firma_llave
            cert = data.get("efirma_certificado") or data.get("efirma_cert")
            key_ = data.get("efirma_llave") or data.get("efirma_llave")
            if cert and not key_:
                raise OnboardingError(
                    "e.firma incompleta. Se requiere tanto certificado "
                    "como llave privada.")
            if key_ and not cert:
                raise OnboardingError(
                    "e.firma incompleta. Se requiere tanto certificado "
                    "como llave privada.")

    def _validate_step3(self, data: Dict[str, Any]) -> None:
        """ERP connection: selección + credenciales.

        Soporta tanto formato anidado {"credentials": {"host": ...}}
        como formato plano {"credentials_host": ..., "credentials_user": ...}.
        """
        self._require(data, ["erp"])
        erp_in = str(data.get("erp", "")).strip()
        by_key = {opt.upper(): opt for opt in ERP_OPTIONS}
        if erp_in.upper() not in by_key:
            raise OnboardingError(
                f"ERP inválido: {erp_in!r}. Opciones: "
                + ", ".join(ERP_OPTIONS) + ".")
        data["erp"] = by_key[erp_in.upper()]  # normaliza grafía

        erp_type = data["erp"].lower()
        if erp_type == "csv":
            # Para CSV, se requiere al menos una referencia al archivo
            if not (data.get("csv_file") or data.get("csv_path")):
                raise OnboardingError(
                    "Conexión CSV requiere 'csv_file' o 'csv_path'.")
        elif erp_type in ("contpaqi", "aspel"):
            # Credenciales del ERP: soporta formato anidado y plano
            creds = data.get("credentials") or {}
            # Normalizar a formato anidado si viene plano
            if not creds:
                host = data.get("credentials_host") or data.get("host")
                user = data.get("credentials_user") or data.get("user")
                pwd = data.get("credentials_password") or data.get("password")
                if host or user or pwd:
                    creds = {"host": host, "user": user, "password": pwd}
                    data["credentials"] = creds
            missing = [k for k in ("host", "user", "password")
                       if not creds.get(k)]
            if missing:
                raise OnboardingError(
                    f"Conexión {data['erp']} requiere credenciales. "
                    f"Faltan: {', '.join(missing)}")

    def _validate_step4(self, data: Dict[str, Any]) -> None:
        """Billing plan selection."""
        self._require(data, ["plan"])
        plan = str(data.get("plan", "")).strip().lower()
        if plan not in PLAN_OPTIONS:
            raise OnboardingError(
                f"Plan inválido: {data.get('plan')!r}. Opciones: "
                + ", ".join(PLAN_OPTIONS) + ".")
        data["plan"] = plan  # normaliza
        data["plan_detail"] = PLAN_DETAILS[plan]

    def _validate_step5(self, data: Dict[str, Any]) -> None:
        """First CFDI upload test."""
        self._require(data, ["cfdi_xml"])
        cfdi_xml = str(data["cfdi_xml"]).strip()
        if len(cfdi_xml) < 50:
            raise OnboardingError(
                "El contenido del CFDI parece demasiado corto para ser un XML válido.")
        # Verificar que parece un XML de CFDI
        if not ("<cfdi:" in cfdi_xml or "<CFDI" in cfdi_xml.upper()):
            raise OnboardingError(
                "El contenido no parece ser un CFDI válido. "
                "Debe contener elementos del namespace CFDI.")

    _VALIDATORS = {
        1: _validate_step1, 2: _validate_step2, 3: _validate_step3,
        4: _validate_step4, 5: _validate_step5,
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
            "steps": {
                STEP_NAMES[s]: {
                    "title": STEP_TITLES[s],
                    "description": STEP_DESCRIPTIONS[s],
                }
                for s in STEP_ORDER
            },
            "completed_steps": [STEP_NAMES[s] for s in completed],
            "next_step": STEP_NAMES.get(state["current_step"]),
        }

    def get_step(self, step: int) -> Dict[str, Any]:
        """Devuelve el data de un paso (vacío si no está completado)."""
        self._ensure_tenant()
        if step not in STEP_ORDER:
            raise OnboardingError(f"Paso inválido: {step} (usa 1..5).")
        step_data = self._load_step(step)
        return {
            "step": step,
            "name": STEP_NAMES[step],
            "title": STEP_TITLES[step],
            "description": STEP_DESCRIPTIONS[step],
            "complete": step_data is not None,
            "data": step_data or {},
        }

    def set_step(self, step: int, data: Dict[str, Any],
                 advance: bool = True) -> Dict[str, Any]:
        """Valida, persiste el paso y (por defecto) avanza el wizard.

        Si el paso ya se había completado, se reemplaza su data. El paso en
        curso avanza al siguiente únicamente si `step == current_step` (o si
        es un repaso de un paso anterior). El paso 5 marca complete=True.
        """
        self._ensure_tenant()
        if step not in STEP_ORDER:
            raise OnboardingError(f"Paso inválido: {step} (usa 1..5).")
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

    def get_step_definitions(self) -> List[Dict[str, Any]]:
        """Lista definiciones de todos los pasos (para UI / CLI)."""
        return [
            {
                "step": s,
                "name": STEP_NAMES[s],
                "title": STEP_TITLES[s],
                "description": STEP_DESCRIPTIONS[s],
            }
            for s in STEP_ORDER
        ]

    def get_plan_options(self) -> List[Dict[str, Any]]:
        """Lista de planes disponibles con precios (para UI)."""
        return list(PLAN_DETAILS.values())

    def get_erp_options(self) -> List[str]:
        """Lista de ERPs disponibles."""
        return list(ERP_OPTIONS)
