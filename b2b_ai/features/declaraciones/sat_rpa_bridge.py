# -*- coding: utf-8 -*-
"""sat_rpa_bridge.py — Puente honesto entre declaration_api.py, el RPA real
(SATPortalRPADriver) y compliance_tracker.

Por qué existe este módulo (en vez de meter todo esto directo en
declaration_api.py):
    - Aísla el flag de entorno nuevo (B2B_SAT_SUBMIT_MODE) y su
      retrocompatibilidad (default 'stub' == comportamiento actual, sin
      cambios) del resto del router.
    - Reutiliza — no reinventa — el gating ya existente de Computer Use
      (`B2B_COMPUTER_USE_MODE`, `B2B_COMPUTER_USE_ALLOW_WRITES` en
      b2b_ai/computer_use/config.py y security.py) para decidir si el modo
      'rpa' puede tocar un navegador de verdad.
    - Hace testeable por separado, sin FastAPI, la única parte nueva de
      lógica real: invocar SATPortalRPADriver y, SOLO si confirma con folio,
      marcar la obligación DIOT correspondiente en compliance_tracker.

Alcance honesto (importante): `SATPortalRPADriver` hoy solo sabe presentar
DIOT (`submit_diot`, que sube un archivo, no un XML firmado). No existe un
flujo RPA real para IVA/ISR mensual/anual — inventar uno aquí sería fabricar
un comportamiento no probado. Por eso el modo 'rpa' solo cambia la ruta de
ejecución cuando `tipo == 'diot'`; para cualquier otro tipo, declaration_api
sigue usando el stub `SATSubmitter` (que ya es honesto: nunca regresa
ACCEPTED, siempre `simulado=True`) — no es un fallback silencioso, es una
limitación documentada del alcance actual del driver RPA.

Nunca se debilita `_assert_host_is_not_real_sat()` desde aquí: si alguien
configura `SAT_PORTAL_URL` apuntando a un dominio `*.gob.mx`, el driver lo
rechaza igual que siempre y este módulo solo convierte esa excepción en una
respuesta explícita de fallo (nunca la ignora, nunca reintenta).
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Optional

from b2b_ai.computer_use.security import writes_allowed
from b2b_ai.features.compliance_tracker.models import ObligationStatus, ObligationType
from b2b_ai.features.compliance_tracker.service import ComplianceService
from b2b_ai.features.declaraciones.sat_portal_rpa_driver import (
    PortalStatus,
    SATPortalRealDomainBlocked,
    SATPortalRPADriver,
)

logger = logging.getLogger("b2b_ai.declaraciones.sat_rpa_bridge")


# ---------------------------------------------------------------------------
# Modo de ejecución (B2B_SAT_SUBMIT_MODE)
# ---------------------------------------------------------------------------
VALID_SAT_SUBMIT_MODES = frozenset({"stub", "rpa"})
_DIOT_DEFAULT_DUE_DAY = 17  # mismo día que templates.py usa para DIOT


class SATSubmitModeConfigurationError(ValueError):
    """B2B_SAT_SUBMIT_MODE tiene un valor que no reconocemos."""


def get_sat_submit_mode() -> str:
    """Lee B2B_SAT_SUBMIT_MODE. Default 'stub' == comportamiento actual.

    Retrocompatibilidad explícita: si la variable no está definida (el caso
    de todo despliegue existente hoy), esta función regresa 'stub' y
    declaration_api.py sigue exactamente igual que antes de este cambio.
    """
    raw = os.environ.get("B2B_SAT_SUBMIT_MODE", "stub").strip().lower()
    if raw not in VALID_SAT_SUBMIT_MODES:
        raise SATSubmitModeConfigurationError(
            f"B2B_SAT_SUBMIT_MODE='{raw}' no reconocido. "
            f"Valores válidos: {sorted(VALID_SAT_SUBMIT_MODES)}."
        )
    return raw


# ---------------------------------------------------------------------------
# Gate: ¿se permite ejecutar RPA de verdad? (reutiliza el patrón existente)
# ---------------------------------------------------------------------------
def _computer_use_mode() -> str:
    return os.environ.get("B2B_COMPUTER_USE_MODE", "disabled").strip().lower()


def _headless() -> bool:
    raw = os.environ.get("B2B_COMPUTER_USE_HEADLESS", "true").strip().lower()
    return raw in ("true", "1", "yes")


def rpa_execution_allowed() -> "tuple[bool, str]":
    """True solo si los gates YA existentes de Computer Use permiten RPA real.

    No define un gate nuevo y paralelo: exige exactamente lo que el resto
    del sistema ya exige para cualquier automatización real de navegador
    (B2B_COMPUTER_USE_MODE=playwright) y para cualquier escritura
    (B2B_COMPUTER_USE_ALLOW_WRITES=true, default false).
    """
    mode = _computer_use_mode()
    if mode != "playwright":
        return False, (
            f"B2B_COMPUTER_USE_MODE='{mode}' (se requiere 'playwright' para "
            "ejecutar RPA real; ver b2b_ai/computer_use/config.py)."
        )
    if not writes_allowed():
        return False, (
            "B2B_COMPUTER_USE_ALLOW_WRITES no está habilitado (default "
            "seguro: false). Presentar una declaración es una operación de "
            "escritura; ver b2b_ai/computer_use/security.py."
        )
    return True, "ok"


# ---------------------------------------------------------------------------
# compliance_tracker: marcar la obligación DIOT como cumplida
# ---------------------------------------------------------------------------
_PERIODO_RE = re.compile(r"^(\d{4})-(\d{2})$")


def _parse_periodo_year_month(periodo: str) -> Optional[tuple]:
    m = _PERIODO_RE.match((periodo or "").strip())
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    if not (1 <= month <= 12):
        return None
    return year, month


def mark_diot_obligation_completed(
    tenant_id: str,
    periodo: str,
    user_id: str = "",
) -> Dict[str, Any]:
    """Marca (o crea+marca) la obligación DIOT del periodo como cumplida.

    Nunca lanza: cualquier problema se reporta en el dict de retorno para
    que el llamador pueda seguir reportando el resultado real del envío RPA
    (que ya ocurrió) aunque el tracking de obligaciones no se pueda ubicar o
    actualizar. Devuelve siempre `{"updated": bool, ...}`.

    Solo debe llamarse cuando el envío RPA ya fue confirmado con folio real
    por el portal (o su simulador) — ver `submit_diot_via_rpa`.
    """
    if not tenant_id:
        return {"updated": False, "reason": "tenant_id vacío; no se pudo ubicar la obligación."}

    parsed = _parse_periodo_year_month(periodo)
    if parsed is None:
        return {
            "updated": False,
            "reason": f"periodo '{periodo}' no tiene formato YYYY-MM; no se pudo ubicar la obligación DIOT.",
        }
    year, month = parsed

    service = ComplianceService()
    existing = [
        o
        for o in service.get_obligations(tenant_id, year=year, month=month)
        if o.obligation_type == ObligationType.DIOT
    ]

    pending = next((o for o in existing if o.status != ObligationStatus.COMPLETED), None)

    if pending is None and existing:
        # Todas las que hay ya estaban completadas: no es un error, no hay nada que hacer.
        return {
            "updated": False,
            "reason": "La obligación DIOT del periodo ya estaba marcada como cumplida.",
            "obligation_id": existing[0].id,
        }

    if pending is None:
        # No había calendario previo para este tenant/periodo: se crea la
        # obligación (con el mismo día de vencimiento que usa el calendario
        # anual, ver templates.py) para que quede registro de que SÍ se
        # presentó, en vez de perder la trazabilidad.
        pending = service.create_obligation(
            tenant_id=tenant_id,
            obligation_type=ObligationType.DIOT,
            due_date=date(year, month, _DIOT_DEFAULT_DUE_DAY),
            notes="Obligación creada automáticamente al confirmar un envío RPA sin calendario previo.",
        )

    try:
        completed = service.complete_obligation(pending.id, user_id=user_id)
    except ValueError:
        # Carrera improbable (otra llamada la completó justo antes): no es un fallo del envío.
        return {
            "updated": False,
            "reason": "La obligación DIOT ya fue completada (posible actualización concurrente).",
            "obligation_id": pending.id,
        }

    return {"updated": True, "obligation_id": completed.id}


# ---------------------------------------------------------------------------
# Orquestación: presentar DIOT vía RPA real
# ---------------------------------------------------------------------------
@dataclass
class RPASubmitOutcome:
    """Resultado uniforme de un intento de envío vía SATPortalRPADriver."""

    ok: bool
    status: str
    mensaje: str
    folio: Optional[str] = None
    fecha_recepcion: Optional[str] = None
    simulado: bool = True
    compliance_updated: bool = False
    compliance_detail: str = ""


async def submit_diot_via_rpa(
    *,
    tenant_id: str,
    rfc: str,
    periodo: str,
    declaration_id: Optional[str],
    diot_content: bytes,
    cer_path: Optional[str],
    key_path: Optional[str],
    password: Optional[str],
    confirm: bool,
) -> RPASubmitOutcome:
    """Presenta un DIOT vía SATPortalRPADriver y, SOLO si el portal confirma
    con folio real, marca la obligación DIOT correspondiente como cumplida.

    Fail-closed en cada paso, igual que SATPortalRPADriver y que
    SATSubmitter: cualquier cosa que no sea una confirmación explícita con
    folio se reporta como fallo y NUNCA toca compliance_tracker.
    """
    if not confirm:
        return RPASubmitOutcome(
            ok=False,
            status=PortalStatus.CONFIRMATION_REQUIRED.value,
            mensaje=(
                "Confirmación explícita requerida (confirm=True). "
                "No se realizó ninguna acción contra el portal."
            ),
        )

    allowed, reason = rpa_execution_allowed()
    if not allowed:
        logger.warning("Envío RPA de DIOT bloqueado por gates de computer_use: %s", reason)
        return RPASubmitOutcome(
            ok=False,
            status="rpa_disabled",
            mensaje=f"Modo rpa solicitado pero no permitido: {reason}",
        )

    if not cer_path or not key_path or not password:
        return RPASubmitOutcome(
            ok=False,
            status=PortalStatus.LOCAL_VALIDATION_ERROR.value,
            mensaje="Modo rpa requiere cer_path, key_path y password (credenciales e.firma).",
        )

    if not diot_content:
        return RPASubmitOutcome(
            ok=False,
            status=PortalStatus.LOCAL_VALIDATION_ERROR.value,
            mensaje="Contenido DIOT vacío; no se intenta el envío RPA.",
        )

    portal_url = os.environ.get("SAT_PORTAL_URL", "").strip()
    if not portal_url:
        return RPASubmitOutcome(
            ok=False,
            status="rpa_misconfigured",
            mensaje=(
                "SAT_PORTAL_URL no está configurado. El modo rpa requiere "
                "apuntar explícitamente al simulador de pruebas o a un "
                "entorno propio; nunca se asume una URL real del SAT."
            ),
        )

    tmp_path: Optional[str] = None
    driver: Optional[SATPortalRPADriver] = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="diot_rpa_", suffix=".txt", delete=False
        ) as tmp:
            tmp.write(diot_content)
            tmp_path = tmp.name

        driver = SATPortalRPADriver(
            portal_url=portal_url,
            cer_path=cer_path,
            key_path=key_path,
            password=password,
            rfc=rfc,
            headless=_headless(),
        )
        result = await driver.submit_diot(tmp_path, periodo=periodo, confirm=True)
    except SATPortalRealDomainBlocked as exc:
        # El candado de dominio hizo su trabajo. Se reporta explícito; NUNCA
        # se debilita ni se reintenta desde aquí.
        logger.critical("SATPortalRealDomainBlocked durante envío RPA: %s", exc)
        return RPASubmitOutcome(
            ok=False, status="blocked_real_sat_domain", mensaje=str(exc),
        )
    except (FileNotFoundError, ValueError) as exc:
        return RPASubmitOutcome(
            ok=False, status=PortalStatus.LOCAL_VALIDATION_ERROR.value, mensaje=str(exc),
        )
    finally:
        if driver is not None:
            try:
                await driver.close()
            except Exception:
                logger.debug("Error cerrando SATPortalRPADriver tras el envío", exc_info=True)
        if tmp_path and os.path.isfile(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                logger.debug("No se pudo borrar el temporal DIOT %s", tmp_path, exc_info=True)

    outcome = RPASubmitOutcome(
        ok=result.is_final_success,
        status=result.status.value,
        mensaje=result.mensaje,
        folio=result.folio_acuse,
        fecha_recepcion=result.fecha_recepcion,
        # Honestidad: simulado=True salvo que el driver alguna vez reporte
        # verificado_contra_sat_real=True (hoy SIEMPRE False, ver
        # sat_portal_rpa_driver.py).
        simulado=not result.verificado_contra_sat_real,
    )

    if result.is_final_success:
        detail = mark_diot_obligation_completed(
            tenant_id, periodo, user_id=declaration_id or ""
        )
        outcome.compliance_updated = bool(detail.get("updated"))
        outcome.compliance_detail = detail.get("reason") or (
            f"Obligación DIOT {detail.get('obligation_id')} marcada como cumplida."
        )

    return outcome
