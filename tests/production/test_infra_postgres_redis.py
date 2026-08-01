# -*- coding: utf-8 -*-
"""
test_infra_postgres_redis.py — Validación de infraestructura REAL.

PostgreSQL y Redis se provisionan en docker-compose.prod.yml como infra de
producción. La capa de datos de la app (b2b_ai/db/db.py) hoy es SQLite y los
adaptadores PG/Redis son roadmap documentado; por eso aquí validamos la
infraestructura real (contenedores) contra la que el adaptador se conectará:
  - PostgreSQL: conectividad, transacciones (commit/rollback), aislamiento
    por esquema/fila (patrón multi-tenant), tipado estricto.
  - Redis: ping, SET/GET, INCR atómico (rate limit), TTL/expiración,
    clave por tenant.

Si docker no está o los puertos no responden, los tests se saltan (skip) y el
reporte lo marca explícitamente.
"""
import pytest


# --------------------------------------------------------------------------- #
# PostgreSQL real
# --------------------------------------------------------------------------- #
def test_pg_conectividad_y_version(real_postgres):
    cur = real_postgres.cursor()
    cur.execute("SELECT current_database(), current_user")
    db, user = cur.fetchone()
    assert db == "b2b_ai"
    assert user == "b2b"
    cur.execute("SHOW server_version")
    assert cur.fetchone()[0].startswith("16")
    cur.close()


def test_pg_transaccion_commit_y_rollback(real_postgres):
    """Una escritura commitea y persiste; una rollbackeada no deja rastro."""
    cur = real_postgres.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS _prod_tx(tenant_id int, monto numeric)")
    cur.execute("DELETE FROM _prod_tx")
    real_postgres.commit()

    cur.execute("INSERT INTO _prod_tx VALUES (%s,%s)", (1, 100.50))
    real_postgres.commit()
    cur.execute("SELECT COUNT(*) FROM _prod_tx")
    assert cur.fetchone()[0] == 1

    cur.execute("INSERT INTO _prod_tx VALUES (%s,%s)", (2, 999))
    real_postgres.rollback()
    cur.execute("SELECT COUNT(*) FROM _prod_tx")
    assert cur.fetchone()[0] == 1  # solo sobrevive el commit
    cur.close()


def test_pg_multi_tenant_aislamiento_por_fila(real_postgres):
    """Dos tenants conviven en la misma tabla; las lecturas se filtran."""
    cur = real_postgres.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS _prod_tenant_data(tenant_id int, factura_id text, total numeric)")
    cur.execute("DELETE FROM _prod_tenant_data")
    cur.executemany(
        "INSERT INTO _prod_tenant_data VALUES (%s,%s,%s)",
        [(1, "F-A-1", 100), (1, "F-A-2", 200), (2, "F-B-1", 50)])
    real_postgres.commit()

    cur.execute("SELECT factura_id, total FROM _prod_tenant_data WHERE tenant_id=%s ORDER BY total", (1,))
    rows_a = cur.fetchall()
    cur.execute("SELECT COUNT(*) FROM _prod_tenant_data WHERE tenant_id=%s", (2,))
    n_b = cur.fetchone()[0]
    assert len(rows_a) == 2
    assert n_b == 1
    # ningún id de B se filtra en las lecturas de A
    assert all("B" not in r[0] for r in rows_a)
    cur.close()


def test_pg_tipado_estricto_rechaza_invalido(real_postgres):
    """numeric no acepta texto: evidencia de que no hay coerción permisiva."""
    cur = real_postgres.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS _prod_typed(total numeric)")
    cur.execute("DELETE FROM _prod_typed")
    with pytest.raises(Exception):
        cur.execute("INSERT INTO _prod_typed VALUES (%s)", ("not-a-number",))
    real_postgres.rollback()
    cur.close()


# --------------------------------------------------------------------------- #
# Redis real
# --------------------------------------------------------------------------- #
def test_redis_ping_y_set_get(real_redis):
    assert real_redis.ping() is True
    k = "prod:test:setget"
    real_redis.delete(k)
    assert real_redis.set(k, "ok") is True
    assert real_redis.get(k) == b"ok"


def test_redis_incr_atomico_rate_limit(real_redis):
    """INCR es atómico: 50 incrementos concurrentes => contador exacto de 50.
    Es la primitiva que sostiene un rate limiter compartido multi-replica."""
    import threading
    k = "prod:test:counter"
    real_redis.delete(k)
    n = 50
    errors = []

    def bump():
        try:
            real_redis.incr(k)
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=bump) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert int(real_redis.get(k)) == n


def test_redis_ttl_expira(real_redis):
    k = "prod:test:ttl"
    real_redis.delete(k)
    real_redis.set(k, "1", ex=1)
    assert real_redis.ttl(k) <= 1
    # con expiración de 1s debe desaparecer
    k2 = "prod:test:ttl2"
    real_redis.set(k2, "x", ex=1)
    import time
    time.sleep(1.1)
    assert real_redis.get(k2) is None


def test_redis_claves_por_tenant_aisladas(real_redis):
    """Prefijo por tenant: una clave de tenant A no colisiona con B."""
    k_a, k_b = "tenant:1:rllimit", "tenant:2:rllimit"
    real_redis.delete(k_a, k_b)
    real_redis.set(k_a, "10")
    real_redis.set(k_b, "20")
    assert real_redis.get(k_a) == b"10"
    assert real_redis.get(k_b) == b"20"
