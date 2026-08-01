# -*- coding: utf-8 -*-
"""Tests del ERP (interfaz abstracta, CONTPAQi mock, CSV fallback)."""
import pytest

from b2b_ai.erp.base import ERPInterface
from b2b_ai.erp.contpaqi import MockCONTPAQi
from b2b_ai.erp.csv_erp import CSVErp


def _invoice():
    return {"folio_fiscal": "abc-123", "archivo": "f.xml",
            "emisor_rfc": "CON950820K12", "total": "5800.00",
            "categoria": "gasto_operativo"}


def test_interfaz_es_abstracta():
    with pytest.raises(TypeError):
        ERPInterface()


def test_mock_contpaqi_registra():
    erp = MockCONTPAQi()
    r = erp.register_invoice(_invoice())
    assert r["ok"] is True
    assert r["poliza"].startswith("POL-")
    assert erp.get_invoice("abc-123")["poliza"] == r["poliza"]


def test_mock_contpaqi_health():
    assert MockCONTPAQi().health()["ok"] is True


def test_mock_contpaqi_sin_folio():
    r = MockCONTPAQi().register_invoice({})
    assert r["ok"] is False


def test_csv_erp_registra(tmp_path):
    path = str(tmp_path / "erp.csv")
    erp = CSVErp(path)
    r = erp.register_invoice(_invoice())
    assert r["ok"] is True
    assert r["poliza"].startswith("CSV-")
    assert erp.get_invoice("abc-123")["poliza"] == r["poliza"]
    # El archivo existe y tiene la fila
    import csv
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["folio_fiscal"] == "abc-123"


def test_csv_erp_accumula(tmp_path):
    path = str(tmp_path / "erp.csv")
    erp = CSVErp(path)
    erp.register_invoice(_invoice())
    erp2 = CSVErp(path)  # reabre y lee lo existente
    r = erp2.register_invoice({**_invoice(), "folio_fiscal": "xyz-999"})
    assert r["ok"] is True
    assert erp2.get_invoice("abc-123") is not None
    assert erp2.get_invoice("xyz-999") is not None
