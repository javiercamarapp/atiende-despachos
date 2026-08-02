# -*- coding: utf-8 -*-
"""
routes.py — Demo mode API routes for Likida AI Enterprise.

When ``DEMO_MODE=true`` is set in the environment, these routes are mounted
on the FastAPI app and provide realistic mock data for all major endpoints.
Prospects can try the product without a real backend, CFDI data, or ERP.

Mount with::

    from b2b_ai.demo.routes import mount_demo_routes
    mount_demo_routes(app)

New endpoints for enterprise sales:
    GET  /api/demo/firm          — Full firm data (50 clients, 500 CFDIs)
    GET  /api/demo/firm/clients  — Client list with details
    GET  /api/demo/firm/roi      — ROI metrics and KPIs
    GET  /api/demo/firm/report   — Generate/download PDF report
    GET  /api/demo/firm/summary  — Executive summary JSON
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse

from b2b_ai.demo.mock_data import (
    DEMO_CFDI_SAMPLES,
    DEMO_STATS,
    DEMO_ANALYTICS,
    DEMO_INVOICES,
    DEMO_DASHBOARD_SUMMARY,
    demo_process_result,
)


def is_demo_mode() -> bool:
    """Return True if DEMO_MODE is active."""
    return os.environ.get("DEMO_MODE", "").strip().lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Lazy-loaded firm data cache (generated once per session)
# ---------------------------------------------------------------------------
_firm_data_cache = None


def _get_firm_data():
    """Generate or return cached firm demo data."""
    global _firm_data_cache
    if _firm_data_cache is None:
        from b2b_ai.demo.firm_generator import generate_demo_firm
        _firm_data_cache = generate_demo_firm(month="2026-07", seed=42)
    return _firm_data_cache


def mount_demo_routes(app) -> None:
    """Mount all demo routes on the FastAPI app."""
    router = APIRouter(prefix="/api/demo", tags=["demo"])

    # ------------------------------------------------------------------ #
    # Health / status
    # ------------------------------------------------------------------ #

    @router.get("/health")
    def demo_health():
        """Health check — confirms demo mode is active."""
        return {
            "status": "healthy",
            "mode": "demo",
            "message": "Likida AI Enterprise Demo Mode — todos los datos son simulados.",
            "timestamp": datetime.now().isoformat(),
        }

    @router.get("/status")
    def demo_status():
        """Processing stats in demo mode."""
        firm = _get_firm_data()
        return {
            "status": "running",
            "mode": "demo",
            "total_processed": len(DEMO_CFDI_SAMPLES),
            "total_anomalies": DEMO_ANALYTICS["anomalias_detectadas"],
            "started_at": "2026-08-01T00:00:00",
            "last_processed_at": datetime.now().isoformat(),
            "available_xmls": len(DEMO_CFDI_SAMPLES),
            "results_count": len(DEMO_INVOICES),
            "firm_clients": len(firm["clients"]),
            "firm_cfdis": len(firm["cfdis"]),
        }

    # ------------------------------------------------------------------ #
    # CFDI processing
    # ------------------------------------------------------------------ #

    @router.post("/process", summary="Procesa un CFDI (demo — mock data).")
    def demo_process(
        sample_index: int = Query(
            default=0,
            ge=0,
            le=len(DEMO_CFDI_SAMPLES) - 1,
            description="Índice del CFDI de demo a procesar (0-9).",
        ),
    ):
        """Process a single CFDI from the demo dataset.

        Returns realistic mock data as if the CFDI was parsed, classified,
        and anomaly-checked against historical data.
        """
        return {"result": demo_process_result(sample_index)}

    @router.get(
        "/process-all",
        summary="Procesa todos los CFDIs de demo y devuelve resultados.",
    )
    def demo_process_all():
        """Process all 10 demo CFDIs and return a batch summary."""
        t_start = time.time()
        results = []
        total_monto = 0.0
        total_iva = 0.0
        cats = {}

        for i, sample in enumerate(DEMO_CFDI_SAMPLES):
            result = demo_process_result(i)
            results.append(result)
            try:
                total_monto += float(str(result["datos"]["total"]).replace(",", ""))
            except (TypeError, ValueError):
                pass
            try:
                total_iva += float(str(result["datos"].get("iva", 0)).replace(",", ""))
            except (TypeError, ValueError):
                pass
            cat = result["clasificacion"]["categoria"]
            cats[cat] = cats.get(cat, 0) + 1

        anomalies_count = sum(len(r["anomalias"]) for r in results)
        elapsed = time.time() - t_start

        return {
            "elapsed_seconds": round(elapsed, 3),
            "processed": len(results),
            "errors": [],
            "summary": {
                "monto_total": round(total_monto, 2),
                "iva_total": round(total_iva, 2),
                "por_categoria": cats,
                "anomalies_detected": anomalies_count,
            },
            "results": results,
        }

    # ------------------------------------------------------------------ #
    # Invoices
    # ------------------------------------------------------------------ #

    @router.get("/invoices", summary="Lista facturas de demo.")
    def demo_invoices(
        limit: int = Query(default=100, le=1000),
    ):
        """Return mock invoices list."""
        return {
            "count": len(DEMO_INVOICES[:limit]),
            "invoices": DEMO_INVOICES[:limit],
        }

    @router.get("/invoices/{invoice_id}", summary="Detalle de una factura.")
    def demo_invoice_detail(invoice_id: int):
        """Return a single mock invoice by ID."""
        for inv in DEMO_INVOICES:
            if inv["id"] == invoice_id:
                return inv
        raise HTTPException(404, "Factura no encontrada (demo).")

    # ------------------------------------------------------------------ #
    # Stats / Analytics
    # ------------------------------------------------------------------ #

    @router.get("/stats", summary="Estadísticas globales (demo).")
    def demo_stats():
        """Return mock global statistics."""
        return DEMO_STATS

    @router.get("/analytics", summary="Analytics avanzado (demo).")
    def demo_analytics(
        periodo: Optional[str] = Query(default=None),
        desde: Optional[str] = Query(default=None),
        hasta: Optional[str] = Query(default=None),
    ):
        """Return mock analytics data."""
        result = dict(DEMO_ANALYTICS)
        if periodo:
            result["periodo"] = periodo
        return result

    # ------------------------------------------------------------------ #
    # Dashboard
    # ------------------------------------------------------------------ #

    @router.get("/dashboard/summary", summary="Resumen dashboard (demo).")
    def demo_dashboard_summary():
        """Return mock dashboard summary with KPIs."""
        return DEMO_DASHBOARD_SUMMARY

    @router.get("/dashboard/kpi", summary="KPIs del dashboard (demo).")
    def demo_dashboard_kpi():
        """Return mock KPI data."""
        return DEMO_DASHBOARD_SUMMARY["kpis"]

    @router.get("/dashboard/monthly", summary="Tendencia mensual (demo).")
    def demo_dashboard_monthly():
        """Return mock monthly trend data."""
        return {"monthly": DEMO_DASHBOARD_SUMMARY["monthly_trend"]}

    @router.get("/dashboard/anomalies", summary="Anomalías recientes (demo).")
    def demo_dashboard_anomalies():
        """Return mock recent anomalies."""
        return {"anomalies": DEMO_DASHBOARD_SUMMARY["recent_anomalies"]}

    # ------------------------------------------------------------------ #
    # Upload (simulated)
    # ------------------------------------------------------------------ #

    @router.post("/upload", summary="Upload CFDI XML (demo — simulated).")
    async def demo_upload(file: UploadFile = File(...)):
        """Simulate uploading and processing a CFDI XML file.

        In demo mode, the file content is ignored and a realistic mock
        result is returned as if the file was successfully processed.
        """
        if not file.filename or not file.filename.lower().endswith(".xml"):
            raise HTTPException(
                status_code=400,
                detail="Solo se aceptan archivos XML en modo demo.",
            )
        # Pick a result based on filename hash for variety
        idx = hash(file.filename) % len(DEMO_CFDI_SAMPLES)
        result = demo_process_result(idx)
        result["archivo"] = file.filename
        return result

    # ------------------------------------------------------------------ #
    # Notifications (simulated)
    # ------------------------------------------------------------------ #

    @router.post("/notifications/send", summary="Envía notificación (demo).")
    def demo_notification_send():
        """Simulate sending a notification."""
        return {
            "status": "simulado",
            "channel": "email",
            "message": "Notificación simulada en modo demo. No se envió nada real.",
            "timestamp": datetime.now().isoformat(),
        }

    @router.get("/notifications/history", summary="Historial notificaciones.")
    def demo_notification_history():
        """Return mock notification history."""
        return {
            "count": 7,
            "notifications": [
                {
                    "id": i + 1,
                    "channel": "email",
                    "recipient": f"usuario{i+1}@empresa.com",
                    "subject": f"Notificación demo #{i+1}",
                    "status": "simulado",
                    "created_at": f"2026-08-0{i+1}T10:00:00",
                }
                for i in range(7)
            ],
        }

    # ------------------------------------------------------------------ #
    # Collections (simulated)
    # ------------------------------------------------------------------ #

    @router.get("/collections", summary="Estado de cobranza (demo).")
    def demo_collections():
        """Return mock collections data."""
        return {
            "total_pendiente": 245_000.00,
            "total_vencido": 82_000.00,
            "cuentas_pendientes": [
                {
                    "cliente": "Constructora del Sur S de RL",
                    "rfc": "COS850101QR3",
                    "monto": 45_000.00,
                    "dias_vencido": 15,
                    "status": "vencido",
                    "ultimo_contacto": "2026-07-20",
                },
                {
                    "cliente": "Plásticos Industriales SA",
                    "rfc": "PLA970815HV5",
                    "monto": 37_000.00,
                    "dias_vencido": 8,
                    "status": "por_vencer",
                    "ultimo_contacto": "2026-07-28",
                },
            ],
        }

    # ------------------------------------------------------------------ #
    # Onboarding (simulated)
    # ------------------------------------------------------------------ #

    @router.get("/onboarding/checklist", summary="Checklist onboarding (demo).")
    def demo_onboarding_checklist():
        """Return mock onboarding checklist."""
        return {
            "checklist": [
                {"item": "RFC registrado", "status": "completado", "peso": 20},
                {"item": "API key configurada", "status": "completado", "peso": 20},
                {"item": "Primer CFDI procesado", "status": "completado", "peso": 25},
                {"item": "Notificaciones activadas", "status": "pendiente", "peso": 15},
                {"item": "Dashboard configurado", "status": "pendiente", "peso": 10},
                {"item": "Integración ERP", "status": "no_iniciado", "peso": 10},
            ],
            "score": 65,
            "max_score": 100,
            "next_step": "Activar notificaciones por email",
        }

    # ------------------------------------------------------------------ #
    # Landing demo info
    # ------------------------------------------------------------------ #

    @router.get("/landing-info", summary="Info para la landing page.")
    def demo_landing_info():
        """Return demo configuration for the landing page."""
        return {
            "demo_mode": True,
            "company": "Demo Corp SA de CV",
            "available_features": [
                "Procesamiento de CFDI",
                "Clasificación automática de gastos",
                "Detección de anomalías",
                "Dashboard analítico",
                "Notificaciones por email",
                "Reportes PDF",
                "Conciliación bancaria",
                "Billing (Stripe/Conekta)",
            ],
            "sample_data": {
                "invoices_processed": len(DEMO_CFDI_SAMPLES),
                "categories": [
                    {"code": "G01", "name": "Gastos en general"},
                    {"code": "SER", "name": "Servicios profesionales"},
                    {"code": "NOM", "name": "Nómina"},
                    {"code": "COM", "name": "Comunicaciones y marketing"},
                ],
            },
        }

    # ================================================================== #
    # ENTERPRISE SALES ENDPOINTS (New)
    # ================================================================== #

    @router.get("/firm", summary="Datos completos de la firma demo.")
    def demo_firm():
        """Return full firm data: 50 clients, 500 CFDIs, anomalies, ROI.

        This is the main endpoint for the enterprise sales demo.
        Returns everything a prospect needs to understand the product.
        """
        firm = _get_firm_data()
        return {
            "firm": firm["firm"],
            "client_count": len(firm["clients"]),
            "cfdi_count": len(firm["cfdis"]),
            "anomaly_count": len(firm["anomalies"]),
            "nomina_count": len(firm["nominas"]),
            "month": firm["month"],
            "generated_at": firm["generated_at"],
        }

    @router.get("/firm/clients", summary="Lista de clientes de la firma demo.")
    def demo_firm_clients(
        limit: int = Query(default=50, le=100),
        tamano: Optional[str] = Query(default=None, description="Filtrar por tamaño: pequena, mediana, grande"),
    ):
        """Return mock client list for the accounting firm.

        Each client includes: name, RFC, city, industry, size,
        expected monthly invoices, and monthly subscription fee.
        """
        firm = _get_firm_data()
        clients = firm["clients"][:limit]
        if tamano:
            clients = [c for c in clients if c["tamano"] == tamano]
        return {
            "count": len(clients),
            "clients": clients,
        }

    @router.get("/firm/clients/{client_id}", summary="Detalle de un cliente demo.")
    def demo_firm_client_detail(client_id: int):
        """Return a single client with their CFDIs and metrics."""
        firm = _get_firm_data()
        client = next((c for c in firm["clients"] if c["id"] == client_id), None)
        if not client:
            raise HTTPException(404, "Cliente no encontrado (demo).")

        client_cfdis = [c for c in firm["cfdis"] if c["client_id"] == client_id]
        total_monto = sum(float(c["total"]) for c in client_cfdis)

        return {
            "client": client,
            "cfdis_count": len(client_cfdis),
            "monto_total": round(total_monto, 2),
            "anomalies": [a for a in firm["anomalies"] if a.get("client") == client["nombre"]],
        }

    @router.get("/firm/cfdi", summary="CFDIs de la firma demo.")
    def demo_firm_cfdis(
        limit: int = Query(default=100, le=1000),
        client_id: Optional[int] = Query(default=None),
        tipo: Optional[str] = Query(default=None),
    ):
        """Return generated CFDIs with optional filters.

        Returns a sample of the ~500 CFDIs generated for the demo firm.
        """
        firm = _get_firm_data()
        cfdis = firm["cfdis"]
        if client_id:
            cfdis = [c for c in cfdis if c["client_id"] == client_id]
        if tipo:
            cfdis = [c for c in cfdis if c["tipo"].lower() == tipo.lower()]
        return {
            "count": len(cfdis[:limit]),
            "total_in_firm": len(firm["cfdis"]),
            "cfdis": cfdis[:limit],
        }

    @router.get("/firm/roi", summary="Métricas de ROI de la firma demo.")
    def demo_firm_roi():
        """Return ROI metrics, KPIs, and comparative analysis.

        Key metrics:
        - Hours saved per month (automation vs manual)
        - Cost savings in MXN
        - ROI percentage
        - Payback period
        - Quality improvement (error rate reduction)
        """
        firm = _get_firm_data()
        return firm["roi_metrics"]

    @router.get("/firm/summary", summary="Resumen ejecutivo de la firma demo.")
    def demo_firm_summary():
        """Return executive summary for presentations.

        Includes: KPI cards, top clients, financial overview,
        and recommendation text suitable for a pitch deck.
        """
        from b2b_ai.demo.firm_generator import build_executive_summary
        firm = _get_firm_data()
        return build_executive_summary(firm)

    @router.get("/firm/anomalies", summary="Anomalías de la firma demo.")
    def demo_firm_anomalies(
        severity: Optional[str] = Query(default=None),
    ):
        """Return detected anomalies with optional severity filter."""
        firm = _get_firm_data()
        anomalies = firm["anomalies"]
        if severity:
            anomalies = [a for a in anomalies if a["severity"] == severity]
        return {
            "count": len(anomalies),
            "anomalies": anomalies,
        }

    @router.get("/firm/nominas", summary="Nómina de la firma demo.")
    def demo_firm_nominas():
        """Return mock payroll data for the firm's employees."""
        firm = _get_firm_data()
        return {
            "periodo": firm["month"],
            "empleados": len(firm["nominas"]),
            "nominas": firm["nominas"],
        }

    @router.get("/firm/report-pdf", summary="Genera reporte PDF de ROI.")
    def demo_firm_report_pdf():
        """Generate and return the ROI PDF report.

        The PDF includes:
        - Executive summary with KPI cards
        - Detailed ROI metrics (savings, quality, investment)
        - Top clients table
        - Anomaly detection results
        - Conclusions and recommendations

        Returns the PDF as a file download.
        """
        import tempfile
        from fastapi.responses import FileResponse

        firm = _get_firm_data()
        output_dir = tempfile.mkdtemp(prefix="bbai_report_")

        try:
            from b2b_ai.demo.report_pdf import generate_roi_report
            from b2b_ai.demo.firm_generator import build_executive_summary

            summary = build_executive_summary(firm)
            pdf_path = generate_roi_report(firm, output_dir, summary)

            return FileResponse(
                path=pdf_path,
                filename="Likida_AI_Reporte_ROI_Demo.pdf",
                media_type="application/pdf",
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error generando reporte PDF: {str(e)}",
            )

    @router.get("/firm/top-proveedores", summary="Top proveedores de la firma demo.")
    def demo_firm_top_proveedores():
        """Return top providers by invoice count and amount."""
        firm = _get_firm_data()
        return {
            "proveedores": firm["top_proveedores"],
        }

    @router.get("/firm/top-giros", summary="Distribución por giro económico.")
    def demo_firm_top_giros():
        """Return distribution by economic sector."""
        firm = _get_firm_data()
        return {
            "giros": firm["top_giros"],
        }

    app.include_router(router)
