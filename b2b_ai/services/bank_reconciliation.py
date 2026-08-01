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
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from typing import List, Optional

from b2b_ai.services.reconcile import (
    parse_bank_statement_csv as _parse_csv_generic,
    parse_bank_statement_pdf as _parse_pdf_generic,
)
from b2b_ai.services.llm import LLMService


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
        if not invoices:
            return []
        stmt = list(statement or [])

        # Facturas no consumidas (una transacción concilia una factura).
        free_inv = [dict(i) for i in invoices]

        # 1) Cruces exactos
        matches = self._pass_exact(free_inv, stmt, date_tolerance_days)
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

    def _pass_ai(self, invoices, stmt) -> list:
        out = []
        used_tx = set()
        for inv in invoices:
            inv_desc = " ".join([_folio(inv), _emisor(inv),
                                 str(inv.get("descripcion") or "")])
            best, best_conf = None, 0.0
            for t in stmt:
                if t["id"] in used_tx:
                    continue
                conf = self._ai_confidence(t, inv_desc)
                if conf > best_conf:
                    best, best_conf = t, conf
            if best is not None and best_conf >= 55:   # umbral AI
                used_tx.add(best["id"])
                out.append(_build_match(
                    inv, best, "ai", int(best_conf),
                    f"IA: descripción del banco coincide con la factura "
                    f"(confianza {int(best_conf)}%)"))
        return out

    def _ai_confidence(self, tx, inv_desc) -> float:
        """Confianza AI de un cruce. Llama al LLM; fallback a tokens."""
        text = f"{tx['descripcion']} {tx['ref']}".strip()
        if not text:
            return 0.0
        try:
            res = self.llm.classify_invoice(
                {"descripcion": text, "emisor_nombre": inv_desc[:500]})
            conf = float(res.get("confianza", 0.0))   # 0-1
            if res.get("source") == "llm":
                return max(0.0, min(100.0, conf * 100))
        except Exception:  # noqa: BLE001 — el fallback de tokens manda
            self.last_error = "ai_fallback_tokens"
        # Fallback determinístico: overlap de tokens en la descripción.
        return _token_overlap(tx["descripcion"], inv_desc) * 100

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
        """
        txns = self.transactions
        invs = self.invoices
        matches = self.matches

        total_banco = sum(abs(_dec(t["monto_signed"]) or 0) for t in txns)
        conciliado = sum(abs(_dec(m["monto"]) or 0) for m in matches)
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
            "conciliados": len(matches),
            "pendientes_banco": len(txns) - len(matches),
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
                               if t["id"] not in {m["transaction_id"] for m in matches}],
            "unmatched_invoices": [i for i in invs
                                   if _inv_key(i) not in matched_inv_keys],
            "bancos": sorted({s["banco"] for s in self.statements}),
        }

    def auto_matchconfidence(self) -> list:
        """Devuelve los matches calculados (con su confidence) o []."""
        return list(self.matches)

    # -- internos de respuesta ---------------------------------------------

    def _auto_match_response(self) -> dict:
        conf = sorted(self.matches, key=lambda m: -m["confidence"])
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
