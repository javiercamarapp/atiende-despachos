# -*- coding: utf-8 -*-
"""
bank_reconciliation.py — Conciliación bancaria REAL con upload de estados
de cuenta (servicio orientado a clases + sesión por tenant).

Objetivo: cruzar facturas (invoices) contra movimientos bancarios subidos
desde un estado de cuenta (CSV/PDF), asignando un CONFIDENCE SCORE 0-100 a
cada cruce, permitiendo confirmación manual y generando un reporte de
conciliación.

Bancos soportados (formato CSV):
  - BBVA, Banorte, Santander, HSBC y CSV genérico.
  El parser auto-detecta delimitador y columnas; los perfiles de banco solo
  afinan prioridades de columnas y el signo del monto.

Matching (3 niveles + manual):
  - Exact match   : monto igual (±0.01) + fecha dentro de tolerancia.
  - Partial match : monto similar (tolerancia %) + referencia/descripción
                    que coincide (tokens o folio).
  - AI match      : el LLM analiza descripciones/emisor cuando monto y
                    fecha NO alcanzan para un cruce exacto. Fallback a
                    similitud de tokens si el LLM no está configurado.
  - Manual match  : el usuario confirma un cruce (confidence = 100).

Diseño:
  - `BankReconciliation` es la fachada. Se instancia por tenant (o con una
    sesión inyectable). La sesión guarda los estados subidos, las facturas
    de referencia y los cruces (matches) calculados + confirmados.
  - Sin API keys externas por defecto: el "AI match" usa LLMService (mock si
    no hay proveedor configurado), que falla limpiamente a reglas.
  - Reutiliza los parsers de bajo nivel de `b2b_ai.services.reconcile`
    (probados) y les añade el perfil bancario y el scoring.
"""
from __future__ import annotations

import re
from datetime import datetime, date, timedelta
from decimal import Decimal, InvalidOperation
from itertools import combinations
from typing import List, Optional

from b2b_ai.services.reconcile import (
    parse_bank_statement_csv as _parse_csv_generic,
    parse_bank_statement_pdf as _parse_pdf_generic,
)
from b2b_ai.services.llm import LLMService
from b2b_ai.services.group_scoring import compute_group_score
from b2b_ai.services.subset_sum import (
    find_matching_subsets,
    SubsetSumBudgetExceeded,
)
from b2b_ai.services.settlement_profiles import get_settlement_profile


# ---------------------------------------------------------------------------
# Helpers numéricos / de fechas
# ---------------------------------------------------------------------------

def _dec(v) -> Optional[Decimal]:
    """Convierte a Decimal de forma tolerante (None o texto raro -> None)."""
    if v is None:
        return None
    s = str(v).strip().replace(",", "").replace("$", "").replace(" ", "")
    if s in ("", "-", "--", "N/A", "n/a"):
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _norm_fecha(f) -> str:
    if not f:
        return ""
    return str(f)[:10]


def _parse_date(s) -> Optional[date]:
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y",
                "%Y/%m/%d", "%m/%d/%Y", "%d %b %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _coerce_date(v) -> date:
    """Convierte str/date/datetime a `date`. Lanza ValueError si no se puede."""
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    d = _parse_date(v)
    if d is None:
        raise ValueError(f"fecha_banco inválida o no reconocida: {v!r}")
    return d


def _perfil_get(perfil, campo: str, default=None):
    """Lee un campo de `perfil`, que puede ser dict o un objeto con atributos
    (p. ej. una futura instancia de `SettlementProfile`, REQ-CONC-001)."""
    if perfil is None:
        return default
    if isinstance(perfil, dict):
        return perfil.get(campo, default)
    return getattr(perfil, campo, default)


def _subtract_business_days(d: date, n: int) -> date:
    """Retrocede `n` días HÁBILES (excluyendo sábado/domingo) desde `d`.

    `n <= 0` devuelve `d` sin cambios (no hay retroceso que hacer).
    """
    cur = d
    steps = 0
    n = max(0, int(n))
    while steps < n:
        cur = cur - timedelta(days=1)
        if cur.weekday() < 5:   # lunes(0)..viernes(4) = hábil
            steps += 1
    return cur


