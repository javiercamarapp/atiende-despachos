# -*- coding: utf-8 -*-
"""
security.py — Validación de inputs, PII y cifrado para hardening enterprise.

Agrupa los controles de la FASE security-hardening que no viven en un
middleware:

  * `allowed_upload_extension`  — acepta solo XML/PDF (CFDI).
  * `detect_pii`                — detecta PII en los datos de un CFDI
                                  (RFC, emails, teléfonos, CURP, cuentas
                                  bancarias) para el audit de protección de
                                  datos.
  * `encrypt_field` / `decrypt_field` — cifrado simétrico en reposo (AES-GCM)
                                  de campos sensibles (webhook_url,
                                  notif_recipient) con clave derivada de
                                  B2B_ENCRYPTION_KEY. Si no hay clave
                                  configurada, devuelve el texto plano (modo
                                  degradado: NUNCA rompe lecturas/existentes).
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
from pathlib import Path

from b2b_ai.common.rfc import RFC_RE as _CANONICAL_RFC_RE

# --------------------------------------------------------------------------- #
# Upload validation
# --------------------------------------------------------------------------- #
# Extensiones permitidas para subida de CFDI. El pipeline valida el contenido
# (XML del SAT); aquí cerramos la puerta a subir binarios/scripts con otras
# extensiones antes siquiera de tocar el disco.
_ALLOWED_UPLOAD_EXT = (".xml", ".pdf")
_ALLOWED_EXT_RE = re.compile(r"\.(xml|pdf)$", re.IGNORECASE)


def allowed_upload_extension(filename: str) -> bool:
    """True si `filename` termina en .xml o .pdf (extensión CFDI válida)."""
    return bool(_ALLOWED_EXT_RE.search(filename or ""))


# --------------------------------------------------------------------------- #
# Path traversal defense
# --------------------------------------------------------------------------- #
# Directorios permitidos para xml_path (resolved, no trailing slash).
def _allowed_dirs():
    """Devuelve directorios permitidos para xml_path."""
    base = Path(__file__).resolve().parent.parent.parent  # enterprise/
    return [
        (base / "data").resolve(),
        (base / "tmp").resolve(),
        (base / "uploads").resolve(),
        (base / "fixtures").resolve(),
        (base / "demo-data").resolve(),
        (base / "b2b_ai" / "demo-data").resolve(),
        Path(tempfile.gettempdir()).resolve(),
    ]


import tempfile  # noqa: E402 — needed by _allowed_dirs


def validate_xml_path(xml_path: str) -> str:
    """Valida que xml_path no contenga path traversal.

    Resuelve symlinks y '..' y verifica que el path real esté dentro de
    un directorio permitido. Lanza ValueError si el path es inseguro.
    Devuelve el path resuelto (absoluto, sin symlinks).
    """
    if not xml_path or not isinstance(xml_path, str):
        raise ValueError("xml_path es obligatorio.")
    # Resolve para colapsar '..', symlinks, etc.
    try:
        resolved = Path(xml_path).resolve()
    except (OSError, ValueError) as e:
        raise ValueError(f"xml_path inválido: {e}") from e
    # Verificar que el path resuelto está dentro de un directorio permitido.
    allowed = _allowed_dirs()
    for d in allowed:
        try:
            resolved.relative_to(d)
            return str(resolved)
        except ValueError:
            continue
    # Si no está en ningún directorio permitido, rechazar.
    raise ValueError(
        f"xml_path fuera de directorios permitidos: {xml_path}. "
        f"Directorios permitidos: {[str(d) for d in allowed]}"
    )


# --------------------------------------------------------------------------- #
# PII detection
# --------------------------------------------------------------------------- #
# Use canonical RFC regex from b2b_ai.common.rfc for consistency.
_RFC_RE = _CANONICAL_RFC_RE
_CURP_RE = re.compile(r"^[A-Z][AEIOUX][A-Z]{2}\d{6}[HM][A-Z]{5}[A-Z0-9]\d$")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)[\s.-]?)?"
    r"\d{3}[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)")
# Tarjetas / cuentas CLABE de 18 dígitos (tarjetas 13-16).
_CARD_RE = re.compile(r"\b\d{13,16}\b")
_CLABE_RE = re.compile(r"\b\d{18}\b")


def _norm(v) -> str:
    return "" if v is None else str(v)


def detect_pii(datos: dict) -> dict:
    """Escanea los datos parseados de un CFDI en busca de PII.

    Devuelve {"pii": bool, "tipos": {tipo: [valores]}, "found": [...]} para
    que el pipeline la incluya en el audit log / validación sin romper el flujo
    existente.
    """
    campos = ["emisor_nombre", "receptor_nombre", "emisor_rfc", "receptor_rfc",
              "descripcion", "conceptos", "observaciones", "comentarios",
              "referencia", "metodo_pago", "forma_pago", "lugar_expedicion"]
    texto = " ".join(_norm(datos.get(c)) for c in campos)
    # Añade los conceptos (listas) serializados.
    for c in ("conceptos", "impuestos"):
        val = datos.get(c)
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    texto += " " + " ".join(_norm(item.get(k)) for k in item)
                else:
                    texto += " " + _norm(item)
        elif val:
            texto += " " + _norm(val)

    found: dict = {}

    # RFC (atributos específicos primero: son PII identificativa de persona/
    # empresa). Físicas llevan CURP. El RFC genérico XAXX010101000 es un
    # placeholder público (no identifica a nadie) y se excluye.
    _GENERIC_RFC = "XAXX010101000"
    for c in ("emisor_rfc", "receptor_rfc"):
        rfc = _norm(datos.get(c)).strip().upper()
        if rfc == _GENERIC_RFC:
            continue
        if _RFC_RE.match(rfc):
            found.setdefault("rfc", []).append(rfc)

    curp = _norm(datos.get("curp") or datos.get("receptor_curp")).strip().upper()
    if curp and _CURP_RE.match(curp):
        found.setdefault("curp", []).append(curp)

    for m in _EMAIL_RE.findall(texto):
        found.setdefault("email", []).append(m)

    # Teléfonos: excluye montos/códigos postales cortos con prefijo de ≥10 díg.
    for m in _PHONE_RE.findall(texto):
        digits = re.sub(r"\D", "", m)
        if 10 <= len(digits) <= 15:
            found.setdefault("telefono", []).append(m)

    for m in _CLABE_RE.findall(texto):
        found.setdefault("clabe_cuenta", []).append(m)
    for m in _CARD_RE.findall(texto):
        # Evita confundir totales (ej. 1234567890123 sin separadores) si no
        # hay contexto — solo cuenta como tarjeta si aparece en descripción
        # con prefijo de tarjeta (4 | 5[1-5] | 3[47] | 6).
        if re.match(r"^(4|5[1-5]|3[47]|6)", m):
            found.setdefault("tarjeta", []).append(m)

    # Dedup y orden.
    for k in found:
        found[k] = sorted(set(found[k]))

    pii = bool(found)
    return {
        "pii": pii,
        "tipos": list(found.keys()),
        "found": found,
    }


# --------------------------------------------------------------------------- #
# Encryption at rest (AES-GCM) — opt-in vía B2B_ENCRYPTION_KEY
# --------------------------------------------------------------------------- #
# Prefijo que identifica un valor cifrado frente a uno en claro.
_CIPHER_PREFIX = "enc1:"


def _encryption_key() -> bytes | None:
    """Clave de 32 bytes derivada (SHA-256) de B2B_ENCRYPTION_KEY.

    Devuelve None si la env no está definida → cifrado desactivado (modo
    degradado, sin romper lecturas).
    """
    raw = os.environ.get("B2B_ENCRYPTION_KEY", "").strip()
    if not raw or len(raw) < 16:
        return None
    return hashlib.sha256(raw.encode("utf-8")).digest()


def _cipher():
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = _encryption_key()
    if key is None:
        return None
    return AESGCM(key)


def encrypt_field(value: str) -> str:
    """Cifra `value` en reposo. Sin clave configurada, devuelve el valor tal
    cual (degradado transparente). Los valores ya cifrados no se recifran."""
    if not value or value.startswith(_CIPHER_PREFIX):
        return value
    c = _cipher()
    if c is None:
        return value
    import os as _os
    nonce = _os.urandom(12)
    ct = c.encrypt(nonce, value.encode("utf-8"), None)
    return _CIPHER_PREFIX + base64.urlsafe_b64encode(nonce + ct).decode("ascii")


def decrypt_field(value: str) -> str:
    """Descifra un valor cifrado con encrypt_field. Los valores en claro o sin
    clave configurada se devuelven tal cual (compatibilidad con datos viejos
    y con el modo degradado)."""
    if not value or not value.startswith(_CIPHER_PREFIX):
        return value
    try:
        blob = base64.urlsafe_b64decode(value[len(_CIPHER_PREFIX):])
        nonce, ct = blob[:12], blob[12:]
        c = _cipher()
        if c is None:
            return value
        return c.decrypt(nonce, ct, None).decode("utf-8")
    except Exception:  # noqa: BLE001 — no romper lectura ante datos corruptos
        return value
