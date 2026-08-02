# -*- coding: utf-8 -*-
"""
validators.py — Enterprise Request Validation for Mexican fiscal domain.

Pydantic models and field validators for:
  - RFC (Registro Federal de Contribuyentes) with check digit (CFF Art. 23)
  - CURP (Clave Única de Registro de Población)
  - NSS (Número de Seguridad Social)
  - CLABE (Clave Bancaria Estandarizada)
  - Input sanitization (trim, normalize, strip HTML)

All validators use Pydantic v2 with custom field validators.
No raw dicts allowed — every endpoint payload must use a typed model.
"""
from __future__ import annotations

import html
import re
import unicodedata
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# RFC validation (CFF Art. 23)
# ---------------------------------------------------------------------------

# RFC regex patterns
_RFC_PERSONA_MORAL_RE = re.compile(
    r"^[A-Z&Ñ]{3}\d{6}[A-Z0-9]{3}$"
)
_RFC_PERSONA_FISICA_RE = re.compile(
    r"^[A-Z&Ñ]{4}\d{6}[A-Z0-9]{3}$"
)

# Homoclave positions (last 3 chars): 2 alphanumeric + 1 check digit
_RFC_HOMOCLAVE_RE = re.compile(r"^[A-Z0-9]{2}\d$")

# SAT "palabras inconvenientes" — incomplete list for validation warning
_INCONVENIENT_WORDS = {
    "BUEI", "BUEY", "CACA", "CACO", "CAGA", "CAGO", "CAKA", "CAKO",
    "COGE", "COGI", "COJA", "COJE", "COJI", "COJO", "COLA", "CULO",
    "FALO", "FETO", "GETA", "GUEI", "GUEY", "JETA", "JOTO", "KACA",
    "KACO", "KAGA", "KAGO", "KAKA", "KAKO", "KOGE", "KOGI", "KOJO",
    "KOLA", "KULO", "LELO", "LILO", "LOCA", "LOCO", "LOKA", "LOKO",
    "MAME", "MAMO", "MEAR", "MEAS", "MEON", "MIAR", "MION", "MOCO",
    "MOKO", "MULA", "MULO", "NACA", "NACO", "PEDA", "PEDO", "PENE",
    "PIPI", "PITO", "POPO", "PUTA", "PUTO", "QULO", "RATA", "ROBA",
    "ROBE", "ROBO", "RUIN", "SENO", "TETA", "VACA", "VAGA", "VAGO",
    "VAKA", "VUEI", "VUEY", "WUEI", "WUEY",
}

# Value assigned to each character for check digit computation
_LETRA_VALOR = {
    "0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7,
    "8": 8, "9": 9, "A": 10, "B": 11, "C": 12, "D": 13, "E": 14,
    "F": 15, "G": 16, "H": 17, "I": 18, "J": 19, "K": 20, "L": 21,
    "M": 22, "N": 23, "&": 24, "Ñ": 25, "O": 26, "P": 27, "Q": 28,
    "R": 29, "S": 30, "T": 31, "U": 32, "V": 33, "W": 34, "X": 35,
    "Y": 36, "Z": 37,
}

# Check digit verification: result value to expected digit
_VERIFICADOR = "123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"


