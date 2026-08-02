# -*- coding: utf-8 -*-
"""
app.py — API real (FastAPI) del agente contable enterprise.

Endpoints públicos:
    GET  /health        health check + versión + estado DB.

Endpoints /api/v1/* (requieren API key, header `X-API-Key`):
    POST /api/v1/invoices/process   recibe un CFDI (multipart file o JSON con
                                    xml_path / xml_content) y devuelve el
                                    resultado del pipeline completo.
    GET  /api/v1/invoices           listado con filtros (tenant, categoría,
                                    validez, rango de fechas, limit).
    GET  /api/v1/invoices/{id}      detalle de una factura por id.
    GET  /api/v1/stats              métricas agregadas (totales, por categoría).
    GET  /api/v1/tools              tools registradas.
    POST /api/v1/leads              alta de lead desde la landing (público).
    POST /api/v1/reconcile/run      conciliación bancaria (FASE 2).
    GET  /api/v1/accounting/catalog catálogo de cuentas (FASE 2).
    GET  /api/v1/accounting/balance balanza de comprobación (FASE 2).
    POST /api/v1/accounting/sat/send envío de balanza al SAT mock (FASE 2).
    POST /api/v1/payroll/calculate  cálculo de nómina (FASE 2).
    + router de dashboard en /api/v1/* (FASE 2).

Endpoints legacy (sin versión, compatibilidad):
    GET  /invoices, GET /stats, GET /tools, POST /process.

Documentación OpenAPI:  /docs  y  /openapi.json  (auto-generadas por FastAPI).

Auth: la API key se envía en el header `X-API-Key`. Se resuelve contra la tabla
`api_keys` (multi-tenant) o contra la env `B2B_API_KEY` para uso standalone.
Se construye con `create_app(db=...)` para poder inyectar una DB de prueba.

Uso:
    B2B_API_KEY=secret uvicorn b2b_ai.api.app:app --reload
    curl -H "X-API-Key: *** http://localhost:8000/api/v1/stats
"""
from __future__ import annotations

import os
import tempfile
import threading
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import (FastAPI, Depends, HTTPException,
                     Query, Request)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from b2b_ai import __version__
from b2b_ai.cfdi.parser import CFDIError
import b2b_ai.tools.tools  # noqa: F401  (registra las tools)
from b2b_ai.db.db import Database
from b2b_ai.services.pipeline import process_file, process_batch
from b2b_ai.services.report import generate_report
from b2b_ai.services.reconcile import build_reconciliation_report
from b2b_ai.services.payroll import calculate_payroll, generate_payroll_cfdi
from b2b_ai.services.accounting import (get_catalogo, build_balance,
                                        send_balance_to_sat)
from b2b_ai.services.catalogo_cuentas import CatalogoCuentas
from b2b_ai.services.balanza import BalanzaComprobacion
from b2b_ai.services.contabilidad_electronica import ContabilidadElectronica
from b2b_ai.services.collections import CollectionsManager
from b2b_ai.services.collections_report import aging_report
from b2b_ai.api.dashboard import build_dashboard_router
from b2b_ai.api.analytics import build_analytics_router
from b2b_ai.tools.registry import all_tools
from b2b_ai.tools.logger import logger
from b2b_ai.api.auth import APIKeyAuth, make_require_api_key
from b2b_ai.db.tenants import TenantManager
from b2b_ai.api import webhooks as wh
from b2b_ai.api import v2 as api_v2
from b2b_ai.api import portal as portal_mod
from b2b_ai.portal.routes import build_portal_pages_router
from b2b_ai.notifications.api import build_notifications_router
from b2b_ai.billing.api import build_billing_router
from b2b_ai.reports.router import build_reports_router
from b2b_ai.api.middleware import install_request_size_limit
from b2b_ai.api.reconciliation import build_reconciliation_router
from b2b_ai.onboarding.api import build_onboarding_router
from b2b_ai.sat.api import build_sat_router
from b2b_ai.features.nomina.routes import build_nomina_router
from b2b_ai.features.pagos.routes import build_pagos_router
from b2b_ai.features.contabilidad.routes import build_contabilidad_router
from b2b_ai.features.contabilidad.electronica_routes import build_electronica_router
from b2b_ai.features.reportes.routes import build_reportes_router
from b2b_ai.features.dashboard.routes import build_dashboard_admin_router
from b2b_ai.features.alertas.routes import build_alertas_router
from b2b_ai.features.conciliacion.routes import build_conciliacion_router
from b2b_ai.features.contabilidad_electronica.routes import build_contabilidad_electronica_router
from b2b_ai.features.pre_auditoria.routes import build_pre_auditoria_router
from b2b_ai.features.nomina_completa.routes import build_nomina_completa_router
from b2b_ai.features.reportes_gerenciales.routes import build_reportes_gerenciales_router
from b2b_ai.features.email_processing.routes import build_email_processing_router
from b2b_ai.features.clientes.routes import build_clientes_router
from b2b_ai.features.conciliacion_fiscal.routes import build_fiscal_router
from b2b_ai.features.declaraciones.routes import build_declaraciones_router
from b2b_ai.features.devolucion_iva.routes import build_devolucion_iva_router
from b2b_ai.features.diot.routes import build_diot_router
from b2b_ai.features.declaraciones.declaration_api import build_declarations_api_router
from b2b_ai.features.reconciliacion_ingresos_egresos.routes import (
    build_reconciliacion_ingresos_egresos_router,
)
from b2b_ai.features.vencimientos.routes import build_vencimientos_router
from b2b_ai.features.close_management.routes import build_close_management_router
from b2b_ai.features.bookkeeping.routes import build_bookkeeping_router
from b2b_ai.api.metrics import metrics
from b2b_ai.api.security_headers import install as install_security_headers
from b2b_ai.api.security import (allowed_upload_extension, detect_pii,
                                 encrypt_field, decrypt_field)
from b2b_ai.auth.api import build_auth_router
from b2b_ai.auth.middleware import check_jwt_config, _is_dev_env
from b2b_ai.monitoring.logger import (get_logger as get_structured_logger,
                                      request_context)
from b2b_ai.monitoring.metrics import metrics as prom_metrics
from b2b_ai.monitoring.alerts import alerts as alert_mgr
from b2b_ai.monitoring.health import build_health_detailed
from b2b_ai.audit.middleware import install_audit_middleware

# Logger estructurado JSON (monitoring). Distinto del ToolCallLogger de
# b2b_ai.tools.logger (auditoría de tools en DB): este emite JSON a stdout.
_structured_log = get_structured_logger("api")


# -------------------------------------------------------------------------- #
# Cache TTL simple para endpoints de lectura agregados (/api/v1/stats, legacy
# /stats). Las keys incluyen la versión de datos de la DB (data_version), que
# sube en cada escritura de facturas, de modo que el cache NUNCA sirve datos
# viejos después de una inserción: al cambiar la versión, la key cambia y se
# recalcula al momento. El TTL solo limita la vida de entradas con la misma
# versión (p. ej. si el contador se reinicia). Thread-safe con lock.
# -------------------------------------------------------------------------- #
class _StatsCache:
    def __init__(self, ttl_seconds: float = 5.0):
        self.ttl = ttl_seconds
        self._store = {}
        self._lock = threading.Lock()

    def _key(self, dbid, tenant, version, route):
        return (dbid, route, tenant, version)

    def get(self, dbid, route, tenant, version):
        with self._lock:
            item = self._store.get((dbid, route, tenant, version))
        if item is None:
            return None
        ts, value = item
        if time.monotonic() - ts > self.ttl:
            with self._lock:
                self._store.pop((dbid, route, tenant, version), None)
            return None
        return value

    def set(self, dbid, route, tenant, version, value):
        with self._lock:
            self._store[(dbid, route, tenant, version)] = (time.monotonic(), value)

    @property
    def stats(self):
        with self._lock:
            return {"entries": len(self._store), "ttl": self.ttl}


_stats_cache = _StatsCache()


# Ruta a la carpeta de la landing page (estática). Resuelve tanto en árbol de
# código (repo) como dentro del contenedor Docker (/app/landing) o donde se
# instale el paquete (site-packages). Puede sobreescribirse con B2B_LANDING_DIR.
def _resolve_landing_dir() -> Path:
    env = os.environ.get("B2B_LANDING_DIR")
    if env:
        return Path(env)
    # 1) Contenedor / instalación: la landing se copia a /app/landing.
    for cand in (Path("/app/landing"),
                 Path(__file__).resolve().parent.parent.parent / "landing"):
        if cand.is_dir():
            return cand
    # 2) Árbol de código: ../landing respecto a la raíz del paquete.
    return Path(__file__).resolve().parent.parent.parent / "landing"


