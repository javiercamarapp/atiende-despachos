# -*- coding: utf-8 -*-
"""test_pipeline_e2e.py — Test del flujo completo CFDI → bookkeeping → conciliación.

Cablea los bloques que estaban desconectados (QA 220):
  parse_cfdi_4 (emisor['rfc'] anidado) → adapter → bookkeeping (rfc_emisor plano)
  → pólizas → motor de conciliación real (conciliacion.service) en RECONCILING.

Cubre:
  1. adapter.to_bookkeeping_format mapea emisor/receptor/tipo correctamente.
  2. adapt_batch sobre una lista.
  3. EndToEndOrchestrator.upload_cfdis: parse→adapt→entries→reconcile completo.
  4. PipelineOrchestrator.process_cfdis ejecuta el motor real (sin auto-advance):
     job.reconciliation poblado con matches/discrepancias cuando hay transacciones.
  5. Router POST /api/v1/pipeline/run (con auth por tenant del token).
"""
from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from b2b_ai.cfdi.adapter import adapt_batch, to_bookkeeping_format
from b2b_ai.cfdi.parser import parse_cfdi_4
from b2b_ai.features.bookkeeping.pipeline import PipelineOrchestrator
from b2b_ai.features.pipeline.orchestrator import (
    EndToEndOrchestrator,
    EndToEndPipelineError,
)
from b2b_ai.features.pipeline.routes import build_pipeline_router

# CFDI 4.0 realista (mismo fixture que test_batch_cfdi.py).
SAMPLE_CFDI = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
    Version="4.0" Serie="D" Folio="100"
    Fecha="2026-07-03T10:00:00"
    FormaPago="03" MetodoPago="PUE" Moneda="MXN"
    TipoDeComprobante="I" Exportacion="01"
    LugarExpedicion="06600" SubTotal="1000.00" Descuento="0.00" Total="1160.00">
    <cfdi:Emisor Rfc="PAP850101JKL" Nombre="PAPELERIA TEST" RegimenFiscal="601"/>
    <cfdi:Receptor Rfc="XAXX010101000" Nombre="RECEPTOR TEST"
        DomicilioFiscalReceptor="06600" RegimenFiscalReceptor="603" UsoCFDI="G03"/>
    <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="44122000" Cantidad="1"
            ClaveUnidad="E48" Unidad="Servicio"
            Descripcion="Papeleria y articulos de oficina"
            ValorUnitario="1000.00" Importe="1000.00" ObjetoImp="02">
            <cfdi:Impuestos>
                <cfdi:Traslados>
                    <cfdi:Traslado Base="1000.00" Impuesto="002" TipoFactor="Tasa"
                        TasaOCuota="0.160000" Importe="160.00"/>
                </cfdi:Traslados>
            </cfdi:Impuestos>
        </cfdi:Concepto>
    </cfdi:Conceptos>
    <cfdi:Impuestos TotalImpuestosTrasladados="160.00">
        <cfdi:Traslados>
            <cfdi:Traslado Base="1000.00" Impuesto="002" TipoFactor="Tasa"
                TasaOCuota="0.160000" Importe="160.00"/>
        </cfdi:Traslados>
    </cfdi:Impuestos>
    <cfdi:Complemento>
        <tfd:TimbreFiscalDigital Version="1.1"
            UUID="550e8400-e29b-41d4-a716-446655440000"
            FechaTimbrado="2026-07-03T10:01:00" RfcProvCertif="SAT970701NN3"
            SelloCFD="AABBCC" NoCertificado="00001000000000000000" SelloSAT="DDEEFF"/>
    </cfdi:Complemento>
