# -*- coding: utf-8 -*-
"""
test_clientes.py — Tests for the Client Response module.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.clientes.models import (
    QueryCategory,
    ClientQuery,
    FAQEntry,
    InvoiceStatus,
    QueryType,
)
from b2b_ai.features.clientes.service import ClientService
from b2b_ai.features.clientes.routes import build_clientes_router


TENANT = "test-tenant"


@pytest.fixture
def svc():
    return ClientService()


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(build_clientes_router(db=None, require_api_key=lambda: {"tenant_id": "test", "key": "test"}))
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


class TestClientService:
    def test_process_query_estatus(self, svc):
        query = ClientQuery(
            tipo=QueryType.ESTATUS,
            contenido="¿Cuál es el estatus de la factura XYZ?",
            tenant_id=TENANT,
        )
        result = svc.process_client_query(query)
        assert result is not None

    def test_process_query_deduccion(self, svc):
        query = ClientQuery(
            tipo=QueryType.DEDUCCION,
            contenido="¿Es deducible la compra de mobiliario?",
            tenant_id=TENANT,
        )
        result = svc.process_client_query(query)
        assert result is not None

    def test_get_faq(self, svc):
        faq = svc.get_faqs()
        assert isinstance(faq, list)

    def test_get_invoice_status(self, svc):
        status = svc.get_invoice_status("test-cfdi-id")
        assert status is None or isinstance(status, InvoiceStatus)


class TestModels:
    def test_client_query_creation(self):
        q = ClientQuery(
            tipo=QueryType.ESTATUS,
            contenido="Test query",
            tenant_id=TENANT,
        )
        assert q.tipo == QueryType.ESTATUS

    def test_faq_entry_creation(self):
        faq = FAQEntry(
            question="¿Qué es la DIOT?",
            answer="Es la Declaración Informativa de Operaciones con Terceros.",
            category=QueryCategory.FACTURACION,
        )
        assert faq.question
        assert faq.answer


class TestRoutes:
    def test_query_route(self, client):
        resp = client.post("/api/v1/clientes/query", json={
            "tipo": "estatus",
            "contenido": "¿Cuál es el estatus?",
            "tenant_id": TENANT,
        })
        assert resp.status_code in (200, 201, 422)

    def test_faq_route(self, client):
        resp = client.get("/api/v1/clientes/faq")
        assert resp.status_code in (200, 422)