def _business_days_window(fecha_banco, perfil, buffer_dias_habiles: int = 1):
    """Calcula la ventana de captura (en días calendario) que pudo originar
    un movimiento bancario liquidado en `fecha_banco`, según el perfil de
    liquidación (`perfil.liquidacion_dias_habiles_min/max`, ver REQ-CONC-001).

    Devuelve `(fecha_inicio, fecha_fin)` — ambos `date`, ambos inclusive —
    representando el rango de fechas de CAPTURA (no de liquidación) de las
    facturas/cobros candidatos a conciliarse contra este movimiento.

    Reglas (REQ-CONC-002):
      - El conteo de días de liquidación es en DÍAS HÁBILES: sábado y
        domingo nunca cuentan como un paso de liquidación.
      - `buffer_dias_habiles` (1-2, se acota a ese rango) amplía el extremo
        más antiguo de la ventana para absorber feriados bancarios no
        capturados en un calendario simple lunes-viernes.
      - Corrimiento de fin de semana: cuando `fecha_banco` cae LUNES, el
        último día hábil anterior es viernes, pero un cobro capturado
        sábado o domingo también liquida el lunes siguiente (no hay
        procesamiento bancario en fin de semana). Por eso, si
        `fecha_banco` es lunes, el extremo más reciente de la ventana se
        extiende hasta el domingo inmediatamente anterior, para no excluir
        capturas de viernes/sábado/domingo.
    """
    fecha_banco = _coerce_date(fecha_banco)

    dias_min = int(_perfil_get(perfil, "liquidacion_dias_habiles_min", 1) or 0)
    dias_max = int(_perfil_get(
        perfil, "liquidacion_dias_habiles_max", dias_min) or dias_min)
    if dias_max < dias_min:
        dias_max = dias_min
    incluye_fin_de_semana = _perfil_get(
        perfil, "incluye_fin_de_semana_en_lunes", True)

    # El buffer configurable siempre es 1 o 2 días hábiles (nunca 0 ni >2):
    # un feriado bancario no capturado desplaza la ventana, nunca la
    # angosta.
    buffer_dias_habiles = int(buffer_dias_habiles or 1)
    buffer_dias_habiles = min(2, max(1, buffer_dias_habiles))

    # Extremo más reciente de la ventana: el día hábil más cercano a
    # fecha_banco que aún puede haberla originado (T + dias_min hábiles).
    fecha_fin = _subtract_business_days(fecha_banco, dias_min)

    # Extremo más antiguo: el día hábil más lejano contemplado por el
    # perfil, más el buffer de feriados.
    fecha_inicio = _subtract_business_days(
        fecha_banco, dias_max + buffer_dias_habiles)

    # Corrimiento de fin de semana (ver docstring): si fecha_banco cae
    # lunes, la ventana debe alcanzar hasta el domingo anterior.
    if incluye_fin_de_semana and fecha_banco.weekday() == 0:
        domingo_anterior = fecha_banco - timedelta(days=1)
        if domingo_anterior > fecha_fin:
            fecha_fin = domingo_anterior

    if fecha_inicio > fecha_fin:
        fecha_inicio = fecha_fin   # nunca invertir el rango

    return fecha_inicio, fecha_fin


def _fecha_dist(f1, f2):
    try:
        d1 = datetime.strptime(f1, "%Y-%m-%d").date()
        d2 = datetime.strptime(f2, "%Y-%m-%d").date()
        return abs((d1 - d2).days)
    except ValueError:
        return None


def _norm_tokens(s: str):
    """Normaliza un texto a un set de tokens para comparar referencias."""
    s = (s or "").lower()
    s = re.sub(r"[^0-9a-zñáéíóú ]+", " ", s)
    return {t for t in s.split() if t}


def _token_overlap(a: str, b: str):
    ta, tb = _norm_tokens(a), _norm_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


# ---------------------------------------------------------------------------
# Perfiles de banco
# ---------------------------------------------------------------------------
# Cada perfil declara preferencias de columnas (por prioridad) y el delimitador
# esperado. El parser genérico de reconcile ya auto-detecta; el perfil sirve
# para afinar cuando hay ambigüedad (p. ej. BBVA usa ';').
BANK_PROFILES = {
    "bbva": {
        "label": "BBVA",
        "delimiter_hint": ";",
        "monto_sign": "cargo_abono",       # columnas Cargo/Abono separadas
    },
    "banorte": {
        "label": "Banorte",
        "delimiter_hint": ";",
        "monto_sign": "cargo_abono",
    },
    "santander": {
        "label": "Santander",
        "delimiter_hint": ";",
        "monto_sign": "cargo_abono",
    },
    "hsbc": {
        "label": "HSBC",
        "delimiter_hint": ",",
        "monto_sign": "single",            # columna única con signo o importe
    },
    "generico": {
        "label": "CSV genérico",
        "delimiter_hint": None,            # auto-detect
        "monto_sign": "auto",
    },
}

SUPPORTED_BANKS = list(BANK_PROFILES.keys())


def _normalize_bank(bank) -> str:
    """Devuelve la clave de banco normalizada o 'generico' si no se reconoce."""
    if not bank:
        return "generico"
    b = str(bank).strip().lower().replace(" ", "_")
    if b in BANK_PROFILES:
        return b
    # Tolerancia a nombres como 'BBVA Bancomer' o 'Banorte (nómina)'.
    for key in BANK_PROFILES:
        if key in b:
            return key
    return "generico"


# ---------------------------------------------------------------------------
# Datos normalizados: un movimiento bancario
# ---------------------------------------------------------------------------

def _normalize_transaction(raw: dict, bank: str) -> dict:
    """Limpia y normaliza un movimiento bancario (estructura canónica)."""
    monto = _dec(raw.get("monto"))
    return {
        "id": _tx_id(raw),
        "fecha": _norm_fecha(raw.get("fecha")),
        "monto": str(abs(monto)) if monto is not None else "",
        "monto_signed": str(monto) if monto is not None else "",
        "naturaleza": ("cargo" if monto is not None and monto < 0 else "abono"),
        "descripcion": str(raw.get("descripcion") or "").strip(),
        "ref": str(raw.get("ref") or "").strip(),
        "banco": bank,
    }


def _tx_id(raw: dict) -> str:
    """Id estable por movimiento (hash de sus campos)."""
    import hashlib
    seed = "|".join([_norm_fecha(raw.get("fecha")),
                     str(raw.get("monto")),
                     str(raw.get("descripcion")),
                     str(raw.get("ref"))])
    return "tx_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Servicio: BankReconciliation
# ---------------------------------------------------------------------------

