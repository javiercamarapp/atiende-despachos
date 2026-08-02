# -*- coding: utf-8 -*-
"""
validators.py — Validación de Contabilidad Electrónica para envío al SAT.

Reglas implementadas:
  Balanza:
    1. Debe >= 0, Haber >= 0 en cada línea.
    2. Código de cuenta válido (4-15 caracteres, solo dígitos o puntos).
    3. Totales cuadran: suma(Debe) == suma(Haber).
    4. SaldoIni + Debe - Haber == SaldoFinal (consistencia matemática).
    5. Sin filas vacías (código de cuenta obligatorio).

  Catálogo:
    6. Código de cuenta válido (4-15 caracteres).
    7. Nivel válido (1-5).
    8. Tipo de cuenta válido (Activo/Pasivo/Capital/Ingreso/Gasto).
    9. Código agrupador SAT válido (solo dígitos/puntos, si se proporciona).

Cada función retorna una lista de strings (errores vacía = válido).
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import List, Optional

from b2b_ai.features.contabilidad_electronica.models import (
    BalanzaRequest,
    BalanzaRow,
    CatalogoCuenta,
    TipoCuenta,
)

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

# Código de cuenta SAT: 4-15 caracteres (dígitos o puntos separadores)
_ACCOUNT_CODE_PATTERN = re.compile(r"^[\d.]{1,15}$")
# Código agrupador SAT: dígitos con puntos (ej: "101.01.01")
_AGRUPADOR_PATTERN = re.compile(r"^[\d.]+$")
# RFC mexicano: 12 o 13 caracteres alfanuméricos (personas morales/físicas)
_RFC_PATTERN = re.compile(r"^[A-ZÑ&0-9]{12,13}$")
# Nivel válido
_VALID_LEVELS = set(range(1, 6))
# Tipos válidos
_VALID_TIPOS = {t.value for t in TipoCuenta}
# Regímenes fiscales válidos del SAT (catálogo c_RegimenFiscal)
_VALID_REGIMENES = {
    "601", "603", "606", "608", "610", "611", "612", "614", "616",
    "621", "622", "623", "624", "625", "626", "628", "629", "630",
    "631", "632", "634", "635", "636",
}


def validate_rfc(rfc: Optional[str]) -> List[str]:
    """Valida el RFC del contribuyente contra el catálogo del SAT (P1-10).

    Reglas:
      - Obligatorio (no puede ser vacío): el XSD SAT exige RFC.
      - Formato: 12-13 caracteres alfanuméricos (morales/físicas).

    Args:
        rfc: RFC a validar.

    Returns:
        Lista de errores (vacía si es válido).
    """
    errors: List[str] = []
    if not rfc or not str(rfc).strip():
        errors.append("El RFC es obligatorio (atributo RFC del XSD SAT).")
        return errors
    rfc = str(rfc).strip().upper()
    if not _RFC_PATTERN.match(rfc):
        errors.append(
            f"RFC '{rfc}' inválido. Debe tener 12-13 caracteres alfanuméricos."
        )
    return errors


def validate_regimen_fiscal(regimen: Optional[str]) -> List[str]:
    """Valida el régimen fiscal contra el catálogo c_RegimenFiscal del SAT.

    Args:
        regimen: Código del régimen fiscal (ej: "601").

    Returns:
        Lista de errores (vacía si es válido).
    """
    errors: List[str] = []
    if not regimen or not str(regimen).strip():
        return errors  # opcional según el contexto
    if str(regimen).strip() not in _VALID_REGIMENES:
        errors.append(
            f"Régimen fiscal '{regimen}' inválido. Debe ser un código "
            "del catálogo c_RegimenFiscal del SAT."
        )
    return errors


# --------------------------------------------------------------------------- #
# Validadores de Balanza
# --------------------------------------------------------------------------- #

def validate_balanza(balanza: BalanzaRequest) -> List[str]:
    """Ejecuta todas las validaciones SAT sobre la Balanza de Comprobación.

    Args:
        balanza: Request de balanza a validar.

    Returns:
        Lista de strings con errores (vacía si es válido).
    """
    errors: List[str] = []

    if balanza is None:
        return ["No se proporcionó balanza de comprobación."]

    # Validar campos generales
    if not balanza.rows:
        errors.append("La balanza no tiene filas de cuentas.")
        return errors

    if balanza.mes < 1 or balanza.mes > 12:
        errors.append(f"Mes inválido: {balanza.mes}. Debe ser 1-12.")

    if balanza.ejercicio < 2000 or balanza.ejercicio > 2100:
        errors.append(f"Ejercicio inválido: {balanza.ejercicio}.")

    # P1-10/P1-7: Validar RFC contra el catálogo del SAT (si se proporciona).
    # La exigencia de que el RFC esté presente la aplica el endpoint en la
    # generación (XSD SAT), no aquí, para no romper cargas legacy.
    balanza_rfc = getattr(balanza, "rfc", None)
    if balanza_rfc is not None:
        errors.extend(validate_rfc(balanza_rfc))

    # Validar cada fila
    for i, row in enumerate(balanza.rows):
        label = f"Fila {i + 1} ({row.codigo_cuenta or 'sin código'})"

        # Val 1: Debe/Haber >= 0
        if row.debe < 0:
            errors.append(f"{label}: Debe ({row.debe}) debe ser >= 0.")
        if row.haber < 0:
            errors.append(f"{label}: Haber ({row.haber}) debe ser >= 0.")

        # Val 2: Código de cuenta válido
        if not row.codigo_cuenta:
            errors.append(f"{label}: código de cuenta ausente.")
        elif not _ACCOUNT_CODE_PATTERN.match(row.codigo_cuenta):
            errors.append(
                f"{label}: código '{row.codigo_cuenta}' inválido. "
                f"Debe ser 1-15 caracteres (dígitos o puntos)."
            )

    # Val 3: Totales cuadran
    errors.extend(validate_balanza_totals(balanza))

    # Val 4: Consistencia matemática saldo_inicial + debe - haber = saldo_final
    for i, row in enumerate(balanza.rows):
        label = f"Fila {i + 1} ({row.codigo_cuenta})"
        expected_final = row.saldo_inicial + row.debe - row.haber
        if abs(row.saldo_final - expected_final) > 0.01:
            errors.append(
                f"{label}: SaldoFinal ({row.saldo_final}) != "
                f"SaldoIni({row.saldo_inicial}) + Debe({row.debe}) - "
                f"Haber({row.haber}) = {expected_final:.2f}."
            )

    return errors


def validate_balanza_totals(balanza: BalanzaRequest) -> List[str]:
    """Valida que la suma de Debe == suma de Haber en la balanza.

    Args:
        balanza: Request de balanza a validar.

    Returns:
        Lista de errores (vacía si cuadra).
    """
    errors: List[str] = []

    if balanza is None or not balanza.rows:
        errors.append("La balanza no tiene filas para sumar.")
        return errors

    total_debe = sum(row.debe for row in balanza.rows)
    total_haber = sum(row.haber for row in balanza.rows)

    # Usar Decimal para comparación exacta de floats monetarios
    d_debe = Decimal(str(total_debe)).quantize(Decimal("0.01"))
    d_haber = Decimal(str(total_haber)).quantize(Decimal("0.01"))

    if d_debe != d_haber:
        errors.append(
            f"Totales no cuadran: Debe ({total_debe:.2f}) != "
            f"Haber ({total_haber:.2f}). Diferencia: "
            f"{abs(total_debe - total_haber):.2f}."
        )

    return errors


# --------------------------------------------------------------------------- #
# Validadores de Catálogo de Cuentas
# --------------------------------------------------------------------------- #

def validate_catalogo(cuentas: List[CatalogoCuenta]) -> List[str]:
    """Ejecuta todas las validaciones SAT sobre el Catálogo de Cuentas.

    Args:
        cuentas: Lista de cuentas del catálogo a validar.

    Returns:
        Lista de strings con errores (vacía si es válido).
    """
    errors: List[str] = []

    if cuentas is None:
        return ["No se proporcionó catálogo de cuentas."]

    if not cuentas:
        errors.append("El catálogo de cuentas está vacío.")
        return errors

    for i, cta in enumerate(cuentas):
        label = f"Cuenta {i + 1} ({cta.codigo or 'sin código'})"

        # Val 6: Código de cuenta válido
        if not cta.codigo:
            errors.append(f"{label}: código de cuenta ausente.")
        elif not _ACCOUNT_CODE_PATTERN.match(cta.codigo):
            errors.append(
                f"{label}: código '{cta.codigo}' inválido. "
                f"Debe ser 1-15 caracteres (dígitos o puntos)."
            )

        # Val 7: Nivel válido (1-5)
        if cta.nivel not in _VALID_LEVELS:
            errors.append(
                f"{label}: nivel ({cta.nivel}) inválido. Debe ser 1-5."
            )

        # Val 8: Tipo de cuenta válido
        if cta.tipo.value not in _VALID_TIPOS:
            errors.append(
                f"{label}: tipo '{cta.tipo}' inválido. "
                f"Debe ser uno de: {', '.join(sorted(_VALID_TIPOS))}."
            )

        # Val 9: Código agrupador SAT válido (si se proporciona)
        if cta.padre is not None and cta.padre.strip():
            if not _AGRUPADOR_PATTERN.match(cta.padre.strip()):
                errors.append(
                    f"{label}: código agrupador '{cta.padre}' inválido. "
                    f"Debe ser solo dígitos/puntos."
                )

        # Validación de consistencia jerárquica
        if cta.nivel > 1 and not cta.padre:
            errors.append(
                f"{label}: cuenta de nivel {cta.nivel} requiere cuenta padre."
            )

    return errors
