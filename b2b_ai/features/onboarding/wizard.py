# -*- coding: utf-8 -*-
"""wizard.py — OnboardingWizard: la clase que guía el flujo del Día 1.

Cada paso tiene validación estricta antes de avanzar y el orden es secuencial
(no se puede saltar un paso). El progreso se persiste en memoria (patrón del
módulo `bank_feeds` / `batch`: store en dict + `_reset_state()` para tests),
con la interfaz preparada para inyectar una capa de persistencia (db) sin
cambiar la firma.

Flujo:
    w = OnboardingWizard()
    session = w.start()
    session = w.advance_step(sid, "tenant", {...})      # + crea tenant/admin
    session = w.advance_step(sid, "fiscal", {...})
    session = w.advance_step(sid, "data_source", {...})
    session = w.advance_step(sid, "test_cfdi", {...})
    session = w.advance_step(sid, "checkout", {"plan": "starter"})
    report = w.complete(sid)                             # health check
"""
from __future__ import annotations

import re
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from b2b_ai.features.onboarding.models import (
    OnboardingSession,
    OnboardingStatus,
    OnboardingStep,
    STEP_NAMES,
    STEP_ORDER,
)


# ---------------------------------------------------------------------------
# Store en memoria (patrón bank_feeds / batch)
# ---------------------------------------------------------------------------

_sessions: Dict[str, OnboardingSession] = {}
# tenant_id -> {"tenant": {...}, "admin": {...}}  (aislado por tenant)
_tenants: Dict[str, Dict[str, Any]] = {}


def _reset_state() -> None:
    """Limpia el estado en memoria (uso en tests)."""
    _sessions.clear()
    _tenants.clear()


# ---------------------------------------------------------------------------
# Excepciones
# ---------------------------------------------------------------------------

class OnboardingWizardError(Exception):
    """Error de dominio del wizard (con mensaje amigable)."""


# ---------------------------------------------------------------------------
# Constantes de validación (catálogos fiscales MX)
# ---------------------------------------------------------------------------

# RFC: 12 (moral) o 13 (física) caracteres alfanuméricos, con al menos 6 dígitos.
_RFC_RE = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{2,3}$", re.IGNORECASE)

# Códigos de régimen fiscal (catálogo SAT c_RegimenFiscal, común).
REGIMENES_VALIDOS = {
    "601",  # General de Ley Personas Morales
    "603",  # Personas Morales con Fines no Lucrativos
    "606",  # Arrendamiento
    "612",  # Personas Físicas con Actividades Empresariales y Profesionales
    "621",  # Incorporación Fiscal
    "625",  # Plataformas Tecnológicas
    "626",  # Régimen Simplificado de Confianza (RESICO)
    "610",  # Residentes en el Extranjero
    "615",  # Sin Obligaciones Fiscales
}

FUENTES_DATOS_VALIDAS = {"cfdi_upload", "sat_bridge", "bank_feed"}

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Validadores por paso
# ---------------------------------------------------------------------------

