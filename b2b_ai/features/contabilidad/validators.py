# -*- coding: utf-8 -*-
"""
validators.py — Validación de Contabilidad Electrónica contra reglas SAT.

Reglas implementadas:
  Balanza:
    1. Debe >= 0, Haber >= 0, SaldoDeudor >= 0, SaldoAcreedor >= 0.
    2. Código de cuenta válido (solo dígitos, 4-15 caracteres).
    3. Totales cuadran: suma(Debe) == suma(Haber) en la balanza.
    4. SaldoDeudor y SaldoAcreedor mutuamente excluyentes (uno cero, otro cero).
    5. SaldoDeudor == SaldoIni + Debe - Haber (si es deudor).
    6. SaldoAcreedor == SaldoIni - Debe + Haber (si es acreedor).

  Catálogo:
    7. Código de cuenta válido (solo dígitos, 4-15 caracteres).
    8. Nivel válido (1-5).
    9. Naturaleza debe ser D o A.
    10. Código agrupador SAT válido (si se proporciona, solo dígitos).

  Estado de Resultados:
    11. Importe no nulo.

Cada función retorna una lista de strings (errores vacía = válido).
"""
from __future__ import annotations

from decimal import Decimal
import re
from typing import List

from b2b_ai.features.contabilidad.parser import (
    BalanzaData,
    CatalogoData,
    EstadoResultadosData,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Cuentas SAT: código solo dígitos, 4 a 15 caracteres
_ACCOUNT_CODE_PATTERN = re.compile(r"^\d{4,15}$")
# Código agrupador SAT: solo dígitos
# Código agrupador SAT: dígitos con puntos (ej: "101.01.01")
_AGRUPADOR_PATTERN = re.compile(r"^[\d.]+$")


# ---------------------------------------------------------------------------
# Validadores de Balanza
# ---------------------------------------------------------------------------

def validate_balanza_saldos_no_negativos(
    balanza: BalanzaData,
) -> List[str]:
    """Val. 1: Debe >= 0, Haber >= 0, SaldoDeudor >= 0, SaldoAcreedor >= 0."""
    errors: List[str] = []
    for i, cuenta in enumerate(balanza.cuentas):
        label = f"Cuenta {i + 1} ({cuenta.num_cuenta})"
        if cuenta.debe is not None and cuenta.debe < 0:
            errors.append(f"{label}: Debe ({cuenta.debe}) debe ser >= 0.")
        if cuenta.haber is not None and cuenta.haber < 0:
            errors.append(f"{label}: Haber ({cuenta.haber}) debe ser >= 0.")
        if cuenta.saldo_deudor is not None and cuenta.saldo_deudor < 0:
            errors.append(
                f"{label}: SaldoDeudor ({cuenta.saldo_deudor}) debe ser >= 0."
            )
        if cuenta.saldo_acreedor is not None and cuenta.saldo_acreedor < 0:
            errors.append(
                f"{label}: SaldoAcreedor ({cuenta.saldo_acreedor}) debe ser >= 0."
            )
    return errors


def validate_balanza_codigo_cuenta(
    balanza: BalanzaData,
) -> List[str]:
    """Val. 2: Código de cuenta válido (solo dígitos, 4-15 caracteres)."""
    errors: List[str] = []
    for i, cuenta in enumerate(balanza.cuentas):
        label = f"Cuenta {i + 1}"
        if not cuenta.num_cuenta:
            errors.append(f"{label}: código de cuenta ausente.")
        elif not _ACCOUNT_CODE_PATTERN.match(cuenta.num_cuenta):
            errors.append(
                f"{label}: código '{cuenta.num_cuenta}' inválido. "
                f"Debe ser 4-15 dígitos."
            )
    return errors


def validate_balanza_totales_cuadran(
    balanza: BalanzaData,
) -> List[str]:
    """Val. 3: suma(Debe) == suma(Haber) en la balanza."""
    errors: List[str] = []
    if not balanza.cuentas:
        errors.append("La balanza no tiene cuentas.")
        return errors
    total_debe = Decimal("0")
    for c in balanza.cuentas:
        if c.debe is not None:
            total_debe += c.debe
    total_haber = Decimal("0")
    for c in balanza.cuentas:
        if c.haber is not None:
            total_haber += c.haber
    if total_debe != total_haber:
        errors.append(
            f"Totales no cuadran: Debe ({total_debe}) != Haber ({total_haber})."
        )
    return errors


def validate_balanza_saldos_excluyentes(
    balanza: BalanzaData,
) -> List[str]:
    """Val. 4: SaldoDeudor y SaldoAcreedor mutuamente excluyentes."""
    errors: List[str] = []
    for i, cuenta in enumerate(balanza.cuentas):
        sd = cuenta.saldo_deudor or 0
        sa = cuenta.saldo_acreedor or 0
        if sd > 0 and sa > 0:
            errors.append(
                f"Cuenta {i + 1} ({cuenta.num_cuenta}): "
                f"SaldoDeudor ({sd}) y SaldoAcreedor ({sa}) no pueden "
                f"ambos ser > 0."
            )
    return errors


def validate_balanza_saldo_consistente(
    balanza: BalanzaData,
) -> List[str]:
    """Val. 5-6: SaldoDeudor/SaldoAcreedor consistente con SaldoIni, Debe, Haber.

    Si saldo_deudor > 0: saldo_deudor == saldo_inicial + debe - haber.
    Si saldo_acreedor > 0: saldo_acreedor == saldo_inicial - debe + haber.
    """
    errors: List[str] = []
    for i, cuenta in enumerate(balanza.cuentas):
        label = f"Cuenta {i + 1} ({cuenta.num_cuenta})"
        ini = cuenta.saldo_inicial or 0
        debe = cuenta.debe or 0
        haber = cuenta.haber or 0
        sd = cuenta.saldo_deudor or 0
        sa = cuenta.saldo_acreedor or 0

        if sd > 0:
            expected = ini + debe - haber
            if sd != expected:
                errors.append(
                    f"{label}: SaldoDeudor ({sd}) != "
                    f"SaldoIni({ini}) + Debe({debe}) - Haber({haber}) "
                    f"= {expected}."
                )
        elif sa > 0:
            expected = ini - debe + haber
            if sa != expected:
                errors.append(
                    f"{label}: SaldoAcreedor ({sa}) != "
                    f"SaldoIni({ini}) - Debe({debe}) + Haber({haber}) "
                    f"= {expected}."
                )
    return errors


def validate_balanza(balanza: BalanzaData) -> List[str]:
    """Ejecuta todas las validaciones SAT sobre la Balanza de Comprobación."""
    if balanza is None:
        return ["No se encontró nodo Balanza de Comprobación en el XML."]

    errors: List[str] = []
    errors.extend(validate_balanza_saldos_no_negativos(balanza))
    errors.extend(validate_balanza_codigo_cuenta(balanza))
    errors.extend(validate_balanza_totales_cuadran(balanza))
    errors.extend(validate_balanza_saldos_excluyentes(balanza))
    errors.extend(validate_balanza_saldo_consistente(balanza))
    return errors


# ---------------------------------------------------------------------------
# Validadores de Catálogo de Cuentas
# ---------------------------------------------------------------------------

def validate_catalogo_codigo_cuenta(
    catalogo: CatalogoData,
) -> List[str]:
    """Val. 7: Código de cuenta válido (solo dígitos, 4-15 caracteres)."""
    errors: List[str] = []
    for i, cuenta in enumerate(catalogo.cuentas):
        label = f"Cuenta {i + 1}"
        if not cuenta.num_cuenta:
            errors.append(f"{label}: código de cuenta ausente.")
        elif not _ACCOUNT_CODE_PATTERN.match(cuenta.num_cuenta):
            errors.append(
                f"{label}: código '{cuenta.num_cuenta}' inválido. "
                f"Debe ser 4-15 dígitos."
            )
    return errors


def validate_catalogo_nivel(catalogo: CatalogoData) -> List[str]:
    """Val. 8: Nivel válido (1-5)."""
    errors: List[str] = []
    for i, cuenta in enumerate(catalogo.cuentas):
        label = f"Cuenta {i + 1} ({cuenta.num_cuenta})"
        if cuenta.nivel is None:
            errors.append(f"{label}: Nivel ausente.")
        elif cuenta.nivel < 1 or cuenta.nivel > 5:
            errors.append(
                f"{label}: Nivel ({cuenta.nivel}) inválido. Debe ser 1-5."
            )
    return errors


def validate_catalogo_naturaleza(
    catalogo: CatalogoData,
) -> List[str]:
    """Val. 9: Naturaleza debe ser D o A."""
    errors: List[str] = []
    for i, cuenta in enumerate(catalogo.cuentas):
        label = f"Cuenta {i + 1} ({cuenta.num_cuenta})"
        nat = (cuenta.naturaleza or "").strip().upper()
        if not nat:
            errors.append(f"{label}: Naturaleza ausente.")
        elif nat not in ("D", "A"):
            errors.append(
                f"{label}: Naturaleza '{cuenta.naturaleza}' inválida. "
                f"Debe ser D (Deudor) o A (Acreedor)."
            )
    return errors


def validate_catalogo_codigo_agrupador(
    catalogo: CatalogoData,
) -> List[str]:
    """Val. 10: Código agrupador SAT válido (solo dígitos, si se proporciona)."""
    errors: List[str] = []
    for i, cuenta in enumerate(catalogo.cuentas):
        label = f"Cuenta {i + 1} ({cuenta.num_cuenta})"
        agrupador = cuenta.codigo_agrupador
        if agrupador is not None:
            agrupador = agrupador.strip()
            if agrupador and not _AGRUPADOR_PATTERN.match(agrupador):
                errors.append(
                    f"{label}: CodigoAgrupador '{agrupador}' inválido. "
                    f"Debe ser solo dígitos."
                )
    return errors


def validate_catalogo(catalogo: CatalogoData) -> List[str]:
    """Ejecuta todas las validaciones SAT sobre el Catálogo de Cuentas."""
    if catalogo is None:
        return ["No se encontró nodo Catálogo de Cuentas en el XML."]

    errors: List[str] = []
    errors.extend(validate_catalogo_codigo_cuenta(catalogo))
    errors.extend(validate_catalogo_nivel(catalogo))
    errors.extend(validate_catalogo_naturaleza(catalogo))
    errors.extend(validate_catalogo_codigo_agrupador(catalogo))
    return errors


# ---------------------------------------------------------------------------
# Validadores de Estado de Resultados
# ---------------------------------------------------------------------------

def validate_estado_resultados_importes(
    er: EstadoResultadosData,
) -> List[str]:
    """Val. 11: Importe no nulo en cada línea."""
    errors: List[str] = []
    for i, linea in enumerate(er.lineas):
        label = f"Línea {i + 1} ({linea.concepto})"
        if linea.importe is None:
            errors.append(f"{label}: Importe ausente.")
    return errors


def validate_estado_resultados(
    er: EstadoResultadosData,
) -> List[str]:
    """Ejecuta todas las validaciones sobre el Estado de Resultados."""
    if er is None:
        return ["No se encontró nodo Estado de Resultados en el XML."]

    errors: List[str] = []
    errors.extend(validate_estado_resultados_importes(er))
    return errors