class BankReconciliation:
    """Fachada de conciliación bancaria por tenant/sesión.

    La sesión guarda:
      - statements  : estados de cuenta subidos [{banco, filename, rows}]
      - transactions: movimientos normalizados (aplanados de los statements)
      - invoices    : facturas de referencia (cargadas / inyectadas)
      - matches     : cruces calculados + confirmados
      - confirmed   : ids de transacción confirmados manualmente (sobrescriben)
    """

    def __init__(self, tenant_id=None, llm=None):
        self.tenant_id = tenant_id
        self.llm = llm or LLMService()
        self.statements = []
        self.transactions = []
        self.invoices = []
        self.matches = []
        self.confirmed = {}            # tx_id -> invoice_id (manual)
        # Casos de ambigüedad real detectados por _pass_group (REQ-CONC-003,
        # ADR-2): 2+ combinaciones de facturas cuadran la misma suma de un
        # depósito. Nunca se auto-resuelven; quedan aquí para revisión
        # humana explícita.
        self.grouped_ambiguous = []
        # Candidatos de _pass_group que NO se auto-confirmaron (REQ-CONC-008):
        # o hubo 2+ combinaciones válidas (ambigüedad real, también viven en
        # grouped_ambiguous) o hubo exactamente 1 pero con score de
        # desambiguación < UMBRAL_AUTO_CONFIRMA_GRUPO (REQ-CONC-009). En
        # AMBOS casos el resultado queda estado="sugerido" y nunca se
        # auto-aplica (ADR-2): no generan filas en `matches`, la factura y
        # el movimiento quedan libres.
        self.grouped_suggestions = []
        self.last_error = None
        self.date_tolerance_days = 3
        self.monto_tolerance_pct = 5   # tolerancia parcial de monto (%)

    # -- upload ------------------------------------------------------------

    def upload_statement(self, file_path: str, bank: str = "generico",
                         kind: Optional[str] = None) -> dict:
        """Sube un estado de cuenta (CSV o PDF) y lo carga en la sesión.

        Devuelve un resumen: nº de movimientos parseados, banco normalizado
        y los primeros movimientos. Lanza ValueError si no se pudo parsear.
        """
        bank = _normalize_bank(bank)
        rows = self.parse_statement(file_path, bank, kind=kind)
        txns = [_normalize_transaction(r, bank) for r in rows]
        stmt = {
            "banco": bank,
            "filename": str(file_path).split("/")[-1],
            "rows": len(txns),
            "transactions": txns,
        }
        self.statements.append(stmt)
        self.transactions.extend(txns)
        return {
            "banco": bank,
            "filename": stmt["filename"],
            "movimientos": len(txns),
            "muestra": txns[:3],
        }

    def parse_statement(self, file_path: str, bank: str = "generico",
                        kind: Optional[str] = None) -> list:
        """Parsea un estado de cuenta (CSV o PDF) a movimientos crudos."""
        bank = _normalize_bank(bank)
        name = str(file_path).lower()
        if kind is None:
            kind = "pdf" if name.endswith(".pdf") else "csv"
        if kind == "pdf":
            return _parse_pdf_generic(file_path)
        return _parse_csv_generic(file_path)

    def parse_csv_statement(self, file) -> list:
        """Parsea un archivo CSV de estado de cuenta a movimientos crudos.

        `file` puede ser una ruta (str) o un file-like con `read()`.
        """
        path = _coerce_path(file)
        return _parse_csv_generic(path)

    def parse_pdf_statement(self, file) -> list:
        """Parsea un PDF de estado de cuenta a movimientos crudos."""
        path = _coerce_path(file)
        return _parse_pdf_generic(path)

    # -- facturas de referencia --------------------------------------------

    def load_invoices(self, invoices: list) -> None:
        """Carga/inyecta las facturas de referencia a cruzar."""
        self.invoices = list(invoices or [])

    def clear(self) -> None:
        """Resetea la sesión actual."""
        self.statements = []
        self.transactions = []
        self.invoices = []
        self.matches = []
        self.confirmed = {}

    # -- matching ----------------------------------------------------------

    def auto_match(self, invoices: Optional[list] = None,
                   date_tolerance_days: int = 3,
                   monto_tolerance_pct: float = 5) -> dict:
        """Calcula los cruces automáticos (exacto + parcial + AI) con score.

        Devuelve la lista de matches (con confidence 0-100). Si no hay
        movimientos cargados, devuelve lista vacía con aviso.
        """
        if invoices is not None:
            self.load_invoices(invoices)
        self.date_tolerance_days = date_tolerance_days
        self.monto_tolerance_pct = monto_tolerance_pct

        if not self.transactions:
            return {"matches": [], "aviso": "No hay movimientos cargados.",
                    "auto_matchconfidence": []}

        # Reconstruye los cruces desde cero (idempotente) conservando
        # confirmaciones manuales previas.
        self.matches = self.match_transactions(
            self.invoices, self.transactions,
            date_tolerance_days=date_tolerance_days,
            monto_tolerance_pct=monto_tolerance_pct)
        return self._auto_match_response()

    def match_transactions(self, invoices: list, statement: list,
                           date_tolerance_days: int = 3,
                           monto_tolerance_pct: float = 5) -> list:
        """Cruza facturas contra movimientos bancarios y puntúa cada cruce.

        `statement` es la lista de movimientos normalizados. Devuelve la
        lista de matches: {transaction_id, invoice_ref, confidence, method,
        detail, fecha_invoice, fecha_bank, monto}.

        Métodos:
          - exact      : monto igual + fecha dentro de tolerancia
          - parcial    : monto similar + referencia/descripción que coincide
          - ai         : LLM / similitud de tokens sobre descripción
          - manual     : confirmación humana (confidence 100)
        """
        # Recalcula desde cero en cada llamada: nunca acumular ambigüedades
        # de una corrida anterior sobre la sesión.
        self.grouped_ambiguous = []
        self.grouped_suggestions = []
        if not invoices:
            return []
        stmt = list(statement or [])

        # Facturas no consumidas (una transacción concilia una factura).
        free_inv = [dict(i) for i in invoices]

        # 1) Cruces exactos
        matches = self._pass_exact(free_inv, stmt, date_tolerance_days)
        consumed_inv, consumed_tx = self._consumed(matches)

        # 1.5) Cruces agrupados N-a-1 (varias facturas suman UN movimiento,
        # p. ej. una liquidación de terminal que agrupa varios cobros).
        # Ver REQ-CONC-003. Nunca inventa un match: si 0 o 2+ combinaciones
        # de facturas cuadran la misma suma, no auto-resuelve (ADR-1/ADR-2).
        rest_inv = [i for i in free_inv if _inv_key(i) not in consumed_inv]
        rest_tx = [t for t in stmt if t["id"] not in consumed_tx]
        matches += self._pass_group(rest_inv, rest_tx)
        consumed_inv, consumed_tx = self._consumed(matches)

        # 2) Cruces parciales (monto similar + referencia)
        rest_inv = [i for i in free_inv if _inv_key(i) not in consumed_inv]
        rest_tx = [t for t in stmt if t["id"] not in consumed_tx]
        matches += self._pass_partial(rest_inv, rest_tx, monto_tolerance_pct)
        consumed_inv, consumed_tx = self._consumed(matches)

        # 3) AI match sobre lo que queda (descripción/emisor)
        rest_inv = [i for i in free_inv if _inv_key(i) not in consumed_inv]
        rest_tx = [t for t in stmt if t["id"] not in consumed_tx]
        matches += self._pass_ai(rest_inv, rest_tx)

        # 4) Aplica confirmaciones manuales (sobrescriben, confidence=100).
        matches = self._apply_manual(matches)

        return matches

    # -- pases internos ----------------------------------------------------

    @staticmethod
    def _consumed(matches) -> tuple:
        """Devuelve (invoice_refs, tx_ids) ya consumidos por los matches."""
        return ({m.get("invoice_ref") for m in matches},
                {m["transaction_id"] for m in matches})

    def _pass_exact(self, invoices, stmt, tolerance_days) -> list:
        out = []
        used_tx = set()
        for inv in invoices:
            inv_total = _dec(inv.get("total"))
            inv_date = _norm_fecha(inv.get("fecha"))
            if inv_total is None:
                continue
            best, best_dist = None, None
            for t in stmt:
                if t["id"] in used_tx:
                    continue
                if abs(_dec(t["monto_signed"]) or 0) != abs(inv_total):
                    continue
                d = _fecha_dist(inv_date, t["fecha"])
                if d is not None and d <= tolerance_days:
                    if best_dist is None or d < best_dist:
                        best, best_dist = t, d
            if best is not None:
                used_tx.add(best["id"])
                conf = max(90, 100 - best_dist * 3)   # cercanía en fechas
                out.append(_build_match(inv, best, "exact", conf,
                                        f"monto igual ({inv_total}) y fecha "
                                        f"a {best_dist}d"))
        return out

    # Techo de facturas libres consideradas por movimiento en este pase, y
    # tamaño máximo de subconjunto explorado. `_subset_sums_exact` (vía
    # `b2b_ai.services.subset_sum`, REQ-CONC-006) usa meet-in-the-middle en
    # vez de fuerza bruta pasado `subset_sum.MITM_THRESHOLD` (40) candidatos,
    # así que este techo ya no protege contra una explosión combinatoria en
    # `_pass_group` mismo — solo mantiene el universo de candidatos por
    # movimiento en un tamaño operativamente razonable (REQ-CONC-015 lo fija
    # en <= 50 típico; se deja algo de margen sobre eso).
    MAX_GROUP_CANDIDATE_INVOICES = 60
    MAX_GROUP_SIZE = 15

    # REQ-CONC-008: score mínimo (0-100, ver REQ-CONC-009 /
    # `group_scoring.compute_group_score`) para que un candidato ÚNICO se
    # auto-confirme sin intervención humana. Deliberadamente MÁS estricto
    # que la tolerancia del pase 1-a-1 (`_pass_partial`, que no tiene un
    # score comparable pero opera con 5% de tolerancia de monto sin
    # desambiguación) — ver REQ-CONC-017.
    UMBRAL_AUTO_CONFIRMA_GRUPO = 85

    def _pass_group(self, invoices, stmt, perfil=None) -> list:
        """Cruce N-a-1: varias facturas (N) suman EXACTAMENTE un solo
        movimiento bancario (1), p. ej. una liquidación de terminal que
        agrupa varios cobros en un único depósito.

        Solo considera depósitos (`naturaleza == "abono"`) — el caso
        simétrico de egresos agrupados (nómina dispersada, REQ-CONC-012)
        queda fuera de este pase. Busca TODOS los subconjuntos de 2+
        facturas (1 factura ya la cubre `_pass_exact`) cuya suma en
        CENTAVOS (enteros, nunca floats) sea exactamente igual al monto
        del movimiento:

          - 0 subconjuntos válidos -> no genera match; el movimiento queda
            sin conciliar (ADR-1: nunca se inventa el candidato más
            parecido).
          - 1 subconjunto válido -> se puntúa con
            `group_scoring.compute_group_score` (REQ-CONC-009). Si el
            score es `>= UMBRAL_AUTO_CONFIRMA_GRUPO` (85), el match se
            AUTO-CONFIRMA (`confidence="alta"`,
            `requiere_confirmacion_humana=False`, method
            `grouped_n_a_1`, REQ-CONC-008). Si el score queda por debajo
            del umbral, NUNCA se auto-aplica pese a ser el único
            candidato: se registra en `self.grouped_suggestions` con
            `estado="sugerido"` para que un humano decida, y el
            movimiento/las facturas quedan libres.
          - 2+ subconjuntos válidos -> AMBIGÜEDAD REAL: ninguno se aplica
            automáticamente (ADR-2), sin importar qué score tuviera cada
            uno individualmente — el score es una heurística descriptiva,
            nunca se usa para resolver un empate por su cuenta. Se
            registra en `self.grouped_ambiguous` (detalle completo de
            todas las combinaciones) y también en
            `self.grouped_suggestions` (`estado="sugerido"`) para que un
            humano decida; el movimiento y esas facturas quedan libres
            para los pases siguientes (parcial/AI), que tampoco podrán
            inventar un match porque ya vieron que 2+ combinaciones
            cuadran.
        """
        out = []
        used_tx = set()
        used_inv_keys = set()

        candidatos = [i for i in invoices if _dec(i.get("total")) is not None
                     and (_dec(i.get("total")) or 0) > 0]
        if len(candidatos) < 2:
            return out
        # Universo tratable por fuerza bruta; con más candidatos que el
        # techo, este pase se abstiene en vez de arriesgar una búsqueda
        # combinatoria descontrolada (o peor, un timeout silencioso).
        if len(candidatos) > self.MAX_GROUP_CANDIDATE_INVOICES:
            candidatos = candidatos[:self.MAX_GROUP_CANDIDATE_INVOICES]

        for t in stmt:
            if t["id"] in used_tx:
                continue
            if t.get("naturaleza") != "abono":
                continue
            monto_tx = _dec(t.get("monto_signed"))
            if not monto_tx:
                continue
            target_cents = _to_cents(abs(monto_tx))
            if target_cents <= 0:
                continue
            libres = [i for i in candidatos if _inv_key(i) not in used_inv_keys]
            if len(libres) < 2:
                continue
            subconjuntos = _subset_sums_exact(
                libres, target_cents, max_size=self.MAX_GROUP_SIZE)
            if not subconjuntos:
                continue
            if len(subconjuntos) > 1:
                # Ambigüedad real (ADR-2): nunca se auto-resuelve, sin
                # importar el score. Se deja constancia explícita para
                # decisión humana y el movimiento sigue libre (no se marca
                # used_tx).
                if not hasattr(self, "grouped_ambiguous"):
                    self.grouped_ambiguous = []
                candidatos_folios = [[_inv_key(i) for i in grupo]
                                     for grupo in subconjuntos]
                self.grouped_ambiguous.append({
                    "transaction_id": t["id"],
                    "monto": str(abs(monto_tx)),
                    "candidatos": candidatos_folios,
                    "estado": "sugerido",
                })
                self.grouped_suggestions.append({
                    "transaction_id": t["id"],
                    "monto": str(abs(monto_tx)),
                    "candidatos": candidatos_folios,
                    "score": None,
                    "estado": "sugerido",
                    "requiere_confirmacion_humana": True,
                    "razon": (f"{len(subconjuntos)} combinaciones distintas "
                             "cuadran la misma suma (ambigüedad real, "
                             "ADR-2): ninguna se auto-resuelve"),
                })
                continue

            grupo = subconjuntos[0]
            # `_pass_group` todavía busca la suma EXACTA (bruto == neto,
            # sin descontar comisión — la banda de grossing-up de
            # REQ-CONC-004 aún no está integrada aquí), que es exactamente
            # el comportamiento del perfil sin comisión
            # ("spei_transferencia"/"cheque", 0%-0%). Sin un `perfil`
            # explícito, ese es el default correcto para la dimensión de
            # comisión del score (REQ-CONC-009) — no un perfil inventado,
            # sino el que describe con precisión lo que este pase ya hace
            # hoy. Un llamador que sepa que el canal real es Clip/Banorte
            # puede pasar ese perfil explícitamente.
            perfil_score = perfil if perfil is not None else (
                get_settlement_profile("spei_transferencia"))
            score = compute_group_score(
                grupo, sum_cents=target_cents, target_cents=target_cents,
                es_unico=True, perfil=perfil_score)
            if score >= self.UMBRAL_AUTO_CONFIRMA_GRUPO:
                group_id = "grp_" + t["id"]
                out.extend(_build_group_match(grupo, t, group_id, score))
                used_tx.add(t["id"])
                used_inv_keys.update(_inv_key(i) for i in grupo)
            else:
                # Único candidato, pero no lo bastante limpio (REQ-CONC-008):
                # NUNCA se auto-aplica. Queda sugerido para decisión humana;
                # el movimiento y las facturas quedan libres.
                self.grouped_suggestions.append({
                    "transaction_id": t["id"],
                    "monto": str(abs(monto_tx)),
                    "candidatos": [[_inv_key(i) for i in grupo]],
                    "score": score,
                    "estado": "sugerido",
                    "requiere_confirmacion_humana": True,
                    "razon": (f"score de desambiguación {score} < "
                             f"{self.UMBRAL_AUTO_CONFIRMA_GRUPO} "
                             "(único candidato, pero no lo bastante "
                             "confiable para auto-confirmar)"),
                })
        return out

    def _pass_partial(self, invoices, stmt, tolerance_pct) -> list:
        out = []
        used_tx = set()
        for inv in invoices:
            inv_total = _dec(inv.get("total"))
            inv_ref = _folio(inv)
            if inv_total is None:
                continue
            best, best_overlap = None, -1.0
            for t in stmt:
                if t["id"] in used_tx:
                    continue
                t_amount = _dec(t["monto_signed"]) or 0
                if abs(t_amount) == 0:
                    continue
                diff_pct = abs(abs(t_amount) - abs(inv_total)) / abs(inv_total) * 100
                if diff_pct > tolerance_pct:
                    continue
                # La referencia/factura debe coincidir razonablemente.
                over = max(_token_overlap(t["ref"], inv_ref),
                           _token_overlap(t["descripcion"], inv_ref))
                if over < 0.25:
                    continue
                if over > best_overlap:
                    best, best_overlap = t, over
            if best is not None:
                used_tx.add(best["id"])
                conf = int(60 + best_overlap * 30)   # 60-90 según overlap
                conf = min(conf, 89)                 # nunca "exacto"
                out.append(_build_match(
                    inv, best, "parcial", conf,
                    f"monto similar (dif {tolerance_pct}%) y referencia "
                    f"coincide ({best_overlap:.0%})"))
        return out

    # Límite superior de pares (factura × movimiento) para evitar N×M LLM
    # calls en requests síncronos. Con 200 facturas × 150 movimientos serían
    # 30,000 llamadas.  El token overlap (gratis) actúa como pre-filtro y
    # solo los pares con señal ≥ 15% llegan al LLM.
    MAX_AI_PAIRS = 500
    TOKEN_PRE_FILTER_THRESHOLD = 0.15   # overlap mínimo para invocar LLM

    def _pass_ai(self, invoices, stmt) -> list:
        out = []
        used_tx = set()
        pair_count = 0
        for inv in invoices:
            inv_desc = " ".join([_folio(inv), _emisor(inv),
                                 str(inv.get("descripcion") or "")])
            best, best_conf = None, 0.0
            for t in stmt:
                if t["id"] in used_tx:
                    continue
                pair_count += 1
                if pair_count > self.MAX_AI_PAIRS:
                    break
                # Pre-filtro por token overlap (gratis) — descarta pares sin
                # relación textual antes de quemar un call al LLM.
                tok_pre = _token_overlap(
                    f"{t.get('descripcion', '')} {t.get('ref', '')}".strip(),
                    inv_desc)
                if tok_pre < self.TOKEN_PRE_FILTER_THRESHOLD:
                    continue
                conf = self._ai_confidence(t, inv_desc)
                if conf > best_conf:
                    best, best_conf = t, conf
            if best is not None and best_conf >= 50:   # umbral AI
                used_tx.add(best["id"])
                out.append(_build_match(
                    inv, best, "ai", int(best_conf),
                    f"IA: descripción del banco coincide con la factura "
                    f"(confianza {int(best_conf)}%)"))
            if pair_count > self.MAX_AI_PAIRS:
                break
        return out

    def _ai_confidence(self, tx, inv_desc) -> float:
        """Confianza AI de un cruce. Primero intenta LLM; fallback a tokens.

        Solo llama al LLM si el overlap de tokens ya tiene alguna señal;
        evita quemar el presupuesto de LLM en pares sin relación textual.
        """
        text = f"{tx['descripcion']} {tx['ref']}".strip()
        if not text:
            return 0.0
        # Overlap determinístico primero (gratis, siempre disponible)
        tok_conf = _token_overlap(tx["descripcion"], inv_desc) * 100
        # Solo invoca LLM si los tokens ya dan algo (> 10%)
        llm_conf = 0.0
        if tok_conf > 10:
            try:
                res = self.llm.classify_invoice(
                    {"descripcion": text, "emisor_nombre": inv_desc[:500]})
                llm_conf = float(res.get("confianza", 0.0))   # 0-1
            except Exception:  # noqa: BLE001 — el fallback de tokens manda
                self.last_error = "ai_fallback_tokens"
        return max(0.0, min(100.0, max(llm_conf * 100, tok_conf)))

    def _apply_manual(self, matches) -> list:
        """Sobrescribe cruces según confirmaciones manuales."""
        # Consumidos automáticamente: se re-aplica manual sobre ellos.
        for tx_id, inv_id in self.confirmed.items():
            inv = self._find_invoice(inv_id)
            tx = self._find_tx(tx_id)
            if inv is None or tx is None:
                continue
            # Quita cualquier match previo que use esa tx o esa factura.
            matches = [m for m in matches
                       if m["transaction_id"] != tx_id
                       and m.get("invoice_ref") != _inv_key(inv)]
            matches.append(_build_match(inv, tx, "manual", 100,
                                        "Confirmado manualmente por el usuario"))
        return matches

    def _find_invoice(self, inv_id):
        for i in self.invoices:
            if str(_inv_key(i)) == str(inv_id):
                return i
        return None

    def _find_tx(self, tx_id):
        for t in self.transactions:
            if t["id"] == tx_id:
                return t
        return None

    # -- confirmación manual -----------------------------------------------

    def manual_match(self, transaction_id: str, invoice_id) -> dict:
        """Confirma manualmente que una transacción concilia una factura.

        Valida que ambos existan en la sesión. Devuelve el match creado con
        confidence=100.
        """
        tx = self._find_tx(transaction_id)
        if tx is None:
            raise ValueError(f"Transacción {transaction_id} no encontrada.")
        inv = self._find_invoice(invoice_id)
        if inv is None:
            raise ValueError(f"Factura {invoice_id} no encontrada.")
        self.confirmed[transaction_id] = str(_inv_key(inv))
        # Recalcula los cruces aplicando la confirmación.
        self.matches = self.match_transactions(
            self.invoices, self.transactions,
            date_tolerance_days=self.date_tolerance_days,
            monto_tolerance_pct=self.monto_tolerance_pct)
        m = next((x for x in self.matches if x["transaction_id"] == transaction_id),
                 None)
        if m is None:   # no debería ocurrir; defensivo
            m = _build_match(inv, tx, "manual", 100, "Confirmado manualmente")
            self.matches.append(m)
        return m

    # -- reporte -----------------------------------------------------------

    def generate_reconciliation_report(self) -> dict:
        """Construye el reporte de conciliación de la sesión actual.

        Agrega montos conciliados vs pendientes (por método y totales),
        la tasa de conciliación y la lista de cruces + pendientes.

        REQ-CONC-011: cuando un `group_id` hace que varias filas de
        `matches` compartan el mismo `transaction_id` (conciliación N-a-1,
        REQ-CONC-003/010), el "monto conciliado" y el conteo de
        movimientos conciliados/pendientes se calculan agrupando por
        `transaction_id` ÚNICO -- nunca sumando/contando una fila por
        factura del grupo -- para no contar el mismo depósito bancario
        varias veces. Se usa el monto REAL del movimiento bancario
        (`monto_banco`, igual al `monto_signed` de la transacción) para
        cada `transaction_id` único, en vez de sumar el `monto` (lado
        factura) de cada fila -- así el total también queda correcto
        cuando el grupo suma bruto de facturas por encima del neto
        depositado (comisión de terminal, REQ-CONC-004: el subset-sum
        acepta un rango `[A, A_grossed_up]`, no solo `A` exacto).
        """
        txns = self.transactions
        invs = self.invoices
        matches = self.matches

        total_banco = sum(abs(_dec(t["monto_signed"]) or 0) for t in txns)

        # Un solo monto por `transaction_id` único, sin importar cuántas
        # filas de match (facturas) comparten ese movimiento vía group_id.
        monto_banco_por_tx: dict = {}
        for m in matches:
            tx_id = m["transaction_id"]
            if tx_id not in monto_banco_por_tx:
                monto_banco_por_tx[tx_id] = m.get("monto_banco", m.get("monto"))
        matched_tx_ids = set(monto_banco_por_tx.keys())
        conciliado = sum(abs(_dec(v) or 0) for v in monto_banco_por_tx.values())
        pendiente_banco = total_banco - conciliado

        factura_monto = sum((_dec(i.get("total")) or 0) for i in invs)
        matched_inv_keys = {m["invoice_ref"] for m in matches}
        pendiente_facturas = sum(
            (abs(_dec(i.get("total"))) or 0)
            for i in invs if _inv_key(i) not in matched_inv_keys)

        por_metodo = {}
        for m in matches:
            por_metodo[m["method"]] = por_metodo.get(m["method"], 0) + 1

        return {
            "tenant_id": self.tenant_id,
            "facturas": len(invs),
            "movimientos_banco": len(txns),
            "conciliados": len(matched_tx_ids),
            "pendientes_banco": len(txns) - len(matched_tx_ids),
            "pendientes_facturas": len(invs) - len(matches),
            "monto_conciliado": str(conciliado),
            "monto_banco_total": str(total_banco),
            "monto_pendiente_banco": str(pendiente_banco),
            "monto_pendiente_facturas": str(pendiente_facturas),
            "tasa_conciliacion": round(float(conciliado / total_banco * 100), 2)
                if total_banco else 0.0,
            "por_metodo": por_metodo,
            "matches": matches,
            "unmatched_bank": [t for t in txns
                               if t["id"] not in matched_tx_ids],
            "unmatched_invoices": [i for i in invs
                                   if _inv_key(i) not in matched_inv_keys],
            "bancos": sorted({s["banco"] for s in self.statements}),
        }

    def auto_matchconfidence(self) -> list:
        """Devuelve los matches calculados (con su confidence) o []."""
        return list(self.matches)

    # -- internos de respuesta ---------------------------------------------

    def _auto_match_response(self) -> dict:
        conf = sorted(self.matches,
                      key=lambda m: -_confidence_sort_value(m["confidence"]))
        return {
            "matches": self.matches,
            "auto_matchconfidence": conf,
            "total": len(self.matches),
            "confirmados": len(self.confirmed),
        }


