# -*- coding: utf-8 -*-
"""
categorizer.py — Motor de auto-categorización IA para transacciones bancarias MX.

Clasifica una transacción bancaria en una :class:`Category` contable usando:

1. **Reglas por RFC** (prioridad alta): si la contraparte/caja o el proveedor
   coincide con un RFC configurado, se asigna esa categoría directamente.
2. **Reglas por monto**: rangos opcionales (p. ej. nómina si monto >= umbral).
3. **Patrones de palabras clave**: matching regex sobre descripción/referencia/
   contraparte para capturar conceptos comunes del landscape MX (nómina, SAT,
   servicios, transferencias, comisiones, etc.).
4. **Canal de pago**: SPEI/CoDi/tarjeta orientan la categoría cuando no hay
   evidencia textual.

Soporte futuro: la clase acepta un ``llm_router`` opcional (callable) que se
invoca solo cuando las reglas no alcanzan; si devuelve una categoría válida,
se usa. Esto permite pluggear un LLM sin romper el comportamiento determinista
rule-based.

Uso:
    categorizer = TransactionCategorizer()                      # reglas por defecto
    categorizer.add_rfc_rule("PAP850101JKL", Category.PROVEEDOR)
    cat = categorizer.categorize_transaction(txn)               # txn dict o Transaction
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Pattern, Tuple, Union

from b2b_ai.features.bank_feeds.models import Category, Transaction, TransactionType

logger = logging.getLogger("b2b_ai.bank_feeds")

# ---------------------------------------------------------------------------
# Reglas por defecto: (patrón regex insensible, categoría)
# El orden importa — la primera coincidencia gana. Las categorías esperadas
# del entregable (nomina, proveedor, impuestos/SAT, servicios, transferencias,
# depositos, retiros, comisiones bancarias) se mapean a Category.
# ---------------------------------------------------------------------------
DEFAULT_KEYWORD_RULES: List[Tuple[str, Category]] = [
    # Nómina
    (r"nomina|sueldo|salario|quincena|pago.*(nomi|personal|emplead)", Category.NOMINA),
    # Impuestos / SAT
    (r"\bsat\b|impuesto|retencion|\bisr\b|\biva\b|diot|declaracion|pago.*sat|automatico.*sat",
     Category.IMPUESTOS),
    # Comisiones / financieros
    (r"comision|interes|anualidad|membresia|seguro|mantenimiento.*cuenta|pago.*tarjeta",
     Category.FINANCIEROS),
    # Proveedores / compras
    (r"proveedor|factura|compra|mercancia|inventario|insumo|pago.*proveedor|adquisicion",
     Category.COMPRAS),
    # Servicios
    (r"renta|arrendamiento|luz|agua|internet|telefono|software|servicio|honorarios|energia",
     Category.SERVICIOS),
    # Transferencias (entre cuentas / SPEI / CLABE)
    (r"transferencia|spei|abono|clabe|traspaso|envio|movimiento.*interna",
     Category.TRANSFERENCIAS),
    # Depósitos / ventas / clientes
    (r"deposito|abono.*cuenta|cobro|codi|venta|ingreso|cliente|pagado.*cliente|recibo",
     Category.VENTAS),
]

# Canal → categoría cuando no hay coincidencia textual.
CHANNEL_HINTS: Dict[str, Category] = {
    "SPEI": Category.TRANSFERENCIAS,
    "CODI": Category.VENTAS,
    "NOMINA": Category.NOMINA,
    "TARJETA": Category.FINANCIEROS,
}

# --- Helpers internos --------------------------------------------------------


def _lower(value: Optional[str]) -> str:
    """Minúsculas sin acentos (p. ej. 'comisión' -> 'comision') para un
    matching de palabras clave robusto en texto bancario MX."""
    import unicodedata
    text = (value or "").strip().lower()
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


def _clean_rfc(value: Optional[str]) -> str:
    """Normaliza un RFC a mayúsculas sin espacios."""
    return (value or "").upper().replace(" ", "").strip()


def _coerce_amount(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def _get_field(txn: Any, name: str) -> Any:
    """Lee un atributo de un dict, un objeto o un Pydantic model."""
    if isinstance(txn, dict):
        return txn.get(name)
    return getattr(txn, name, None)


# ---------------------------------------------------------------------------
# TransactionCategorizer
# ---------------------------------------------------------------------------


class TransactionCategorizer:
    """Motor de categorización rule-based + pattern matching para MX.

    Configurable en tiempo de construcción o en caliente:

        cat = TransactionCategorizer(
            keyword_rules=[...],
            amount_rules=[(Category.NOMINA, 10000.0, None)],   # (cat, min, max)
            channel_hints={...},
        )
        cat.add_rfc_rule("PAP850101JKL", Category.PROVEEDOR)

    ``llm_router`` (opcional) es un callable ``(txn) -> Category|str|None`` que
    se consulta únicamente cuando las reglas no clasifican. Su salida se valida
    contra el enum antes de usarse.
    """

    def __init__(
        self,
        keyword_rules: Optional[List[Tuple[str, Category]]] = None,
        amount_rules: Optional[List[Tuple[Category, Optional[float], Optional[float]]]] = None,
        channel_hints: Optional[Dict[str, Category]] = None,
        default_category: Category = Category.OTROS,
        llm_router: Optional[Callable[[Any], Any]] = None,
    ) -> None:
        self._keyword_rules: List[Tuple[Pattern, Category]] = [
            (re.compile(pattern, re.IGNORECASE), cat)
            for pattern, cat in (keyword_rules or DEFAULT_KEYWORD_RULES)
        ]
        self._amount_rules: List[Tuple[Category, Optional[float], Optional[float]]] = [
            r for r in (amount_rules or [])
        ]
        self._channel_hints: Dict[str, Category] = dict(channel_hints or CHANNEL_HINTS)
        self._rfc_rules: Dict[str, Category] = {}
        self.default_category = default_category
        self.llm_router = llm_router

    # ------------------------------------------------------------------
    # Configuración
    # ------------------------------------------------------------------
    def add_rfc_rule(self, rfc: str, category: Category) -> None:
        """Asocia un RFC (emisor/proveedor/cliente) a una categoría."""
        cleaned = _clean_rfc(rfc)
        if not cleaned:
            raise ValueError("RFC no puede estar vacío")
        self._rfc_rules[cleaned] = category

    def add_keyword_rule(self, pattern: str, category: Category) -> None:
        """Agrega una regla de palabra clave (regex insensible)."""
        self._keyword_rules.append((re.compile(pattern, re.IGNORECASE), category))

    def add_amount_rule(
        self,
        category: Category,
        min_amount: Optional[float] = None,
        max_amount: Optional[float] = None,
    ) -> None:
        """Agrega una regla por rango de monto absoluto."""
        self._amount_rules.append((category, min_amount, max_amount))

    # ------------------------------------------------------------------
    # Clasificación
    # ------------------------------------------------------------------
    def categorize_transaction(self, txn: Any) -> str:
        """Devuelve la categoría (string del enum) para una transacción.

        Params:
            txn: una :class:`Transaction` o un dict con los campos
                ``description``, ``reference``, ``counterparty``, ``amount``,
                ``channel`` y ``type``.

        Returns:
            str: valor de :class:`Category` (p. ej. ``"NOMINA"``).
        """
        category = self._classify_rule_based(txn)
        if category is None and self.llm_router is not None:
            logger.info("categorizer: no rule matched, invoking llm_router")
            candidate = self.llm_router(txn)
            category = self._coerce_category(candidate)
            if category is not None:
                logger.info("categorizer: llm_router matched rule -> %s", category.value)
        if category is None:
            category = self.default_category
            logger.info("categorizer: no rule matched, default -> %s", category.value)
        return category.value if isinstance(category, Category) else str(category)

    def classify_with_llm(self, txn: Any) -> str:
        """Clasifica una transacción mediante un LLM (futuro).

        Slot reservado para la integración con un modelo de lenguaje que
        categorice transacciones que las reglas deterministas no alcanzan.

        .. warning::
            Aún no implementado. Lanza :class:`NotImplementedError` hasta que
            el router LLM esté disponible en producción. La categorización
            actual es 100% determinista (rule-based).

        Args:
            txn: la transacción a clasificar (:class:`Transaction` o dict).

        Raises:
            NotImplementedError: siempre, por diseño.
        """
        raise NotImplementedError("Future LLM integration")

    def _classify_rule_based(self, txn: Any) -> Optional[Category]:
        # 1) Regla por RFC (mayor prioridad)
        counterparty = _clean_rfc(_get_field(txn, "counterparty"))
        description = _lower(_get_field(txn, "description"))
        for rfc, cat in self._rfc_rules.items():
            if counterparty and (rfc == counterparty or rfc in counterparty):
                logger.info("categorizer: matched RFC rule rfc=%s -> %s", rfc, cat.value)
                return cat
            if rfc.lower() in description:
                logger.info("categorizer: matched RFC rule (in description) rfc=%s -> %s", rfc, cat.value)
                return cat

        # 2) Palabras clave sobre descripción/referencia
        reference = _lower(_get_field(txn, "reference"))
        text = f"{description} {reference}"
        for pattern, cat in self._keyword_rules:
            if pattern.search(text):
                logger.info("categorizer: matched keyword rule pattern=%r -> %s", pattern.pattern, cat.value)
                return cat

        # 3) Reglas por monto (absoluto)
        amount = _coerce_amount(_get_field(txn, "amount"))
        if amount is not None:
            for cat, lo, hi in self._amount_rules:
                amt = abs(amount)
                if (lo is None or amt >= lo) and (hi is None or amt <= hi):
                    logger.info(
                        "categorizer: matched amount rule range=[%s,%s] amount=%s -> %s",
                        lo, hi, amt, cat.value,
                    )
                    return cat

        # 4) Pista de canal
        channel = _get_field(txn, "channel")
        if channel is not None:
            ch_key = str(channel).upper().replace(" ", "_")
            if ch_key in self._channel_hints:
                logger.info("categorizer: matched channel hint channel=%s -> %s", ch_key, self._channel_hints[ch_key].value)
                return self._channel_hints[ch_key]

        return None

    @staticmethod
    def _coerce_category(candidate: Any) -> Optional[Category]:
        if candidate is None:
            return None
        if isinstance(candidate, Category):
            return candidate
        try:
            return Category(str(candidate).strip().upper())
        except ValueError:
            return None


def categorize_transaction(txn: Any, categorizer: Optional[TransactionCategorizer] = None) -> str:
    """Función de conveniencia: categoriza con un categorizer por defecto."""
    return (categorizer or TransactionCategorizer()).categorize_transaction(txn)
