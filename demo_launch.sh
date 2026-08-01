#!/usr/bin/env bash
# ============================================================================
# demo_launch.sh — One-Click Demo Launch for B&B AI Sales Presentations
#
# This script:
#   1. Activates the virtual environment
#   2. Generates realistic mock data (50 clients, 500 CFDIs/month)
#   3. Generates a sample PDF report with ROI metrics
#   4. Starts the demo server with all endpoints enabled
#   5. Opens the dashboard in the default browser
#
# Usage:
#   ./demo_launch.sh              # Full demo (data + PDF + server)
#   ./demo_launch.sh --pdf-only   # Generate PDF report only
#   ./demo_launch.sh --server-only # Start server only (skip PDF)
#   ./demo_launch.sh --port 9090  # Custom port
#   ./demo_launch.sh --no-browser # Don't auto-open browser
#   ./demo_launch.sh --month 2026-08  # Generate for specific month
# ============================================================================
set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Defaults
PORT="${PORT:-8080}"
MONTH="2026-07"
OPEN_BROWSER=true
PDF_ONLY=false
SERVER_ONLY=false
DIR="$(cd "$(dirname "$0")" && pwd)"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --pdf-only) PDF_ONLY=true; shift ;;
        --server-only) SERVER_ONLY=true; shift ;;
        --port) PORT="$2"; shift 2 ;;
        --no-browser) OPEN_BROWSER=false; shift ;;
        --month) MONTH="$2"; shift 2 ;;
        --help|-h)
            echo ""
            echo "  B&B AI — One-Click Demo Launcher"
            echo "  ================================="
            echo ""
            echo "  Usage: ./demo_launch.sh [OPTIONS]"
            echo ""
            echo "  Options:"
            echo "    --pdf-only       Generate PDF report only, no server"
            echo "    --server-only    Start server only, skip PDF generation"
            echo "    --port PORT      Server port (default: 8080)"
            echo "    --month YYYY-MM  Month for data generation (default: 2026-07)"
            echo "    --no-browser     Don't auto-open browser"
            echo "    --help           Show this help"
            echo ""
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Find Python
PYTHON=""
if [ -f "$DIR/.venv/bin/python3" ]; then
    PYTHON="$DIR/.venv/bin/python3"
elif command -v python3 &>/dev/null; then
    PYTHON="$(command -v python3)"
elif command -v python &>/dev/null; then
    PYTHON="$(command -v python)"
else
    echo -e "  ${RED}❌ Error: Python not found in PATH${NC}"
    exit 1
fi

echo ""
echo -e "  ${BOLD}${BLUE}╔══════════════════════════════════════════════════╗${NC}"
echo -e "  ${BOLD}${BLUE}║         B&B AI — Demo Completo de Ventas         ║${NC}"
echo -e "  ${BOLD}${BLUE}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${CYAN}🐍 Python:${NC}    $PYTHON"
echo -e "  ${CYAN}📂 Directorio:${NC} $DIR"
echo -e "  ${CYAN}📅 Periodo:${NC}    $MONTH"
echo -e "  ${CYAN}🌐 Puerto:${NC}     $PORT"
echo ""

cd "$DIR"

# --------------------------------------------------------------------------
# Step 1: Generate mock data and PDF report
# --------------------------------------------------------------------------
if [ "$SERVER_ONLY" = false ]; then
    echo -e "  ${BOLD}Paso 1/3:${NC} Generando datos realistas de firma contable..."
    echo -e "            (50 clientes, ~500 CFDIs, anomalías, métricas ROI)"
    echo ""

    $PYTHON -c "
import sys, os
sys.path.insert(0, '$DIR')

print('  📊 Generando datos de firma contable demo...')
from b2b_ai.demo.firm_generator import generate_demo_firm, build_executive_summary
data = generate_demo_firm(month='$MONTH', seed=42)
print(f'     ✓ {len(data[\"clients\"])} clientes generados')
print(f'     ✓ {len(data[\"cfdis\"])} CFDIs generados')
print(f'     ✓ {len(data[\"anomalies\"])} anomalías inyectadas')
print(f'     ✓ {len(data[\"nominas\"])} nóminas generadas')
print()