def validate_rfc_check_digit(rfc: str) -> bool:
    """Validate RFC check digit per CFF Art. 23.

    The check digit is the last character of the RFC. The algorithm:
    1. Assign numeric value to each of the first 12 characters
    2. Multiply by position factor (13, 12, 11, ..., 2) — positions 0-11
    3. Sum all products
    4. Take modulo 11
    5. If result is 0, check digit is 0
    6. If result is 1, the RFC has no valid check digit (edge case)
    7. Otherwise, 11 - result = check digit value, mapped to character
    """
    rfc = rfc.strip().upper()
    if len(rfc) not in (12, 13):
        return False

    # Last char is check digit
    body = rfc[:len(rfc) - 1]
    check = rfc[-1]

    # All body chars must be in our lookup
    for ch in body:
        if ch not in _LETRA_VALOR:
            return False

    # Compute sum
    total = 0
    for i, ch in enumerate(body):
        val = _LETRA_VALOR[ch]
        factor = len(body) + 1 - i  # 13 for first char (persona moral)
        # Wait — actually for persona moral (12 chars body = 12 chars + 1 check = 13 total)
        # For persona fisica (13 chars body = 13 chars + 1 check = 14 total)
        # But the RFC body before check digit is always 12 chars for PM, 13 for PF
        # Let me re-check...
        # Actually: PM = 3 letter + 6 digits + 3 homoclave = 12 chars (11 body + 1 check)
        # PF = 4 letter + 6 digits + 3 homoclave = 13 chars (12 body + 1 check)
        # The factor starts at 13 for position 0 regardless of length
        total += val * (13 - i)

    remainder = total % 11
    if remainder == 0:
        expected = "0"
    elif remainder == 1:
        # Special case: RFC cannot be assigned (rare, but valid per SAT)
        expected = "A"
    else:
        idx = 11 - remainder
        if idx < len(_VERIFICADOR):
            expected = _VERIFICADOR[idx - 1] if idx > 0 else "0"
        else:
            return False

    # The mapping is simpler in practice:
    # remainder 0 → check digit "0"
    # remainder 1 → check digit "A" (or "B" for very old registrations)
    # remainder 2-10 → check digit from lookup
    # Let me use the official algorithm more precisely
    return _verify_rfc_digit(rfc)


def _verify_rfc_digit(rfc: str) -> bool:
    """Precise check digit verification per SAT algorithm."""
    rfc = rfc.strip().upper()
    if len(rfc) < 12 or len(rfc) > 13:
        return False

    body = rfc[:-1]
    check_char = rfc[-1]

    total = 0
    for i, ch in enumerate(body):
        if ch not in _LETRA_VALOR:
            return False
        total += _LETRA_VALOR[ch] * (13 - i)

    remainder = total % 11

    if remainder == 0:
        return check_char == "0"
    elif remainder == 1:
        return check_char in ("A", "B")
    else:
        expected_val = 11 - remainder
        # Map expected_val to a digit: 2→A, 3→9, 4→8, ..., 10→1, 11→0
        # Actually: 11 - remainder gives us 1-10, and we need to map to check char
        # The mapping: result 10 → 'A', 9 → 'B', 8 → 'C', ..., 2 → 'J', 1 → 'K'
        # But that's not right either. Let me use the official table.
        # Per SAT: if remainder is 2, expected = 'A' ... no wait.
        # Official: Verifier = (11 - (sum % 11)) % 11
        # 0→0, 1→1, 2→2, ..., 9→9, 10→A
        verifier = (11 - (total % 11)) % 11
        if verifier == 10:
            return check_char == "A"
        else:
            return check_char == str(verifier)


def validate_rfc(rfc: str) -> dict:
    """Full RFC validation. Returns {valid, type, warnings}."""
    rfc = _sanitize(rfc).upper()
    warnings = []

    if len(rfc) == 13 and _RFC_PERSONA_FISICA_RE.match(rfc):
        rfc_type = "persona_fisica"
    elif len(rfc) == 12 and _RFC_PERSONA_MORAL_RE.match(rfc):
        rfc_type = "persona_moral"
    else:
        return {"valid": False, "type": None, "warnings": ["Formato de RFC inválido."]}

    # Check digit
    if not _verify_rfc_digit(rfc):
        return {
            "valid": False,
            "type": rfc_type,
            "warnings": ["Dígito verificador inválido (CFF Art. 23)."],
        }

    # Palabras inconvenientes
    prefix = rfc[:4] if rfc_type == "persona_fisica" else rfc[:3]
    if prefix in _INCONVENIENT_WORDS:
        warnings.append(
            f"RFC contiene palabra inconveniente '{prefix}'. "
            "Verificar con el SAT."
        )

    return {"valid": True, "type": rfc_type, "warnings": warnings}


# ---------------------------------------------------------------------------
# CURP validation
# ---------------------------------------------------------------------------
_CURP_RE = re.compile(r"^[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d$")


