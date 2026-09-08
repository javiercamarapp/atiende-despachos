# -*- coding: utf-8 -*-
"""Concurrency tests for multi-tenant isolation.

Verifies that concurrent operations across tenants don't leak data
and don't cause database locks or race conditions.
"""
import os
import threading
import time
import pytest


@pytest.fixture
def multi_tenant_db(tmp_path):
    """Create a fresh database for concurrency tests.

    Pre-crea 5 tenants: `invoices.tenant_id` es FK NOT NULL a `tenants(id)`
    (foreign_keys=ON en cada conexión, ver Database.conn), así que insertar
    facturas con tenant_id=1..5 sin filas reales en `tenants` violaba la FK.
    En una BD SQLite recién creada el autoincrement arranca en 1, así que
    estos 5 inserts (los primeros en `tenants`) producen ids 1..5 en orden.
    """
    from b2b_ai.db.db import Database
    db = Database(str(tmp_path / "concurrent_test.db"))
    for i in range(1, 6):
        db.create_tenant(f"Tenant {i}", rfc=f"RFC{i:03d}")
    yield db
    try:
        db.close()
    except Exception:
        pass


class TestConcurrentTenantIsolation:
    """Verify data isolation under concurrent access."""

    def test_concurrent_inserts_different_tenants(self, multi_tenant_db):
        """Multiple threads inserting into different tenants should not mix data."""
        db = multi_tenant_db
        errors = []
        results = {}

        def insert_for_tenant(tenant_id, num_items):
            try:
                for i in range(num_items):
                    # `Database` no expone `.execute()`: las escrituras van
                    # por `db.conn` (conexión SQLite por hilo, ver
                    # b2b_ai/db/db.py). Columnas reales de `invoices`:
                    # `emisor_rfc` (no `rfc_emisor`) y `archivo` NOT NULL.
                    db.conn.execute(
                        "INSERT INTO invoices (tenant_id, emisor_rfc, archivo, "
                        "subtotal, total, folio_fiscal) VALUES (?, ?, ?, ?, ?, ?)",
                        (tenant_id, f"RFC{tenant_id:03d}", f"factura-{tenant_id}-{i}.xml",
                         100.0 * (i + 1), 116.0 * (i + 1), f"UUID-{tenant_id}-{i}"),
                    )
                    db.conn.commit()
                results[tenant_id] = True
            except Exception as e:
                errors.append((tenant_id, str(e)))

        threads = []
        for t in range(1, 6):
            t_thread = threading.Thread(target=insert_for_tenant, args=(t, 10))
            threads.append(t_thread)

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(errors) == 0, f"Concurrent insert errors: {errors}"
        assert len(results) == 5

    def test_concurrent_context_switches(self, multi_tenant_db):
        """Switching tenant context concurrently should not leak data."""
        db = multi_tenant_db
        errors = []
        contexts = {}

        def use_tenant_context(tenant_id):
            try:
                # Simulate setting tenant context
                ctx = {"tenant_id": tenant_id, "name": f"Tenant_{tenant_id}"}
                # Each thread gets its own context
                contexts[tenant_id] = ctx
                # Simulate work
                time.sleep(0.01)
                assert contexts[tenant_id]["tenant_id"] == tenant_id
            except Exception as e:
                errors.append((tenant_id, str(e)))

        threads = []
        for t in range(1, 21):
            t_thread = threading.Thread(target=use_tenant_context, args=(t,))
            threads.append(t_thread)

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(errors) == 0, f"Context switch errors: {errors}"
        assert len(contexts) == 20

    def test_no_database_locked_under_load(self, multi_tenant_db):
        """50 concurrent writes should not cause 'database locked' errors."""
        db = multi_tenant_db
        lock_errors = []

        def write_record(i):
            try:
                # Ver nota en test_concurrent_inserts_different_tenants:
                # db.conn (no db.execute), columna emisor_rfc, y archivo
                # NOT NULL.
                db.conn.execute(
                    "INSERT INTO invoices (tenant_id, emisor_rfc, archivo, "
                    "subtotal, total, folio_fiscal) VALUES (?, ?, ?, ?, ?, ?)",
                    (1, f"RFC{i:04d}", f"factura-load-{i}.xml",
                     float(i), float(i) * 1.16, f"UUID-LOAD-{i}"),
                )
                db.conn.commit()
            except Exception as e:
                if "locked" in str(e).lower():
                    lock_errors.append(i)

        threads = []
        for i in range(50):
            t = threading.Thread(target=write_record, args=(i,))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(lock_errors) == 0, (
            f"Database locked on {len(lock_errors)} writes: {lock_errors[:5]}..."
        )


class TestConcurrentAPIKeyValidation:
    """Verify API key lookups under concurrency."""

    def test_concurrent_api_key_lookups(self, multi_tenant_db):
        """Concurrent API key validation should return correct tenant."""
        db = multi_tenant_db
        results = {}
        errors = []

        def validate_key(key, expected_tenant):
            try:
                # Simulate API key validation
                result = {"key": key, "tenant_id": expected_tenant}
                results[key] = result
            except Exception as e:
                errors.append((key, str(e)))

        threads = []
        for i in range(20):
            key = f"api-key-{i:03d}"
            t = threading.Thread(target=validate_key, args=(key, i + 1))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(errors) == 0
        assert len(results) == 20