# ---------------------------------------------------------------------------
# Helpers de construcción
# ---------------------------------------------------------------------------

def _inv_key(inv) -> str:
    return str(inv.get("folio_fiscal") or inv.get("id")
               or inv.get("factura_id") or "inv_" + str(id(inv)))


def _folio(inv) -> str:
    return str(inv.get("folio_fiscal") or inv.get("referencia") or "").strip()


def _emisor(inv) -> str:
    return " ".join(str(x) for x in [
        inv.get("emisor_nombre"), inv.get("emisor"), inv.get("emisor_rfc")]
        if x)


def _consumed(matches) -> tuple:
    return ({m.get("invoice_ref") for m in matches},
            {m["transaction_id"] for m in matches})


def _build_match(inv, tx, method, confidence, detail) -> dict:
    return {
        "transaction_id": tx["id"],
        "invoice_ref": _inv_key(inv),
        "invoice_fecha": _norm_fecha(inv.get("fecha")),
        "bank_fecha": tx["fecha"],
        "monto": str(abs(_dec(inv.get("total")) or 0)),
        "monto_banco": tx["monto"],
        "ref_banco": tx["ref"] or tx["descripcion"],
        "emisor": _emisor(inv) or inv.get("emisor"),
        "method": method,
        "confidence": int(max(0, min(100, confidence))),
        "detail": detail,
    }


