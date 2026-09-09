# -*- coding: utf-8 -*-
"""Tests de `_to_money` y del contrato numérico de invoices.subtotal/iva/total.

Cubre la capa Python (b2b_ai/db/db.py) que ya no debe asumir que estas tres
columnas son texto -- ver migrations/versions/0014_invoices_money_numeric.py
para el cambio de esquema en PostgreSQL (probado por separado contra PG real
en tests/migrations/test_0014_invoices_money_numeric.py).

Estos tests corren sobre SQLite (tmp_db), que sigue declarando las columnas
como TEXT (b2b_ai/db/models.py) -- por eso importa que `_to_money` deje el
mismo resultado que antes en ese backend, mientras arregla el bug real:
ya no se guarda "" para un monto ausente, y un valor no numérico ya no se
cuela como texto arbitrario.
"""
from decimal import Decimal

import pytest

from b2b_ai.db.db import _to_money


# ---------------------------------------------------------------------------
# _to_money: normalización pura, sin DB
# ---------------------------------------------------------------------------

class TestToMoney:
    def test_none_es_none(self):
        assert _to_money(None) is None

    def test_cadena_vacia_o_blanco_es_none(self):
        assert _to_money("") is None
        assert _to_money("   ") is None

    def test_decimal_pasa_igual(self):
        d = Decimal("116.00")
        assert _to_money(d) is d

    def test_string_numerica_se_convierte_a_decimal(self):
        assert _to_money("100") == Decimal("100")
        assert _to_money("1160.00") == Decimal("1160.00")
        assert _to_money("-50.25") == Decimal("-50.25")

    def test_int_y_float_se_convierten_a_decimal(self):
        assert _to_money(100) == Decimal("100")
        assert _to_money(100.5) == Decimal("100.5")

    def test_bool_no_se_trata_como_int(self):
        # bool es subclase de int en Python -- True/False nunca son montos.
        assert _to_money(True) is None
        assert _to_money(False) is None

    def test_valor_no_numerico_se_guarda_como_none_no_como_texto(self):
        """El bug original: TEXT permitía guardar "N/A" o cualquier basura
        como si fuera un monto. Ahora se descarta a NULL en vez de mentir."""
        assert _to_money("N/A") is None
        assert _to_money("mil pesos") is None

    def test_separador_de_miles_no_es_numero_valido(self):
        # "1,160.00" no es un Decimal válido tal cual -- se rechaza en vez
        # de parsearse silenciosamente distinto (1160 vs 1.16).
        assert _to_money("1,160.00") is None


# ---------------------------------------------------------------------------
# insert_invoice / get_invoice: la basura ya no se cuela, pero la factura
# sigue guardándose (el pipeline de revisión humana depende de eso).
# ---------------------------------------------------------------------------

def _base_datos(**overrides):
    datos = {"folio_fiscal": "u-money-1", "archivo": "a.xml",
             "fecha": "2026-07-01", "tipo": "I", "emisor_rfc": "X1",
             "emisor_nombre": "E", "receptor_rfc": "X2",
             "subtotal": "100.00", "iva": "16.00", "total": "116.00",
             "moneda": "MXN", "descripcion": "x"}
    datos.update(overrides)
    return datos


def _clasif_val():
    clasif = {"categoria": "gasto_operativo", "confianza": 0.9, "razon": "r"}
    val = {"ok": True, "issues": [], "requires_human_review": False}
    return clasif, val


def test_insert_invoice_guarda_montos_validos(tmp_db):
    tid = tmp_db.create_tenant("A")
    clasif, val = _clasif_val()
    inv_id, _ = tmp_db.insert_invoice(tid, _base_datos(), clasif, val)
    inv = tmp_db.get_invoice(inv_id)
    assert inv["subtotal"] == "100.00"
    assert inv["iva"] == "16.00"
    assert inv["total"] == "116.00"


def test_insert_invoice_none_no_se_guarda_como_cadena_vacia(tmp_db):
    """Antes de este fix: `str(None)` con guard -> "" (cadena vacía) para un
    monto ausente. Con PostgreSQL NUMERIC eso hubiera roto el INSERT; ahora
    se guarda NULL en ambos backends."""
    tid = tmp_db.create_tenant("A")
    clasif, val = _clasif_val()
    datos = _base_datos(subtotal=None, iva=None, total=None)
    inv_id, _ = tmp_db.insert_invoice(tid, datos, clasif, val)
    inv = tmp_db.get_invoice(inv_id)
    assert inv["subtotal"] is None
    assert inv["iva"] is None
    assert inv["total"] is None


def test_insert_invoice_factura_invalida_con_monto_basura_no_crashea(tmp_db):
    """Refleja b2b_ai/agent/loop.py: una factura que reprueba `validate_cfdi`
    igual se inserta (para la cola de revisión humana). Si el parser hubiera
    fallado en extraer un monto y `datos["subtotal"]` trae basura, insertar
    NO debe tronar -- se guarda NULL, no la basura ni un crash."""
    tid = tmp_db.create_tenant("A")
    clasif = {"categoria": "desconocido", "confianza": 0.0, "razon": ""}
    val = {"ok": False, "requires_human_review": True,
           "issues": [{"mensaje": "monto ilegible"}]}
    datos = _base_datos(subtotal="N/A", iva="16.00", total="1,160.00")
    inv_id, inserted = tmp_db.insert_invoice(tid, datos, clasif, val)
    assert inserted is True
    inv = tmp_db.get_invoice(inv_id)
    assert inv["subtotal"] is None       # "N/A" descartado, no guardado tal cual
    assert inv["iva"] == "16.00"         # el campo válido sí se conserva
    assert inv["total"] is None          # "1,160.00" tampoco es válido


def test_insert_invoice_acepta_decimal_nativo(tmp_db):
    """El parser real (b2b_ai/cfdi/parser.py::_dec) entrega Decimal, no str.
    insert_invoice debe aceptarlo directo sin pasar por str()."""
    tid = tmp_db.create_tenant("A")
    clasif, val = _clasif_val()
    datos = _base_datos(subtotal=Decimal("100.00"), iva=Decimal("16.00"),
                        total=Decimal("116.00"))
    inv_id, _ = tmp_db.insert_invoice(tid, datos, clasif, val)
    inv = tmp_db.get_invoice(inv_id)
    assert inv["subtotal"] == "100.00"
    assert inv["total"] == "116.00"


def test_invoice_stats_suma_correctamente_con_decimales(tmp_db):
    """SUM(CAST(... AS NUMERIC)) no debe perder precisión como sí lo hacía
    CAST(... AS REAL) con sumas de centavos (0.1 + 0.2 clásico de binario)."""
    tid = tmp_db.create_tenant("A")
    clasif, val = _clasif_val()
    for i in range(3):
        datos = _base_datos(folio_fiscal=f"u-money-stat-{i}",
                            subtotal="0.10", iva="0.00", total="0.10")
        tmp_db.insert_invoice(tid, datos, clasif, val)
    stats = tmp_db.invoice_stats(tenant_id=tid)
    assert stats["total_facturas"] == 3
    assert stats["monto_total"] == pytest.approx(0.30, abs=1e-9)
