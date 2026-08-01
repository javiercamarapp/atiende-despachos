# -*- coding: utf-8 -*-
"""
validator.py — Validación fiscal avanzada de un CFDI parseado.

Cubre validaciones determinísticas (sin LLM):
  1. Aritmética por concepto: cantidad × valor_unitario = importe
  2. Suma de conceptos == subtotal
  3. IVA por concepto: base × tasa = importe (y global)
  4. Coherencia: subtotal + IVA − descuento ≈ total
  5. Catálogos SAT (UsoCFDI, FormaPago, MetodoPago, Tipo, Régimen)
  6. RFC bien formados
  7. Coherencia de fechas (FechaTimbrado ≥ Fecha)
  8. Retenciones declaradas coherentes
  9. DIOT: identificación de proveedores reportables y preparación de líneas
  10. Flags de "requiere revisión humana" en decisiones con efecto fiscal

Principio (de `04-leyes-fiscales.md`): cada salida con efecto fiscal lleva
referencia legal + supuesto + flag de revisión humana.
"""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from b2b_ai.cfdi import catalogs
from b2b_ai.common.rfc import RFC_RE, is_valid_rfc

# Tasas de IVA vigentes (LIVA art. 1-C)
IVA_TASA_GENERAL = Decimal("0.16")    # 16% - General
IVA_TASA_FRONTERA = Decimal("0.08")  # 8% - Zona fronteriza (art. 1-C fracc. II)
IVA_TASA_EXENTO = Decimal("0.00")    # 0% - Exento
# Tasa por defecto para validación
IVA_TASA = IVA_TASA_GENERAL
TOLERANCIA = Decimal("0.02")

# Umbrales referenciales (sujetos a validación humana; regla 2.7.1.47 RMF)
# Montos que suelen requerir aceptación del receptor para cancelar.
UMBRAL_CANCELACION_ACEPTACION = Decimal("500.00")


def _dec(v):
    try:
        return Decimal(str(v))
    except Exception:
        return None


def _parse_fecha(f):
    if not f:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(f, fmt)
        except ValueError:
            continue
    return None


def _es_rfc_valido(rfc):
    """Valida RFC usando la función canónica centralizada."""
    return is_valid_rfc(rfc)


class ValidationResult(dict):
    """dict con acceso por atributo."""

    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k)