_CONFIDENCE_LABEL_ORDER = {"alta": 95, "media": 70, "baja": 40}


def _confidence_sort_value(v) -> float:
    """Valor numérico proxy para ordenar por `confidence` cuando el campo
    puede ser un int 0-100 (matches 1-a-1) O una etiqueta cualitativa
    como `"alta"` (matches de grupo auto-confirmados, REQ-CONC-008).
    Nunca se usa como el valor mostrado al usuario, solo para el orden."""
    if isinstance(v, (int, float)):
        return float(v)
    return float(_CONFIDENCE_LABEL_ORDER.get(str(v).strip().lower(), 0))


def _to_cents(d: Decimal) -> int:
    """Convierte un Decimal (pesos) a centavos ENTEROS (nunca floats)."""
    return int((d * 100).to_integral_value())


def _subset_sums_exact(items: list, target_cents: int, max_size: int = 15,
                       min_size: int = 2) -> list:
    """Encuentra TODOS los subconjuntos de `items` (facturas) cuya suma en
    centavos sea EXACTAMENTE `target_cents`, con tamaño entre `min_size` y
    `max_size`.

    Deliberadamente reporta la lista completa de subconjuntos válidos, sin
    truncar a 1 en silencio: quien llama decide qué hacer con 0, 1 o 2+
    resultados (ver ADR-1/ADR-2 en `docs/BLUEPRINT-AGENTES-FISCALES.md`).
    Tamaño 1 se excluye por defecto porque ese caso ya lo cubre el cruce
    exacto 1-a-1 (`_pass_exact`).

    Delega en `b2b_ai.services.subset_sum.find_matching_subsets` con
    `r_min=0` (la banda de aceptación colapsa a un único valor: suma
    EXACTA, el caso sin comisión que usa este pase) — ese módulo despacha
    a meet-in-the-middle en vez de fuerza bruta pasado
    `subset_sum.MITM_THRESHOLD` (40) candidatos (REQ-CONC-006), en vez de
    la enumeración `itertools.combinations` directa que usaba esta función
    antes (intratable más allá de un puñado de decenas de candidatos).

    Si la búsqueda agota su presupuesto de exploración
    (`subset_sum.SubsetSumBudgetExceeded` — puede ocurrir con muchas
    facturas de monto similar y un depósito cuya suma exacta cae cerca
    de la mitad de la suma total, el peor caso para cualquier enumeración
    exhaustiva), se trata igual que "no se pudo evaluar automáticamente
    este movimiento": se devuelve `[]`, NUNCA se inventa un candidato
    parcial (ADR-1) — el movimiento queda libre para los pases siguientes
    o para revisión manual, igual que si nunca hubiera candidatos.
    """
    valores = []
    for inv in items:
        total = _dec(inv.get("total"))
        if total is None or total <= 0:
            continue
        valores.append((total, inv))

    if len(valores) < max(2, min_size):
        return []

    net = Decimal(target_cents) / Decimal(100)
    montos = [v[0] for v in valores]
    try:
        candidatos = find_matching_subsets(
            montos, net, Decimal("0"), max_size=max_size)
    except SubsetSumBudgetExceeded:
        return []

    min_size = max(2, min_size)
    resultados = []
    for c in candidatos:
        if len(c.indices) < min_size:
            continue
        resultados.append([valores[i][1] for i in c.indices])
    return resultados


