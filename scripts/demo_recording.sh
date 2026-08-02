#!/usr/bin/env bash
# demo_recording.sh — Graba la demo de Likida AI Enterprise como salida de
# terminal + transcripción Markdown (+ capturas de pantalla en macOS).
#
# Uso:
#   bash scripts/demo_recording.sh                 # salida a scripts/demo_output/
#   bash scripts/demo_recording.sh /tmp/demo_out   # carpeta de salida custom
#
# Genera:
#   TRANSCRIPCION.md   — la salida formateada como Markdown (bloque de código)
#   salida_raw.txt     — la salida cruda del terminal (con ANSI)
#   capturas/*.png     — screenshots de la terminal (macOS, best-effort)
set -euo pipefail

# ── Resolución de rutas ──────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="${PYTHON:-$REPO_ROOT/.venv/bin/python}"

OUT_DIR="${1:-$SCRIPT_DIR/demo_output}"
mkdir -p "$OUT_DIR/capturas"

RAW="$OUT_DIR/salida_raw.txt"
MD="$OUT_DIR/TRANSCRIPCION.md"

echo "── Likida AI — grabación de demo ─────────────────────────────"
echo "  Output : $OUT_DIR"
echo "  Python : $PYTHON"
echo ""

# ── 1. Grabar la demo (captura el TTY, conserva ANSI) ───────────────────────
echo "▶ Ejecutando demo_pilot.py (captura de terminal)…"
START=$(date +%s)

if command -v script >/dev/null 2>&1; then
  # macOS/Linux: `script` captura la salida del TTY.
  script -q "$RAW" "$PYTHON" "$SCRIPT_DIR/demo_pilot.py" --db "$SCRIPT_DIR/demo_data/demo_pilot_rec.db" \
    >/dev/null 2>&1 || true
else
  # Fallback: redirección directa.
  "$PYTHON" "$SCRIPT_DIR/demo_pilot.py" --db "$SCRIPT_DIR/demo_data/demo_pilot_rec.db" > "$RAW" 2>&1 || true
fi

END=$(date +%s)
echo "  Demo terminada en $((END - START))s."

# ── 2. Limpiar ANSI para la transcripción ────────────────────────────────────
echo "▶ Generando TRANSCRIPCION.md …"
{
  echo "# Transcripción de la demo — Likida AI Enterprise"
  echo ""
  echo "Fecha : $(date '+%Y-%m-%d %H:%M')"
  echo "Comando: \`$PYTHON $SCRIPT_DIR/demo_pilot.py\`"
  echo ""
  echo "## Salida"
  echo ""
  echo '```text'
  # Elimina secuencias ANSI y CR, conserva el texto legible.
  sed -e 's/\x1b\[[0-9;]*[a-zA-Z]//g' \
      -e 's/\r//g' \
      "$RAW" 2>/dev/null | grep -v '^{"ts":' || true
  echo '```'
} > "$MD"
echo "  Transcripción: $MD"

# ── 3. Captura de pantalla (macOS, best-effort) ─────────────────────────────
if command -v screencapture >/dev/null 2>&1; then
  echo "▶ Captura de pantalla (macOS)…"
  SHOT="$OUT_DIR/capturas/terminal_$(date +%H%M%S).png"
  if screencapture -x "$SHOT" 2>/dev/null; then
    echo "  Captura: $SHOT"
  else
    echo "  ⚠ No se pudo capturar la pantalla (¿permisos de Grabación de pantalla?)."
  fi
else
  echo "  ℹ screencapture no disponible (solo macOS). Se omite la captura."
fi

echo ""
echo "✅ Grabación completada."
echo "   Transcripción : $MD"
echo "   Salida cruda   : $RAW"
