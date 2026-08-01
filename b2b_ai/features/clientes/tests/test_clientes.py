# -*- coding: utf-8 -*-
"""
test_clientes.py — Tests for the Client Query Response module.

Covers:
  - Models: construction, defaults, validation, serialization
  - Service: query routing, FAQ search, response generation, invoice status
  - Validators: query type, CFDI ID, concepto validation
  - Routes: all endpoints via TestClient
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from b2b_ai.features.clientes.models import (
    ClientQuery,
    FAQEntry,
    InvoiceStatus,
    QueryCategory,
    QueryType,
)
from b2b_ai.features.clientes.service import ClientService
from b2b_ai.features.clientes.validators import (
    validate_cfdi_id,
    validate_client_query,
    validate_concepto,
    validate_query_type,
)


# ===========================================================================
# 1. MODEL TESTS
# ===========================================================================

class TestModels:
    """Test Pydantic model construction and validation."""

    def test_client_query_construction(self):
        q = ClientQuery(
            tipo=QueryType.FACTURA,
            contenido="¿Cuándo tendré mi factura?",
            tenant_id="t1",
        )
        assert q.tipo == QueryType.FACTURA
        assert q.contenido == "¿Cuándo tendré mi factura?"
        assert q.tenant_id == "t1"
        assert q.prioridad == 3  # default

    def test_client_query_strips_whitespace(self):
        q = ClientQuery(
            tipo=QueryType.PREGUNTA,
            contenido="  ¿Qué es el CFDI?  ",
            tenant_id="t1",
        )
        assert q.contenido == "¿Qué es el CFDI?"

    def test_client_query_empty_contenido_fails(self):
        with pytest.raises(Exception):
            ClientQuery(
                tipo=QueryType.PREGUNTA,
                contenido="",
                tenant_id="t1",
            )

    def test_invoice_status_construction(self):
        inv = InvoiceStatus(
            cfdi_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            estado="timbrada",
            total=15000.0,
        )
        assert inv.cfdi_id == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        assert inv.estado == "timbrada"
        assert inv.total == 15000.0

    def test_invoice_status_empty_cfdi_id_fails(self):
        with pytest.raises(Exception):
            InvoiceStatus(cfdi_id="")

    def test_faq_entry_construction(self):
        faq = FAQEntry(
            question="¿Cómo facturo?",
            answer="Use el portal del SAT.",
            category=QueryCategory.FACTURACION,
        )
        assert faq.question == "¿Cómo facturo?"
        assert faq.category == QueryCategory.FACTURACION

    def test_faq_entry_empty_question_fails(self):
        with pytest.raises(Exception):
            FAQEntry(question="", answer="Test answer")

    def test_faq_entry_empty_answer_fails(self):
        with pytest.raises(Exception):
            FAQEntry(question="Test question?", answer="")

    def test_query_type_values(self):
        assert QueryType.FACTURA.value == "factura"
        assert QueryType.DEDUCCION.value == "deduccion"
        assert QueryType.ESTATUS.value == "estatus"
        assert QueryType.PREGUNTA.value == "pregunta"
        assert QueryType.RECLAMO.value == "reclamo"


# ===========================================================================
# 2. SERVICE TESTS
# ===========================================================================

class TestService:
    """Test ClientService logic."""

    def setup_method(self):
        self.service = ClientService(tenant_id="test-tenant")

    def test_process_factura_query(self):
        query = ClientQuery(
            tipo=QueryType.FACTURA,
            contenido="¿Qué documentos necesito para facturar?",
            tenant_id="test-tenant",
        )
        result = self.service.process_client_query(query)
        assert result.respuesta is not None
        assert result.categoria == QueryCategory.FACTURACION
        assert result.id is not None
        assert result.created_at is not None

    def test_process_deduccion_query(self):
        query = ClientQuery(
            tipo=QueryType.DEDUCCION,
            contenido="¿Puedo deducir la renta de mi oficina?",
            tenant_id="test-tenant",
        )
        result = self.service.process_client_query(query)
        assert result.respuesta is not None
        assert "deducción" in result.respuesta.lower() or "deducible" in result.respuesta.lower()

    def test_process_estatus_query_with_unknown_cfdi(self):
        query = ClientQuery(
            tipo=QueryType.ESTATUS,
            contenido="¿Cuál es el estatus de la factura a1b2c3d4-e5f6-7890-abcd-ef1234567890?",
            tenant_id="test-tenant",
        )
        result = self.service.process_client_query(query)
        assert result.respuesta is not None
        assert "no encontrado" in result.respuesta.lower() or "estatus" in result.respuesta.lower()

    def test_process_estatus_query_with_known_invoice(self):
        # Register invoice first
        inv = InvoiceStatus(
            cfdi_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            estado="timbrada",
            observaciones="Factura válida",
        )
        self.service.register_invoice(inv)

        query = ClientQuery(
            tipo=QueryType.ESTATUS,
            contenido="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            tenant_id="test-tenant",
        )
        result = self.service.process_client_query(query)
        assert "timbrada" in result.respuesta.lower()

    def test_process_pregunta_with_faq_match(self):
        query = ClientQuery(
            tipo=QueryType.PREGUNTA,
            contenido="¿Cuánto tiempo tengo para emitir una factura?",
            tenant_id="test-tenant",
        )
        result = self.service.process_client_query(query)
        assert result.respuesta is not None
        # Should match FAQ about time to issue invoice
        assert "mes siguiente" in result.respuesta.lower() or "plazo" in result.respuesta.lower()

    def test_process_reclamo_query(self):
        query = ClientQuery(
            tipo=QueryType.RECLAMO,
            contenido="Mi factura tiene errores en los datos fiscales",
            tenant_id="test-tenant",
        )
        result = self.service.process_client_query(query)
        assert result.respuesta is not None
        assert "48 horas" in result.respuesta or "reclamo" in result.respuesta.lower()

    def test_auto_classification(self):
        # Test auto-classification by content
        test_cases = [
            ("Necesito mi factura XML", QueryCategory.FACTURACION),
            ("¿Cómo funciona la deducción de IVA?", QueryCategory.IMPUESTOS),
            ("¿Puedo pagar con transferencia?", QueryCategory.PAGOS),
            ("Quiero una devolución", QueryCategory.DEVOLUCIONES),
            ("Hola, ¿cómo están?", QueryCategory.GENERAL),
        ]
        for content, expected_cat in test_cases:
            query = ClientQuery(
                tipo=QueryType.PREGUNTA,
                contenido=content,
                tenant_id="test-tenant",
            )
            result = self.service.process_client_query(query)
            assert result.categoria == expected_cat, f"Failed for: {content}"

    def test_get_invoice_status(self):
        inv = InvoiceStatus(
            cfdi_id="test-uuid-1234",
            estado="cancelada",
        )
        self.service.register_invoice(inv)
        result = self.service.get_invoice_status("test-uuid-1234")
        assert result is not None
        assert result.estado == "cancelada"

    def test_get_invoice_status_not_found(self):
        result = self.service.get_invoice_status("nonexistent-uuid")
        assert result is None

    def test_deductibility_info_salary(self):
        info = self.service.get_deductibility_info("Salarios y nómina")
        assert info["deductible"] is True
        assert info["percentage"] == 100.0
        assert len(info["requirements"]) > 0

    def test_deductibility_info_food(self):
        info = self.service.get_deductibility_info("Cena de negocios")
        assert info["deductible"] is True
        assert info["percentage"] == 50.0

    def test_deductibility_info_fine(self):
        info = self.service.get_deductibility_info("Multa por infracción")
        assert info["deductible"] is False
        assert info["percentage"] == 0.0

    def test_deductibility_info_unknown(self):
        info = self.service.get_deductibility_info("Crypto random purchase")
        assert info["deductible"] is None

    def test_get_faqs(self):
        faqs = self.service.get_faqs()
        assert len(faqs) >= 6

    def test_get_faqs_by_category(self):
        faqs = self.service.get_faqs(category=QueryCategory.FACTURACION)
        for faq in faqs:
            assert faq.category == QueryCategory.FACTURACION

    def test_add_faq(self):
        new_faq = FAQEntry(
            question="¿Qué es el RFC?",
            answer="Registro Federal de Contribuyentes.",
            category=QueryCategory.IMPUESTOS,
            keywords=["rfc", "registro"],
        )
        result = self.service.add_faq(new_faq)
        assert result.id is not None

    def test_generate_response_with_data(self):
        query = ClientQuery(
            tipo=QueryType.ESTATUS,
            contenido="test",
            tenant_id="t1",
        )
        data = {"cfdi_id": "abc-123", "estado": "timbrada", "observaciones": "OK"}
        response = self.service.generate_client_response(query, data)
        assert "timbrada" in response
        assert "abc-123" in response


# ===========================================================================
# 3. VALIDATOR TESTS
# ===========================================================================

class TestValidators:
    """Test validation functions."""

    def test_validate_query_type_valid(self):
        is_valid, errors = validate_query_type("factura")
        assert is_valid
        assert len(errors) == 0

    def test_validate_query_type_invalid(self):
        is_valid, errors = validate_query_type("invalid_type")
        assert not is_valid
        assert len(errors) > 0

    def test_validate_query_type_empty(self):
        is_valid, errors = validate_query_type("")
        assert not is_valid

    def test_validate_cfdi_id_valid(self):
        is_valid, errors = validate_cfdi_id("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
        assert is_valid

    def test_validate_cfdi_id_empty(self):
        is_valid, errors = validate_cfdi_id("")
        assert not is_valid

    def test_validate_cfdi_id_short(self):
        is_valid, errors = validate_cfdi_id("abc")
        assert not is_valid

    def test_validate_concepto_known(self):
        is_valid, errors = validate_concepto("Salarios y nómina")
        assert is_valid

    def test_validate_concepto_unknown(self):
        is_valid, errors = validate_concepto("Crypto mining equipment")
        # Unknown concepto still passes but warns
        assert len(errors) > 0  # warning

    def test_validate_concepto_empty(self):
        is_valid, errors = validate_concepto("")
        assert not is_valid

    def test_validate_client_query_valid(self):
        data = {
            "tipo": "factura",
            "contenido": "Necesito mi factura",
            "tenant_id": "t1",
        }
        is_valid, errors = validate_client_query(data)
        assert is_valid

    def test_validate_client_query_missing_fields(self):
        data = {"tipo": ""}
        is_valid, errors = validate_client_query(data)
        assert not is_valid


# ===========================================================================
# 4. ROUTE TESTS (via TestClient)
# ===========================================================================

class TestRoutes:
    """Test API endpoints via TestClient."""

    @pytest.fixture
    def client(self):
        from b2b_ai.features.clientes.routes import build_clientes_router
        from fastapi import FastAPI

        app = FastAPI()
        router = build_clientes_router()
        app.include_router(router)
        return TestClient(app)

    def test_post_query(self, client):
        response = client.post("/api/v1/clientes/query", json={
            "tipo": "factura",
            "contenido": "¿Cuándo tendré mi factura?",
            "tenant_id": "test",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["respuesta"] is not None

    def test_post_query_invalid_type(self, client):
        response = client.post("/api/v1/clientes/query", json={
            "tipo": "invalid",
            "contenido": "Test",
            "tenant_id": "test",
        })
        assert response.status_code == 422

    def test_get_faq(self, client):
        response = client.get("/api/v1/clientes/faq")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["total"] >= 6

    def test_get_faq_by_category(self, client):
        response = client.get("/api/v1/clientes/faq?category=facturacion")
        assert response.status_code == 200
        data = response.json()
        for entry in data["entries"]:
            assert entry["category"] == "facturacion"

    def test_get_status_not_found(self, client):
        response = client.get("/api/v1/clientes/status/a1b2c3d4-e5f6-7890-abcd-ef1234567890")
        assert response.status_code == 404

    def test_get_status_invalid_id(self, client):
        response = client.get("/api/v1/clientes/status/short")
        assert response.status_code == 422

    def test_deductibility(self, client):
        response = client.post("/api/v1/clientes/deductibility", json={
            "concepto": "Renta de oficina",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["deductible"] is True
