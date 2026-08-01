#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
demo_server.py — Live demo server for B&B AI.

FastAPI app that demonstrates CFDI processing to prospects.
Run with: python demo_server.py
Or use:   ./demo_run.sh
"""
from __future__ import annotations

import os
import sys
import json
import time
import uuid
import shutil
import tempfile
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

# ---------------------------------------------------------------------------
# Ensure the enterprise/ directory is on sys.path so b2b_ai is importable
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from b2b_ai.cfdi.parser import parse_cfdi, CFDIError
from b2b_ai.services.classify import classify_cfdi, CATEGORIA_NOMBRE
from b2b_ai.services.anomaly import detect_anomalies, summarize_anomalies

# ---------------------------------------------------------------------------
# App state
# ---------------------------------------------------------------------------
app = FastAPI(
    title="B&B AI — Demo CFDI",
    description="Demo server for B&B AI CFDI processing",
    version="1.0.0",
)

DEMO_DATA_DIR = _HERE / "b2b_ai" / "demo-data"
TEMP_UPLOAD_DIR = Path(tempfile.mkdtemp(prefix="bbai_demo_"))

# In-memory results store
_results_store: Dict[str, Any] = {
    "results": [],
    "history": [],  # processed invoices for anomaly cross-check
    "stats": {
        "total_processed": 0,
        "total_anomalies": 0,
        "started_at": None,
        "last_processed_at": None,
    },
}


def _process_cfdi(xml_path: str, filename: str = "") -> Dict[str, Any]:
    """Process a single CFDI XML through parse → classify → anomaly detection."""
    datos = parse_cfdi(xml_path)
    clasificacion = classify_cfdi(datos)

    # Build invoice record for anomaly cross-check
    invoice = dict(datos)
    invoice["categoria"] = clasificacion["categoria"]
    invoice["confianza"] = clasificacion["confianza"]

    # Use all previously processed invoices as historical context
    historical = _results_store["history"]
    anomalias = detect_anomalies(invoice, historical)
    anom_summary = summarize_anomalies(anomalias)

    # Store in history for future cross-checks
    _results_store["history"].append({
        "emisor_rfc": datos.get("emisor_rfc"),
        "total": str(datos.get("total")),
        "fecha": datos.get("fecha"),
        "folio_fiscal": datos.get("folio_fiscal"),
    })

    return {
        "id": str(uuid.uuid4())[:8],
        "archivo": filename or os.path.basename(xml_path),
        "datos": {
            "version": datos.get("version"),
            "tipo": datos.get("tipo"),
            "fecha": datos.get("fecha"),
            "serie": datos.get("serie"),
            "folio": datos.get("folio"),
            "subtotal": str(datos.get("subtotal", "")),
            "descuento": str(datos.get("descuento") or ""),
            "total": str(datos.get("total", "")),
            "moneda": datos.get("moneda"),
            "metodo_pago": datos.get("metodo_pago"),
            "forma_pago": datos.get("forma_pago"),
            "emisor_rfc": datos.get("emisor_rfc"),
            "emisor_nombre": datos.get("emisor_nombre"),
            "emisor_regimen": datos.get("emisor_regimen"),
            "receptor_rfc": datos.get("receptor_rfc"),
            "receptor_nombre": datos.get("receptor_nombre"),
            "folio_fiscal": datos.get("folio_fiscal"),
            "iva": str(datos.get("iva", "")),
            "tasa_iva": datos.get("tasa_iva"),
            "conceptos_count": len(datos.get("conceptos", [])),
            "conceptos": [
                {
                    "descripcion": c.get("descripcion", ""),
                    "importe": str(c.get("importe", "")),
                    "clave_prod_serv": c.get("clave_prod_serv", ""),
                }
                for c in (datos.get("conceptos") or [])
            ],
        },
        "clasificacion": clasificacion,
        "anomalias": anomalias,
        "anomalias_summary": anom_summary,
        "timestamp": datetime.now().isoformat(),
    }


def _get_category_label(cat: str) -> str:
    return CATEGORIA_NOMBRE.get(cat, cat)


def _get_all_demo_xmls() -> List[Path]:
    """Return sorted list of demo XML files."""
    return sorted(DEMO_DATA_DIR.glob("*.xml"))


# ===========================================================================
# API ENDPOINTS
# ===========================================================================


@app.get("/api/demo/status")
async def demo_status():
    """Shows processing stats."""
    stats = _results_store["stats"]
    return {
        "status": "running",
        "total_processed": stats["total_processed"],
        "total_anomalies": stats["total_anomalies"],
        "started_at": stats["started_at"],
        "last_processed_at": stats["last_processed_at"],
        "available_xmls": len(_get_all_demo_xmls()),
        "results_count": len(_results_store["results"]),
    }


@app.get("/api/demo/results")
async def demo_results():
    """Returns all processed results as JSON."""
    return {
        "count": len(_results_store["results"]),
        "results": _results_store["results"],
    }


@app.post("/api/demo/upload")
async def demo_upload(file: UploadFile = File(...)):
    """Upload a CFDI XML file and process it."""
    if not file.filename or not file.filename.lower().endswith(".xml"):
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos XML")

    content = await file.read()
    tmp_path = TEMP_UPLOAD_DIR / file.filename
    tmp_path.write_bytes(content)

    try:
        result = _process_cfdi(str(tmp_path), file.filename)
        _results_store["results"].append(result)
        _results_store["stats"]["total_processed"] += 1
        _results_store["stats"]["total_anomalies"] += len(result["anomalias"])
        _results_store["stats"]["last_processed_at"] = datetime.now().isoformat()
        return result
    except CFDIError as e:
        raise HTTPException(status_code=400, detail=f"Error al parsear CFDI: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error procesando: {e}")
    finally:
        tmp_path.unlink(missing_ok=True)


@app.get("/api/demo/process-all")
async def demo_process_all():
    """Processes all 10 demo XMLs and returns results."""
    xml_files = _get_all_demo_xmls()
    if not xml_files:
        raise HTTPException(status_code=404, detail="No se encontraron XMLs de demo")

    results = []
    errors = []
    t_start = time.time()

    for xml_path in xml_files:
        try:
            result = _process_cfdi(str(xml_path), xml_path.name)
            results.append(result)
            _results_store["results"].append(result)
            _results_store["stats"]["total_processed"] += 1
            _results_store["stats"]["total_anomalies"] += len(result["anomalias"])
        except Exception as e:
            errors.append({"archivo": xml_path.name, "error": str(e)})

    elapsed = time.time() - t_start
    _results_store["stats"]["last_processed_at"] = datetime.now().isoformat()

    # Summary
    total_monto = 0.0
    total_iva = 0.0
    cats: Dict[str, int] = {}
    for r in results:
        try:
            total_monto += float(str(r["datos"].get("total", 0)).replace(",", ""))
        except (TypeError, ValueError):
            pass
        try:
            total_iva += float(str(r["datos"].get("iva", 0)).replace(",", ""))
        except (TypeError, ValueError):
            pass
        cat = r["clasificacion"]["categoria"]
        cats[cat] = cats.get(cat, 0) + 1

    anomalies_count = sum(len(r["anomalias"]) for r in results)

    return {
        "elapsed_seconds": round(elapsed, 3),
        "processed": len(results),
        "errors": errors,
        "summary": {
            "monto_total": round(total_monto, 2),
            "iva_total": round(total_iva, 2),
            "por_categoria": {CATEGORIA_NOMBRE.get(k, k): v for k, v in cats.items()},
            "anomalies_detected": anomalies_count,
        },
        "results": results,
    }


# ===========================================================================
# HTML DASHBOARD
# ===========================================================================


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>B&B AI — Demo Procesamiento CFDI</title>
<style>
:root {
  --blue: #2563EB;
  --blue-dark: #1D4ED8;
  --blue-light: #DBEAFE;
  --green: #16A34A;
  --green-light: #DCFCE7;
  --amber: #D97706;
  --amber-light: #FEF3C7;
  --red: #DC2626;
  --red-light: #FEE2E2;
  --gray-50: #F9FAFB;
  --gray-100: #F3F4F6;
  --gray-200: #E5E7EB;
  --gray-300: #D1D5DB;
  --gray-400: #9CA3AF;
  --gray-500: #6B7280;
  --gray-600: #4B5563;
  --gray-700: #374151;
  --gray-800: #1F2937;
  --gray-900: #111827;
  --radius: 12px;
  --shadow: 0 1px 3px rgba(0,0,0,0.1), 0 1px 2px rgba(0,0,0,0.06);
  --shadow-md: 0 4px 6px rgba(0,0,0,0.07), 0 2px 4px rgba(0,0,0,0.06);
  --shadow-lg: 0 10px 15px rgba(0,0,0,0.1), 0 4px 6px rgba(0,0,0,0.05);
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, sans-serif;
  background: var(--gray-50);
  color: var(--gray-800);
  line-height: 1.6;
  min-height: 100vh;
}

/* Header */
.header {
  background: linear-gradient(135deg, var(--blue) 0%, var(--blue-dark) 100%);
  color: white;
  padding: 1.5rem 2rem;
  box-shadow: var(--shadow-md);
}
.header-inner {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 1rem;
}
.logo {
  font-size: 1.75rem;
  font-weight: 800;
  letter-spacing: -0.02em;
}
.logo span { font-weight: 300; opacity: 0.85; font-size: 1rem; margin-left: 0.5rem; }
.header-badge {
  background: rgba(255,255,255,0.2);
  padding: 0.35rem 0.75rem;
  border-radius: 999px;
  font-size: 0.8rem;
  font-weight: 500;
}

/* Main */
.main { max-width: 1200px; margin: 0 auto; padding: 2rem; }

/* Stats grid */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1rem;
  margin-bottom: 2rem;
}
.stat-card {
  background: white;
  border-radius: var(--radius);
  padding: 1.25rem;
  box-shadow: var(--shadow);
  border-left: 4px solid var(--blue);
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.stat-card:hover { transform: translateY(-2px); box-shadow: var(--shadow-md); }
.stat-card.green { border-left-color: var(--green); }
.stat-card.amber { border-left-color: var(--amber); }
.stat-card.red { border-left-color: var(--red); }
.stat-card h3 {
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--gray-500);
  margin-bottom: 0.25rem;
}
.stat-card .value {
  font-size: 1.75rem;
  font-weight: 700;
  color: var(--gray-900);
}
.stat-card .value.green { color: var(--green); }
.stat-card .value.amber { color: var(--amber); }
.stat-card .value.red { color: var(--red); }

/* Sections */
.section {
  background: white;
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 1.5rem;
  margin-bottom: 1.5rem;
}
.section-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--gray-900);
  margin-bottom: 1rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

/* Buttons */
.btn {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.6rem 1.25rem;
  border-radius: 8px;
  font-size: 0.9rem;
  font-weight: 600;
  border: none;
  cursor: pointer;
  transition: all 0.15s ease;
}
.btn:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-primary {
  background: var(--blue);
  color: white;
}
.btn-primary:hover:not(:disabled) { background: var(--blue-dark); box-shadow: var(--shadow-md); }
.btn-secondary {
  background: var(--gray-100);
  color: var(--gray-700);
  border: 1px solid var(--gray-200);
}
.btn-secondary:hover:not(:disabled) { background: var(--gray-200); }
.btn-sm { padding: 0.4rem 0.8rem; font-size: 0.8rem; }

/* Upload area */
.upload-area {
  border: 2px dashed var(--gray-300);
  border-radius: var(--radius);
  padding: 2rem;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s ease;
  background: var(--gray-50);
}
.upload-area:hover, .upload-area.dragover {
  border-color: var(--blue);
  background: var(--blue-light);
}
.upload-area p { color: var(--gray-500); font-size: 0.9rem; }
.upload-area .icon { font-size: 2rem; margin-bottom: 0.5rem; }

/* Table */
.table-wrap { overflow-x: auto; }
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}
th {
  text-align: left;
  padding: 0.6rem 0.75rem;
  font-weight: 600;
  color: var(--gray-500);
  text-transform: uppercase;
  font-size: 0.7rem;
  letter-spacing: 0.05em;
  border-bottom: 2px solid var(--gray-200);
  white-space: nowrap;
}
td {
  padding: 0.6rem 0.75rem;
  border-bottom: 1px solid var(--gray-100);
  vertical-align: middle;
}
tr:hover td { background: var(--gray-50); }
.monto { font-family: 'SF Mono', 'Cascadia Code', monospace; text-align: right; font-weight: 500; }

/* Badges */
.badge {
  display: inline-block;
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
  font-size: 0.7rem;
  font-weight: 600;
  white-space: nowrap;
}
.badge-ok { background: var(--green-light); color: var(--green); }
.badge-warn { background: var(--amber-light); color: var(--amber); }
.badge-error { background: var(--red-light); color: var(--red); }
.badge-info { background: var(--blue-light); color: var(--blue); }

/* Anomaly cards */
.anomaly-card {
  background: white;
  border-left: 4px solid var(--amber);
  border-radius: 8px;
  padding: 1rem;
  margin-bottom: 0.75rem;
  box-shadow: var(--shadow);
}
.anomaly-card.high { border-left-color: var(--red); }
.anomaly-card.medium { border-left-color: var(--amber); }
.anomaly-card.low { border-left-color: var(--gray-400); }
.anomaly-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}
.anomaly-type { font-weight: 600; color: var(--gray-900); text-transform: capitalize; }
.anomaly-desc { color: var(--gray-600); font-size: 0.85rem; }
.anomaly-detail { color: var(--gray-400); font-size: 0.8rem; margin-top: 0.25rem; }
.anomaly-legal {
  color: var(--blue);
  font-size: 0.75rem;
  margin-top: 0.25rem;
  font-style: italic;
}

/* Progress */
.progress-bar {
  width: 100%;
  height: 6px;
  background: var(--gray-200);
  border-radius: 3px;
  overflow: hidden;
  margin-top: 0.75rem;
}
.progress-fill {
  height: 100%;
  background: var(--blue);
  border-radius: 3px;
  transition: width 0.3s ease;
}

/* Toast */
.toast {
  position: fixed;
  bottom: 2rem;
  right: 2rem;
  background: var(--gray-900);
  color: white;
  padding: 0.75rem 1.25rem;
  border-radius: 8px;
  font-size: 0.85rem;
  box-shadow: var(--shadow-lg);
  z-index: 1000;
  opacity: 0;
  transform: translateY(10px);
  transition: all 0.3s ease;
}
.toast.show { opacity: 1; transform: translateY(0); }

/* Chart */
.chart-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 0.5rem;
}
.chart-label {
  width: 140px;
  font-size: 0.8rem;
  text-align: right;
  color: var(--gray-600);
  flex-shrink: 0;
}
.chart-bar-bg {
  flex: 1;
  height: 24px;
  background: var(--gray-100);
  border-radius: 12px;
  overflow: hidden;
}
.chart-bar {
  height: 100%;
  border-radius: 12px;
  transition: width 0.6s ease;
  min-width: 4px;
}
.chart-count {
  width: 40px;
  font-size: 0.8rem;
  color: var(--gray-500);
  flex-shrink: 0;
}

/* Empty state */
.empty-state {
  text-align: center;
  padding: 3rem 1rem;
  color: var(--gray-400);
}
.empty-state .icon { font-size: 3rem; margin-bottom: 0.5rem; }
.empty-state p { font-size: 0.9rem; }

/* Spinner */
.spinner {
  display: inline-block;
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* Footer */
.footer {
  text-align: center;
  padding: 2rem;
  color: var(--gray-400);
  font-size: 0.8rem;
}
.footer strong { color: var(--blue); font-weight: 700; }

/* Responsive */
@media (max-width: 768px) {
  .main { padding: 1rem; }
  .header { padding: 1rem; }
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
  .chart-label { width: 100px; font-size: 0.7rem; }
}
@media (max-width: 480px) {
  .stats-grid { grid-template-columns: 1fr; }
}

/* Tab navigation */
.tabs {
  display: flex;
  gap: 0;
  border-bottom: 2px solid var(--gray-200);
  margin-bottom: 1.5rem;
}
.tab {
  padding: 0.75rem 1.25rem;
  font-size: 0.85rem;
  font-weight: 500;
  color: var(--gray-500);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
  transition: all 0.15s ease;
}
.tab:hover { color: var(--gray-700); }
.tab.active { color: var(--blue); border-bottom-color: var(--blue); }
.tab-content { display: none; }
.tab-content.active { display: block; }

/* Detail modal */
.detail-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.5);
  z-index: 999;
  justify-content: center;
  align-items: center;
  padding: 2rem;
}
.detail-overlay.open { display: flex; }
.detail-panel {
  background: white;
  border-radius: var(--radius);
  box-shadow: var(--shadow-lg);
  max-width: 700px;
  width: 100%;
  max-height: 80vh;
  overflow-y: auto;
  padding: 1.5rem;
}
.detail-panel h3 { margin-bottom: 1rem; }
.detail-row {
  display: flex;
  justify-content: space-between;
  padding: 0.4rem 0;
  border-bottom: 1px solid var(--gray-100);
  font-size: 0.85rem;
}
.detail-row .label { color: var(--gray-500); }
.detail-row .val { font-weight: 500; text-align: right; }
.close-btn {
  position: absolute;
  top: 1rem;
  right: 1rem;
  background: none;
  border: none;
  font-size: 1.5rem;
  cursor: pointer;
  color: var(--gray-400);
}
</style>
</head>
<body>

<div class="header">
  <div class="header-inner">
    <div>
      <div class="logo">B&B AI <span>— Agente Contable Inteligente</span></div>
    </div>
    <div class="header-badge">DEMO — Procesamiento CFDI</div>
  </div>
</div>

<div class="main">
  <!-- Stats -->
  <div class="stats-grid">
    <div class="stat-card" id="stat-total">
      <h3>Facturas Procesadas</h3>
      <div class="value" id="val-total">0</div>
    </div>
    <div class="stat-card green" id="stat-validas">
      <h3>Válidas</h3>
      <div class="value green" id="val-validas">0</div>
    </div>
    <div class="stat-card amber" id="stat-anomalias">
      <h3>Anomalías Detectadas</h3>
      <div class="value amber" id="val-anomalias">0</div>
    </div>
    <div class="stat-card" id="stat-monto">
      <h3>Monto Total</h3>
      <div class="value" id="val-monto">$0.00</div>
    </div>
  </div>

  <!-- Tabs -->
  <div class="tabs">
    <div class="tab active" data-tab="dashboard">📊 Dashboard</div>
    <div class="tab" data-tab="upload">📤 Subir CFDI</div>
    <div class="tab" data-tab="results">📋 Resultados</div>
  </div>

  <!-- Tab: Dashboard -->
  <div class="tab-content active" id="tab-dashboard">
    <div class="section">
      <div class="section-title">⚡ Acciones Rápidas</div>
      <div style="display:flex;gap:0.75rem;flex-wrap:wrap;">
        <button class="btn btn-primary" onclick="processAll()" id="btn-process-all">
          🔄 Procesar los 10 CFDI de Demo
        </button>
        <button class="btn btn-secondary" onclick="loadResults()">📋 Ver Resultados</button>
        <button class="btn btn-secondary" onclick="refreshStatus()">🔄 Actualizar Status</button>
      </div>
      <div class="progress-bar" id="progress-bar" style="display:none;">
        <div class="progress-fill" id="progress-fill" style="width:0%"></div>
      </div>
    </div>

    <!-- Category chart -->
    <div class="section" id="chart-section" style="display:none;">
      <div class="section-title">📊 Distribución por Categoría</div>
      <div id="chart-container"></div>
    </div>
  </div>

  <!-- Tab: Upload -->
  <div class="tab-content" id="tab-upload">
    <div class="section">
      <div class="section-title">📤 Subir CFDI XML</div>
      <div class="upload-area" id="upload-area" onclick="document.getElementById('file-input').click()">
        <div class="icon">📄</div>
        <p><strong>Arrastra un archivo XML aquí</strong> o haz clic para seleccionar</p>
        <p style="margin-top:0.25rem;font-size:0.8rem;color:var(--gray-400);">CFDI 4.0 — Formato estándar del SAT</p>
      </div>
      <input type="file" id="file-input" accept=".xml" style="display:none" onchange="uploadFile(this.files[0])">
      <div id="upload-result" style="margin-top:1rem;"></div>
    </div>
  </div>

  <!-- Tab: Results -->
  <div class="tab-content" id="tab-results">
    <div class="section">
      <div class="section-title">📋 Facturas Procesadas</div>
      <div class="table-wrap" id="results-table-wrap">
        <div class="empty-state">
          <div class="icon">📭</div>
          <p>No hay resultados aún. Procesa los CFDI de demo o sube un archivo.</p>
        </div>
      </div>
    </div>

    <div class="section" id="anomalies-section" style="display:none;">
      <div class="section-title">🚨 Anomalías Detectadas</div>
      <div id="anomalies-container"></div>
    </div>
  </div>
</div>

<!-- Detail overlay -->
<div class="detail-overlay" id="detail-overlay" onclick="if(event.target===this)closeDetail()">
  <div class="detail-panel" id="detail-panel"></div>
</div>

<!-- Toast -->
<div class="toast" id="toast"></div>

<div class="footer">
  <strong>B&B AI</strong> — Agente contable inteligente para despachos mexicanos.<br>
  Los resultados son informativos y no constituyen asesoría fiscal.
</div>

<script>
// ---- State ----
let allResults = [];

// ---- Tabs ----
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
  });
});

// ---- Toast ----
function showToast(msg, duration=3000) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), duration);
}

// ---- Format helpers ----
function fmtMonto(val) {
  const n = parseFloat(String(val).replace(/,/g, ''));
  if (isNaN(n)) return '$0.00';
  return '$' + n.toLocaleString('es-MX', {minimumFractionDigits: 2, maximumFractionDigits: 2});
}

const CAT_COLORS = {
  'GASTO OPERATIVO': '#16A34A',
  'ACTIVO FIJO': '#D97706',
  'NOMINA': '#2563EB',
  'INVERSION': '#7C3AED',
  'DESCONOCIDO': '#6B7280',
};

// ---- Process All ----
async function processAll() {
  const btn = document.getElementById('btn-process-all');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Procesando...';
  document.getElementById('progress-bar').style.display = 'block';

  // Animate progress
  let progress = 0;
  const iv = setInterval(() => {
    progress = Math.min(progress + 5, 90);
    document.getElementById('progress-fill').style.width = progress + '%';
  }, 200);

  try {
    const resp = await fetch('/api/demo/process-all');
    const data = await resp.json();
    clearInterval(iv);
    document.getElementById('progress-fill').style.width = '100%';

    allResults = data.results || [];
    updateStats(data);
    renderResultsTable();
    renderAnomalies();
    renderChart(data.summary.por_categoria || {});
    showToast(`✅ ${data.processed} facturas procesadas en ${data.elapsed_seconds}s`);

    // Switch to results tab
    document.querySelector('[data-tab="results"]').click();
  } catch (err) {
    clearInterval(iv);
    showToast('❌ Error: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '🔄 Procesar los 10 CFDI de Demo';
    setTimeout(() => {
      document.getElementById('progress-bar').style.display = 'none';
      document.getElementById('progress-fill').style.width = '0%';
    }, 1000);
  }
}

// ---- Upload ----
const uploadArea = document.getElementById('upload-area');
uploadArea.addEventListener('dragover', e => { e.preventDefault(); uploadArea.classList.add('dragover'); });
uploadArea.addEventListener('dragleave', () => uploadArea.classList.remove('dragover'));
uploadArea.addEventListener('drop', e => {
  e.preventDefault();
  uploadArea.classList.remove('dragover');
  if (e.dataTransfer.files.length) uploadFile(e.dataTransfer.files[0]);
});

async function uploadFile(file) {
  if (!file) return;
  const resultDiv = document.getElementById('upload-result');
  resultDiv.innerHTML = '<p style="color:var(--gray-500);">⏳ Procesando ' + file.name + '...</p>';

  const formData = new FormData();
  formData.append('file', file);

  try {
    const resp = await fetch('/api/demo/upload', { method: 'POST', body: formData });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || 'Error desconocido');
    }
    const result = await resp.json();
    allResults.push(result);
    updateStatsFromResults();
    renderResultsTable();
    renderAnomalies();

    const hasAnomaly = (result.anomalias || []).length > 0;
    resultDiv.innerHTML = `
      <div style="padding:1rem;background:${hasAnomaly ? 'var(--amber-light)' : 'var(--green-light)'};border-radius:8px;">
        <strong>${hasAnomaly ? '⚠️' : '✅'} ${file.name} procesado</strong>
        <div style="font-size:0.85rem;margin-top:0.25rem;color:var(--gray-600);">
          Categoría: <strong>${result.clasificacion.categoria}</strong> |
          Confianza: ${(result.clasificacion.confianza * 100).toFixed(0)}% |
          Total: ${fmtMonto(result.datos.total)}
          ${hasAnomaly ? '| <span style="color:var(--red);">⚠ ' + result.anomalias.length + ' anomalía(s)</span>' : ''}
        </div>
      </div>`;
    showToast('✅ ' + file.name + ' procesado correctamente');
  } catch (err) {
    resultDiv.innerHTML = `<div style="padding:1rem;background:var(--red-light);border-radius:8px;">
      <strong>❌ Error:</strong> ${err.message}</div>`;
    showToast('❌ Error: ' + err.message);
  }
}

// ---- Refresh Status ----
async function refreshStatus() {
  try {
    const resp = await fetch('/api/demo/status');
    const data = await resp.json();
    document.getElementById('val-total').textContent = data.total_processed;
    document.getElementById('val-anomalias').textContent = data.total_anomalies;
    showToast('🔄 Status actualizado');
  } catch (err) {
    showToast('❌ Error al obtener status');
  }
}

// ---- Load Results ----
async function loadResults() {
  try {
    const resp = await fetch('/api/demo/results');
    const data = await resp.json();
    allResults = data.results || [];
    updateStatsFromResults();
    renderResultsTable();
    renderAnomalies();
    document.querySelector('[data-tab="results"]').click();
  } catch (err) {
    showToast('❌ Error al cargar resultados');
  }
}

// ---- Update stats ----
function updateStats(data) {
  const results = data.results || [];
  let validas = 0, totalMonto = 0, totalAnom = 0;
  results.forEach(r => {
    if (r.datos && r.datos.total) {
      totalMonto += parseFloat(String(r.datos.total).replace(/,/g, '')) || 0;
    }
    if (r.clasificacion && r.clasificacion.requires_human_review === false) validas++;
    totalAnom += (r.anomalias || []).length;
  });
  document.getElementById('val-total').textContent = results.length;
  document.getElementById('val-validas').textContent = validas;
  document.getElementById('val-anomalias').textContent = totalAnom;
  document.getElementById('val-monto').textContent = fmtMonto(totalMonto);
}

function updateStatsFromResults() {
  let validas = 0, totalMonto = 0, totalAnom = 0;
  allResults.forEach(r => {
    if (r.datos && r.datos.total) {
      totalMonto += parseFloat(String(r.datos.total).replace(/,/g, '')) || 0;
    }
    if (r.clasificacion && r.clasificacion.requires_human_review === false) validas++;
    totalAnom += (r.anomalias || []).length;
  });
  document.getElementById('val-total').textContent = allResults.length;
  document.getElementById('val-validas').textContent = validas;
  document.getElementById('val-anomalias').textContent = totalAnom;
  document.getElementById('val-monto').textContent = fmtMonto(totalMonto);
}

// ---- Render table ----
function renderResultsTable() {
  const wrap = document.getElementById('results-table-wrap');
  if (!allResults.length) {
    wrap.innerHTML = '<div class="empty-state"><div class="icon">📭</div><p>No hay resultados aún.</p></div>';
    return;
  }

  let html = '<table><thead><tr>';
  html += '<th>#</th><th>Archivo</th><th>Emisor</th><th>Fecha</th><th>Total</th><th>Categoría</th><th>Confianza</th><th>Estado</th><th></th>';
  html += '</tr></thead><tbody>';

  allResults.forEach((r, i) => {
    const d = r.datos || {};
    const c = r.clasificacion || {};
    const anomalies = r.anomalias || [];
    const hasAnomaly = anomalies.length > 0;
    const maxSev = anomalies.reduce((max, a) => {
      const rank = {'low':0,'medium':1,'high':2,'critical':3};
      return (rank[a.severity]||0) > (rank[max]||0) ? a.severity : max;
    }, 'low');

    const rowStyle = hasAnomaly ? 'background:var(--red-light);' : '';
    const badge = hasAnomaly
      ? `<span class="badge badge-error">${maxSev.toUpperCase()}</span>`
      : '<span class="badge badge-ok">OK</span>';
    const confPct = ((c.confianza || 0) * 100).toFixed(0);
    const confClass = (c.confianza || 0) < 0.7 ? 'badge-warn' : 'badge-ok';

    html += `<tr style="${rowStyle}">
      <td>${i+1}</td>
      <td><strong>${(r.archivo||'').substring(0,25)}</strong></td>
      <td>${(d.emisor_nombre||d.emisor_rfc||'?').substring(0,30)}</td>
      <td>${(d.fecha||'?').substring(0,10)}</td>
      <td class="monto">${fmtMonto(d.total)}</td>
      <td><span class="badge badge-info">${CAT_COLORS[c.categoria] ? c.categoria : (c.categoria||'?')}</span></td>
      <td><span class="badge ${confClass}">${confPct}%</span></td>
      <td>${badge}</td>
      <td><button class="btn btn-sm btn-secondary" onclick="showDetail(${i})">Ver</button></td>
    </tr>`;
  });

  html += '</tbody></table>';
  wrap.innerHTML = html;
}

// ---- Render anomalies ----
function renderAnomalies() {
  const container = document.getElementById('anomalies-container');
  const section = document.getElementById('anomalies-section');
  const allAnomalies = [];

  allResults.forEach(r => {
    (r.anomalias || []).forEach(a => {
      allAnomalies.push({...a, archivo: r.archivo});
    });
  });

  if (!allAnomalies.length) {
    section.style.display = 'none';
    return;
  }

  section.style.display = 'block';
  let html = '';
  allAnomalies.forEach(a => {
    const sevClass = a.severity || 'low';
    const det = a.detalle || {};
    const detStr = Object.entries(det).map(([k,v]) => `${k}: ${v}`).join(' | ');
    html += `<div class="anomaly-card ${sevClass}">
      <div class="anomaly-header">
        <span class="anomaly-type">${(a.tipo||'?').replace(/_/g,' ')}</span>
        <span class="badge badge-${sevClass === 'high' || sevClass === 'critical' ? 'error' : sevClass === 'medium' ? 'warn' : 'info'}">${(a.severity||'').toUpperCase()}</span>
      </div>
      <div class="anomaly-desc">${a.descripcion||''}</div>
      <div class="anomaly-detail"><strong>Detalle:</strong> ${detStr}</div>
      ${a.referencia_legal ? '<div class="anomaly-legal">📋 ' + a.referencia_legal + '</div>' : ''}
      <div class="anomaly-detail"><strong>Factura:</strong> ${a.archivo||''}</div>
    </div>`;
  });
  container.innerHTML = html;
}

// ---- Render chart ----
function renderChart(cats) {
  const section = document.getElementById('chart-section');
  const container = document.getElementById('chart-container');
  if (!Object.keys(cats).length) { section.style.display = 'none'; return; }
  section.style.display = 'block';

  const maxCount = Math.max(...Object.values(cats));
  let html = '';
  Object.entries(cats).sort((a,b) => b[1]-a[1]).forEach(([cat, count]) => {
    const pct = (count / maxCount) * 100;
    const color = CAT_COLORS[cat] || '#6B7280';
    html += `<div class="chart-row">
      <span class="chart-label">${cat}</span>
      <div class="chart-bar-bg">
        <div class="chart-bar" style="width:${pct}%;background:${color};"></div>
      </div>
      <span class="chart-count">${count}</span>
    </div>`;
  });
  container.innerHTML = html;
}

// ---- Detail modal ----
function showDetail(idx) {
  const r = allResults[idx];
  if (!r) return;
  const d = r.datos || {};
  const c = r.clasificacion || {};
  const panel = document.getElementById('detail-panel');

  let conceptsHtml = '';
  (d.conceptos || []).forEach((c2, i) => {
    conceptsHtml += `<div class="detail-row">
      <span class="label">Concepto ${i+1}</span>
      <span class="val">${c2.descripcion||''}</span>
    </div>`;
  });

  panel.innerHTML = `
    <h3 style="display:flex;justify-content:space-between;align-items:center;">
      📄 ${r.archivo || 'CFDI'}
      <button class="btn btn-sm btn-secondary" onclick="closeDetail()">✕ Cerrar</button>
    </h3>
    <div style="margin-bottom:1rem;">
      <div class="detail-row"><span class="label">Versión</span><span class="val">${d.version||'?'}</span></div>
      <div class="detail-row"><span class="label">Tipo</span><span class="val">${d.tipo||'?'}</span></div>
      <div class="detail-row"><span class="label">Serie / Folio</span><span class="val">${d.serie||''} ${d.folio||''}</span></div>
      <div class="detail-row"><span class="label">Fecha</span><span class="val">${d.fecha||'?'}</span></div>
      <div class="detail-row"><span class="label">Folio Fiscal</span><span class="val" style="font-size:0.75rem;">${d.folio_fiscal||'?'}</span></div>
    </div>
    <div style="margin-bottom:1rem;">
      <div class="detail-row"><span class="label">Emisor RFC</span><span class="val">${d.emisor_rfc||'?'}</span></div>
      <div class="detail-row"><span class="label">Emisor</span><span class="val">${d.emisor_nombre||'?'}</span></div>
      <div class="detail-row"><span class="label">Régimen Fiscal</span><span class="val">${d.emisor_regimen||'?'}</span></div>
      <div class="detail-row"><span class="label">Receptor RFC</span><span class="val">${d.receptor_rfc||'?'}</span></div>
      <div class="detail-row"><span class="label">Receptor</span><span class="val">${d.receptor_nombre||'?'}</span></div>
    </div>
    <div style="margin-bottom:1rem;">
      <div class="detail-row"><span class="label">Subtotal</span><span class="val monto">${fmtMonto(d.subtotal)}</span></div>
      <div class="detail-row"><span class="label">IVA</span><span class="val monto">${fmtMonto(d.iva)}</span></div>
      <div class="detail-row"><span class="label">Total</span><span class="val monto" style="font-size:1.1rem;font-weight:700;color:var(--blue);">${fmtMonto(d.total)}</span></div>
    </div>
    <div style="margin-bottom:1rem;">
      <div class="detail-row"><span class="label">Categoría</span><span class="val"><span class="badge badge-info">${c.categoria||'?'}</span></span></div>
      <div class="detail-row"><span class="label">Confianza</span><span class="val">${((c.confianza||0)*100).toFixed(0)}%</span></div>
      <div class="detail-row"><span class="label">Razón</span><span class="val" style="max-width:300px;text-align:right;">${c.razon||'?'}</span></div>
      <div class="detail-row"><span class="label">Revisión humana</span><span class="val">${c.requires_human_review ? '⚠️ Sí' : '✅ No'}</span></div>
    </div>
    ${conceptsHtml ? '<div style="margin-bottom:1rem;"><strong style="font-size:0.85rem;">Conceptos:</strong>' + conceptsHtml + '</div>' : ''}
    ${(r.anomalias||[]).length ? '<div style="margin-top:1rem;"><strong style="font-size:0.85rem;color:var(--red);">🚨 Anomalías:</strong></div>' +
      r.anomalias.map(a => `<div class="anomaly-card ${a.severity}" style="margin-top:0.5rem;">
        <div class="anomaly-header">
          <span class="anomaly-type">${(a.tipo||'').replace(/_/g,' ')}</span>
          <span class="badge badge-${a.severity==='high'||a.severity==='critical'?'error':'warn'}">${(a.severity||'').toUpperCase()}</span>
        </div>
        <div class="anomaly-desc">${a.descripcion||''}</div>
        ${a.referencia_legal ? '<div class="anomaly-legal">📋 ' + a.referencia_legal + '</div>' : ''}
      </div>`).join('') : '<p style="color:var(--gray-400);margin-top:1rem;">✅ Sin anomalías detectadas</p>'}
  `;

  document.getElementById('detail-overlay').classList.add('open');
}

function closeDetail() {
  document.getElementById('detail-overlay').classList.remove('open');
}

// ESC to close detail
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDetail(); });
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serves the beautiful HTML dashboard."""
    return DASHBOARD_HTML


# ===========================================================================
# Main
# ===========================================================================

if __name__ == "__main__":
    print("\n  🚀 B&B AI — Demo Server")
    print("  " + "=" * 40)
    print(f"  📂 Demo data: {DEMO_DATA_DIR}")
    print(f"  🌐 Dashboard: http://localhost:8080")
    print(f"  📡 API docs:  http://localhost:8080/docs")
    print("  " + "=" * 40 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