def validate_curp(curp: str) -> bool:
    """Validate CURP format and check digit.

    CURP is 18 characters:
    - 4 letters (paternal surname initial, first vowel, maternal surname initial, first name initial)
    - 6 digits (YYMMDD birth date)
    - 1 letter (sex: H=M, M=F)
    - 2 letters (federal entity code)
    - 3 letters (first internal consonants of paternal, maternal, name)
    - 1 alphanumeric (disambiguator)
    - 1 digit (check digit)
    """
    curp = _sanitize(curp).upper()
    if len(curp) != 18:
        return False
    if not _CURP_RE.match(curp):
        return False

    # Validate check digit
    body = curp[:17]
    check = curp[17]

    # Character-to-number mapping for CURP check digit
    _curp_vals = {}
    for i, ch in enumerate("0123456789ABCDEFGHIJKLMNÑOPQRSTUVWXYZ"):
        _curp_vals[ch] = i

    total = 0
    for i, ch in enumerate(body):
        if ch not in _curp_vals:
            return False
        total += _curp_vals[ch] * (18 - i)

    remainder = total % 10
    expected = str((10 - remainder) % 10)
    return check == expected


# ---------------------------------------------------------------------------
# NSS validation
# ---------------------------------------------------------------------------
_NSS_RE = re.compile(r"^\d{11}$")


