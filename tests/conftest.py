# -*- coding: utf-8 -*-
import os
import sys

import pytest

# Asegurar que el paquete b2b_ai sea importable (root = directorio con el paquete)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FIXTURES = os.path.join(ROOT, "fixtures", "cfdis")


def fixture_path(name):
    return os.path.join(FIXTURES, name)


@pytest.fixture
def fixture_dir():
    return FIXTURES


@pytest.fixture
def sample_papeleria():
    return fixture_path("01_gasto_operativo_papeleria.xml")


@pytest.fixture
def sample_consultoria():
    return fixture_path("02_inversion_consultoria.xml")


@pytest.fixture
def sample_nomina():
    return fixture_path("04_nomina_pago.xml")


@pytest.fixture
def sample_honorarios():
    return fixture_path("06_honorarios_retenciones.xml")


@pytest.fixture
def sample_pago():
    return fixture_path("07_pago_parcialidad.xml")


@pytest.fixture
def tmp_db(tmp_path):
    """Devuelve una Database en un archivo temporal."""
    from b2b_ai.db.db import Database
    return Database(str(tmp_path / "test.db"))


@pytest.fixture
def parsed_consultoria(sample_consultoria):
    from b2b_ai.cfdi.parser import parse_cfdi
    return parse_cfdi(sample_consultoria)
