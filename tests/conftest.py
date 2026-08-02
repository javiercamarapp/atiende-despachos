# -*- coding: utf-8 -*-
import os
import resource
import sys
import tempfile

import pytest

# macOS: raise file-descriptor limit so 800+ SQLite connections don't exhaust
# the default ulimit (256).  Safe to call on Linux too (no-op if already ≥ 10240).
try:
    resource.setrlimit(resource.RLIMIT_NOFILE, (10240, 10240))
except (ValueError, OSError):
    pass  # already higher or unprivileged container — ignore

# Ensure a JWT secret is available for tests that exercise auth middleware.
# The production code reads B2B_JWT_SECRET from the environment; in tests we
# supply a deterministic value so nothing falls through to the (now removed)
# hardcoded dev secret.
os.environ.setdefault("B2B_JWT_SECRET", "test-jwt-secret-safe-for-ci-only")
os.environ.setdefault("B2B_ENV", "test")

# Asegurar que el paquete b2b_ai sea importable (root = directorio con el paquete)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FIXTURES = os.path.join(ROOT, "fixtures", "cfdis")


def fixture_path(name):
    return os.path.join(FIXTURES, name)


@pytest.fixture(autouse=True)
def _ingesta_local_habilitada(monkeypatch, tmp_path_factory):
    """Habilita la ingesta por ruta local para toda la suite.

    `xml_path` / `folder` dejan que el cliente elija una ruta DEL SERVIDOR, así
    que ahora son opt-in y están confinadas a `B2B_LOCAL_XML_DIRS` (ver
    `_resolve_local_path` en api/app.py). Sin esta variable la API responde 400.

    Las pruebas que usan `xml_path` representan un despliegue que SÍ habilitó la
    ingesta local, así que se apuntan los dos directorios de los que leen: las
    fixtures del repo y la raíz de los temporales de pytest. Que el confinamiento
    funcione lo cubre `tests/test_ingesta_local.py`, que limpia esta variable a
    propósito.
    """
    roots = os.pathsep.join([FIXTURES, ROOT,
                             str(tmp_path_factory.getbasetemp()),
                             tempfile.gettempdir()])
    monkeypatch.setenv("B2B_LOCAL_XML_DIRS", roots)
    # `B2B_ENV` sin definir cuenta como PRODUCCIÓN (ver auth/middleware.py), y
    # en producción la ausencia de B2B_JWT_SECRET aborta el arranque. La suite
    # se declara entorno de test para tomar el secreto efímero por proceso.
    monkeypatch.setenv("B2B_ENV", "test")


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

# ---------------------------------------------------------------------------
# Enterprise hardening fixtures (from conftest_enterprise.py)
# ---------------------------------------------------------------------------
import secrets

@pytest.fixture
def db_session(tmp_path):
    """Fresh SQLite database per test, fully migrated."""
    from b2b_ai.db.db import Database
    db_path = str(tmp_path / "test_enterprise.db")
    db = Database(db_path)
    yield db
    try:
        db.close()
    except Exception:
        pass

@pytest.fixture
def tenant_context():
    """Simulated tenant context."""
    return {
        "tenant_id": 1,
        "name": "Test Despacho",
        "rfc": "TDE220101AB1",
    }

@pytest.fixture
def api_key():
    return "test-api-key-enterprise-12345678"

@pytest.fixture
def auth_headers(api_key):
    return {"X-API-Key": api_key}

@pytest.fixture
def jwt_token():
    from b2b_ai.auth.middleware import encode_token
    return encode_token(
        {"type": "access", "sub": "1", "tenant_id": 1,
         "role": "admin", "email": "test@test.com",
         "jti": secrets.token_urlsafe(16)},
        ttl_seconds=3600,
    )

@pytest.fixture
def jwt_headers(jwt_token):
    return {"Authorization": f"Bearer {jwt_token}"}
