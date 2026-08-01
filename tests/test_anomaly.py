# -*- coding: utf-8 -*-
"""Tests de detección de anomalías en facturas (FASE 2)."""
from b2b_ai.services.anomaly import (detect_anomalies, summarize_anomalies,
                                     SEVERITIES)


def _inv(total, rfc="CON950820K12", fecha="2026-07-03", iva=None,
         subtotal=None, folio=None, tasa_iva=None):
    if subtotal is None and total is not None:
        subtotal = round(total / 1.16, 2)
    if iva is None and subtotal is not None:
        iva = round(subtotal * 0.16, 2)
    return {"folio_fiscal": folio or f"FAC-{total}", "emisor_rfc": rfc,
            "total": str(total), "subtotal": str(subtotal), "iva": str(iva),
            "fecha": fecha, "tasa_iva": tasa_iva}


def test_sin_historial_detecta_proveedor_nuevo():
    inv = _inv(1000)
    an = detect_anomalies(inv, [])
    tipos = {a["tipo"] for a in an}
    assert "proveedor_nuevo" in tipos
    nuevo = [a for a in an if a["tipo"] == "proveedor_nuevo"][0]
    assert nuevo["severity"] == "low"
    assert nuevo["referencia_legal"]


def test_sin_anomalias_con_historial_normal():
    inv = _inv(1000)
    historial = [_inv(900), _inv(1100), _inv(950)]
    an = detect_anomalies(inv, historial)
    tipos = {a["tipo"] for a in an}
    # Historial del mismo RFC -> ya no es proveedor nuevo; montos normales
    assert "proveedor_nuevo" not in tipos
    assert "monto_atipico" not in tipos
    assert "duplicado" not in tipos


def test_duplicado_mismo_monto_rfc_fecha():
    inv = _inv(1000, fecha="2026-07-03")
    historial = [_inv(1000, fecha="2026-07-01"),
                 _inv(1000, fecha="2026-07-05")]  # ambos <= 3 días
    an = detect_anomalies(inv, historial)
    dups = [a for a in an if a["tipo"] == "duplicado"]
    assert len(dups) == 2
    assert all(a["severity"] == "high" for a in dups)
    assert "29-A" in dups[0]["referencia_legal"]


def test_duplicado_fuera_de_3_dias_no_detecta():
    inv = _inv(1000, fecha="2026-07-20")
    historial = [_inv(1000, fecha="2026-07-01")]  # 19 días de distancia
    an = detect_anomalies(inv, historial)
    assert not [a for a in an if a["tipo"] == "duplicado"]


def test_duplicado_requiere_mismo_rfc():
    inv = _inv(1000, rfc="RFC-A", fecha="2026-07-03")
    historial = [_inv(1000, rfc="RFC-B", fecha="2026-07-01")]
    an = detect_anomalies(inv, historial)
    assert not [a for a in an if a["tipo"] == "duplicado"]


def test_monto_atipico_mas_de_2_desviaciones():
    # Historial concentrado ~1000, la factura nueva es 10000
    historial = [_inv(1000), _inv(1000), _inv(1000), _inv(1000), _inv(1000)]
    inv = _inv(10000)
    an = detect_anomalies(inv, historial)
    atip = [a for a in an if a["tipo"] == "monto_atipico"]
    assert len(atip) == 1
    assert atip[0]["severity"] == "medium"


def test_monto_atipico_necesita_3_datos():
    historial = [_inv(1000), _inv(1000)]
    inv = _inv(10000)
    an = detect_anomalies(inv, historial)
    assert not [a for a in an if a["tipo"] == "monto_atipico"]


def test_iva_inconsistente():
    inv = _inv(1000)
    # Corromper el IVA a un valor distinto del esperado
    inv["iva"] = "999.99"
    an = detect_anomalies(inv, [])
    ivas = [a for a in an if a["tipo"] == "iva_inconsistente"]
    assert len(ivas) == 1
    assert ivas[0]["severity"] == "medium"
    assert "IVA" in ivas[0]["referencia_legal"]


def test_iva_consistente_no_detecta():
    inv = _inv(1000)
    an = detect_anomalies(inv, [])
    assert not [a for a in an if a["tipo"] == "iva_inconsistente"]


def test_iva_con_tasa_distinta():
    inv = _inv(1000, tasa_iva=0.08)
    # esperado subtotal*0.08; _inv calculó con 0.16 -> debe marcar inconsistente
    an = detect_anomalies(inv, [])
    assert [a for a in an if a["tipo"] == "iva_inconsistente"]


def test_toda_anomalia_tiene_campos_completos():
    an = detect_anomalies(_inv(1000), [])
    for a in an:
        assert a["severity"] in SEVERITIES
        assert a["descripcion"]
        assert a["supuestos"]
        assert a["referencia_legal"]
        assert a["detalle"]


def test_summarize_vacio():
    s = summarize_anomalies([])
    assert s["total"] == 0
    assert s["max_severity"] is None


def test_summarize_con_anomalias():
    an = detect_anomalies(_inv(1000), [])  # proveedor nuevo
    s = summarize_anomalies(an)
    assert s["total"] == len(an)
    assert s["por_tipo"]["proveedor_nuevo"] == 1
    assert s["max_severity"] == "low"


def test_max_severity_prioriza_critical():
    from b2b_ai.services.anomaly import _anomaly
    an = [_anomaly("x", "low", "d", ["s"], "l", {}),
          _anomaly("y", "critical", "d", ["s"], "l", {})]
    assert summarize_anomalies(an)["max_severity"] == "critical"


def test_no_detecta_con_datos_incompletos():
    an = detect_anomalies({}, [])
    assert an == []
