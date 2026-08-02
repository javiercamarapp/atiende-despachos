# -*- coding: utf-8 -*-
"""rfc_validator.py — Validación de RFC mexicano.

Valida el RFC (Registro Federal de Contribuyentes) de personas físicas y
morales. Los RFC en México tienen una forma definida:

  Persona moral (12 caracteres):
      3 letras + fecha YYMMDD (6 dígitos) + 3 caracteres homoclave

  Persona física (13 caracteres):
      4 letras + fecha YYMMDD (6 dígitos) + 3 caracteres homoclave

  RFC genérico / extranjero (13 caracteres):
      XAXX010101000, XEXX010101000

La validación aquí es sintáctica (formato + dígitos de fecha válidos). La
verificación contra el SAT (que el RFC exista y esté activo) queda fuera de
alcance del MVP y se documenta como límite.
"""
from __future__ import annotations

import re

# Caracteres válidos en las posiciones alfabéticas (A-Z, Ñ, &) y la homoclave
# (A-Z, 0-9). Las posiciones no incluyen vocales como primera letra de física
# (según regla SAT: excluye las combinaciones prohibidas), pero por simplicidad
# aceptamos el rango completo; el énfasis está en la forma general y la fecha.
_ALPHA_RE = r"[A-ZÑ&]{3,4}"
_DATE_RE = r"(?P<year>\d{2})(?P<month>0[1-9]|1[0-2])(?P<day>0[1-9]|[12]\d|3[01])"
_HOMOCLAVE_RE = r"[A-Z0-9]{3}"

# RFC completo: moral (12) o física (13). La fecha se valida numéricamente aparte.
RFC_MORAL_RE = re.compile(r"^[A-ZÑ&]{3}\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])[A-Z0-9]{3}$")
RFC_FISICA_RE = re.compile(r"^[A-ZÑ&]{4}\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])[A-Z0-9]{3}$")

# RFC genérico / extranjero permitido
RFC_GENERICO = {"XAXX010101000", "XEXX010101000"}

# RFC genérico con formato de 12 (moral) usado a veces para personas morales
RFC_GENERICO_MORAL = {"XAXX010101000"}


def normalize_rfc(rfc: str) -> str:
    """Limpia el RFC: mayúsculas, sin espacios ni guiones."""
    if rfc is None:
        return ""
    return rfc.upper().replace(" ", "").replace("-", "").replace("_", "").strip()


def _valid_date(yy: str, mm: str, dd: str) -> bool:
    """Valida que la fecha YYMMDD sea real (incluye años bisiestos)."""
    try:
        import calendar
        month = int(mm)
        day = int(dd)
        if month < 1 or month > 12:
            return False
        # El año del RFC es de dos dígitos; asumimos siglo 19xx/20xx.
        year_4 = 1900 + int(yy) if int(yy) >= 0 else 2000 + int(yy)
        # Mapeo simple: 00-99 -> 19xx para fechas plausibles de personas vivas.
        if int(yy) > 70:
            year_4 = 1900 + int(yy)
        else:
            year_4 = 2000 + int(yy)
        max_day = calendar.monthrange(year_4, month)[1]
        return 1 <= day <= max_day
    except (ValueError, TypeError):
        return False


def is_valid_mx_rfc(rfc: str) -> bool:
    """Devuelve True si el RFC tiene forma sintáctica válida.

    Acepta el RFC genérico XAXX010101000 / XEXX010101000 y formas de persona
    física (13) y moral (12). La fecha embebida debe ser calendario real.
    """
    norm = normalize_rfc(rfc)
    if not norm:
        return False
    if norm in RFC_GENERICO:
        return True

    if len(norm) == 12:
        m = RFC_MORAL_RE.match(norm)
        if not m:
            return False
    elif len(norm) == 13:
        m = RFC_FISICA_RE.match(norm)
        if not m:
            return False
    else:
        return False

    # Extraer YYMMDD: para 12 (moral) posiciones 3-8, para 13 (física) 4-9.
    if len(norm) == 12:
        yy, mm, dd = norm[3:5], norm[5:7], norm[7:9]
    else:
        yy, mm, dd = norm[4:6], norm[6:8], norm[8:10]
    return _valid_date(yy, mm, dd)


def describe_rfc_error(rfc: str) -> str:
    """Devuelve un mensaje descriptivo de por qué el RFC es inválido."""
    norm = normalize_rfc(rfc)
    if not norm:
        return "RFC vacío"
    if len(norm) not in (12, 13):
        return f"RFC '{rfc}' debe tener 12 (moral) o 13 (física) caracteres, tiene {len(norm)}"
    if not is_valid_mx_rfc(norm):
        return f"RFC '{rfc}' no tiene formato válido (letras + fecha + homoclave)"
    return ""
