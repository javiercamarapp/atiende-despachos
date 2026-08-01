# syntax=docker/dockerfile:1
# =============================================================================
# B&B AI — Agente contable IA enterprise
# Imagen de la API FastAPI (servida por uvicorn) en build multi-stage.
#
# Build:
#   docker build -t b2b-ai:1.0.0 .
# Run (single container):
#   docker run --rm -p 8000:8000 \
#     -e B2B_API_KEY=$(openssl rand -hex 32) \
#     -v b2b-data:/data \
#     b2b-ai:1.0.0
# En producción se orquesta con docker-compose.prod.yml (api+postgres+redis+nginx).
# =============================================================================

# ---- Stage 1: builder — instala dependencias + empaqueta en un prefix ----
# Base de imagen fija para builds reproducibles.
FROM python:3.11-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

# Instalar dependencias del sistema mínimas que algunas wheels compiladas
# puedan necesitar (psycopg2-binary / lxml traen sus binaries: no requiere
# compilación; se mantiene para futuras dependencias).
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Primero el manifiesto de dependencias → capa cacheable por separado.
# (El código cambia mucho más a menudo que pyproject.toml.)
COPY pyproject.toml README.md ./
COPY b2b_ai ./b2b_ai
COPY landing ./landing

# Instala en /install (prefix) para copiar solo lo necesario al runtime.
# NOTA: se usa pip install directo (sin --mount=type=cache de BuildKit) para
# que el Dockerfile funcione con el builder legacy y con BuildKit por igual.
RUN pip install --prefix=/install --no-cache-dir . \
    && pip install --prefix=/install --no-cache-dir "uvicorn[standard]>=0.20"

# ---- Stage 2: runtime — solo lo necesario para servir ----
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    B2B_DB_PATH=/data/b2b_ai.db \
    B2B_API_KEY="" \
    B2B_WORKERS=1 \
    B2B_HOST=0.0.0.0 \
    B2B_PORT=8000

WORKDIR /app

# Etiquetas de trazabilidad de la imagen.
LABEL org.opencontainers.image.title="b2b-ai" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.description="Agente contable IA enterprise (B&B AI)"

# Copia solo el prefix instalado + la landing estática (no el builder completo).
COPY --from=builder /install /usr/local
COPY --from=builder /build/landing /app/landing

# Herramienta mínima para el healthcheck sin traer toda la app.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Directorio de datos persistente (montar como volumen).
RUN mkdir -p /data

# No corre como root (buena práctica en contenedores).
RUN useradd --create-home --uid 1000 b2b \
    && chown -R b2b:b2b /data /app
USER b2b

EXPOSE 8000

# Healthcheck del API vía curl (más robusto que urllib para stack).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# Workers configurables vía B2B_WORKERS. En producción detrás de Nginx se
# recomienda B2B_WORKERS=$(nproc). El contenedor con SQLite debe correr con 1
# worker (concurrencia de escritura); el backend Postgres (en desarrollo) puede
# escalar a N.
CMD ["sh", "-c", "uvicorn b2b_ai.api.app:app --host ${B2B_HOST} --port ${B2B_PORT} --workers ${B2B_WORKERS} --proxy-headers"]