def _build_group_match(grupo: list, tx: dict, group_id: str,
                       score: int = 100) -> list:
    """Construye N filas de match (una por factura del subconjunto) que
    comparten el mismo `transaction_id` y `group_id`, method="grouped_n_a_1"
    (REQ-CONC-003/010).

    Solo se llama cuando `_pass_group` ya decidió AUTO-CONFIRMAR el grupo
    (score de desambiguación >= `UMBRAL_AUTO_CONFIRMA_GRUPO`, REQ-CONC-008):
    por eso `confidence="alta"` y `requiere_confirmacion_humana=False` son
    fijos aquí — el caso "no confiable" nunca llega a construir estas filas,
    se queda en `self.grouped_suggestions` con `estado="sugerido"`.
    """
    n = len(grupo)
    rows = []
    for inv in grupo:
        m = _build_match(
            inv, tx, "grouped_n_a_1", 95,
            f"conciliación N-a-1: {n} facturas suman el depósito "
            f"({tx.get('monto')}), score de desambiguación {score}")
        m["group_id"] = group_id
        # REQ-CONC-008: auto-confirmación explícita — nunca se llega aquí
        # con 0, 2+ candidatos o score < umbral.
        m["confidence"] = "alta"
        m["requiere_confirmacion_humana"] = False
        m["estado"] = "confirmado"
        m["score"] = score
        rows.append(m)
    return rows