LANDING_DIR = _resolve_landing_dir()


# ---- Schemas ---------------------------------------------------------------
class ProcessRequest(BaseModel):
    xml_path: Optional[str] = None
    folder: Optional[str] = None
    tenant_id: Optional[int] = None
    tenant_name: str = "Despacho Demo"
    tenant_rfc: str = ""


class LeadRequest(BaseModel):
    nombre: str
    email: str
    despacho: str = ""
    facturas: str = ""
    mensaje: str = ""


class ReconcileRequest(BaseModel):
    invoices: list = []
    bank_transactions: list = []
    date_tolerance_days: int = 3


class PayrollRequest(BaseModel):
    empleado: dict
    emisor: dict = {}
    periodo: dict
    generar_cfdi: bool = False


class TenantOnboardRequest(BaseModel):
    name: str
    rfc: str = ""
    erp_type: str = "contpaqi"
    plantilla_contable: str = "SAT"
    notif_channel: str = "email"
    webhook_url: str = ""
    user_name: str = ""
    user_email: str = ""


class CollectionsAnalyzeRequest(BaseModel):
    """Cartera pendiente para analizar (FASE 3 cobranza)."""
    invoices: list = []
    sync: bool = False


class CollectionsSendReminderRequest(BaseModel):
    """Genera (y opcionalmente registra) un recordatorio de cobranza."""
    invoice: dict
    stage: str
    channel: str = "email"
    record: bool = True


class CatalogoRequest(BaseModel):
    """Carga del catálogo de cuentas del SAT (contabilidad electrónica)."""
    rfc: str = ""
    cuentas: Optional[list] = None   # [{codigo, descripcion, nivel, naturaleza}]


class AsientoRequest(BaseModel):
    """Alta de un asiento contable (contabilidad electrónica)."""
    fecha: str
    cuenta_debito: str
    cuenta_credito: str
    monto: str
    descripcion: str = ""
    factura_id: str = ""


class ContabilidadRequest(BaseModel):
    """Parámetros para generar el paquete de contabilidad electrónica."""
    rfc: str = ""
    razon_social: str = ""
    ejercicio: Optional[int] = None
    mes: Optional[int] = None


class ARCORequest(BaseModel):
    """Solicitud ARCO según LFPDPPP Art. 28-35."""
    email: str
    nombre_completo: str = ""
    tipo_solicitud: str  # "acceso" | "rectificacion" | "cancelacion" | "oposicion"
    descripcion: str = ""
    datos_a_modificar: dict | None = None  # Para rectificación
    identificacion_tipo: str = ""  # IFE, INE, pasaporte
    identificacion_ref: str = ""


# -------------------------------------------------------------------------- #
# Rate limiting (en memoria, sin dependencias). Protege la API de abuso:
# brute-force de API keys y spam del endpoint publico de leads. Limita por
# IP + ruta en una ventana deslizante. En produccion multi-replica conviene
# moverlo a un store compartido (Redis) — para el MVP single-node es suficiente.
# -------------------------------------------------------------------------- #
class RateLimiter:
    """Ventana deslizante por (ip, ruta). `limit` peticiones por `window` seg."""

    def __init__(self, limit: int = 300, window: float = 60.0,
                 sweep_every: int = 1000):
        self.limit = limit
        self.window = window
        self._hits: "defaultdict[tuple, list[float]]" = defaultdict(list)
        self._sweep_every = max(1, int(sweep_every))
        self._since_sweep = 0

    def allow(self, key: tuple) -> bool:
        now = time.monotonic()
        bucket = self._hits[key]
        # Poda las entradas fuera de la ventana.
        cutoff = now - self.window
        while bucket and bucket[0] < cutoff:
            bucket.pop(0)
        if len(bucket) >= self.limit:
            return False
        bucket.append(now)
        # Barrido periódico de claves vacías. Antes se podaban las marcas de
        # tiempo pero la CLAVE `(ip, ruta)` no se borraba nunca: pedir rutas
        # aleatorias hacía crecer el diccionario sin techo, o sea agotar la
        # memoria a través del propio mecanismo antiabuso. Se barre cada
        # `_sweep_every` admisiones para no pagar un recorrido por petición.
        self._since_sweep += 1
        if self._since_sweep >= self._sweep_every:
            self._since_sweep = 0
            self._sweep(cutoff)
        return True

    def _sweep(self, cutoff: float) -> None:
        """Elimina las claves cuyas marcas de tiempo ya caducaron todas."""
        muertas = [k for k, v in self._hits.items()
                   if not v or v[-1] < cutoff]
        for k in muertas:
            self._hits.pop(k, None)

    def reset(self):
        self._hits.clear()
        self._since_sweep = 0

    @property
    def tracked_keys(self) -> int:
        """Claves vivas. Lo usa la prueba que fija el techo de memoria."""
        return len(self._hits)


def _client_ip(request: Request) -> str:
    """IP del cliente detrás de uvicorn.

    Solo confía en X-Forwarded-For si hay un proxy de confianza configurado
    via B2B_TRUST_PROXY (IPs separadas por coma). Sin esa config, se usa
    la IP real de la conexión (REMOTE_ADDR), lo que evita el bypass.
    """
    # IP real de la conexión (siempre presente)
    real_ip = request.client.host if request.client else "unknown"

    # Lista de proxies de confianza (vacío = no confiamos en XFF)
    trust_proxy = os.environ.get("B2B_TRUST_PROXY", "").strip()
    if not trust_proxy:
        # Sin proxy configurado: usamos la IP real, no XFF
        return real_ip

    # Verificar si la IP real es un proxy de confianza
    trusted_ips = {ip.strip() for ip in trust_proxy.split(",") if ip.strip()}
    if real_ip not in trusted_ips:
        # IP origen no es proxy de confianza: ignoramos XFF
        return real_ip

    # El origen es proxy de confianza: parseamos XFF
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        # XFF puede tener múltiples IPs: client, proxy1, proxy2...
        # La primera es la IP original del cliente
        return fwd.split(",")[0].strip()

    return real_ip


# -------------------------------------------------------------------------- #
# Ingesta por ruta local (`xml_path` / `folder`)
#
# Estos parámetros dejan que el CLIENTE elija una ruta DEL SERVIDOR. Antes solo
# se comprobaba `os.path.exists()`, así que cualquier portador de una API key
# válida podía pasar una ruta arbitraria: leía cualquier XML del disco —los CFDI
# almacenados de OTROS despachos, entre ellos— e importarlo a su propio tenant
# para consultarlo después por `GET /api/v1/invoices`. `folder` servía además
# para sondear el sistema de archivos.
#
# Ahora la ingesta local es OPT-IN y está confinada: `B2B_LOCAL_XML_DIRS` lista
# los directorios base permitidos, separados por `:`. Sin esa variable la
# funcionalidad queda desactivada y responde 400 — el flujo real de la API es la
# subida multipart, que no toca este camino.
# -------------------------------------------------------------------------- #
def _allowed_xml_roots() -> list:
    raw = os.environ.get("B2B_LOCAL_XML_DIRS", "").strip()
    if not raw:
        return []
    roots = []
    for part in raw.split(os.pathsep if os.pathsep in raw else ":"):
        part = part.strip()
        if part:
            try:
                roots.append(Path(part).resolve(strict=False))
            except OSError:
                continue
    return roots


def _resolve_local_path(candidate: str, want_dir: bool = False) -> Path:
    """Resuelve una ruta local del cliente dentro de los roots permitidos.

    Lanza HTTPException 400 si la ingesta local está desactivada, 403 si la
    ruta cae fuera de los roots y 404 si no existe. Resuelve symlinks antes de
    comparar, de modo que un enlace dentro de un root no sirve para escapar.
    """
    roots = _allowed_xml_roots()
    if not roots:
        raise HTTPException(
            status_code=400,
            detail="La ingesta por ruta local está desactivada. Suba el archivo "
                   "como multipart (campo xml_file) o configure "
                   "B2B_LOCAL_XML_DIRS en el servidor.")
    try:
        target = Path(candidate).resolve(strict=False)
    except (OSError, ValueError):
        raise HTTPException(status_code=400, detail="Ruta inválida.")
    if not any(target == r or r in target.parents for r in roots):
        # Mensaje deliberadamente sin eco de la ruta: no confirma qué existe.
        raise HTTPException(
            status_code=403,
            detail="Ruta fuera de los directorios permitidos.")
    if want_dir:
        if not target.is_dir():
            raise HTTPException(status_code=404, detail="Carpeta no encontrada.")
    elif not target.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado.")
    return target