if '$PDF_ONLY' == 'true' or True:
    print('  📄 Generando reporte PDF con métricas de ROI...')
    from b2b_ai.demo.report_pdf import generate_roi_report
    output_dir = os.path.join('$DIR', 'demo-output')
    os.makedirs(output_dir, exist_ok=True)
    pdf_path = generate_roi_report(data, output_dir)
    print(f'     ✓ Reporte PDF: {pdf_path}')
    print()

    # Also save JSON summary for the server
    import json
    summary = build_executive_summary(data)
    json_path = os.path.join(output_dir, 'demo-summary.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump({
            'firm': data['firm'],
            'roi_metrics': data['roi_metrics'],
            'summary': summary,
            'client_count': len(data['clients']),
            'cfdi_count': len(data['cfdis']),
            'anomaly_count': len(data['anomalies']),
        }, f, ensure_ascii=False, indent=2)
    print(f'     ✓ Datos JSON: {json_path}')
    print()
    print(f'  ✅ Datos y reporte generados exitosamente')
"
    echo ""

    if [ "$PDF_ONLY" = true ]; then
        echo -e "  ${BOLD}${GREEN}╔══════════════════════════════════════════════════╗${NC}"
        echo -e "  ${BOLD}${GREEN}║  ✅ Reporte PDF generado exitosamente             ║${NC}"
        echo -e "  ${BOLD}${GREEN}╚══════════════════════════════════════════════════╝${NC}"
        echo ""
        echo -e "  📄 PDF: $DIR/demo-output/B&B_AI_Reporte_ROI_Demo.pdf"
        echo -e "  📊 JSON: $DIR/demo-output/demo-summary.json"
        echo ""
        # Open PDF
        if command -v open &>/dev/null; then
            open "$DIR/demo-output/B&B_AI_Reporte_ROI_Demo.pdf"
        fi
        exit 0
    fi
fi

# --------------------------------------------------------------------------
# Step 2: Generate demo CFDI XMLs for the server
# --------------------------------------------------------------------------
if [ "$SERVER_ONLY" = true ]; then
    echo -e "  ${BOLD}Paso 2/3:${NC} Preparando datos de demo para el servidor..."
    $PYTHON -c "
import sys, os
sys.path.insert(0, '$DIR')
os.makedirs('$DIR/demo-data', exist_ok=True)
from b2b_ai.services.demo import generate_sample_xmls
xmls = generate_sample_xmls('$DIR/demo-data')
print(f'  ✓ {len(xmls)} XMLs de demo listos')
"
    echo ""
fi

# --------------------------------------------------------------------------
# Step 3: Start the demo server
# --------------------------------------------------------------------------
echo -e "  ${BOLD}Paso 3/3:${NC} Iniciando servidor demo..."
echo ""
echo -e "  ${BOLD}${GREEN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "  ${BOLD}${GREEN}║          🚀 Demo Server Listo para Venta         ║${NC}"
echo -e "  ${BOLD}${GREEN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}🌐 Dashboard:${NC}    http://localhost:$PORT"
echo -e "  ${BOLD}📡 API Docs:${NC}     http://localhost:$PORT/docs"
echo -e "  ${BOLD}📊 Demo API:${NC}     http://localhost:$PORT/api/demo/health"
echo -e "  ${BOLD}📄 ROI Report:${NC}   $DIR/demo-output/B&B_AI_Reporte_ROI_Demo.pdf"
echo ""
echo -e "  ${YELLOW}💡 Tips para la venta:${NC}"
echo -e "     • Abre el dashboard para mostrar la UI"
echo -e "     • Usa /api/demo/process-all para demostrar procesamiento"
echo -e "     • Muestra el PDF de ROI para justificar la inversión"
echo -e "     • Los endpoints /api/demo/invoices y /analytics muestran datos"
echo ""
echo -e "  ${BOLD}Presiona Ctrl+C para detener el servidor.${NC}"
echo ""

# Open browser (if available and not disabled)
if [ "$OPEN_BROWSER" = true ]; then
    (sleep 2 && (open "http://localhost:$PORT" 2>/dev/null || true)) &
fi

# Start server
exec "$PYTHON" -c "
import uvicorn, sys, os
sys.path.insert(0, '$DIR')
os.environ['DEMO_MODE'] = 'true'
from demo_server import app
uvicorn.run(app, host='0.0.0.0', port=$PORT, log_level='info')
"
