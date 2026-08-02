# -*- coding: utf-8 -*-
"""error_handler.py — SAT ErrorHandler with 14 specific error codes and retries.

Handles the 14 specific rejection/error codes from SAT per BLUEPRINT §3.5:
  1.  UUID no válido
  2.  RFC incorrecto
  3.  Periodo incorrecto
  4.  Base cero en pago provisional
  5.  DIOT con omisiones
  6.  Tipo de cambio incorrecto
  7.  Doble declaración
  8.  Firma FIEL/CSD expirada
  9.  Estructura XML inválida
  10. Conceptos no deducibles
  11. IVA acreditable incorrecto
  12. ISR en ceros
  13. Plazo vencido
  14. Certificado sin vigencia

Each error has: severity, retry strategy, auto-fix capability, and
human escalation path.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("b2b_ai.declaraciones.error_handler")


class ErrorSeverity(str, Enum):
    """Error severity levels."""
    LOW = "low"           # Warning, can proceed
    MEDIUM = "medium"     # Should fix before submission
    HIGH = "high"         # Must fix, submission will be rejected
    CRITICAL = "critical" # Blocks all operations


class RetryStrategy(str, Enum):
    """Retry strategy for each error type."""
    NO_RETRY = "no_retry"               # Don't retry, fix data first
    RETRY_IMMEDIATE = "retry_immediate"  # Retry immediately
    RETRY_BACKOFF = "retry_backoff"      # Retry with exponential backoff
    RETRY_AFTER_FIX = "retry_after_fix"  # Fix data, then retry
    MANUAL_ONLY = "manual_only"          # Requires human intervention


class ErrorCode(str, Enum):
    """SAT-specific error codes per BLUEPRINT §3.5."""
    UUID_INVALIDO = "SAT-001"
    RFC_INCORRECTO = "SAT-002"
    PERIODO_INCORRECTO = "SAT-003"
    BASE_CERO = "SAT-004"
    DIOT_OMISIONES = "SAT-005"
    TIPO_CAMBIO = "SAT-006"
    DUPLICADA = "SAT-007"
    FIRMA_EXPIRADA = "SAT-008"
    XML_INVALIDO = "SAT-009"
    NO_DEDUCIBLE = "SAT-010"
    IVA_ACREDITABLE = "SAT-011"
    ISR_CEROS = "SAT-012"
    PLAZO_VENCIDO = "SAT-013"
    CERTIFICADO_VENCIDO = "SAT-014"


@dataclass
class SATError:
    """A specific SAT error with metadata."""
    code: ErrorCode
    message: str
    severity: ErrorSeverity
    retry_strategy: RetryStrategy
    auto_fixable: bool
    requires_human: bool
    fix_suggestion: str
    max_retries: int = 3
    details: Optional[str] = None


@dataclass
class RetryAttempt:
    """Record of a retry attempt."""
    attempt_number: int
    timestamp: float
    error_code: ErrorCode
    success: bool
    message: str


@dataclass
class ErrorHandlerResult:
    """Result of error handling."""
    handled: bool
    retriable: bool
    auto_fixed: bool
    requires_human: bool
    error: SATError
    retry_attempts: List[RetryAttempt] = field(default_factory=list)
    total_attempts: int = 0
    final_success: bool = False
    message: str = ""


# ===================================================================
# SAT Error Definitions (14 specific errors from BLUEPRINT §3.5)
# ===================================================================

SAT_ERRORS: Dict[ErrorCode, SATError] = {
    ErrorCode.UUID_INVALIDO: SATError(
        code=ErrorCode.UUID_INVALIDO,
        message="UUID del CFDI no válido o cancelado",
        severity=ErrorSeverity.HIGH,
        retry_strategy=RetryStrategy.RETRY_AFTER_FIX,
        auto_fixable=False,
        requires_human=False,
        fix_suggestion=(
            "Validar cada UUID contra el PAC antes de incluir en declaración. "
            "Remover CFDIs cancelados y buscar sustitutos."
        ),
    ),
    ErrorCode.RFC_INCORRECTO: SATError(
        code=ErrorCode.RFC_INCORRECTO,
        message="RFC incorrecto — error de captura o homoclave mal",
        severity=ErrorSeverity.HIGH,
        retry_strategy=RetryStrategy.RETRY_AFTER_FIX,
        auto_fixable=True,
        requires_human=False,
        fix_suggestion=(
            "Validar RFC con dígito verificador (Art. 23 CFF). "
            "Corregir homoclave si es necesario."
        ),
    ),
    ErrorCode.PERIODO_INCORRECTO: SATError(
        code=ErrorCode.PERIODO_INCORRECTO,
        message="Periodo fuera de rango o formato inválido",
        severity=ErrorSeverity.HIGH,
        retry_strategy=RetryStrategy.RETRY_AFTER_FIX,
        auto_fixable=True,
        requires_human=False,
        fix_suggestion=(
            "Verificar que el periodo esté dentro del ejercicio fiscal actual. "
            "Formato: YYYY-MM para mensuales, YYYY para anuales."
        ),
    ),
    ErrorCode.BASE_CERO: SATError(
        code=ErrorCode.BASE_CERO,
        message="Base cero en pago provisional — no se determinó utilidad fiscal",
        severity=ErrorSeverity.MEDIUM,
        retry_strategy=RetryStrategy.RETRY_AFTER_FIX,
        auto_fixable=True,
        requires_human=False,
        fix_suggestion=(
            "Verificar que haya ingresos y deducciones > 0. "
            "Si hay pérdida fiscal, generar con coeficiente."
        ),
    ),
    ErrorCode.DIOT_OMISIONES: SATError(
        code=ErrorCode.DIOT_OMISIONES,
        message="DIOT con omisiones — CFDIs no incluidos",
        severity=ErrorSeverity.MEDIUM,
        retry_strategy=RetryStrategy.RETRY_AFTER_FIX,
        auto_fixable=True,
        requires_human=False,
        fix_suggestion=(
            "Cruce automático: CFDIs en DB vs. DIOT generada. "
            "Alertar diferencias y agregar CFDIs faltantes."
        ),
    ),
    ErrorCode.TIPO_CAMBIO: SATError(
        code=ErrorCode.TIPO_CAMBIO,
        message="Tipo de cambio incorrecto",
        severity=ErrorSeverity.MEDIUM,
        retry_strategy=RetryStrategy.RETRY_AFTER_FIX,
        auto_fixable=True,
        requires_human=False,
        fix_suggestion=(
            "Usar siempre tipo de cambio oficial Banco de México "
            "(API pública) del último día del mes."
        ),
    ),
    ErrorCode.DUPLICADA: SATError(
        code=ErrorCode.DUPLICADA,
        message="Doble declaración — ya existe declaración del periodo",
        severity=ErrorSeverity.CRITICAL,
        retry_strategy=RetryStrategy.NO_RETRY,
        auto_fixable=False,
        requires_human=True,
        fix_suggestion=(
            "Verificar si ya existe declaración del periodo en tabla declarations. "
            "Si es complementaria, usar tipo 'Complementaria'. "
            "Si es error, cancelar la duplicada."
        ),
    ),
    ErrorCode.FIRMA_EXPIRADA: SATError(
        code=ErrorCode.FIRMA_EXPIRADA,
        message="Firma FIEL/CSD expirada",
        severity=ErrorSeverity.CRITICAL,
        retry_strategy=RetryStrategy.MANUAL_ONLY,
        auto_fixable=False,
        requires_human=True,
        fix_suggestion=(
            "Renovar FIEL/CSD en portal SAT. "
            "Verificar vigencia del certificado al inicio de cada ciclo."
        ),
    ),
    ErrorCode.XML_INVALIDO: SATError(
        code=ErrorCode.XML_INVALIDO,
        message="Estructura XML inválida",
        severity=ErrorSeverity.HIGH,
        retry_strategy=RetryStrategy.RETRY_AFTER_FIX,
        auto_fixable=True,
        requires_human=False,
        fix_suggestion=(
            "Validar contra XSD del SAT antes de firmar. "
            "Verificar namespaces, encoding y estructura."
        ),
    ),
    ErrorCode.NO_DEDUCIBLE: SATError(
        code=ErrorCode.NO_DEDUCIBLE,
        message="Conceptos no deducibles incluidos en declaración",
        severity=ErrorSeverity.LOW,
        retry_strategy=RetryStrategy.RETRY_AFTER_FIX,
        auto_fixable=True,
        requires_human=False,
        fix_suggestion=(
            "Filtrar por catálogo de conceptos deducibles (Art. 26 LISR). "
            "Remover gastos personales detectados."
        ),
    ),
    ErrorCode.IVA_ACREDITABLE: SATError(
        code=ErrorCode.IVA_ACREDITABLE,
        message="IVA acreditable incorrecto — proporcionalidad mal calculada",
        severity=ErrorSeverity.HIGH,
        retry_strategy=RetryStrategy.RETRY_AFTER_FIX,
        auto_fixable=True,
        requires_human=False,
        fix_suggestion=(
            "Recalcular proporción: ingresos_gravados / ingresos_totales. "
            "Verificar que no se incluyan CFDIs exentos en el cálculo."
        ),
    ),
    ErrorCode.ISR_CEROS: SATError(
        code=ErrorCode.ISR_CEROS,
        message="ISR en ceros — utilidad fiscal no determinada",
        severity=ErrorSeverity.MEDIUM,
        retry_strategy=RetryStrategy.RETRY_AFTER_FIX,
        auto_fixable=True,
        requires_human=False,
        fix_suggestion=(
            "Si hay ingresos, calcular utilidad. "
            "Si resultado es negativo (pérdida fiscal), declarar con coeficiente."
        ),
    ),
    ErrorCode.PLAZO_VENCIDO: SATError(
        code=ErrorCode.PLAZO_VENCIDO,
        message="Plazo vencido — se pasó el día 17",
        severity=ErrorSeverity.CRITICAL,
        retry_strategy=RetryStrategy.MANUAL_ONLY,
        auto_fixable=False,
        requires_human=True,
        fix_suggestion=(
            "Presentar declaración extemporánea con recargos y actualizaciones. "
            "Scheduler debe enviar alertas día 10, 14 y 16 del mes siguiente."
        ),
    ),
    ErrorCode.CERTIFICADO_VENCIDO: SATError(
        code=ErrorCode.CERTIFICADO_VENCIDO,
        message="Certificado sin vigencia (> 4 años)",
        severity=ErrorSeverity.CRITICAL,
        retry_strategy=RetryStrategy.MANUAL_ONLY,
        auto_fixable=False,
        requires_human=True,
        fix_suggestion=(
            "Solicitar nuevo CSD en portal SAT. "
            "Monitorear fecha de vencimiento, alertar 60 días antes."
        ),
    ),
}


class SATErrorHandler:
    """Handle SAT-specific errors with retry logic.

    Usage:
        handler = SATErrorHandler()
        result = handler.handle_error(ErrorCode.RFC_INCORRECTO, details="...")
        if result.retriable:
            # Retry logic
    """

    def __init__(self, max_global_retries: int = 3):
        self._max_global_retries = max_global_retries
        self._retry_log: Dict[ErrorCode, List[RetryAttempt]] = {}

    def get_error_definition(self, code: ErrorCode) -> SATError:
        """Get the full error definition for an error code."""
        return SAT_ERRORS.get(code, SATError(
            code=code,
            message=f"Error desconocido: {code.value}",
            severity=ErrorSeverity.HIGH,
            retry_strategy=RetryStrategy.MANUAL_ONLY,
            auto_fixable=False,
            requires_human=True,
            fix_suggestion="Contactar soporte técnico.",
        ))

    def handle_error(
        self,
        code: ErrorCode,
        details: Optional[str] = None,
        attempt: int = 1,
    ) -> ErrorHandlerResult:
        """Handle a specific SAT error.

        Determines retry strategy, checks attempt limits, and returns
        actionable result.

        Args:
            code: The SAT error code
            details: Additional error details (e.g., from SAT response)
            attempt: Current attempt number

        Returns:
            ErrorHandlerResult with handling decision
        """
        error = SAT_ERRORS.get(code)
        if error is None:
            # Unknown error
            return ErrorHandlerResult(
                handled=False,
                retriable=False,
                auto_fixed=False,
                requires_human=True,
                error=SATError(
                    code=code,
                    message=f"Error desconocido: {code.value}",
                    severity=ErrorSeverity.CRITICAL,
                    retry_strategy=RetryStrategy.MANUAL_ONLY,
                    auto_fixable=False,
                    requires_human=True,
                    fix_suggestion="Contactar soporte técnico.",
                ),
                message=f"Código de error desconocido: {code.value}",
            )

        # Add details if provided
        if details:
            error.details = details

        # Check if we've exceeded retries for this error
        past_attempts = self._retry_log.get(code, [])
        total_attempts = len(past_attempts) + 1

        # Determine retriable
        retriable = (
            error.retry_strategy not in (
                RetryStrategy.NO_RETRY,
                RetryStrategy.MANUAL_ONLY,
            )
            and total_attempts <= error.max_retries
        )

        # Record attempt
        attempt_record = RetryAttempt(
            attempt_number=total_attempts,
            timestamp=time.time(),
            error_code=code,
            success=False,
            message=details or error.message,
        )
        if code not in self._retry_log:
            self._retry_log[code] = []
        self._retry_log[code].append(attempt_record)

        # Log
        logger.warning(
            "SAT Error [%s] %s (attempt %d/%d): %s — %s",
            code.value, error.severity.value,
            total_attempts, error.max_retries,
            error.message, error.fix_suggestion,
        )

        return ErrorHandlerResult(
            handled=True,
            retriable=retriable,
            auto_fixed=error.auto_fixable and retriable,
            requires_human=error.requires_human,
            error=error,
            retry_attempts=self._retry_log.get(code, []),
            total_attempts=total_attempts,
            message=(
                f"[{code.value}] {error.message}. "
                f"{'Reintentable' if retriable else 'No reintentable'}. "
                f"Sugerencia: {error.fix_suggestion}"
            ),
        )

    def should_retry(self, code: ErrorCode, current_attempt: int) -> bool:
        """Check if we should retry for a given error code."""
        error = SAT_ERRORS.get(code)
        if error is None:
            return False

        if error.retry_strategy in (RetryStrategy.NO_RETRY, RetryStrategy.MANUAL_ONLY):
            return False

        return current_attempt < error.max_retries

    def get_retry_delay(self, code: ErrorCode, attempt: int) -> float:
        """Get delay in seconds before next retry (exponential backoff)."""
        error = SAT_ERRORS.get(code)
        if error is None or error.retry_strategy != RetryStrategy.RETRY_BACKOFF:
            return 0.0

        # Exponential backoff: 1s, 2s, 4s, 8s...
        return min(2.0 ** attempt, 30.0)

    def get_error_summary(self) -> Dict[str, Any]:
        """Get summary of all errors handled in this session."""
        summary: Dict[str, Any] = {
            "total_errors": 0,
            "by_severity": {},
            "by_code": {},
            "requiring_human": [],
        }

        for code, attempts in self._retry_log.items():
            error = SAT_ERRORS.get(code)
            if error is None:
                continue

            summary["total_errors"] += len(attempts)
            severity = error.severity.value
            summary["by_severity"][severity] = (
                summary["by_severity"].get(severity, 0) + len(attempts)
            )
            summary["by_code"][code.value] = len(attempts)

            if error.requires_human:
                summary["requiring_human"].append({
                    "code": code.value,
                    "message": error.message,
                    "fix": error.fix_suggestion,
                })

        return summary

    def reset(self):
        """Reset retry logs for a fresh session."""
        self._retry_log.clear()
