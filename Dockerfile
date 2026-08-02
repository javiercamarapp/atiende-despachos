# syntax=docker/dockerfile:1
# =============================================================================
# Likida AI — Agente contable IA enterprise
# Imagen de la API FastAPI (servida por uvicorn) en build multi-stage.
# =============================================================================

# ---- Stage 1: builder ----
FROM python:3.11-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY b2b_ai ./b2b_ai
COPY landing ./landing

RUN pip install --prefix=/install --no-cache-dir . \
    && pip install --prefix=/install --no-cache-dir "uvicorn[standard]>=0.20" \
    && pip install --prefix=/install --no-cache-dir playwright

# Download Chromium (no --with-deps to avoid GPG issues)
RUN PYTHONPATH=/install/lib/python3.11/site-packages \
    python -m playwright install chromium

# ---- Stage 2: runtime ----
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    B2B_DB_PATH=/data/b2b_ai.db \
    B2B_API_KEY="" \
    B2B_WORKERS=1 \
    B2B_HOST=0.0.0.0 \
    B2B_PORT=8000 \
    PORT=8000 \
    PLAYWRIGHT_BROWSERS_PATH=/home/b2b/.cache/ms-playwright

WORKDIR /app

LABEL org.opencontainers.image.title="b2b-ai" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.description="Agente contable IA enterprise (Likida AI)"

COPY --from=builder /install /usr/local
COPY --from=builder /build/landing /app/landing
COPY --from=builder /root/.cache/ms-playwright /home/b2b/.cache/ms-playwright

# Install Chromium system deps + curl in one layer
# Use --allow-unauthenticated to bypass GPG key issues on Railway builder
RUN apt-get update --allow-insecure-repositories \
    && apt-get install -y --allow-unauthenticated --no-install-recommends \
       libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
       libcups2 libdrm2 libdbus-1-3 libxkbcommon0 \
       libatspi2.0-0 libxcomposite1 libxdamage1 libxfixes3 \
       libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
       libwayland-client0 xvfb curl \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /data
RUN useradd --create-home --uid 1000 b2b \
    && chown -R b2b:b2b /data /app /home/b2b/.cache
USER b2b

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["sh", "-c", "uvicorn b2b_ai.api.app:app --host ${B2B_HOST} --port ${PORT:-${B2B_PORT}} --workers ${B2B_WORKERS} --proxy-headers"]