def validate_cfdi(datos):
    issues = []
    warnings = []
    checks = {"pass": 0, "fail": 0}
    diot = {"proveedores_reportables": [], "reportable": False}
    reference_notes = []

    def _fail(code, msg, ref=None):
        entry = {"code": code, "mensaje": msg}
        if ref:
            entry["ref"] = ref
        issues.append(entry)
        checks["fail"] += 1

    def _ok(msg):
        checks["pass"] += 1

    subtotal = _dec(datos.get("subtotal"))
    total = _dec(datos.get("total"))
    descuento = _dec(datos.get("descuento")) or Decimal("0")
    iva = _dec(datos.get("iva"))
    conceptos = datos.get("conceptos", [])
    ret_isr = _dec(datos.get("retenciones_isr"))
    ret_iva = _dec(datos.get("retenciones_iva"))

    # ---- 1. Aritmética por concepto ----
    if conceptos:
        for i, c in enumerate(conceptos):
            cant = _dec(c.get("cantidad"))
            vu = _dec(c.get("valor_unitario"))
            imp = _dec(c.get("importe"))
            if cant is not None and vu is not None and imp is not None:
                esperado = (cant * vu).quantize(Decimal("0.01"))
                if abs(esperado - imp) > TOLERANCIA:
                    _fail("importe_concepto_incoherente",
                          f"Concepto {i + 1}: {cant} × {vu} = {esperado} "
                          f"pero Importe={imp}", "Anexo 20 / Guia de llenado")
                else:
                    _ok(f"Concepto {i + 1}: aritmetica correcta")
            # IVA por concepto
            for tr in c.get("traslados", []):
                if tr.get("impuesto") == "002" and tr.get("tipo_factor") == "Tasa":
                    base = _dec(tr.get("base"))
                    tasa = _dec(tr.get("tasa_cuota"))
                    imp_t = _dec(tr.get("importe"))
                    if base is not None and tasa is not None and imp_t is not None:
                        esperado = (base * tasa).quantize(Decimal("0.01"))
                        if abs(esperado - imp_t) > TOLERANCIA:
                            _fail("iva_concepto_incoherente",
                                  f"Concepto {i + 1}: IVA base {base} × tasa "
                                  f"{tasa} = {esperado} pero Importe={imp_t}",
                                  "LIVA art. 1 y 5, Anexo 20")
                        else:
                            _ok(f"Concepto {i + 1}: IVA desglosado correcto")

    # ---- 2. Suma de conceptos == subtotal ----
    if conceptos and subtotal is not None:
        suma = sum((_dec(c.get("importe")) or Decimal("0")) for c in conceptos)
        suma = suma.quantize(Decimal("0.01"))
        if abs(suma - subtotal) > TOLERANCIA:
            _fail("subtotal_descuadra_conceptos",
                  f"Suma de conceptos {suma} != SubTotal {subtotal}",
                  "Anexo 20")
        else:
            _ok("SubTotal == suma de conceptos")

    # ---- 3. IVA global ----
    if iva is not None and subtotal is not None:
        esperado = (subtotal * IVA_TASA).quantize(Decimal("0.01"))
        if abs(iva - esperado) > TOLERANCIA:
            warnings.append(f"IVA global {iva} difiere de 16% del subtotal "
                            f"({esperado}); puede haber tasas diferenciadas "
                            f"(frontera 8%) u operaciones exentas.")
        else:
            _ok("IVA global coherente con 16%")

    # ---- 4. Coherencia total ----
    if subtotal is not None and total is not None:
        ret_tot = (ret_isr or Decimal("0")) + (ret_iva or Decimal("0"))
        esperado = (subtotal + (iva or Decimal("0")) - descuento - ret_tot)\
            .quantize(Decimal("0.01"))
        if abs(esperado - total) > TOLERANCIA:
            _fail("total_incoherente",
                  f"SubTotal + IVA − Descuento − Retenciones = {esperado} "
                  f"pero Total={total}",
                  "Anexo 20 / Guia de llenado")
        else:
            _ok("Total coherente")

    # ---- 5. Catálogos SAT ----
    uso = datos.get("uso_cfdi", "")
    if uso and not catalogs.is_valid_uso_cfdi(uso):
        _fail("uso_cfdi_invalido", f"UsoCFDI '{uso}' no está en el catálogo c_UsoCFDI.",
              "c_UsoCFDI")
    else:
        _ok("UsoCFDI en catálogo" if uso else "Sin UsoCFDI (no aplica)")
    fp = datos.get("forma_pago", "")
    if fp and not catalogs.is_valid_forma_pago(fp):
        _fail("forma_pago_invalida", f"FormaPago '{fp}' no está en el catálogo c_FormaPago.",
              "c_FormaPago")
    else:
        _ok("FormaPago en catálogo" if fp else "Sin FormaPago")
    mp = datos.get("metodo_pago", "")
    if not mp:
        _fail("metodo_pago_ausente", "MetodoPago es obligatorio (PUE o PPD).", "CFF art. 29-A")
    elif not catalogs.is_valid_metodo_pago(mp):
        _fail("metodo_pago_invalido", f"MetodoPago '{mp}' no es PUE/PPD.", "c_MetodoPago")
    else:
        _ok("MetodoPago valido")
    tdc = datos.get("tipo", "")
    if not tdc:
        _fail("tipo_comprobante_ausente", "TipoDeComprobante es obligatorio (I, E, T, P, N).", "CFF art. 29-A")
    elif not catalogs.is_valid_tipo_comprobante(tdc):
        _fail("tipo_comprobante_invalido", f"TipoDeComprobante '{tdc}' invalido.", "c_TipoDeComprobante")
    else:
        _ok("TipoDeComprobante valido")
    regimen = datos.get("emisor", {}).get("regimen_fiscal", "")
    if not regimen:
        _fail("regimen_fiscal_ausente", "RegimenFiscal del emisor es obligatorio.", "CFF art. 29-A")
    elif not catalogs.is_valid_regimen(regimen):
        _fail("regimen_fiscal_invalido", f"RegimenFiscal '{regimen}' no esta en el catalogo.", "c_RegimenFiscal")
    else:
        _ok("RegimenFiscal del emisor en catalogo")
    else:
        _ok("RegimenFiscal del emisor en catálogo")

    # ---- 6. RFCs ----
    if not _es_rfc_valido(datos.get("emisor_rfc", "")):
        _fail("rfc_emisor_invalido", f"RFC emisor inválido: '{datos.get('emisor_rfc')}'",
              "CFF art. 29-A")
    else:
        _ok("RFC emisor válido")
    if not _es_rfc_valido(datos.get("receptor_rfc", "")):
        _fail("rfc_receptor_invalido", f"RFC receptor inválido: '{datos.get('receptor_rfc')}'",
              "CFF art. 29-A")
    else:
        _ok("RFC receptor válido")

    # ---- 7. Fechas ----
    f_emi = _parse_fecha(datos.get("fecha", ""))
    f_timb = _parse_fecha(datos.get("fecha_timbrado", ""))
    if f_emi is None:
        _fail("fecha_invalida", f"Fecha de emisión inválida: '{datos.get('fecha')}'")
    else:
        _ok("Fecha de emisión válida")
    if f_timb is not None and f_emi is not None and f_timb < f_emi:
        _fail("fecha_timbrado_anterior", "FechaTimbrado es anterior a la fecha de emisión.",
              "Anexo 20")
    elif f_timb is not None:
        _ok("FechaTimbrado posterior a Fecha")
    else:
        warnings.append("Sin TimbreFiscalDigital (comprobante no timbrado).")

    # ---- 8. Retenciones ----
    if ret_isr is not None and subtotal:
        # Retención ISR típica 10% sobre honorarios (tasa referencial)
        esperado = (subtotal * Decimal("0.10")).quantize(Decimal("0.01"))
        if abs(ret_isr - esperado) > Decimal("1.00"):
            warnings.append(f"Retención ISR {ret_isr} no coincide con 10% "
                            f"referencial ({esperado}); revisar caso.")
    if ret_iva is not None and iva:
        esperado = (iva * Decimal("0.6667")).quantize(Decimal("0.01"))
        if abs(ret_iva - esperado) > Decimal("1.00"):
            warnings.append(f"Retención IVA {ret_iva} no coincide con 2/3 "
                            f"del IVA ({esperado}); revisar caso.")

    # ---- 9. DIOT: proveedores reportables ----
    if tdc == "I" and subtotal is not None and subtotal > 0:
        diot["reportable"] = True
        diot["proveedores_reportables"].append({
            "rfc_proveedor": datos.get("emisor_rfc", ""),
            "nombre_proveedor": datos.get("emisor_nombre", ""),
            "total_operacion": str(total or subtotal),
            "iva_acreditable": str(iva or "0"),
            "periodo": (f_emi.strftime("%Y-%m") if f_emi else ""),
        })
        # Flag de revisión humana por DIOT (art. 32 LISR / 31 LIVA)
        if iva and iva > 0:
            reference_notes.append(
                "Proveedor reportable en DIOT (art. 32 LISR, art. 31 LIVA). "
                "Requiere revisión humana antes de presentar.")

    # ---- 10. Nómina: validaciones específicas ----
    nomina = datos.get("nomina")
    if nomina:
        if datos.get("metodo_pago", "") != "PUE":
            _fail("nomina_metodo_pago", "El CFDI de nómina debe usar MetodoPago PUE.",
                  "Complemento de Nomina 1.2")
        if nomina.get("total_percepciones") is None:
            warnings.append("Nómina sin TotalPercepciones declarado.")

    # ---- Comprobante de pagos (PPD) ----
    if datos.get("pagos") and datos.get("tipo") == "P":
        for p in datos["pagos"]:
            if p.get("monto") and p.get("monto") <= 0:
                _fail("pago_monto_invalido", "Pago con monto no positivo.", "Anexo 20")

    ok = checks["fail"] == 0
    requires_human_review = bool(
        issues or diot.get("reportable") or (nomina is not None) or
        (datos.get("tipo") in ("E", "P"))
    )

    return ValidationResult({
        "ok": ok,
        "issues": issues,
        "warnings": warnings,
        "checks": checks,
        "diot": diot,
        "requires_human_review": requires_human_review,
        "reference_notes": reference_notes,
    })


def main():
    import sys
    import json
    from b2b_ai.cfdi.parser import parse_cfdi

    if len(sys.argv) < 2:
        print("Uso: python3 -m b2b_ai.cfdi.validator <archivo.xml>")
        sys.exit(1)

    def _ser(o):
        if isinstance(o, Decimal):
            return str(o)
        if isinstance(o, dict):
            return {k: _ser(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_ser(v) for v in o]
        return o

    datos = parse_cfdi(sys.argv[1])
    res = validate_cfdi(datos)
    print(json.dumps(_ser(res), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