</cfdi:Comprobante>"""

BAD_XML = "<xml>no es un cfdi</xml>"


# ---------------------------------------------------------------------------
# 1. Adapter
# ---------------------------------------------------------------------------

def test_adapter_mapea_emisor_receptor_tipo():
    parsed = parse_cfdi_4(SAMPLE_CFDI)
    adapted = to_bookkeeping_format(parsed)

    assert adapted["rfc_emisor"] == "PAP850101JKL"
    assert adapted["rfc_receptor"] == "XAXX010101000"
    assert adapted["tipo"] == "I"
    assert adapted["tipo_cfdi"] == "I"
    assert adapted["uuid"] == "550e8400-e29b-41d4-a716-446655440000"
    assert adapted["total"] == 1160.0
    assert adapted["subtotal"] == 1000.0
    assert adapted["iva"] == 160.0
    assert adapted["tasa_iva"] == 0.16
    assert "papeleria" in adapted["descripcion"].lower()
    assert len(adapted["conceptos"]) == 1


def test_adapter_es_idempotente():
    """Un CFDI ya adaptado se devuelve sin tocar."""
    parsed = parse_cfdi_4(SAMPLE_CFDI)
    adapted = to_bookkeeping_format(parsed)
    assert to_bookkeeping_format(adapted) is adapted


def test_adapter_adapt_batch():
    parsed = parse_cfdi_4(SAMPLE_CFDI)
    batch = adapt_batch([parsed])
    assert len(batch) == 1
    assert batch[0]["rfc_emisor"] == "PAP850101JKL"


# ---------------------------------------------------------------------------
# 2. Orquestador end-to-end
# ---------------------------------------------------------------------------

def test_orchestrator_flujo_completo_con_conciliacion():
    orch = EndToEndOrchestrator()
    result = orch.upload_cfdis(
        xml_files=[("cfdi1.xml", SAMPLE_CFDI)],
        tenant_id="tenant_e2e",
        periodo="2026-07",
        bank_transactions=[
            {
                "id": "txn-1",
                "date": "2026-07-03",
                "description": "Pago papeleria",
                "amount": 1160.00,
                "type": "EGRESO",
                "reference": "550e8400-e29b-41d4-a716-446655440000",
                "bank_account": "1234",
            },
        ],
    )

    assert result["status"] == "completed"
    assert result["cfdis_parsed"] == 1
    assert result["cfdis_adapted"] == 1
    assert result["polizas_count"] >= 1
    assert result["classifications_count"] >= 1
    # El motor de conciliación real corrió (no auto-advance).
    assert result["reconciliation"] is not None
    assert "report" in result["reconciliation"]
    assert result["reconciliation"]["period"] == "2026-07"


def test_orchestrator_reporte_conciliacion_tiene_matches():
    orch = EndToEndOrchestrator()
    result = orch.upload_cfdis(
        xml_files=[("cfdi1.xml", SAMPLE_CFDI)],
        tenant_id="tenant_e2e",
        periodo="2026-07",
        bank_transactions=[
            {
                "id": "txn-1",
                "date": "2026-07-03",
                "description": "Pago papeleria",
                "amount": 1160.00,
                "type": "EGRESO",
                "reference": "550e8400-e29b-41d4-a716-446655440000",
                "bank_account": "1234",
            },
        ],
    )
    rec = result["reconciliation"]
    assert isinstance(rec["report"], dict)
    assert "poliza_matches" in rec
    assert "discrepancies" in rec
    assert "adjustments" in rec


def test_orchestrator_sin_transacciones_no_crash():
    """Sin transacciones bancarias, reconciliation es None pero el flujo avanza."""
    orch = EndToEndOrchestrator()
    result = orch.upload_cfdis(
        xml_files=[("cfdi1.xml", SAMPLE_CFDI)],
        tenant_id="tenant_e2e",
    )
    assert result["status"] == "completed"
    assert result["reconciliation"] is None


def test_orchestrator_parse_error_aislado():
    """Un CFDI malo se reporta en errors sin abortar los válidos."""
    orch = EndToEndOrchestrator()
    result = orch.upload_cfdis(
        xml_files=[("bad.xml", BAD_XML), ("ok.xml", SAMPLE_CFDI)],
        tenant_id="tenant_e2e",
    )
    assert result["status"] == "completed"
    assert result["cfdis_parsed"] == 1
    assert len(result["parse_errors"]) == 1
    assert result["parse_errors"][0]["file"] == "bad.xml"


def test_orchestrator_sin_cfdis_lanza():
    orch = EndToEndOrchestrator()
    try:
        orch.upload_cfdis([], tenant_id="t")
        assert False, "debería lanzar EndToEndPipelineError"
    except EndToEndPipelineError:
        pass


# ---------------------------------------------------------------------------
# 3. Bookkeeping pipeline — motor de conciliación real (no auto-advance)
# ---------------------------------------------------------------------------

def test_bookkeeping_pipeline_ejecuta_motor_conciliacion():
    parsed = parse_cfdi_4(SAMPLE_CFDI)
    adapted = to_bookkeeping_format(parsed)

    pipeline = PipelineOrchestrator()
    job = pipeline.process_cfdis(
        cfdis=[adapted],
        tenant_id="tenant_e2e",
        periodo="2026-07",
        bank_transactions=[
            {
                "id": "txn-1",
                "date": "2026-07-03",
                "description": "Pago papeleria",
                "amount": 1160.00,
                "type": "EGRESO",
                "reference": "550e8400-e29b-41d4-a716-446655440000",
                "bank_account": "1234",
            },
        ],
    )

    assert job.stage.value == "completed"
    assert job.reconciliation is not None
    assert len(job.reconciliation["poliza_matches"]) >= 1


# ---------------------------------------------------------------------------
# 4. Router POST /api/v1/pipeline/run
# ---------------------------------------------------------------------------

def _auth_for(tenant_id: str):
    async def _dep():
        return {"key": "k", "tenant_id": tenant_id, "user_id": "u1"}
    return _dep


def _grant_admin(tenant_id: str):
    """Concede el rol admin (todos los permisos) a u1 en el tenant.

    El pipeline ahora enforza RBAC (PIPELINE_RUN); el rol admin lo incluye.
    El store RBAC es global-en-memoria, así que sembrar aquí basta para que
    la dependencia require_permission del router lo conceda.
    """
    from b2b_ai.features.roles.service import RolesService, reset_state
    reset_state()
    svc = RolesService()
    admin = next(r for r in svc.list_roles() if r.name == "admin")
    svc.assign_role("u1", tenant_id, admin.id)


def _grant_admin(tenant_id: str):
    """Concede el rol admin (todos los permisos) a u1 en el tenant.

    El pipeline ahora enforza RBAC (PIPELINE_RUN); el rol admin lo incluye.
    El store RBAC es global-en-memoria, así que sembrar aquí basta para que
    la dependencia require_permission del router lo conceda.
    """
    from b2b_ai.features.roles.service import RolesService, reset_state
    reset_state()
    svc = RolesService()
    admin = next(r for r in svc.list_roles() if r.name == "admin")
    svc.assign_role("u1", tenant_id, admin.id)


def _grant_admin(tenant_id: str):
    """Concede el rol admin (todos los permisos) a u1 en el tenant.

    El pipeline ahora enforza RBAC (PIPELINE_RUN); el rol admin lo incluye.
    El store RBAC es global-en-memoria, así que sembrar aquí basta para que
    la dependencia require_permission del router lo conceda.
    """
    from b2b_ai.features.roles.service import RolesService, reset_state
    from b2b_ai.features.roles.seed import seed_default_roles
    reset_state()
    svc = RolesService()
    admin = next(r for r in svc.list_roles() if r.name == "admin")
    svc.assign_role("u1", tenant_id, admin.id)


def _grant_admin(tenant_id: str):
    """Concede el rol admin (todos los permisos) a u1 en el tenant.

    El pipeline ahora enforza RBAC (PIPELINE_RUN); el rol admin lo incluye.
    El store RBAC es global-en-memoria, así que sembrar aquí basta para que
    la dependencia require_permission del router lo conceda.
    """
    from b2b_ai.features.roles.service import RolesService, reset_state
    from b2b_ai.features.roles.seed import seed_default_roles
    reset_state()
    svc = RolesService()
    admin = next(r for r in svc.list_roles() if r.name == "admin")
    svc.assign_role("u1", tenant_id, admin.id)


def test_pipeline_router_run_flujo_completo():
    _grant_admin("tenant_router")
    router = build_pipeline_router(db=None, require_api_key=_auth_for("tenant_router"))
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    resp = client.post("/api/v1/pipeline/run", json={
        "cfdis": [{"filename": "cfdi1.xml", "content": SAMPLE_CFDI}],
        "periodo": "2026-07",
        "bank_transactions": [
            {
                "id": "txn-1",
                "date": "2026-07-03",
                "description": "Pago papeleria",
                "amount": 1160.00,
                "type": "EGRESO",
                "reference": "550e8400-e29b-41d4-a716-446655440000",
                "bank_account": "1234",
            },
        ],
    })

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["status"] == "completed"
    assert body["polizas_count"] >= 1
    assert body["reconciliation"] is not None


def test_pipeline_router_run_sin_cfdis_400():
    _grant_admin("tenant_router")
    router = build_pipeline_router(db=None, require_api_key=_auth_for("tenant_router"))
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    resp = client.post("/api/v1/pipeline/run", json={"cfdis": []})
    assert resp.status_code == 400


def test_pipeline_router_requiere_auth():
    """Sin require_api_key el router no se construye (fail-fast de seguridad)."""
    try:
        build_pipeline_router(db=None, require_api_key=None)
        assert False, "debería lanzar ValueError"
    except ValueError:
        pass