def _validate_tenant(payload: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    name = (payload.get("company_name") or "").strip()
    admin_name = (payload.get("admin_name") or "").strip()
    admin_email = (payload.get("admin_email") or "").strip()
    if not name:
        errors.append("company_name es obligatorio")
    if not admin_name:
        errors.append("admin_name es obligatorio")
    if not admin_email or "@" not in admin_email or "." not in admin_email:
        errors.append("admin_email debe ser un email válido")
    return errors


def _validate_fiscal(payload: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    rfc = (payload.get("rfc") or "").strip().upper()
    regimen = (payload.get("regimen_fiscal") or "").strip()
    cp = str(payload.get("codigo_postal") or "").strip()
    if not _RFC_RE.match(rfc):
        errors.append(
            "rfc inválido: debe ser 12 (moral) o 13 (física) caracteres "
            "alfanuméricos, ej. GYA850101XYZ"
        )
    if regimen not in REGIMENES_VALIDOS:
        errors.append(
            f"regimen_fiscal inválido '{regimen}'. "
            f"Válidos: {', '.join(sorted(REGIMENES_VALIDOS))}"
        )
    if not re.fullmatch(r"\d{5}", cp):
        errors.append("codigo_postal debe ser un código postal mexicano de 5 dígitos")
    return errors


def _validate_data_source(payload: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    source = (payload.get("source") or "").strip().lower()
    if source not in FUENTES_DATOS_VALIDAS:
        errors.append(
            f"source inválido '{source}'. Válidos: {', '.join(sorted(FUENTES_DATOS_VALIDAS))}"
        )
    return errors


def _validate_test_cfdi(payload: Dict[str, Any]) -> List[str]:
    """Valida que el payload permita parsear un CFDI (xml o dict)."""
    errors: List[str] = []
    xml = payload.get("xml")
    record = payload.get("record") or payload.get("cfdi")
    if not xml and not record:
        errors.append("debe enviar 'xml' (string del Comprobante) o 'record' (dict parseado)")
        return errors
    if record:
        if not record.get("rfc"):
            errors.append("record.rfc (RFC emisor) es obligatorio")
        if not record.get("total"):
            errors.append("record.total (monto total) es obligatorio")
        if record.get("uuid") and not _UUID_RE.match(str(record["uuid"])):
            errors.append("record.uuid tiene formato inválido")
    return errors


def _validate_checkout(payload: Dict[str, Any]) -> List[str]:
    """Valida el paso de checkout: requiere un plan de suscripción válido."""
    errors: List[str] = []
    plan = (payload.get("plan") or "").strip().lower()
    if not plan:
        errors.append("plan es obligatorio (starter, pro, business, enterprise)")
        return errors
    # Validación contra el catálogo de planes (import lazy para evitar ciclos).
    from b2b_ai.features.billing.plans import get_plan_or_none
    if get_plan_or_none(plan) is None:
        errors.append(f"plan inválido '{plan}'. Válidos: starter, pro, business, enterprise")
    return errors


# ---------------------------------------------------------------------------
# Wizard
# ---------------------------------------------------------------------------

class OnboardingWizard:
    """Orquesta el onboarding del Día 1 del piloto, paso a paso y validado."""

    def __init__(self, db: Any = None) -> None:
        # db se acepta por firma (patrón del proyecto); el store por defecto
        # es en memoria. Un futuro backend puede persistir aquí.
        self._db = db

    # ------------------------------------------------------------------
    # CRUD de sesiones
    # ------------------------------------------------------------------

    def start(self, tenant_id: Optional[str] = None) -> OnboardingSession:
        """Crea una sesión de onboarding nueva (progreso vacío)."""
        session = OnboardingSession(
            tenant_id=tenant_id or "",
            tenant_name="",
        )
        session.touch()
        _sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> OnboardingSession:
        """Devuelve una sesión, lanzando error si no existe."""
        session = _sessions.get(session_id)
        if session is None:
            raise OnboardingWizardError(
                f"Sesión de onboarding no encontrada: {session_id}"
            )
        return session

    # ------------------------------------------------------------------
    # Avance por pasos
    # ------------------------------------------------------------------

    def advance_step(
        self,
        session_id: str,
        step: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> OnboardingSession:
        """Valida y ejecuta un paso, persistiendo el progreso.

        Reglas:
          - el paso debe ser exactamente el siguiente en `STEP_ORDER`
            (no se puede saltar / repetir);
          - si la sesión ya está completa, se rechaza;
          - el payload se valida antes de ejecutar.
        """
        session = self.get_session(session_id)
        payload = payload or {}

        if session.is_complete:
            raise OnboardingWizardError("La sesión ya está completa")

        try:
            target = OnboardingStep(step)
        except ValueError:
            valid = ", ".join(s.value for s in STEP_ORDER)
            raise OnboardingWizardError(f"Paso inválido '{step}'. Válidos: {valid}")

        expected = STEP_ORDER[len(session.completed_steps)]
        if target != expected:
            raise OnboardingWizardError(
                f"No se puede ejecutar el paso '{target.value}': el siguiente "
                f"paso pendiente es '{expected.value}' ({STEP_NAMES[expected.value]})."
            )

        # Validación específica del paso.
        validate = {
            OnboardingStep.TENANT: _validate_tenant,
            OnboardingStep.FISCAL: _validate_fiscal,
            OnboardingStep.DATA_SOURCE: _validate_data_source,
            OnboardingStep.TEST_CFDI: _validate_test_cfdi,
            OnboardingStep.CHECKOUT: _validate_checkout,
            OnboardingStep.HEALTH_CHECK: lambda p: [],
        }[target]
        errors = validate(payload)
        if errors:
            session.errors[target.value] = "; ".join(errors)
            session.touch()
            raise OnboardingWizardError(
                f"Paso '{target.value}' inválido: {'; '.join(errors)}"
            )

        # Ejecución del paso (el runner devuelve el "output" persistido).
        runner = {
            OnboardingStep.TENANT: self._run_tenant,
            OnboardingStep.FISCAL: self._run_fiscal,
            OnboardingStep.DATA_SOURCE: self._run_data_source,
            OnboardingStep.TEST_CFDI: self._run_test_cfdi,
            OnboardingStep.CHECKOUT: self._run_checkout,
            OnboardingStep.HEALTH_CHECK: self._run_health_check,
        }[target]
        result = runner(session, payload)

        # Persistir progreso.
        session.completed_steps.append(target.value)
        session.data[target.value] = result
        session.errors.pop(target.value, None)
        session.touch()
        return session

    # ------------------------------------------------------------------
    # Ejecución de cada paso
    # ------------------------------------------------------------------

    def _run_tenant(self, session: OnboardingSession, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Paso 1: crea el tenant (empresa contable) + usuario admin."""
        tenant_id = session.tenant_id or str(_uuid.uuid4())
        company_name = payload["company_name"].strip()
        admin = {
            "user_id": str(_uuid.uuid4()),
            "name": payload["admin_name"].strip(),
            "email": payload["admin_email"].strip().lower(),
            "role": "admin",
        }
        _tenants[tenant_id] = {
            "tenant_id": tenant_id,
            "name": company_name,
            "status": "active",
            "created_at": _utcnow(),
            "admin": admin,
            "config": {"plan": "piloto_30d", "onboarding_status": "in_progress"},
        }
        session.tenant_id = tenant_id
        session.tenant_name = company_name
        return {"tenant_id": tenant_id, "admin": admin}

    def _run_fiscal(self, session: OnboardingSession, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Paso 2: configura datos fiscales del tenant."""
        tenant = self._require_tenant(session)
        fiscal = {
            "rfc": payload["rfc"].strip().upper(),
            "regimen_fiscal": payload["regimen_fiscal"],
            "codigo_postal": str(payload["codigo_postal"]).strip(),
            "updated_at": _utcnow(),
        }
        tenant["fiscal"] = fiscal
        return fiscal

    def _run_data_source(self, session: OnboardingSession, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Paso 3: conecta la fuente de datos del tenant."""
        tenant = self._require_tenant(session)
        source = {
            "source": payload["source"],
            "configured_at": _utcnow(),
            "status": "connected",
        }
        tenant["data_source"] = source
        return source

    def _run_test_cfdi(self, session: OnboardingSession, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Paso 4: sube, parsea y valida el primer CFDI de prueba."""
        tenant = self._require_tenant(session)
        parsed = self._parse_cfdi(payload)
        # validar que el CFDI "corresponde" al tenant (RFC emisor coincide).
        fiscal = tenant.get("fiscal") or {}
        emisor_rfc = (parsed.get("rfc") or "").upper()
        if fiscal.get("rfc") and emisor_rfc and emisor_rfc != fiscal["rfc"].upper():
            raise OnboardingWizardError(
                f"El RFC del CFDI ({emisor_rfc}) no coincide con el RFC fiscal "
                f"del tenant ({fiscal['rfc']})."
            )
        parsed["validated"] = True
        parsed["validated_at"] = _utcnow()
        tenant["test_cfdi"] = parsed
        return parsed

    def _run_checkout(self, session: OnboardingSession, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Paso 5: inicia el checkout de Conekta para el plan elegido y
        persiste la referencia de pago en la sesión."""
        plan = (payload.get("plan") or "").strip().lower()
        reference = self.start_checkout(session.session_id, plan)
        return reference

    def _run_health_check(self, session: OnboardingSession, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Paso 5: ejecuta el health check completo (sin payload extra)."""
        return self._health_check(session)

    # ------------------------------------------------------------------
    # Checkout (integración con billing / Conekta)
    # ------------------------------------------------------------------

    def start_checkout(self, session_id: str, plan: str,
                       success_url: str = "",
                       cancel_url: str = "") -> Dict[str, Any]:
        """Inicia el checkout de Conekta para el tenant y plan dados.

        Crea la sesión de pago vía `BillingService.create_checkout` y persiste
        la referencia (checkout_url, order_id, customer_id) en la sesión de
        onboarding (`session.data["checkout"]`) y en el tenant.

        Devuelve la referencia de pago (dict con checkout_url y metadatos).
        """
        session = self.get_session(session_id)
        tenant = self._require_tenant(session)
        plan = (plan or "").strip().lower()

        from b2b_ai.features.billing.plans import get_plan_or_none
        if get_plan_or_none(plan) is None:
            raise OnboardingWizardError(
                f"Plan inválido '{plan}'. Válidos: starter, pro, business, enterprise"
            )

        from b2b_ai.features.billing.conekta_client import ConektaClient
        from b2b_ai.features.billing.service import BillingError, BillingService

        billing = BillingService(client=ConektaClient())
        try:
            result = billing.create_checkout(
                tenant_id=session.tenant_id,
                plan=plan,
                success_url=success_url,
                cancel_url=cancel_url,
            )
        except BillingError as exc:
            raise OnboardingWizardError(exc.message)

        reference = {
            "plan": plan,
            "checkout_url": result.get("checkout_url", ""),
            "order_id": result.get("order_id"),
            "customer_id": result.get("customer_id"),
            "amount_mxn": result.get("amount_mxn"),
            "currency": result.get("currency", "MXN"),
            "started_at": _utcnow(),
            "status": "pending",
        }
        session.data["checkout"] = reference
        if tenant:
            tenant["config"]["checkout"] = reference
        session.touch()
        return reference

    # ------------------------------------------------------------------
    # Cierre / health check
    # ------------------------------------------------------------------

    def complete(self, session_id: str) -> Dict[str, Any]:
        """Cierra el onboarding: corre el health check y completa."""
        session = self.get_session(session_id)
        if session.progress < 4:
            raise OnboardingWizardError(
                f"No se puede completar: faltan pasos "
                f"({session.current_step or 'health_check'}). "
                f"Progreso {session.progress}/6."
            )
        # El paso final (health_check) se ejecuta como parte del cierre si no se
        # avanzó explícitamente antes.
        if OnboardingStep.HEALTH_CHECK.value not in session.completed_steps:
            session.completed_steps.append(OnboardingStep.HEALTH_CHECK.value)
        report = self._health_check(session)
        session.data[OnboardingStep.HEALTH_CHECK.value] = report
        session.status = OnboardingStatus.COMPLETED
        session.completed_at = _utcnow()
        tenant = _tenants.get(session.tenant_id)
        if tenant:
            tenant["config"]["onboarding_status"] = "completed"
        session.touch()
        return {"ok": True, "session": session.to_dict(), "health": report}

    def health_check(self, session_id: str) -> Dict[str, Any]:
        """Devuelve el checklist de salud de una sesión sin cerrarla."""
        session = self.get_session(session_id)
        return self._health_check(session)

    def _health_check(self, session: OnboardingSession) -> Dict[str, Any]:
        """Checklist completo de los 5 pasos del piloto."""
        tenant = _tenants.get(session.tenant_id)
        checks: List[Dict[str, Any]] = []

        def add(step: str, ok: bool, detail: str) -> None:
            checks.append({"step": step, "label": STEP_NAMES[step], "ok": ok, "detail": detail})

        # 1. Tenant + admin
        if tenant and tenant.get("admin"):
            add("tenant", True, f"tenant {tenant['tenant_id']} + admin {tenant['admin']['email']}")
        else:
            add("tenant", False, "tenant/admin no creados")

        # 2. Fiscal
        fiscal = (tenant or {}).get("fiscal")
        if fiscal and fiscal.get("rfc") and fiscal.get("codigo_postal"):
            add("fiscal", True, f"RFC {fiscal['rfc']} configurado")
        else:
            add("fiscal", False, "datos fiscales incompletos")

        # 3. Fuente de datos
        ds = (tenant or {}).get("data_source")
        if ds and ds.get("status") == "connected":
            add("data_source", True, f"fuente {ds['source']} conectada")
        else:
            add("data_source", False, "fuente de datos no conectada")

        # 4. CFDI de prueba
        tc = (tenant or {}).get("test_cfdi")
        if tc and tc.get("validated"):
            add("test_cfdi", True, f"CFDI {tc.get('uuid', 'sin-uuid')} validado, total {tc.get('total')}")
        else:
            add("test_cfdi", False, "no hay CFDI de prueba validado")

        # 5. Checkout / pago
        chk = session.data.get("checkout") or (tenant or {}).get("config", {}).get("checkout")
        if chk and chk.get("checkout_url"):
            add("checkout", True, f"checkout {chk.get('plan')} iniciado ({chk.get('checkout_url')})")
        else:
            add("checkout", False, "no se ha iniciado el checkout")

        # 6. Verificación global
        all_ok = all(c["ok"] for c in checks)
        add("health_check", all_ok, "todo listo para producción" if all_ok else "quedan pasos por resolver")

        return {
            "status": "healthy" if all_ok else "pending",
            "passed": sum(1 for c in checks if c["ok"]),
            "total": len(checks),
            "checks": checks,
        }

    # ------------------------------------------------------------------
    # Helpers privados
    # ------------------------------------------------------------------

    def _require_tenant(self, session: OnboardingSession) -> Dict[str, Any]:
        if not session.tenant_id or session.tenant_id not in _tenants:
            raise OnboardingWizardError(
                "Debe completar primero el paso 'tenant' (crear tenant + admin)."
            )
        return _tenants[session.tenant_id]

    @staticmethod
    def _parse_cfdi(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Parsea un CFDI desde XML string o desde un dict ya parseado."""
        record = payload.get("record") or payload.get("cfdi")
        if record:
            return {
                "uuid": str(record.get("uuid") or ""),
                "rfc": str(record.get("rfc") or ""),
                "total": record.get("total"),
                "fecha": record.get("fecha") or "",
                "emisor": str(record.get("emisor") or ""),
            }
        xml = payload.get("xml")
        if not xml:
            raise OnboardingWizardError("CFDI: no hay 'xml' ni 'record'")
        return _parse_cfdi_xml(xml)


def _parse_cfdi_xml(xml: str) -> Dict[str, Any]:
    """Extrae rfc/total/uuid/fecha de un Comprobante CFDI 4.0 (xml.etree).

    Fallback mínimo sin dependencias externas; tolera namespaces SAT.
    """
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise OnboardingWizardError(f"CFDI: XML inválido ({exc})")

    def attr(*names: str) -> Optional[str]:
        for n in names:
            v = root.attrib.get(n)
            if v is not None:
                return v
        return None

    rfc = attr("Rfc", "rfc")
    total = attr("Total", "total")
    fecha = attr("Fecha", "fecha")
    uuid_v = ""

    # TimbreFiscalDigital (uuid) puede venir en cualquier namespace.
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag in ("TimbreFiscalDigital", "TimbreFiscalDigitalStamped"):
            for k, v in el.attrib.items():
                if k.endswith("UUID") or k == "UUID":
                    uuid_v = v

    if not rfc:
        raise OnboardingWizardError("CFDI: no se encontró el atributo Rfc del emisor")
    if not total:
        raise OnboardingWizardError("CFDI: no se encontró el atributo Total")

    return {
        "uuid": uuid_v,
        "rfc": rfc,
        "total": total,
        "fecha": fecha or "",
        "emisor": "",
    }