def _coerce_path(file):
    """Convierte file (ruta str o file-like) a una ruta en disco."""
    if isinstance(file, (str, bytes)):
        import os
        path = os.fspath(file)
        if not os.path.exists(path):
            raise ValueError(f"Archivo no encontrado: {path}")
        return path
    # file-like: materializa a un tempfile para que los parsers lo lean.
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".bank")
    try:
        with open(fd, "wb") as fh:
            data = file.read()
            if isinstance(data, str):
                data = data.encode("utf-8")
            fh.write(data)
        return path
    finally:
        pass  # el archivo temp lo borra el parser/OS


# ---------------------------------------------------------------------------
# CLI de demostración
# ---------------------------------------------------------------------------

def main():
    import sys
    if len(sys.argv) < 2:
        print("Uso: python -m b2b_ai.services.bank_reconciliation "
              "<estado_cuenta.csv|pdf> [banco]")
        sys.exit(1)
    bank = sys.argv[2] if len(sys.argv) > 2 else "generico"
    svc = BankReconciliation()
    res = svc.upload_statement(sys.argv[1], bank)
    print("Upload:", res)
    invoices = [{"folio_fiscal": "REF-1", "fecha": "2026-07-03",
                 "total": "5800.00", "emisor": "Proveedor A"}]
    svc.load_invoices(invoices)
    auto = svc.auto_match()
    print("Matches:", auto["total"])
    print(svc.generate_reconciliation_report())


if __name__ == "__main__":
    main()