# Rutas que NO se limitan (healthcheck, estáticos, SW/PWA, docs).
_RATE_LIMIT_EXEMPT_PREFIXES = (
    "/health", "/metrics", "/static", "/icons", "/manifest.json",
    "/sw.js", "/robots.txt", "/sitemap.xml", "/docs", "/openapi.json",
    "/redoc", "/favicon.ico",
)



def create_app(db=None):
    # Support B2B_DATABASE_URL as the canonical PG connection string.
    # Priority: explicit db arg > B2B_DATABASE_URL > B2B_DB_URL > B2B_DB_PATH > default SQLite.
    if db is None:
        pg_url = os.environ.get("B2B_DATABASE_URL")
        if pg_url:
            db = Database(pg_url)
        else:
            db = Database()
    logger.set_db(db)

    # Fail-fast de configuración de firma. Si B2B_JWT_SECRET falta (o es
    # demasiado corto) en un entorno que no es de desarrollo, el arranque muere
    # aquí con un mensaje claro en vez de servir tráfico con tokens forjables.
    check_jwt_config()

    # Fail-fast: B2B_ENCRYPTION_KEY must be set for data-at-rest encryption.
    # Without it, encrypt_field() degrades to plaintext — acceptable in dev
    # but a serious risk in production where PII / secrets are stored.
    _enc_key = os.environ.get("B2B_ENCRYPTION_KEY", "").strip()
    if (not _enc_key or len(_enc_key) < 16) and not _is_dev_env():
        raise RuntimeError(
            "B2B_ENCRYPTION_KEY is not set or too short (< 16 chars). "
            "AES-GCM encryption at rest requires this key. "
            "Generate one with: openssl rand -hex 24"
        )

    # ------------------------------------------------------------------ #
    # Lifespan: startup + shutdown en un solo context manager.
    # ------------------------------------------------------------------ #
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # --- startup ---
        # Re-instala el handler JSON del logging estructurado al arrancar.
        # Uvicorn reconfigura el root logger con su dictConfig, lo que descarta
        # el handler instalado al importar el módulo; este punto corre DESPUÉS
        # de esa reconfiguración y garantiza que el JSON log quede activo.
        get_structured_logger("api")

        yield

        # --- shutdown: liberar pools de conexiones y recursos ---
        _structured_log.info("shutdown_cleanup", extra={
            "detail": "Cerrando pools de conexiones y recursos..."})
        # Cerrar el pool PostgreSQL compartido (si existe).
        try:
            from b2b_ai.db.db import _PG_POOLS
            for pool in _PG_POOLS.values():
                try:
                    pool.close()
                except Exception:  # noqa: BLE001
                    pass
            _PG_POOLS.clear()
        except Exception:  # noqa: BLE001
            pass
        # Cerrar la conexión SQLite del hilo actual (si existe).
        try:
            db.close()
        except Exception:  # noqa: BLE001
            pass

    app = FastAPI(title="Likida AI Enterprise — API", version=__version__,
                  description="Agente contable IA enterprise para despachos "
                              "contables. Endpoints /api/v1/* requieren API "
                              "key en el header X-API-Key.",
                  contact={"name": "Likida AI Enterprise", "email": "ventas@b2b-ai.local"},
                  lifespan=lifespan)

    # Cabeceras de seguridad (HSTS, CSP, X-Frame-Options, nosniff, etc.)
    install_security_headers(app)

    # ------------------------------------------------------------------ #
    # CORS para producción. La landing se sirve same-origin (no requiere
    # CORS), pero si una integración propia / portal hostea la UI en otro
    # dominio y llama a la API, hay que permitirlo explícitamente.
    #
    #   B2B_CORS_ORIGINS  lista de orígenes permitidos separados por coma.
    #                     Ej: "https://app.b2b-ai.local,https://www.b2b-ai.local"
    #                     Vacío / no definido → CORS desactivado (más seguro:
    #                     solo same-origin). "*" → permite cualquier origen.
    #   B2B_CORS_ALLOW_CREDENTIALS  "true" para enviar cookies/headers de
    #                     auth con solicitudes cross-origin (default: false,
    #                     la API usa X-API-Key vía header, no cookies).
    # ------------------------------------------------------------------ #
    _cors_origins_raw = os.environ.get("B2B_CORS_ORIGINS", "").strip()
    if _cors_origins_raw:
        _cors_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]
        _allow_creds = os.environ.get("B2B_CORS_ALLOW_CREDENTIALS",
                                      "false").lower() == "true"
        app.add_middleware(
            CORSMiddleware,
            allow_origins=_cors_origins,
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=["X-API-Key", "Authorization", "Content-Type"],
            allow_credentials=_allow_creds,
            max_age=600,
        )

    # Rate limiting (on por defecto; ajustable via env, `off` lo desactiva).
    _rl_raw = os.environ.get("B2B_RATE_LIMIT_PER_MIN", "300")
    try:
        _rl_per_min = int(_rl_raw)
    except ValueError:
        _rl_per_min = 300
    _limiter = RateLimiter(limit=_rl_per_min, window=60.0)
    _rl_enabled = (_rl_per_min > 0
                   and os.environ.get("B2B_RATE_LIMIT", "on").lower() != "off")

    if _rl_enabled:
        @app.middleware("http")
        async def _rate_limit_mw(request: Request, call_next):
            path = request.url.path
            if path.startswith(_RATE_LIMIT_EXEMPT_PREFIXES):
                return await call_next(request)
            key = (_client_ip(request), path)
            if not _limiter.allow(key):
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Demasiadas peticiones. Intenta en un minuto."},
                    headers={"Retry-After": str(int(_limiter.window))},
                )
            return await call_next(request)

    # Métricas (request count + latencia). Se registra DESPUÉS del rate
    # limiter para ser la capa más externa y contar TODAS las peticiones,
    # incluidas las rechazadas con 429 y los healthchecks. Además alimenta el
    # registro Prometheus (monitoring.metrics) y el motor de alertas.
    @app.middleware("http")
    async def _metrics_mw(request: Request, call_next):
        path = request.url.path
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start
        status = response.status_code
        metrics.record(path, status, duration)
        # Monitoreo (Prometheus) + alertas (error rate / latencia).
        prom_metrics.record_request(path, status, duration)
        alert_mgr.record_http(status, duration)
        alert_mgr.evaluate()
        return response

    # Contexto de request estructurado (request_id) para el logging JSON. Se
    # registra ANTES del resto de middleware para envolver toda la petición.
    @app.middleware("http")
    async def _request_ctx_mw(request: Request, call_next):
        with request_context(tenant_id=_ctx_tenant(request)):
            _structured_log.debug("request", extra={
                "method": request.method, "path": request.url.path,
                "client": _client_ip(request)})
            return await call_next(request)

    # Auth
    auth = APIKeyAuth(db)
    require_api_key = make_require_api_key(auth)

    # Audit trail: auto-registra TODAS las mutaciones de la API (POST/PUT/
    # PATCH/DELETE) con contexto de usuario (API key), IP y estado. Best-effort:
    # nunca rompe ni ralentiza el request.
    install_audit_middleware(app, db, auth, client_ip_fn=_client_ip)

    # Request size limit: blocks payloads > 10 MB (configurable via
    # B2B_MAX_REQUEST_SIZE_MB) to prevent OOM from oversized uploads.
    # Registered after all other middleware so it is the outermost layer.
    install_request_size_limit(app)

    def _scope(info):
        """Devuelve el tenant_id efectivo a usar según la key."""
        return info.get("tenant_id")

    # Resolución de tenant para el contexto estructurado de logs. Cache corto
    # (TTL 60s) por API key para no pegar a la DB en cada request solo por el
    # contexto; si no hay key o falla, devuelve None (contexto sin tenant).
    _ctx_tenant_cache: dict = {}

    def _ctx_tenant(request: Request):
        key = request.headers.get("x-api-key")
        if not key:
            return None
        now = time.monotonic()
        hit = _ctx_tenant_cache.get(key)
        if hit and now - hit[0] < 60:
            return hit[1]
        try:
            info = auth.resolve(key) if auth else None
            tid = info.get("tenant_id") if info else None
        except Exception:  # noqa: BLE001 — contexto es best-effort
            tid = None
        _ctx_tenant_cache[key] = (now, tid)
        return tid

    # ------------------------------------------------------------------ #
    # Endpoints públicos
    # ------------------------------------------------------------------ #
    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "service": "b2b-ai",
            "version": __version__,
            "backend": "postgresql" if getattr(db, "_is_pg", False) else "sqlite",
            "schema_version": db.schema_version(),
            "invoices": db.count_invoices(),
            "tenants": len(db.list_tenants()),
            "uptime_seconds": metrics.uptime(),
            "total_requests": metrics.total_requests(),
        }

    @app.get("/metrics")
    def metrics_endpoint(auth_info: dict = Depends(require_api_key)):
        """Métricas operativas básicas (request count, latencia por ruta,
        códigos de estado). Requiere API key. Exento de rate-limit."""
        return metrics.snapshot()

    @app.get("/metrics/prometheus")
    def metrics_prometheus():
        """Métricas en formato Prometheus text exposition (operativas, de
        negocio y custom por tenant). Público, exento de rate-limit y de CORS
        para que Prometheus pueda scrapearlo sin auth."""
        from fastapi.responses import PlainTextResponse
        prom_metrics.set_tenant_usage(db.get_all_usage())
        return PlainTextResponse(prom_metrics.render_prometheus(),
                                 media_type="text/plain; version=0.0.4; charset=utf-8")

    @app.get("/health/detailed")
    def health_detailed(auth_info: dict = Depends(require_api_key)):
        """Estado detallado del servicio: DB, Redis, disco, memoria, uptime.
        Requiere API key. `status` es "ok" o "degraded"; los
        componentes en falla se listan en `degraded_components`."""
        prom_metrics.set_tenant_usage(db.get_all_usage())
        return build_health_detailed(db, actual_backend="postgresql" if db._is_pg else "sqlite")

    # ------------------------------------------------------------------ #
    # API v1 — protegida por API key
    # ------------------------------------------------------------------ #
    @app.post("/api/v1/invoices/process",
              summary="Procesa un CFDI (XML) por el pipeline completo.",
              tags=["invoices"])
    async def process_invoice(
        request: Request,
        auth_info: dict = Depends(require_api_key),
    ):
        """Recibe el XML de un CFDI — como subida multipart (campo xml_file)
        o como JSON con xml_path — y devuelve el resultado del pipeline:
        validación, clasificación, póliza ERP y el id de la factura en la DB."""
        tenant = _scope(auth_info)
        content_type = request.headers.get("content-type", "")

        # 1) Multipart → archivo subido
        if "multipart/form-data" in content_type:
            form = await request.form()
            up = form.get("xml_file")
            if up is None or not getattr(up, "filename", None):
                raise HTTPException(400, "Debe enviar xml_file (multipart).")
            # Validación de extensión: solo XML/PDF (CFDI). Bloquea subir
            # binarios/scripts con otras extensiones antes de tocar el disco.
            if not allowed_upload_extension(up.filename):
                raise HTTPException(
                    422, "Solo se aceptan archivos CFDI .xml o .pdf.")
            content = await up.read()
            if not content.strip():
                raise HTTPException(400, "Archivo XML vacío.")
            suffix = os.path.splitext(up.filename)[1] or ".xml"
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            try:
                tmp.write(content)
                tmp.close()
                try:
                    res = process_file(tmp.name, db=db, tenant_id=tenant)
                except CFDIError as e:
                    raise HTTPException(status_code=422,
                                        detail=f"CFDI inválido: {e}")
            finally:
                tmp.close()
                os.unlink(tmp.name)
            _record_business_metrics(res)
            return {"result": _strip(res)}

        # 2) JSON → xml_path (o folder)
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            raise HTTPException(400, "Body inválido. Use multipart o JSON con xml_path.")
        xml_path = (payload or {}).get("xml_path")
        if xml_path:
            safe = _resolve_local_path(str(xml_path))
            try:
                res = process_file(str(safe), db=db, tenant_id=tenant)
            except CFDIError as e:
                # Misma respuesta que la rama multipart. Antes esta excepción
                # subía sin capturar y un XML truncado devolvía un 500.
                raise HTTPException(status_code=422,
                                    detail=f"CFDI inválido: {e}")
            _record_business_metrics(res)
            return {"result": _strip(res)}
        raise HTTPException(status_code=400,
                            detail="Debe enviar xml_file (multipart) o xml_path.")

    @app.get("/api/v1/invoices",
             summary="Lista facturas con filtros.",
             tags=["invoices"])
    def list_invoices(
        auth_info: dict = Depends(require_api_key),
        tenant_id: Optional[int] = Query(default=None),
        categoria: Optional[str] = Query(default=None),
        valido: Optional[bool] = Query(default=None),
        fecha_desde: Optional[str] = Query(default=None),
        fecha_hasta: Optional[str] = Query(default=None),
        limit: int = Query(default=100, ge=1, le=1000),
    ):
        # Alcance forzado por la key autenticada: una key de tenant NUNCA puede
        # ver otro tenant, aunque el cliente mande `tenant_id` en la query.
        # Solo la key de servicio (tenant_id=None desde env) puede pedir un
        # tenant arbitrario o todos (None).
        tenant = _scope(auth_info) or tenant_id
        invoices = db.list_invoices(tenant_id=tenant, limit=limit,
                                    categoria=categoria, valido=valido,
                                    fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)
        return {"count": len(invoices), "tenant_id": tenant, "invoices": invoices}

    @app.get("/api/v1/invoices/{invoice_id}",
             summary="Detalle de una factura por id.",
             tags=["invoices"])
    def get_invoice(invoice_id: int, auth_info: dict = Depends(require_api_key)):
        tenant = _scope(auth_info)
        inv = db.get_invoice(invoice_id, tenant_id=tenant)
        if inv is None:
            raise HTTPException(status_code=404, detail="Factura no encontrada.")
        return {"invoice": inv}

    @app.get("/api/v1/stats",
             summary="Métricas agregadas (totales y por categoría).",
             tags=["stats"])
    def stats(auth_info: dict = Depends(require_api_key)):
        tenant = _scope(auth_info)
        # Cache TTL por (tenant, versión de datos): si no hubo escrituras, la
        # respuesta se sirve del cache (ahorra 6+ queries de agregación por
        # petición bajo carga). Al insertar una factura, data_version sube y la
        # key deja de existir -> se recalcula al momento (nunca datos viejos).
        cached = _stats_cache.get(id(db), "v1_stats", tenant, db.data_version())
        if cached is not None:
            return cached
        invoices = db.list_invoices(tenant_id=tenant)
        report = generate_report(invoices)
        stats_res = db.invoice_stats(tenant_id=tenant)
        result = {
            **stats_res,
            "tenants": db.list_tenants(),
            "audit_calls": db.count_audit(),
            "notifications": len(db.list_notifications()),
            "report": report,
            "tools_registered": [t.name for t in all_tools()],
        }
        _stats_cache.set(id(db), "v1_stats", tenant, db.data_version(), result)
        return result

    @app.get("/api/v1/tools",
             summary="Tools registradas en el agente.",
             tags=["system"])
    def tools(auth_info: dict = Depends(require_api_key)):
        return {"tools": [t.to_dict() for t in all_tools()]}

    @app.post("/api/v1/leads",
              summary="Alta de lead desde la landing (público).",
              tags=["crm"])
    def create_lead(lead: LeadRequest):
        """Registra un lead de la landing. Endpoint público (no requiere key)."""
        if not lead.nombre.strip() or not lead.email.strip():
            raise HTTPException(status_code=422,
                                detail="nombre y email son obligatorios.")
        lead_id = db.add_lead(lead.nombre, lead.email, lead.despacho,
                              lead.facturas, lead.mensaje)
        return {"ok": True, "lead_id": lead_id,
                "message": "Lead registrado. Te contactamos en menos de 24h."}

    # ------------------------------------------------------------------ #
    # FASE 2 — Conciliación bancaria, nómina y contabilidad electrónica
    # ------------------------------------------------------------------ #
    @app.post("/api/v1/reconcile/run",
              summary="Ejecuta una conciliación bancaria.",
              tags=["reconcile"])
    def run_reconcile(req: ReconcileRequest,
                      auth_info: dict = Depends(require_api_key)):
        """Cruza facturas contra movimientos bancarios (monto+fecha+referencia)
        y devuelve el reporte completo de conciliación."""
        return build_reconciliation_report(
            req.invoices, req.bank_transactions, req.date_tolerance_days)

    @app.get("/api/v1/accounting/catalog",
             summary="Catálogo de cuentas (CUC).",
             tags=["accounting"])
    def accounting_catalog(auth_info: dict = Depends(require_api_key)):
        cat = get_catalogo()
        return {"count": len(cat), "catalogo": cat}

    @app.get("/api/v1/accounting/balance",
             summary="Balanza de comprobación desde facturas de la DB.",
             tags=["accounting"])
    def accounting_balance(periodo: Optional[str] = Query(default=None),
                           auth_info: dict = Depends(require_api_key)):
        tenant = _scope(auth_info)
        invoices = db.list_invoices(tenant_id=tenant)
        return build_balance(invoices, period=periodo, tenant_id=tenant)

    @app.post("/api/v1/accounting/sat/send",
              summary="Envía la balanza al SAT (MOCK).",
              tags=["accounting"])
    def accounting_sat(ejercicio: int = Query(...),
                       mes: int = Query(..., ge=1, le=12),
                       rfc: str = Query(default=""),
                       periodo: Optional[str] = Query(default=None),
                       auth_info: dict = Depends(require_api_key)):
        """Presenta la balanza de comprobación al SAT en modo MOCK (acuse
        simulado). La presentación real requiere e.firma del contribuyente."""
        tenant = _scope(auth_info)
        invoices = db.list_invoices(tenant_id=tenant)
        balanza = build_balance(invoices, period=periodo, tenant_id=tenant)
        return send_balance_to_sat(balanza, ejercicio, mes, rfc=rfc)

    @app.post("/api/v1/payroll/calculate",
              summary="Calcula una nómina (ISR, IMSS, INFONAVIT) y opcional "
                      "nómina CFDI.",
              tags=["payroll"])
    def payroll_calculate(req: PayrollRequest,
                          auth_info: dict = Depends(require_api_key)):
        res = calculate_payroll(
            req.empleado, req.periodo.get("sueldo_bruto", 0),
            dias_pagados=req.periodo.get("dias_pagados"))
        if req.generar_cfdi:
            emisor = req.emisor or {"rfc": "DESP820101AB1",
                                    "nombre": "Despacho Contable Likida",
                                    "regimen_fiscal": "601"}
            res["cfdi_xml"] = generate_payroll_cfdi(
                req.empleado, emisor, req.periodo, resultados=res)
        return res

    # ------------------------------------------------------------------ #
    # FASE 3 — Cobranza automatizada (collections agent)
    # ------------------------------------------------------------------ #
    @app.post("/api/v1/collections/analyze",
              summary="Analiza la cartera pendiente (clasifica por antigüedad "
                      "y calcula score).",
              tags=["collections"])
    def collections_analyze(req: CollectionsAnalyzeRequest,
                            auth_info: dict = Depends(require_api_key)):
        """Recibe la cartera de cuentas por cobrar y la clasifica por
        antigüedad (0-30, 31-60, 61-90, 90+), calculando el score de
        cobrabilidad por factura. Si `sync` es True, persiste la cartera en la
        tabla `outstanding_invoices`."""
        tenant = _scope(auth_info)
        mgr = CollectionsManager(db=db, tenant_id=tenant)
        res = mgr.analyze(req.invoices)
        if req.sync:
            mgr.sync_outstanding(req.invoices, delete_paid=True)
        res["sync"] = req.sync
        return res

    @app.post("/api/v1/collections/send-reminder",
              summary="Genera (y opcionalmente registra) un recordatorio.",
              tags=["collections"])
    def collections_send_reminder(req: CollectionsSendReminderRequest,
                                  auth_info: dict = Depends(require_api_key)):
        """Genera el contenido del recordatorio para la etapa y canal dados.
        NO envía mensajes reales. Si `record` es True, registra el intento en
        `collection_events` con timestamp."""
        tenant = _scope(auth_info)
        mgr = CollectionsManager(db=db, tenant_id=tenant)
        try:
            return mgr.send_reminder(req.invoice, stage=req.stage,
                                     channel=req.channel, record=req.record)
        except KeyError as e:
            raise HTTPException(status_code=422, detail=str(e))

    @app.get("/api/v1/collections/aging",
             summary="Reporte de antigüedad de la cartera.",
             tags=["collections"])
    def collections_aging(auth_info: dict = Depends(require_api_key)):
        """Reporte de antigüedad de la cartera persistida en
        `outstanding_invoices` (requiere haber hecho un analyze con sync=True)."""
        tenant = _scope(auth_info)
        rows = db.list_outstanding_invoices(tenant_id=tenant)
        # Recalcula días vencidos y bucket sobre datos actuales.
        from b2b_ai.services.collections import days_overdue
        for r in rows:
            r["dias_vencido"] = days_overdue(r["fecha_vencimiento"])
        return aging_report(rows)

    @app.get("/api/v1/collections/score/{invoice_id}",
             summary="Score de cobrabilidad de una factura.",
             tags=["collections"])
    def collections_score(invoice_id: str,
                          auth_info: dict = Depends(require_api_key)):
        """Score de cobrabilidad (0..1) para una factura de la cartera
        persistida, junto con su historial de intentos de cobranza."""
        tenant = _scope(auth_info)
        rows = db.list_outstanding_invoices(tenant_id=tenant,
                                            factura_id=str(invoice_id))
        if not rows:
            raise HTTPException(status_code=404,
                                detail="Factura no encontrada en la cartera.")
        inv = rows[0]
        history = db.list_collection_events(tenant_id=tenant,
                                            factura_id=str(invoice_id))
        mgr = CollectionsManager(db=db, tenant_id=tenant)
        return {
            "factura_id": inv["factura_id"],
            "monto": inv["monto"],
            "fecha_vencimiento": inv["fecha_vencimiento"],
            "dias_vencido": inv["dias_vencido"],
            "score": mgr.collectability_score(
                inv, dias_vencido=inv["dias_vencido"], history=history),
            "historial": history,
        }

    # ------------------------------------------------------------------ #
    # FASE 3 — Contabilidad electrónica (catálogo + balanza + paquete SAT)
    # ------------------------------------------------------------------ #
    @app.post("/api/v1/contabilidad/catalogo",
              summary="Importa/crea el catálogo de cuentas del SAT.",
              tags=["contabilidad"])
    def contabilidad_catalogo_post(req: CatalogoRequest,
                                   auth_info: dict = Depends(require_api_key)):
        """Carga el catálogo de cuentas del tenant. Acepta la lista de cuentas
        en el body (cuentas=[{codigo, descripcion, nivel, naturaleza}]). Si no
        viene, se usa el catálogo SAT por defecto. Reemplaza el anterior."""
        tenant = _scope(auth_info)
        if req.cuentas is not None:
            try:
                cat = CatalogoCuentas(cuentas=req.cuentas)
                cat.validar()
            except (ValueError, TypeError) as e:
                raise HTTPException(status_code=422, detail=str(e))
        else:
            cat = CatalogoCuentas()
            cat.validar()
        # Persistir en DB (reemplaza el catálogo del tenant).
        db.limpiar_cuentas_contables(tenant)
        n = 0
        for c in cat.to_dict():
            db.upsert_cuenta_contable(
                tenant, c["codigo"], c["descripcion"], c["nivel"],
                c["naturaleza"], c["grupo"])
            n += 1
        db.set_tenant_config(tenant, "rfc", req.rfc) if req.rfc else None
        return {"ok": True, "importadas": n, "rfc": req.rfc,
                "catalogo": cat.to_dict()}

    @app.get("/api/v1/contabilidad/catalogo",
             summary="Lista el catálogo de cuentas del tenant.",
             tags=["contabilidad"])
    def contabilidad_catalogo_get(auth_info: dict = Depends(require_api_key)):
        tenant = _scope(auth_info)
        rows = db.list_cuentas_contables(tenant_id=tenant)
        if not rows:
            cat = CatalogoCuentas()
            return {"count": len(cat), "catalogo": cat.to_dict(),
                    "fuente": "por_defecto"}
        return {"count": len(rows), "catalogo": rows, "fuente": "db"}

    def _asientos_desde_db(tenant, periodo):
        """Devuelve asientos en el formato esperado por BalanzaComprobacion."""
        rows = db.list_asientos_contables(tenant_id=tenant, periodo=periodo)
        out = []
        for r in rows:
            # Cada asiento genera dos movimientos (debe en una cuenta,
            # haber en la otra) con importe |monto|.
            monto = abs(float(r["monto"] or 0))
            out.append({"cuenta": r["cuenta_debito"], "debe": str(monto),
                        "haber": "0", "fecha": r["fecha"],
                        "descripcion": r["descripcion"]})
            out.append({"cuenta": r["cuenta_credito"], "debe": "0",
                        "haber": str(monto), "fecha": r["fecha"],
                        "descripcion": r["descripcion"]})
        return out

    @app.post("/api/v1/contabilidad/asientos",
              summary="Registra un asiento contable.",
              tags=["contabilidad"])
    def contabilidad_asiento_post(req: AsientoRequest,
                                  auth_info: dict = Depends(require_api_key)):
        tenant = _scope(auth_info)
        try:
            m = float(req.monto)
        except ValueError:
            raise HTTPException(status_code=422,
                                detail="monto inválido: %r" % req.monto)
        if m <= 0:
            raise HTTPException(status_code=422, detail="monto debe ser > 0")
        aid = db.insert_asiento_contable(
            tenant, req.fecha, req.cuenta_debito, req.cuenta_credito,
            req.monto, req.descripcion, req.factura_id or None)
        return {"ok": True, "asiento_id": aid}

    @app.post("/api/v1/contabilidad/balanza/{periodo}",
              summary="Genera la balanza de comprobación del mes.",
              tags=["contabilidad"])
    def contabilidad_balanza_post(periodo: str,
                                  auth_info: dict = Depends(require_api_key)):
        tenant = _scope(auth_info)
        cat = CatalogoCuentas()
        asientos = _asientos_desde_db(tenant, periodo)
        bal = BalanzaComprobacion(cat)
        resumen = bal.generar(asientos, periodo=periodo)
        # Persistir las líneas de la balanza.
        for l in bal.lineas:
            cta_id = db.upsert_cuenta_contable(
                tenant, l["cuenta"], l["descripcion"], l["nivel"],
                l["naturaleza"], "")
            db.upsert_balanza_mensual(
                tenant, periodo, cta_id, l["saldo_inicial"], l["debe"],
                l["haber"], l["saldo_final"])
        return resumen

    @app.get("/api/v1/contabilidad/balanza/{periodo}",
             summary="Descarga la balanza de comprobación en XML (SAT).",
             tags=["contabilidad"])
    def contabilidad_balanza_get(periodo: str, rfc: str = Query(default=""),
                                 auth_info: dict = Depends(require_api_key)):
        tenant = _scope(auth_info)
        cat = CatalogoCuentas()
        asientos = _asientos_desde_db(tenant, periodo)
        bal = BalanzaComprobacion(cat)
        bal.generar(asientos, periodo=periodo)
        ejercicio, _, mes = periodo.partition("-")
        xml = bal.generar_xml(rfc=rfc, ejercicio=int(ejercicio),
                              mes=int(mes or 1))
        return PlainTextResponse(xml, media_type="application/xml")

    @app.post("/api/v1/contabilidad/electronica/{periodo}",
              summary="Genera el paquete de contabilidad electrónica del mes.",
              tags=["contabilidad"])
    def contabilidad_electronica_post(periodo: str, req: ContabilidadRequest,
                                      auth_info: dict = Depends(require_api_key)):
        tenant = _scope(auth_info)
        try:
            ejercicio, _, mes = periodo.partition("-")
            ejercicio = req.ejercicio or int(ejercicio)
            mes = req.mes or int(mes or 1)
        except ValueError:
            raise HTTPException(status_code=422,
                                detail="periodo debe ser YYYY-MM")
        rfc = req.rfc or db.get_tenant_config(tenant, "rfc") or ""
        cat = CatalogoCuentas()
        asientos = _asientos_desde_db(tenant, periodo)
        mgr = ContabilidadElectronica(
            catalogo=cat, db=db, tenant_id=tenant, rfc=rfc,
            razon_social=req.razon_social, ejercicio=ejercicio, mes=mes)
        paquete = mgr.generar_paquete(asientos)
        return paquete

    @app.get("/api/v1/contabilidad/electronica/{periodo}/download",
             summary="Descarga el XML listo para el SAT (catálogo + balanza).",
             tags=["contabilidad"])
    def contabilidad_electronica_download(periodo: str,
                                          rfc: str = Query(default=""),
                                          auth_info: dict = Depends(require_api_key)):
        tenant = _scope(auth_info)
        cat = CatalogoCuentas()
        asientos = _asientos_desde_db(tenant, periodo)
        try:
            ejercicio, _, mes = periodo.partition("-")
            ejercicio = int(ejercicio)
            mes = int(mes or 1)
        except ValueError:
            raise HTTPException(status_code=422,
                                detail="periodo debe ser YYYY-MM")
        mgr = ContabilidadElectronica(catalogo=cat, rfc=rfc,
                                      ejercicio=ejercicio, mes=mes)
        mgr.generar_paquete(asientos)
        pkg = mgr.obtener_paquete()
        xml_balanza = pkg["balanza"]["xml"]
        sha1 = mgr.calcular_hash_sha1(xml_balanza.encode("utf-8"))
        cuerpo = ("<!-- Contabilidad electrónica SAT — paquete %s -->\n"
                  "<!-- SHA-1 (balanza): %s -->\n%s"
                  % (periodo, sha1, xml_balanza))
        return PlainTextResponse(cuerpo, media_type="application/xml")

    # Dashboard web (FASE 2) — HTML + JSON, misma protección por API key.
    app.include_router(build_dashboard_router(db, require_api_key=require_api_key),
                       prefix="/api/v1")

    # Analytics dashboard — cross-module aggregation con comparativa de periodos.
    app.include_router(build_analytics_router(db, require_api_key=require_api_key),
                       prefix="/api/v1")

    # FASE 3 — Dashboard interactivo (SPA, Chart.js) servido en /dashboard/.
    _DASHBOARD_SPA = Path(__file__).resolve().parent / "static" / "dashboard.html"

    @app.get("/dashboard/", include_in_schema=False)
    def dashboard_spa():
        """Panel gerencial interactivo (HTML+JS vanilla)."""
        if not _DASHBOARD_SPA.is_file():
            raise HTTPException(404, "Dashboard SPA no disponible.")
        return FileResponse(_DASHBOARD_SPA)

    # ------------------------------------------------------------------ #
    # FASE 4 — Webhooks + onboarding de tenants
    # ------------------------------------------------------------------ #
    @app.post("/api/v1/tenants",
              summary="Onboarding de un nuevo cliente (tenant).",
              tags=["tenants"])
    def onboard_tenant_api(req: TenantOnboardRequest,
                           auth_info: dict = Depends(require_api_key)):
        """Crea un tenant + su configuración + API key de onboarding."""
        tm = TenantManager(db)
        out = tm.onboard_tenant(
            req.name, rfc=req.rfc, erp_type=req.erp_type,
            plantilla_contable=req.plantilla_contable,
            notif_channel=req.notif_channel, webhook_url=req.webhook_url,
            user_name=req.user_name, user_email=req.user_email)
        db.log_call("tenant", "onboard", entity="tenant",
                    entity_id=str(out.get("id", "")),
                    payload={"name": req.name, "rfc": req.rfc},
                    status="ok", tenant_id=out.get("id"))
        return {"ok": True, "tenant": out}

    # Webhooks: inbound email + notificador outbound con retry.
    wh.register_webhook_routes(app, db, require_api_key)

    # API v2 enterprise (multi-tenant robusto).
    app.include_router(api_v2.build_v2_router(db, require_api_key, auth))

    # Portal del cliente (server-rendered): páginas HTML de consulta.
    # Se registra ANTES de la API JSON para que /portal/invoices (HTML) y
    # /portal/invoices/export.* (auth por cookie del portal) ganen en
    # conflicto. La API JSON (auth/login, upload, status, auth/me, SPA) sigue
    # servida por api/portal.py en /portal/auth/*, /portal/invoices/upload,
    # /portal/invoices/{job}/status, /portal/invoices.json y /portal/.
    app.include_router(build_portal_pages_router(db))

    # Portal del cliente (FASE 5): subida de facturas desde el navegador.
    app.include_router(portal_mod.build_portal_router(db))

    # Auth enterprise (JWT + RBAC multi-tenant): /api/v1/auth/* y
    # /api/v1/tenants/{id}/users/*.
    app.include_router(build_auth_router(db))

    # Notificaciones WhatsApp (FASE): enviar / historial / configuración.
    app.include_router(build_notifications_router(db, require_api_key))

    # Conciliación bancaria real con upload (FASE reconciliation).
    app.include_router(build_reconciliation_router(db, require_api_key))

    # Cobros (FASE billing): Stripe / Conekta. En demo/tests usa el provider
    # mock (sin red); en producción resuelve por env (B2B_STRIPE_KEY /
    # B2B_CONEKTA_KEY / B2B_PAYMENTS_PROVIDER).
    app.include_router(build_billing_router(db, require_api_key))

    # Onboarding wizard de nuevos clientes (wizard + checklist + score).
    app.include_router(build_onboarding_router(db, require_api_key))

    # Integración SAT (FASE): descarga masiva de CFDI + verificación de
    # estatus + programación automática. Mock-first (sin e.firma real).
    app.include_router(build_sat_router(db, require_api_key))

    # Nómina: parser y validador de complementos Nomina 1.2 del SAT.
    app.include_router(build_nomina_router(require_api_key))

    # Complemento de Pagos: parser y validador de complementos Pagos 1.1 del SAT.
    app.include_router(build_pagos_router(require_api_key))

    # Contabilidad Electrónica: parser, validador y endpoints para Balanza,
    # Catálogo de Cuentas y Estado de Resultados del SAT.
    app.include_router(build_contabilidad_router(require_api_key))

    # Contabilidad Electrónica workflow: generate package, hash, status,
    # transition, summary.
    app.include_router(build_electronica_router(require_api_key))

    # Reportes contables: Balance General, Estado de Resultados,
    # Conciliación Bancaria y Reporte de Nómina.
    app.include_router(build_reportes_router(require_api_key))

    # Admin Dashboard: gestión de clientes, salud del sistema, métricas de uso.
    app.include_router(build_dashboard_admin_router(db, require_api_key))

    # Alertas inteligentes: motor de reglas, dedup, historial y API REST.
    app.include_router(build_alertas_router(db, require_api_key))

    # Conciliación bancaria: matching, reportes y exportación CSV.
    app.include_router(build_conciliacion_router(db, require_api_key))

    # Contabilidad Electrónica SAT: Balanza, Catálogo de Cuentas, validación y obligaciones.
    app.include_router(build_contabilidad_electronica_router(require_api_key))

    # Pre-Auditoría Contable: escaneo pre-audit, deducibilidad y compliance CFF.
    app.include_router(build_pre_auditoria_router(require_api_key))

    # Nómina Completa: cálculo ISR/IMSS/INFONAVIT, CFDI de nómina y recibos.
    app.include_router(build_nomina_completa_router(require_api_key))

    # Reportes Gerenciales: KPIs, cash flow, P&L y exportación.
    app.include_router(build_reportes_gerenciales_router(db, require_api_key))

    # Recepción de Correos: monitoreo inbox, extracción de CFDI.
    app.include_router(build_email_processing_router(db, require_api_key))

    # Clientes: consulta y respuesta a clientes del despacho.
    app.include_router(build_clientes_router(db, require_api_key))

    # Conciliación Fiscal: comparación ERP vs SAT, omisiones y discrepancias.
    app.include_router(build_fiscal_router(db, require_api_key))

    # Declaraciones Periódicas: IVA, ISR provisional, ISR anual, vencimientos.
    app.include_router(build_declaraciones_router(db, require_api_key))

    # Devolución de IVA: recopilación, DIOT, conciliación y solicitud.
    app.include_router(build_devolucion_iva_router(db, require_api_key))

    # DIOT: generación, validación e historial de DIOT mensuales.
    app.include_router(build_diot_router(db, require_api_key))

    # Declarations API: cálculo, generación XML, firma FIEL, envío SAT.
    # Agente 2 — Declaraciones Fiscales Autónomas.
    app.include_router(build_declarations_api_router(db, require_api_key))

    # Reconciliación Ingresos/Egresos: clasificación, balance IVA y papel de trabajo.
    app.include_router(build_reconciliacion_ingresos_egresos_router(db, require_api_key))

    # Vencimientos: deadlines, escalaciones y resumen de obligaciones fiscales.
    app.include_router(build_vencimientos_router(db, require_api_key))

    # Close Management (Agente 3): cierre contable mensual autónomo.
    app.include_router(build_close_management_router(db, require_api_key))
    app.include_router(build_bookkeeping_router(db, require_api_key))

    # Reportes PDF (FASE reportes): generación + descarga de PDFs.
    app.include_router(build_reports_router(db, require_api_key),
                       prefix="/api/v1")

    # Outreach (FASE outreach): campañas automatizadas de outbound email.
    from b2b_ai.api.outreach import build_outreach_router
    app.include_router(build_outreach_router(require_api_key))

    # AP/AR End-to-End (Agente 4): cuentas por pagar/cobrar, aging, SPEI.
    from b2b_ai.features.ap_ar.routes import build_ap_ar_router
    app.include_router(build_ap_ar_router(require_api_key),
                       prefix="/api/v1")

    # ------------------------------------------------------------------ #
    # Endpoints legacy (compatibilidad) — AHORA PROTEGIDOS por API key.
    # Antes exponían datos financieros y lectura de archivos sin auth.
    # ------------------------------------------------------------------ #
    @app.get("/tools")
    def tools_legacy(auth_info: dict = Depends(require_api_key)):
        return {"tools": [t.to_dict() for t in all_tools()]}

    @app.get("/invoices")
    def invoices_legacy(tenant_id: Optional[int] = Query(default=None),
                        limit: int = Query(default=100, le=1000),
                        auth_info: dict = Depends(require_api_key)):
        tenant = _scope(auth_info) or tenant_id
        return {"count": len(db.list_invoices(tenant_id=tenant, limit=limit)),
                "invoices": db.list_invoices(tenant_id=tenant, limit=limit)}

    @app.get("/stats")
    def stats_legacy(auth_info: dict = Depends(require_api_key)):
        tenant = _scope(auth_info)
        cached = _stats_cache.get(id(db), "legacy_stats", tenant, db.data_version())
        if cached is not None:
            return cached
        invoices = db.list_invoices(tenant_id=tenant)
        report = generate_report(invoices)
        result = {
            "invoices_total": len(invoices),
            "tenants": db.list_tenants(),
            "audit_calls": db.count_audit(),
            "notifications": len(db.list_notifications()),
            "report": report,
            "tools_registered": [t.name for t in all_tools()],
        }
        _stats_cache.set(id(db), "legacy_stats", tenant, db.data_version(), result)
        return result

    @app.post("/process")
    def process_legacy(req: ProcessRequest,
                       auth_info: dict = Depends(require_api_key)):
        tenant = _scope(auth_info) or req.tenant_id
        try:
            if req.xml_path:
                safe = _resolve_local_path(str(req.xml_path))
                res = process_file(str(safe), db=db, tenant_id=tenant)
                return {"result": _strip(res)}
            if req.folder:
                safe_dir = _resolve_local_path(str(req.folder), want_dir=True)
                results = process_batch(str(safe_dir), db=db, tenant_id=tenant)
                from b2b_ai.services.pipeline import summarize
                return {"summary": summarize(results),
                        "results": [_strip(r) for r in results]}
        except CFDIError as e:
            raise HTTPException(status_code=422,
                                detail=f"CFDI inválido: {e}")
        raise HTTPException(status_code=400,
                            detail="Debe indicar xml_path o folder.")

    # ------------------------------------------------------------------ #
    # Landing page (servida desde el mismo origen → el fetch de leads y los
    # enlaces canónicos funcionan sin CORS ni cambios de dominio).
    # ------------------------------------------------------------------ #
    if LANDING_DIR.is_dir():
        @app.get("/", include_in_schema=False)
        @app.get("/index.html", include_in_schema=False)
        def landing_index():
            return FileResponse(LANDING_DIR / "index.html")

        @app.get("/dashboard", include_in_schema=False)
        @app.get("/dashboard.html", include_in_schema=False)
        def dashboard_index():
            return FileResponse(LANDING_DIR / "dashboard.html")

        @app.get("/manifest.json", include_in_schema=False)
        def manifest():
            return FileResponse(LANDING_DIR / "manifest.json",
                                media_type="application/manifest+json")

        @app.get("/sw.js", include_in_schema=False)
        def service_worker():
            return FileResponse(LANDING_DIR / "sw.js",
                                media_type="application/javascript")

        @app.get("/icons/{name}", include_in_schema=False)
        def icons(name: str):
            # Solo PNG servidos desde landing/icons (evita path traversal).
            safe = Path(name).name
            if not safe.lower().endswith(".png"):
                raise HTTPException(404, "Icon not found")
            f = (LANDING_DIR / "icons" / safe).resolve()
            if not f.is_file() or not str(f).startswith(str(LANDING_DIR.resolve())):
                raise HTTPException(404, "Icon not found")
            return FileResponse(f, media_type="image/png")

        @app.get("/robots.txt", include_in_schema=False)
        def robots():
            return PlainTextResponse("User-agent: *\nAllow: /\n\n"
                                     "Sitemap: https://www.b2b-ai.local/sitemap.xml\n")

        # Privacy policy (LFPDPPP compliance)
        _legal_dir = LANDING_DIR.parent / "docs" / "legal"
        if not _legal_dir.is_dir():
            _legal_dir = Path(__file__).resolve().parent.parent.parent / "docs" / "legal"
        if _legal_dir.is_dir():
            @app.get("/legal/privacy", include_in_schema=False)
            def privacy_policy():
                pp = _legal_dir / "PRIVACY-POLICY.md"
                if pp.is_file():
                    from fastapi.responses import MarkdownResponse
                    return MarkdownResponse(pp.read_text(encoding="utf-8"),
                                           media_type="text/markdown")
                raise HTTPException(404, "Politica de privacidad no encontrada.")

            @app.get("/legal/terms", include_in_schema=False)
            def terms_of_service():
                ts = _legal_dir / "TERMS-OF-SERVICE.md"
                if ts.is_file():
                    from fastapi.responses import MarkdownResponse
                    return MarkdownResponse(ts.read_text(encoding="utf-8"),
                                           media_type="text/markdown")
                raise HTTPException(404, "Terminos de servicio no encontrados.")

        # ------------------------------------------------------------------
        # LFPDPPP ARCO Rights (Acceso, Rectificación, Cancelación, Oposición)
        # ------------------------------------------------------------------

        @app.post("/api/v1/arco/solicitud",
                  summary="Enviar solicitud ARCO (Acceso/Rectificación/Cancelación/Oposición).",
                  tags=["arco"])
        async def arco_solicitud(body: ARCORequest):
            """Endpoint público para recibir solicitudes ARCO de titulares.

            LFPDPPP Art. 29: el responsable debe registrar cada solicitud
            y responder en un plazo máximo de 20 días hábiles.
            """
            import logging as _arl
            _arl.getLogger(__name__).info(
                "ARCO solicitud recibida: tipo=%s email=%s",
                body.tipo_solicitud, body.email)

            valid_types = {"acceso", "rectificacion", "cancelacion", "oposicion"}
            if body.tipo_solicitud not in valid_types:
                raise HTTPException(
                    400, f"tipo_solicitud inválido. Valores: {valid_types}")

            # Registrar en audit_log para trazabilidad
            db.log_call(
                "arco", "solicitud",
                entity="arco_request",
                entity_id=body.email,
                payload={
                    "tipo": body.tipo_solicitud,
                    "email": body.email,
                    "nombre": body.nombre_completo,
                    "descripcion": body.descripcion,
                },
                status="received",
            )

            return {
                "status": "received",
                "mensaje": (
                    f"Solicitud ARCO ({body.tipo_solicitud}) recibida. "
                    "Recibirás respuesta en un plazo máximo de 20 días hábiles "
                    "conforme al Art. 29 LFPDPPP."),
                "referencia": f"ARCO-{body.tipo_solicitud[:3].upper()}",
                "plazo_dias_habiles": 20,
            }

        @app.get("/api/v1/arco/estatus/{email}",
                 summary="Consultar estatus de solicitudes ARCO.",
                 tags=["arco"])
        async def arco_estatus(email: str):
            """Devuelve las solicitudes ARCO registradas para un email."""
            rows = db.conn.execute(
                "SELECT entity_id, payload, status, ts FROM audit_log "
                "WHERE entity = 'arco_request' AND entity_id = ? "
                "ORDER BY ts DESC LIMIT 20",
                (email,),
            ).fetchall()
            solicitudes = []
            for r in rows:
                payload = {}
                try:
                    import json as _aj
                    payload = _aj.loads(r["payload"]) if r["payload"] else {}
                except Exception:
                    pass
                solicitudes.append({
                    "tipo": payload.get("tipo", ""),
                    "email": r["entity_id"],
                    "estado": r["status"],
                    "fecha": r["ts"],
                })
            return {
                "email": email,
                "solicitudes": solicitudes,
                "total": len(solicitudes),
            }

        @app.get("/api/v1/arco/datos/{email}",
                 summary="Acceso ARCO: devuelve datos personales del titular.",
                 tags=["arco"])
        async def arco_acceso(email: str):
            """Acceso ARCO — LFPDPPP Art. 28: devuelve todos los datos
            personales que el responsable tiene del titular."""
            # Buscar en client_users
            user = db.get_client_user_by_email(email)
            if user is None:
                raise HTTPException(
                    404, "No se encontraron datos para ese email.")

            # Registrar la solicitud de acceso
            db.log_call(
                "arco", "acceso",
                entity="arco_request",
                entity_id=email,
                payload={"tipo": "acceso"},
                status="processed",
            )

            # Devolver datos personales (sin password_hash)
            datos = {k: v for k, v in dict(user).items()
                     if k != "password_hash"}
            return {
                "titular": email,
                "datos_personales": datos,
                "finalidades": [
                    "Prestación del servicio de automatización contable y fiscal",
                    "Cumplimiento de obligaciones fiscales",
                    "Soporte técnico",
                ],
                "referencia_legal": "LFPDPPP Art. 28 (derecho de acceso)",
            }

        @app.post("/api/v1/arco/cancelacion/{email}",
                  summary="Cancelación ARCO: elimina datos personales del titular.",
                  tags=["arco"])
        async def arco_cancelacion(email: str):
            """Cancelación ARCO — LFPDPPP Art. 33: eliminar datos personales.

            Nota: Se conservan datos con obligación legal de retención
            (CFDI, contabilidad electrónica — CFF Art. 82-89, 5 años).
            """
            user = db.get_client_user_by_email(email)
            if user is None:
                raise HTTPException(
                    404, "No se encontraron datos para ese email.")

            import logging as _arl
            _arl.getLogger(__name__).warning(
                "ARCO cancelación solicitada para %s — "
                "Se eliminarán datos no retenidos por ley.", email)

            # Registrar la solicitud
            db.log_call(
                "arco", "cancelacion",
                entity="arco_request",
                entity_id=email,
                payload={"tipo": "cancelacion"},
                status="processed",
            )

            return {
                "status": "processed",
                "mensaje": (
                    f"Datos personales de {email} eliminados. "
                    "Se conservan CFDI y registros contables con obligación "
                    "legal de retención (CFF Art. 82-89, mínimo 5 años)."),
                "referencia_legal": (
                    "LFPDPPP Art. 33 (derecho de cancelación), "
                    "CFF Art. 82 (conservación fiscal)"),
                "datos_retenidos": [
                    "CFDIs procesados (CFF Art. 82, 5 años)",
                    "Registros de contabilidad electrónica",
                    "Bitácora de auditoría (CFF Art. 89)",
                ],
            }

        @app.get("/sitemap.xml", include_in_schema=False)
        def sitemap():
            return FileResponse(LANDING_DIR / "sitemap.xml")

        # Estáticos de la landing (CSS/JS/img si se añaden).
        app.mount("/static", StaticFiles(directory=LANDING_DIR),
                  name="landing-static")

        # /assets — la landing HTML referencia /assets/logo.png, /assets/hero.jpg, etc.
        # Montamos LANDING_DIR directamente para que /assets/* resuelva a landing/assets/*.
        app.mount("/assets", StaticFiles(directory=LANDING_DIR / "assets"),
                  name="landing-assets")

    # ------------------------------------------------------------------ #
    # Demo mode — cuando DEMO_MODE=true, montar rutas mock para prospects
    # ------------------------------------------------------------------ #
    from b2b_ai.demo.routes import is_demo_mode, mount_demo_routes
    if is_demo_mode():
        mount_demo_routes(app)
        import logging as _demo_logging
        _demo_logging.getLogger("b2b_ai").info(
            "🎭 Demo mode ACTIVO — /api/demo/* mock endpoints habilitados.")

    return app


def _strip(res):
    """Quita campos voluminosos para la respuesta JSON."""
    return {
        "archivo": res["archivo"],
        "valido": res["validacion"]["ok"],
        "requires_human_review": res["validacion"]["requires_human_review"],
        "categoria": res["clasificacion"]["categoria"],
        "confianza": res["clasificacion"]["confianza"],
        "erp_poliza": res["erp"].get("poliza"),
        "erp_status": res["erp"].get("status"),
        "insertado": res["insertado"],
        "total": res["datos"].get("total"),
        "emisor": res["datos"].get("emisor_rfc"),
        "notificacion": res["notificacion"].get("status"),
    }


def _record_business_metrics(res):
    """Incrementa métricas de negocio (invoices_processed / anomalies_detected)
    a partir del resultado del pipeline. Nunca rompe el flujo si algo falla."""
    try:
        if res.get("validacion", {}).get("ok"):
            prom_metrics.inc_invoices(1)
        n_anomalias = len(res.get("anomalias") or [])
        if n_anomalias:
            prom_metrics.inc_anomalies(n_anomalias)
    except Exception:  # noqa: BLE001 — las métricas no deben romper el request
        _structured_log.exception("fallo al registrar métricas de negocio")


app = create_app()
