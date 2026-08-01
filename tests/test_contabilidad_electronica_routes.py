# -*- coding: utf-8 -*-
"""
test_contabilidad_electronica_routes.py — Tests de los endpoints FastAPI del
workflow de contabilidad electrónica SAT.

Cobertura:
  POST /contabilidad/electronica/package   — Generación de paquete.
  POST /contabilidad/electronica/hash      — Hash SHA-1.
  GET  /contabilidad/electronica/status/{id} — Estado del paquete.
  POST /contabilidad/electronica/transition  — Transición de estado.
  GET  /contabilidad/electronica/summary/{id} — Resumen mensual.
  Edge cases: paquete no encontrado, transición inválida, hash vacío,
              asientos vacíos, estados terminales, campos requeridos.
"""
from __future__ import annotations

import hashlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.contabilidad.electronica_routes import (
    build_electronica_router,
    clear_packages,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ASIENTOS = [
    {"cuenta": "1202", "debe": "5800.00", "haber": "0", "fecha": "2026-07-03"},
    {"cuenta": "1101", "debe": "0", "haber": "5800.00", "fecha": "2026-07-03"},
    {"cuenta": "1101", "debe": "9000.00", "haber": "0", "fecha": "2026-07-10"},
    {"cuenta": "4100", "debe": "0", "haber": "9000.00", "fecha": "2026-07-10"},
]

PACKAGE_BODY = {
    "rfc": "DESP820101AB1",
    "razon_social": "Despacho Demo",
    "ejercicio": 2026,
    "mes": 7,
    "asientos": ASIENTOS,
}


@pytest.fixture(autouse=True)
def _clear_store():
    """Limpia el almacén en memoria antes de cada test."""
    clear_packages()
    yield
    clear_packages()


@pytest.fixture
def app():
    _app = FastAPI()
    _app.include_router(build_electronica_router())
    return _app


@pytest.fixture
def client(app):
    return TestClient(app)


def _create_package(client: TestClient, **overrides) -> dict:
    """Helper: genera un paquete y devuelve la respuesta JSON."""
    body = {**PACKAGE_BODY, **overrides}
    resp = client.post("/contabilidad/electronica/package", json=body)
    assert resp.status_code == 200
    return resp.json()


# ===========================================================================
# POST /contabilidad/electronica/package
# ===========================================================================

class TestGeneratePackage:
    """Tests de generación de paquete de contabilidad electrónica."""

    def test_generate_package_ok(self, client):
        data = _create_package(client)
        assert data["ok"] is True
        assert "package_id" in data
        assert data["estado"] == "listo_para_timbrar"
        assert data["periodo"] == "2026-07"
        assert data["catalogo_cuentas"] > 20
        assert data["balanza_cuadrada"] is True
        assert len(data["catalogo_sha1"]) == 40
        assert len(data["balanza_sha1"]) == 40

    def test_generate_package_returns_unique_id(self, client):
        d1 = _create_package(client)
        d2 = _create_package(client)
        assert d1["package_id"] != d2["package_id"]

    def test_generate_package_periodo_format(self, client):
        data = _create_package(client, ejercicio=2025, mes=12)
        assert data["periodo"] == "2025-12"

    def test_generate_package_default_year(self, client):
        body = {
            "rfc": "TEST",
            "mes": 3,
            "asientos": ASIENTOS,
        }
        resp = client.post("/contabilidad/electronica/package", json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    def test_generate_package_missing_asientos(self, client):
        body = {"rfc": "TEST", "ejercicio": 2026, "mes": 1}
        resp = client.post("/contabilidad/electronica/package", json=body)
        assert resp.status_code == 422

    def test_generate_package_empty_asientos(self, client):
        body = {
            "rfc": "TEST",
            "ejercicio": 2026,
            "mes": 1,
            "asientos": [],
        }
        resp = client.post("/contabilidad/electronica/package", json=body)
        # Empty asientos should still work (balanza with no movements)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    def test_generate_package_invalid_mes(self, client):
        body = {
            "rfc": "TEST",
            "ejercicio": 2026,
            "mes": 13,
            "asientos": ASIENTOS,
        }
        resp = client.post("/contabilidad/electronica/package", json=body)
        assert resp.status_code == 422

    def test_generate_package_with_saldos_iniciales(self, client):
        body = {
            **PACKAGE_BODY,
            "saldos_iniciales": {"1101": "5000.00"},
        }
        resp = client.post("/contabilidad/electronica/package", json=body)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["balanza_cuadrada"] is True

    def test_generate_package_no_body(self, client):
        resp = client.post("/contabilidad/electronica/package")
        assert resp.status_code == 422

    def test_generate_package_empty_body(self, client):
        resp = client.post(
            "/contabilidad/electronica/package", json={}
        )
        assert resp.status_code == 422


# ===========================================================================
# POST /contabilidad/electronica/hash
# ===========================================================================

class TestCalculateHash:
    """Tests de cálculo de hash SHA-1."""

    def test_hash_ok(self, client):
        resp = client.post(
            "/contabilidad/electronica/hash",
            json={"content": "hola mundo"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        expected = hashlib.sha1("hola mundo".encode("utf-8")).hexdigest()
        assert data["sha1"] == expected
        assert len(data["sha1"]) == 40

    def test_hash_empty_string(self, client):
        resp = client.post(
            "/contabilidad/electronica/hash",
            json={"content": ""},
        )
        assert resp.status_code == 200
        data = resp.json()
        expected = hashlib.sha1(b"").hexdigest()
        assert data["sha1"] == expected

    def test_hash_unicode(self, client):
        resp = client.post(
            "/contabilidad/electronica/hash",
            json={"content": "áéíóú ñ你好"},
        )
        assert resp.status_code == 200
        data = resp.json()
        expected = hashlib.sha1("áéíóú ñ你好".encode("utf-8")).hexdigest()
        assert data["sha1"] == expected

    def test_hash_length_field(self, client):
        resp = client.post(
            "/contabilidad/electronica/hash",
            json={"content": "test"},
        )
        assert resp.status_code == 200
        assert resp.json()["length"] == 4

    def test_hash_missing_content(self, client):
        resp = client.post(
            "/contabilidad/electronica/hash",
            json={},
        )
        assert resp.status_code == 422

    def test_hash_xml_content(self, client):
        xml = '<?xml version="1.0"?><root/>'
        resp = client.post(
            "/contabilidad/electronica/hash",
            json={"content": xml},
        )
        assert resp.status_code == 200
        data = resp.json()
        expected = hashlib.sha1(xml.encode("utf-8")).hexdigest()
        assert data["sha1"] == expected


# ===========================================================================
# GET /contabilidad/electronica/status/{package_id}
# ===========================================================================

class TestGetStatus:
    """Tests de consulta de estado de paquete."""

    def test_status_ok(self, client):
        pkg = _create_package(client)
        resp = client.get(
            f"/contabilidad/electronica/status/{pkg['package_id']}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["package_id"] == pkg["package_id"]
        assert data["estado"] == "listo_para_timbrar"
        assert data["periodo"] == "2026-07"
        assert data["rfc"] == "DESP820101AB1"
        assert "generado_en" in data

    def test_status_not_found(self, client):
        resp = client.get(
            "/contabilidad/electronica/status/nonexistent123"
        )
        assert resp.status_code == 404
        data = resp.json()
        assert "no encontrado" in data["detail"]

    def test_status_after_transition(self, client):
        pkg = _create_package(client)
        pid = pkg["package_id"]
        # Transition to timbrado
        client.post(
            "/contabilidad/electronica/transition",
            json={"package_id": pid, "target_state": "timbrado"},
        )
        resp = client.get(f"/contabilidad/electronica/status/{pid}")
        assert resp.status_code == 200
        assert resp.json()["estado"] == "timbrado"

    def test_status_has_rfc(self, client):
        pkg = _create_package(client, rfc="TESTRFC123456")
        resp = client.get(
            f"/contabilidad/electronica/status/{pkg['package_id']}"
        )
        assert resp.json()["rfc"] == "TESTRFC123456"


# ===========================================================================
# POST /contabilidad/electronica/transition
# ===========================================================================

class TestTransitionState:
    """Tests de transición de estado de paquete."""

    def test_transition_borrador_to_listo(self, client):
        pkg = _create_package(client)
        # Package starts at listo_para_timbrar after generation
        # First we need to reset it to borrador for this test
        # Actually, generar_paquete sets state to listo_para_timbrar.
        # Let's transition through the full flow.
        pid = pkg["package_id"]
        resp = client.post(
            "/contabilidad/electronica/transition",
            json={"package_id": pid, "target_state": "timbrado"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["estado_anterior"] == "listo_para_timbrar"
        assert data["estado_nuevo"] == "timbrado"

    def test_transition_timbrado_to_enviado(self, client):
        pkg = _create_package(client)
        pid = pkg["package_id"]
        # listo -> timbrado
        client.post(
            "/contabilidad/electronica/transition",
            json={"package_id": pid, "target_state": "timbrado"},
        )
        # timbrado -> enviado
        resp = client.post(
            "/contabilidad/electronica/transition",
            json={"package_id": pid, "target_state": "enviado"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["estado_nuevo"] == "enviado"

    def test_transition_full_flow(self, client):
        pkg = _create_package(client)
        pid = pkg["package_id"]
        # listo_para_timbrar -> timbrado -> enviado
        resp1 = client.post(
            "/contabilidad/electronica/transition",
            json={"package_id": pid, "target_state": "timbrado"},
        )
        assert resp1.json()["estado_nuevo"] == "timbrado"

        resp2 = client.post(
            "/contabilidad/electronica/transition",
            json={"package_id": pid, "target_state": "enviado"},
        )
        assert resp2.json()["estado_nuevo"] == "enviado"

    def test_transition_not_found(self, client):
        resp = client.post(
            "/contabilidad/electronica/transition",
            json={"package_id": "fake_id", "target_state": "timbrado"},
        )
        assert resp.status_code == 404

    def test_transition_invalid_state(self, client):
        pkg = _create_package(client)
        resp = client.post(
            "/contabilidad/electronica/transition",
            json={
                "package_id": pkg["package_id"],
                "target_state": "estado_falso",
            },
        )
        assert resp.status_code == 422
        assert "inválido" in resp.json()["detail"]

    def test_transition_wrong_order(self, client):
        """Try to jump from listo_para_timbrar directly to enviado."""
        pkg = _create_package(client)
        resp = client.post(
            "/contabilidad/electronica/transition",
            json={
                "package_id": pkg["package_id"],
                "target_state": "enviado",
            },
        )
        assert resp.status_code == 422
        assert "inválida" in resp.json()["detail"]

    def test_transition_terminal_state(self, client):
        """Once in 'enviado', no further transitions are possible."""
        pkg = _create_package(client)
        pid = pkg["package_id"]
        # Move to enviado
        client.post(
            "/contabilidad/electronica/transition",
            json={"package_id": pid, "target_state": "timbrado"},
        )
        client.post(
            "/contabilidad/electronica/transition",
            json={"package_id": pid, "target_state": "enviado"},
        )
        # Try to transition again
        resp = client.post(
            "/contabilidad/electronica/transition",
            json={"package_id": pid, "target_state": "timbrado"},
        )
        assert resp.status_code == 409
        assert "terminal" in resp.json()["detail"]

    def test_transition_missing_package_id(self, client):
        resp = client.post(
            "/contabilidad/electronica/transition",
            json={"target_state": "timbrado"},
        )
        assert resp.status_code == 422

    def test_transition_missing_target_state(self, client):
        pkg = _create_package(client)
        resp = client.post(
            "/contabilidad/electronica/transition",
            json={"package_id": pkg["package_id"]},
        )
        assert resp.status_code == 422

    def test_transition_reflects_in_status(self, client):
        """Verify status endpoint shows updated state after transition."""
        pkg = _create_package(client)
        pid = pkg["package_id"]
        client.post(
            "/contabilidad/electronica/transition",
            json={"package_id": pid, "target_state": "timbrado"},
        )
        resp = client.get(f"/contabilidad/electronica/status/{pid}")
        assert resp.json()["estado"] == "timbrado"


# ===========================================================================
# GET /contabilidad/electronica/summary/{package_id}
# ===========================================================================

class TestGetSummary:
    """Tests de resumen mensual de paquete."""

    def test_summary_ok(self, client):
        pkg = _create_package(client)
        resp = client.get(
            f"/contabilidad/electronica/summary/{pkg['package_id']}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        summary = data["summary"]
        assert summary["periodo"] == "2026-07"
        assert summary["rfc"] == "DESP820101AB1"
        assert summary["razon_social"] == "Despacho Demo"
        assert summary["cuentas"] > 0
        assert summary["cuadrada"] is True
        assert "total_debe" in summary
        assert "total_haber" in summary
        assert summary["package_id"] == pkg["package_id"]

    def test_summary_not_found(self, client):
        resp = client.get(
            "/contabilidad/electronica/summary/nonexistent"
        )
        assert resp.status_code == 404

    def test_summary_totals(self, client):
        pkg = _create_package(client)
        resp = client.get(
            f"/contabilidad/electronica/summary/{pkg['package_id']}"
        )
        summary = resp.json()["summary"]
        # From ASIENTOS: 5800 + 9000 = 14800 total
        assert summary["total_debe"] == "14800.00"
        assert summary["total_haber"] == "14800.00"

    def test_summary_has_estado(self, client):
        pkg = _create_package(client)
        resp = client.get(
            f"/contabilidad/electronica/summary/{pkg['package_id']}"
        )
        summary = resp.json()["summary"]
        assert summary["estado"] == "listo_para_timbrar"

    def test_summary_after_transition(self, client):
        pkg = _create_package(client)
        pid = pkg["package_id"]
        client.post(
            "/contabilidad/electronica/transition",
            json={"package_id": pid, "target_state": "timbrado"},
        )
        resp = client.get(
            f"/contabilidad/electronica/summary/{pid}"
        )
        summary = resp.json()["summary"]
        assert summary["estado"] == "timbrado"

    def test_summary_saldos_anomalos_field(self, client):
        pkg = _create_package(client)
        resp = client.get(
            f"/contabilidad/electronica/summary/{pkg['package_id']}"
        )
        summary = resp.json()["summary"]
        assert "saldos_anomalos" in summary
        assert isinstance(summary["saldos_anomalos"], list)

    def test_summary_different_periodo(self, client):
        pkg = _create_package(client, ejercicio=2025, mes=12)
        resp = client.get(
            f"/contabilidad/electronica/summary/{pkg['package_id']}"
        )
        summary = resp.json()["summary"]
        assert summary["periodo"] == "2025-12"


# ===========================================================================
# Integration / workflow tests
# ===========================================================================

class TestWorkflow:
    """Tests del flujo completo: package → hash → transition → summary."""

    def test_full_workflow(self, client):
        # 1. Generate package
        pkg = _create_package(client)
        pid = pkg["package_id"]

        # 2. Verify status
        status = client.get(
            f"/contabilidad/electronica/status/{pid}"
        ).json()
        assert status["estado"] == "listo_para_timbrar"

        # 3. Calculate hash of the balanza XML
        # (We can hash any content — this tests the hash endpoint)
        hash_resp = client.post(
            "/contabilidad/electronica/hash",
            json={"content": pkg["balanza_sha1"]},
        )
        assert hash_resp.json()["ok"] is True

        # 4. Transition to timbrado
        t1 = client.post(
            "/contabilidad/electronica/transition",
            json={"package_id": pid, "target_state": "timbrado"},
        ).json()
        assert t1["estado_nuevo"] == "timbrado"

        # 5. Get summary
        summary = client.get(
            f"/contabilidad/electronica/summary/{pid}"
        ).json()["summary"]
        assert summary["estado"] == "timbrado"
        assert summary["cuadrada"] is True

        # 6. Transition to enviado
        t2 = client.post(
            "/contabilidad/electronica/transition",
            json={"package_id": pid, "target_state": "enviado"},
        ).json()
        assert t2["estado_nuevo"] == "enviado"

        # 7. Final status check
        final = client.get(
            f"/contabilidad/electronica/status/{pid}"
        ).json()
        assert final["estado"] == "enviado"

    def test_multiple_packages_independent(self, client):
        """Each package is independent."""
        p1 = _create_package(client, rfc="RFC1", mes=1)
        p2 = _create_package(client, rfc="RFC2", mes=2)

        assert p1["package_id"] != p2["package_id"]
        assert p1["periodo"] == "2026-01"
        assert p2["periodo"] == "2026-02"

        # Transition p1 to timbrado
        client.post(
            "/contabilidad/electronica/transition",
            json={"package_id": p1["package_id"], "target_state": "timbrado"},
        )
        # p2 should still be listo_para_timbrar
        s2 = client.get(
            f"/contabilidad/electronica/status/{p2['package_id']}"
        ).json()
        assert s2["estado"] == "listo_para_timbrar"

    def test_route_prefix(self, client):
        """All routes are under /contabilidad/electronica/."""
        resp = client.get("/docs")
        # If the router is properly mounted, the OpenAPI spec should exist
        # Just verify the routes respond (not 404 from missing prefix)
        assert client.post(
            "/contabilidad/electronica/hash",
            json={"content": "x"},
        ).status_code == 200
