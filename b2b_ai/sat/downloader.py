# -*- coding: utf-8 -*-
"""
downloader.py — Descarga masiva de CFDI desde el SAT.

`SATDownloader` implementa el flujo de descarga masiva del SAT:
login con RFC + CIEC + e.firma, descarga de CFDI por rango de fechas,
balanza y catálogo de cuentas, y logout.

MODO MOCK-FIRST (por defecto): NO usa e.firma real ni credenciales de
producción. El transporte simulado genera CFDI deterministas a partir de
(RFC, fecha, tipo, índice), de modo que los tests y las demos son
reproducibles y no dependen de red ni de credenciales. Cuando existan
credenciales reales, se sustituyen los cuerpos de los métodos por las
llamadas al Web Service de Descarga Masiva del SAT (`cfdi40` / portal).

Persistencia: si se pasa `db` + `tenant_id`, el ledger de CFDI descargados
se guarda en la config del tenant (key `sat_cfdi_ledger`), lo que permite
que el scheduler detecte cancelaciones posteriores.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

# Tipos de CFDI soportados en la descarga masiva.
TIPOS_CFDI = ("emitidas", "recibidas")


def _rfc_normalize(rfc: str) -> str:
    """Normaliza RFC usando la función canónica centralizada."""
    from b2b_ai.common.rfc import normalize_rfc
    return normalize_rfc(rfc)

def _es_rfc_valido(rfc: str) -> bool:
    """Valida RFC usando la función canónica centralizada."""
    from b2b_ai.common.rfc import is_valid_rfc
    return is_valid_rfc(rfc)


def _iso(d: date) -> str:
    return d.isoformat()


def _parse_date(value: str) -> date:
    """Acepta 'YYYY-MM-DD' o ISO completo; lanza ValueError si no."""
    s = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Fecha inválida: {value!r} (esperaba YYYY-MM-DD)")


def _mk_uuid(rfc: str, day: str, tipo: str, idx: int) -> str:
    """UUID determinista por (rfc, día, tipo, índice) → tests estables."""
    seed = f"{rfc}|{day}|{tipo}|{idx}".encode("utf-8")
    return str(uuid.UUID(hashlib.md5(seed).hexdigest()))


class SATDownloader:
    """Descarga masiva de CFDI (mock determinista, sin e.firma real)."""

    backend = "SAT Descarga Masiva (mock)"

    def __init__(self, db=None, tenant_id: Optional[Any] = None,
                 rfc: str = "", ciec: str = "", e_firma_path: str = ""):
        self.db = db
        self.tenant_id = tenant_id
        self.rfc = _rfc_normalize(rfc)
        self.ciec = ciec
        self.e_firma_path = e_firma_path
        self.session_token: Optional[str] = None
        self.logged_rfc: Optional[str] = None
        # Ledger en memoria (se persiste si hay db+tenant).
        self._ledger: List[Dict[str, Any]] = []
        self._load_ledger()

    # ------------------------------------------------------------------ #
    # Sesión
    # ------------------------------------------------------------------ #
    def login(self, rfc: str, ciec: str = "", e_firma_path: str = "") -> Dict[str, Any]:
        """Inicia sesión en el SAT (mock).

        Valida el RFC bien formado y que se haya provisto CIEC o e.firma.
        En modo mock NO se verifica el certificado real.
        """
        rfc = _rfc_normalize(rfc)
        if not _es_rfc_valido(rfc):
            return {"ok": False, "error": f"RFC mal formado: {rfc!r}",
                    "backend": self.backend}
        if not ciec and not e_firma_path and not self.ciec and not self.e_firma_path:
            return {"ok": False,
                    "error": "Se requiere CIEC o ruta de e.firma para autenticar.",
                    "backend": self.backend}
        self.rfc = rfc or self.rfc
        self.ciec = ciec or self.ciec
        if e_firma_path:
            self.e_firma_path = e_firma_path
        self.session_token = "sat-sess-" + uuid.uuid4().hex[:16]
        self.logged_rfc = rfc
        return {
            "ok": True, "rfc": rfc, "session_token": self.session_token,
            "backend": self.backend,
            "note": "Modo mock: no se validó e.firma real contra el SAT.",
        }

    @property
    def logged_in(self) -> bool:
        return bool(self.session_token and self.logged_rfc)

    def _require_session(self) -> None:
        if not self.logged_in:
            raise RuntimeError("No hay sesión activa. Llama login() primero.")

    def logout(self) -> Dict[str, Any]:
        """Cierra la sesión activa."""
        was = self.logged_in
        token = self.session_token
        self.session_token = None
        self.logged_rfc = None
        return {"ok": True, "was_logged_in": was, "session_token": token,
                "backend": self.backend}

    # ------------------------------------------------------------------ #
    # Ledger persistido
    # ------------------------------------------------------------------ #
    def _load_ledger(self) -> None:
        if not (self.db and self.tenant_id is not None):
            return
        raw = self.db.get_tenant_config(self.tenant_id, "sat_cfdi_ledger")
        if raw:
            try:
                self._ledger = json.loads(raw)
            except (TypeError, ValueError):
                self._ledger = []

    def _save_ledger(self) -> None:
        if self.db and self.tenant_id is not None:
            self.db.set_tenant_config(self.tenant_id, "sat_cfdi_ledger",
                                      json.dumps(self._ledger))

    def _upsert_ledger(self, cfdi: Dict[str, Any]) -> None:
        for i, existing in enumerate(self._ledger):
            if existing.get("folio_fiscal") == cfdi.get("folio_fiscal"):
                merged = dict(existing)
                merged.update(cfdi)
                self._ledger[i] = merged
                return
        self._ledger.append(cfdi)

    # ------------------------------------------------------------------ #
    # Descarga de CFDI
    # ------------------------------------------------------------------ #
    def download_cfdi(self, fecha_inicio: str, fecha_fin: str,
                      tipo: str = "emitidas") -> Dict[str, Any]:
        """Descarga masiva de CFDI en un rango de fechas (mock).

        Genera `n` CFDI deterministas entre fecha_inicio y fecha_fin
        (inclusive). `tipo` ∈ {"emitidas", "recibidas"}. Requiere login.
        Devuelve la lista de CFDI descargados y los persiste en el ledger.
        """
        self._require_session()
        tipo = (tipo or "emitidas").strip().lower()
        if tipo not in TIPOS_CFDI:
            return {"ok": False, "error": f"tipo debe ser {' o '.join(TIPOS_CFDI)}.",
                    "backend": self.backend}
        try:
            d0 = _parse_date(fecha_inicio)
            d1 = _parse_date(fecha_fin)
        except ValueError as e:
            return {"ok": False, "error": str(e), "backend": self.backend}
        if d1 < d0:
            return {"ok": False, "error": "fecha_fin es anterior a fecha_inicio.",
                    "backend": self.backend}

        emisor, receptor = self.rfc, "AAA010101AAA"
        if tipo == "recibidas":
            emisor, receptor = "AAA010101AAA", self.rfc

        n_days = (d1 - d0).days + 1
        # 2 CFDI por día (mock). Determinista.
        cfdis: List[Dict[str, Any]] = []
        for day_offset in range(n_days):
            day = d0 + timedelta(days=day_offset)
            for k in range(2):
                folio = _mk_uuid(self.rfc, day.isoformat(), tipo, k)
                total = round((day_offset * 137.5 + k * 89.25) + 100, 2)
                estatus = "vigente"
                rec = {
                    "folio_fiscal": folio,
                    "tipo": tipo,
                    "fecha": _iso(day),
                    "emisor_rfc": emisor,
                    "receptor_rfc": receptor,
                    "total": total,
                    "moneda": "MXN",
                    "estatus": estatus,
                    "descargado_en": datetime.now().isoformat(timespec="seconds"),
                    "backend": self.backend,
                }
                cfdis.append(rec)
                self._upsert_ledger(rec)
        self._save_ledger()
        return {
            "ok": True, "tipo": tipo, "rfc": self.rfc,
            "fecha_inicio": _iso(d0), "fecha_fin": _iso(d1),
            "count": len(cfdis), "cfdis": cfdis, "backend": self.backend,
        }

    # ------------------------------------------------------------------ #
    # Balanza de comprobación
    # ------------------------------------------------------------------ #
    def download_balanza(self, periodo: str) -> Dict[str, Any]:
        """Descarga la balanza de comprobación del período (mock).

        `periodo` formato 'YYYY-MM'. Genera una balanza cuadrada con las
        cuentas del catálogo por defecto.
        """
        self._require_session()
        periodo = (periodo or "").strip()
        if not periodo or len(periodo) != 7 or periodo[4] != "-":
            return {"ok": False, "error": "periodo debe tener formato YYYY-MM.",
                    "backend": self.backend}
        try:
            ejercicio = int(periodo[:4])
            mes = int(periodo[5:7])
            if not (1 <= mes <= 12):
                raise ValueError
        except ValueError:
            return {"ok": False, "error": "periodo inválido (ej: 2026-07).",
                    "backend": self.backend}

        cuentas = [
            {"codigo": "1130", "descripcion": "Bancos", "naturaleza": "deudora",
             "saldo_inicial": "10000.00", "debe": "2500.00", "haber": "500.00",
             "saldo_final": "12000.00"},
            {"codigo": "2010", "descripcion": "Proveedores", "naturaleza": "acreedora",
             "saldo_inicial": "8000.00", "debe": "500.00", "haber": "1500.00",
             "saldo_final": "9000.00"},
            {"codigo": "6100", "descripcion": "Gastos por clasificar",
             "naturaleza": "deudora", "saldo_inicial": "0.00",
             "debe": "800.00", "haber": "0.00", "saldo_final": "800.00"},
        ]
        return {
            "ok": True, "rfc": self.rfc, "periodo": periodo,
            "ejercicio": ejercicio, "mes": mes, "cuadrada": True,
            "cuentas": cuentas, "backend": self.backend,
        }

    # ------------------------------------------------------------------ #
    # Catálogo de cuentas
    # ------------------------------------------------------------------ #
    def download_catalogo_cuentas(self) -> Dict[str, Any]:
        """Descarga el catálogo de cuentas del SAT (mock). Requiere login."""
        self._require_session()
        catalogo = [
            {"codigo": "1130", "descripcion": "Bancos", "nivel": 1,
             "naturaleza": "deudora"},
            {"codigo": "2010", "descripcion": "Proveedores", "nivel": 1,
             "naturaleza": "acreedora"},
            {"codigo": "6100", "descripcion": "Gastos por clasificar",
             "nivel": 1, "naturaleza": "deudora"},
            {"codigo": "6110", "descripcion": "Sueldos y salarios", "nivel": 1,
             "naturaleza": "deudora"},
            {"codigo": "6131", "descripcion": "Gastos generales", "nivel": 1,
             "naturaleza": "deudora"},
        ]
        return {"ok": True, "rfc": self.rfc, "count": len(catalogo),
                "catalogo": catalogo, "backend": self.backend}

    # ------------------------------------------------------------------ #
    # Estado
    # ------------------------------------------------------------------ #
    def status(self) -> Dict[str, Any]:
        """Estado de la sesión / descargas del tenant (para /api/v1/sat/status)."""
        return {
            "logged_in": self.logged_in,
            "rfc": self.logged_rfc or self.rfc,
            "backend": self.backend,
            "ledger_count": len(self._ledger),
            "last_download": self._last_download(),
        }

    def _last_download(self) -> Optional[str]:
        if not self._ledger:
            return None
        fechas = [c.get("descargado_en", "") for c in self._ledger if c.get("descargado_en")]
        return max(fechas) if fechas else None