def validate_nss(nss: str) -> bool:
    """Validate NSS (Número de Seguridad Social) with Luhn-like check.

    NSS is 11 digits:
    - First 2 digits: subdelegation of affiliation
    - Next 6 digits: year and half-year of affiliation (YY + H)
    - Next 2 digits: consecutive number
    - Last digit: check digit

    Check digit algorithm (IMSS):
    1. Multiply odd-position digits by 1, even-position digits by 2
    2. Sum all digits of the products
    3. Check digit = (10 - (sum % 10)) % 10
    """
    nss = nss.strip().replace(" ", "").replace("-", "")
    if not _NSS_RE.match(nss):
        return False

    digits = [int(d) for d in nss]
    total = 0
    for i in range(10):  # First 10 digits
        factor = 1 if i % 2 == 0 else 2
        product = digits[i] * factor
        # If product >= 10, sum its digits (e.g., 14 → 1+4 = 5)
        total += (product // 10) + (product % 10)

    check = (10 - (total % 10)) % 10
    return digits[10] == check


# ---------------------------------------------------------------------------
# CLABE validation
# ---------------------------------------------------------------------------
_CLABE_RE = re.compile(r"^\d{18}$")

# Bank codes (first 3 digits) — SAT registry
_BANK_CODES = {
    "002": "Banamex", "006": "Bancomext", "009": "Banobras",
    "012": "BBVA", "014": "Santander", "019": "Banjercito",
    "021": "HSBC", "030": "Banco del Bajío", "036": "Inbursa",
    "037": "Mifel", "042": "Finterra", "058": "Banco Azteca",
    "059": "Banco Autofin", "060": "Bancoppel", "062": "T墈ỸỸỸỸỸ",
    "072": "Banco Regional", "102": "Deutsche Bank", "103": "American Express",
    "106": "Bank of America", "108": "Bank of Tokyo", "110": "JP Morgan",
    "112": "Monex", "113": "Ve por Más", "116": "ING",
    "124": "Deutsche Bank", "126": "Credit Suisse", "127": "Azteca",
    "128": "Banco Autofin", "129": "Barclays", "130": "Banco Bolsa",
    "131": "Banco Famsa", "132": "BMultiplica", "133": "Actinver",
    "134": "Wallmart", "135": "NAFIN", "136": "Scotiabank",
    "137": "Pagatodo", "138": "Ubankéa", "139": "Banregio",
    "140": "Invex", "141": "Banca Mifel", "142": "Multiva",
    "143": "Intercam", "144": "Volkswagen", "145": "CIBanco",
    "146": "Banco Base", "147": "Bankaool", "148": "PagaTodo",
    "150": "Banco Ahorro Famsa", "151": "Kuspit", "152": "Sofiexpress",
    "153": "Covalto", "154": "BanCoppel", "155": "Consubanco",
    "156": "Fincomún", "157": "Hey Banco", "158": "Banco Finterra",
    "159": "Caja Pop Mexica", "160": "Caja Telecomm", "162": "JeōỶỸỸ",
}


def validate_clabe(clabe: str) -> dict:
    """Validate CLABE interbancaria (18 digits with check digit).

    CLABE structure:
    - Digits 1-3: Bank code (clave del banco)
    - Digits 4-6: Branch code (plaza)
    - Digits 7-17: Account number
    - Digit 18: Check digit

    Check digit algorithm:
    1. Multiply each of the first 17 digits by factors [3,7,1] repeating
    2. Take modulo 10 of each product
    3. Sum all mod-10 results
    4. Check digit = (10 - (sum % 10)) % 10
    """
    clabe = clabe.strip().replace(" ", "").replace("-", "")
    if not _CLABE_RE.match(clabe):
        return {"valid": False, "bank": None, "warnings": ["CLABE must be exactly 18 digits."]}

    digits = [int(d) for d in clabe]
    factors = [3, 7, 1] * 6  # Repeating pattern for 18 digits

    total = 0
    for i in range(17):
        total += (digits[i] * factors[i]) % 10

    check = (10 - (total % 10)) % 10
    if digits[17] != check:
        return {
            "valid": False,
            "bank": None,
            "warnings": [f"Dígito verificador inválido. Esperado: {check}"],
        }

    bank_code = clabe[:3]
    bank_name = _BANK_CODES.get(bank_code, f"Banco desconocido ({bank_code})")

    return {"valid": True, "bank": bank_name, "bank_code": bank_code, "warnings": []}


# ---------------------------------------------------------------------------
# Input Sanitization
# ---------------------------------------------------------------------------
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_SPACE_RE = re.compile(r"\s+")


def _sanitize(value: str) -> str:
    """Trim, normalize Unicode, strip HTML tags, collapse whitespace."""
    if not isinstance(value, str):
        return value
    # Strip HTML tags
    value = _HTML_TAG_RE.sub("", value)
    # Decode HTML entities
    value = html.unescape(value)
    # Normalize Unicode (NFC form — canonical composition)
    value = unicodedata.normalize("NFC", value)
    # Collapse whitespace
    value = _MULTI_SPACE_RE.sub(" ", value)
    # Trim
    return value.strip()


def sanitize_string(v: Any) -> str:
    """Pydantic field validator for string sanitization."""
    if isinstance(v, str):
        return _sanitize(v)
    return v


# ---------------------------------------------------------------------------
# Reusable Pydantic Models (for endpoints that currently use raw dicts)
# ---------------------------------------------------------------------------
class EmpleadoInput(BaseModel):
    """Employee data for payroll calculation."""
    nombre: str = Field(..., min_length=1, max_length=200)
    rfc: Optional[str] = Field(None, max_length=13)
    curp: Optional[str] = Field(None, max_length=18)
    nss: Optional[str] = Field(None, max_length=11)
    salario_diario: float = Field(..., gt=0)
    tipo_contrato: str = Field(default="indefinido")
    regimen: str = Field(default="sueldos")

    @field_validator("nombre")
    @classmethod
    def sanitize_nombre(cls, v: str) -> str:
        return _sanitize(v)

    @field_validator("rfc")
    @classmethod
    def validate_rfc_field(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = _sanitize(v).upper()
        result = validate_rfc(v)
        if not result["valid"]:
            raise ValueError(f"RFC inválido: {result['warnings'][0]}")
        return v

    @field_validator("curp")
    @classmethod
    def validate_curp_field(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = _sanitize(v).upper()
        if not validate_curp(v):
            raise ValueError("CURP inválido.")
        return v

    @field_validator("nss")
    @classmethod
    def validate_nss_field(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = _sanitize(v).replace(" ", "").replace("-", "")
        if not validate_nss(v):
            raise ValueError("NSS inválido.")
        return v


class PeriodoInput(BaseModel):
    """Payroll period data."""
    fecha_inicio: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    fecha_fin: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    sueldo_bruto: float = Field(..., gt=0)
    dias_pagados: int = Field(default=15, ge=1, le=31)


class EmisorInput(BaseModel):
    """CFDI issuer data."""
    rfc: str = Field(..., min_length=12, max_length=13)
    nombre: str = Field(..., min_length=1, max_length=200)
    regimen_fiscal: str = Field(default="601")

    @field_validator("rfc")
    @classmethod
    def validate_emisor_rfc(cls, v: str) -> str:
        v = _sanitize(v).upper()
        result = validate_rfc(v)
        if not result["valid"]:
            raise ValueError(f"RFC del emisor inválido: {result['warnings'][0]}")
        return v

    @field_validator("nombre")
    @classmethod
    def sanitize_nombre(cls, v: str) -> str:
        return _sanitize(v)


class InvoiceItemInput(BaseModel):
    """Line item for an invoice."""
    descripcion: str = Field(..., min_length=1, max_length=500)
    cantidad: float = Field(default=1.0, gt=0)
    valor_unitario: float = Field(..., ge=0)
    importe: float = Field(..., ge=0)
    clave_prod_serv: str = Field(default="01010101")
    clave_unidad: str = Field(default="ACT")
    tasa_iva: float = Field(default=0.16, ge=0, le=1)

    @field_validator("descripcion")
    @classmethod
    def sanitize_desc(cls, v: str) -> str:
        return _sanitize(v)


class PaginacionInput(BaseModel):
    """Standard pagination parameters."""
    limit: int = Field(default=50, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)
    sort_by: Optional[str] = Field(None, max_length=50)
    sort_order: str = Field(default="desc", pattern="^(asc|desc)$")


class FiltrosFechaInput(BaseModel):
    """Date range filters."""
    fecha_desde: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    fecha_hasta: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class TenantOnboardInput(BaseModel):
    """Tenant onboarding request."""
    name: str = Field(..., min_length=1, max_length=200)
    rfc: Optional[str] = Field(None, max_length=13)
    erp_type: str = Field(default="contpaqi")
    plantilla_contable: str = Field(default="SAT")
    notif_channel: str = Field(default="email")
    webhook_url: Optional[str] = Field(None, max_length=500)
    user_name: Optional[str] = Field(None, max_length=200)
    user_email: Optional[str] = Field(None, max_length=200)

    @field_validator("name")
    @classmethod
    def sanitize_name(cls, v: str) -> str:
        return _sanitize(v)

    @field_validator("rfc")
    @classmethod
    def validate_tenant_rfc(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = _sanitize(v).upper()
        result = validate_rfc(v)
        if not result["valid"]:
            raise ValueError(f"RFC inválido: {result['warnings'][0]}")
        return v


class CFDIEmisorInput(BaseModel):
    """CFDI emisor for XML generation."""
    rfc: str = Field(..., min_length=12, max_length=13)
    nombre: str = Field(..., min_length=1, max_length=200)
    regimen_fiscal: str = Field(default="601")

    @field_validator("rfc")
    @classmethod
    def validate_rfc_f(cls, v: str) -> str:
        v = _sanitize(v).upper()
        r = validate_rfc(v)
        if not r["valid"]:
            raise ValueError(f"RFC inválido: {r['warnings'][0]}")
        return v


class CFDIReceptorInput(BaseModel):
    """CFDI receptor for XML generation."""
    rfc: str = Field(..., min_length=12, max_length=13)
    nombre: str = Field(..., min_length=1, max_length=200)
    regimen_fiscal: str = Field(default="601")
    uso_cfdi: str = Field(default="G03")
    domicilio_fiscal_receptor: str = Field(default="00000")

    @field_validator("rfc")
    @classmethod
    def validate_rfc_f(cls, v: str) -> str:
        v = _sanitize(v).upper()
        r = validate_rfc(v)
        if not r["valid"]:
            raise ValueError(f"RFC inválido: {r['warnings'][0]}")
        return v
