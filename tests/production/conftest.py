# -*- coding: utf-8 -*-
"""
conftest — Fixtures compartidas de la suite de producción.

Provee:
  - client: TestClient sobre una app con DB limpia, límite de rate bajo
    (para probar 429), y keys multi-tenant creadas.
  - fixtures de infraestructura real (PostgreSQL / Redis vía docker) que
    se saltan automáticamente si docker o los contenedores no están.
"""
import os
import socket
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FIXTURES = os.path.join(ROOT, "fixtures", "cfdis")

# Puertos publicados por los contenedores de infra de pruebas (ver README).
PG_PORT = int(os.environ.get("B2B_TEST_PG_PORT", "54329"))
REDIS_PORT = int(os.environ.get("B2B_TEST_REDIS_PORT", "63799"))
PG_DSN = os.environ.get(
    "B2B_TEST_PG_DSN",
    "host=127.0.0.1 port=%d user=b2b password=b2bpass dbname=b2b_ai" % PG_PORT,
)
REDIS_URL = os.environ.get("B2B_TEST_REDIS_URL", f"redis://127.0.0.1:{REDIS_PORT}/0")


def _port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.5):
            return True
    except OSError:
        return False


def _docker_ok():
    try:
        import subprocess
        r = subprocess.run(["docker", "info"], capture_output=True, timeout=8)
        return r.returncode == 0
    except Exception:
        return False


@pytest.fixture
def fixture_dir():
    return FIXTURES


@pytest.fixture
def sample_papeleria():
    return os.path.join(FIXTURES, "01_gasto_operativo_papeleria.xml")


@pytest.fixture
def sample_consultoria():
    return os.path.join(FIXTURES, "02_inversion_consultoria.xml")


@pytest.fixture
def sample_nomina():
    return os.path.join(FIXTURES, "04_nomina_pago.xml")


@pytest.fixture
def sample_pago():
    return os.path.join(FIXTURES, "07_pago_parcialidad.xml")


@pytest.fixture
def rate_limited_client(tmp_path):
    """App con límite de rate bajo (10/min) y 2 tenants con API keys.

    Devuelve dict con client, db, y keys por tenant.
    """
    from b2b_ai.db.db import Database
    from b2b_ai.api.app import create_app

    os.environ["B2B_RATE_LIMIT_PER_MIN"] = "10"
    os.environ["B2B_RATE_LIMIT"] = "on"
    db = Database(str(tmp_path / "prod_rate.db"))
    ta = db.create_tenant("Despacho A", rfc="XAXX010101000")
    tb = db.create_tenant("Despacho B", rfc="XAXX010101001")
    db.create_api_key(ta, "key-a", "prod-key-tenant-a-0001")
    db.create_api_key(tb, "key-b", "prod-key-tenant-b-0002")
    from fastapi.testclient import TestClient
    client = TestClient(create_app(db))
    return {"client": client, "db": db, "tenant_a": ta, "tenant_b": tb,
            "key_a": "prod-key-tenant-a-0001", "key_b": "prod-key-tenant-b-0002"}


@pytest.fixture
def clean_client(tmp_path):
    """App con DB limpia y límite de rate alto (no interfiere)."""
    from b2b_ai.db.db import Database
    from b2b_ai.api.app import create_app

    os.environ["B2B_RATE_LIMIT_PER_MIN"] = "10000"
    os.environ["B2B_RATE_LIMIT"] = "on"
    db = Database(str(tmp_path / "prod_clean.db"))
    t = db.create_tenant("Despacho A", rfc="XAXX010101000")
    db.create_api_key(t, "key-a", "prod-clean-key-0001")
    from fastapi.testclient import TestClient
    return {"client": TestClient(create_app(db)), "db": db, "key": "prod-clean-key-0001"}


@pytest.fixture
def real_postgres():
    """Conexión a un PostgreSQL REAL (contenedor). Skip si no disponible."""
    if not _docker_ok() or not _port_open(PG_PORT):
        pytest.skip("PostgreSQL real no disponible (docker off o puerto %d cerrado)" % PG_PORT)
    import psycopg2
    conn = psycopg2.connect(PG_DSN, connect_timeout=4)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def real_redis():
    """Conexión a un Redis REAL (contenedor). Skip si no disponible."""
    if not _docker_ok() or not _port_open(REDIS_PORT):
        pytest.skip("Redis real no disponible (docker off o puerto %d cerrado)" % REDIS_PORT)
    import redis
    r = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=4)
    try:
        r.ping()
        yield r
    finally:
        r.close()
