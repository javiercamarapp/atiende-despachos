# Production-Grade para Despachos Contables Reales en México

> **Estado:** Guía de referencia · Likida AI Enterprise  
> **Última actualización:** 2026-08-01  
> **Stack:** Python 3.11 + FastAPI + PostgreSQL + Redis + Docker  

---

## Tabla de Contenidos

1. [Multi-Tenancy Seguro](#1-multi-tenancy-seguro)
2. [Escala para Despachos](#2-escala-para-despachos)
3. [Seguridad Financiera](#3-seguridad-financiera)
4. [Monitoring y Observability](#4-monitoring-y-observability)
5. [Deployment](#5-deployment)
6. [Checklists de Producción](#6-checklists-de-producción)

---

## 1. Multi-Tenancy Seguro

### 1.1 Patrones de Aislamiento — Decisión

| Patrón | Pros | Contras | Recomendación |
|--------|------|---------|---------------|
| **Row-level (RLS)** | Simple, un solo schema, PG nativo | Riesgo de leak si olvidas el filtro | ✅ **Para MVP y fase 1** |
| **Schema per tenant** | Aislamiento fuerte, migración independiente | Complejidad operacional, más schemas que manejar | Fase 2 (despachos enterprise) |
| **DB per tenant** | Máximo aislamiento | Impracticable a escala, costoso | ❌ No recomendado |

#### Decisión: Row-Level Security (RLS) con PostgreSQL

RLS es el sweet spot para despachos contables: cada consulta a la DB filtra automáticamente por `tenant_id`, sin que el código de la aplicación necesite recordar el filtro. PG lo aplica a nivel de engine — un developer que olvide un `WHERE tenant_id = ?` no rompe el aislamiento.

```sql
-- ============================================
-- MIGRACIÓN: Habilitar RLS en todas las tablas
-- ============================================

-- 1. Crear función de sesión que lee el tenant del contexto de conexión
CREATE OR REPLACE FUNCTION current_tenant_id() RETURNS uuid AS $$
  SELECT NULLIF(current_setting('app.current_tenant_id', true), '')::uuid;
$$ LANGUAGE sql STABLE;

-- 2. Habilitar RLS en cada tabla de negocio
ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE cfdi_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE payroll_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE client_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_config ENABLE ROW LEVEL SECURITY;

-- 3. Políticas: solo ven filas de su tenant
CREATE POLICY tenant_isolation_invoices ON invoices
  USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_cfdi ON cfdi_documents
  USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_payroll ON payroll_entries
  USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_audit ON audit_entries
  USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_users ON client_users
  USING (tenant_id = current_tenant_id());

CREATE POLICY tenant_isolation_config ON tenant_config
  USING (tenant_id = current_tenant_id());

-- 4. Permisos: la app NO puede bypassear RLS
-- El rol de la app NO tiene BYPASSRLS
-- Solo superuser puede ver todo (para admin scripts)
```

#### Middleware FastAPI que setea el tenant en cada request:

```python
# b2b_ai/middleware/tenant_context.py
"""
Middleware que extrae el tenant_id del JWT/API key y lo setea
en el contexto de PostgreSQL para que RLS filtre automáticamente.
"""
from __future__ import annotations

import contextvars
from typing import Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# Context var thread-safe para el tenant_id del request actual
_current_tenant_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_tenant_id", default=None
)

def get_current_tenant_id() -> Optional[str]:
    """Obtiene el tenant_id del request actual (desde context var)."""
    return _current_tenant_id.get()


class TenantContextMiddleware(BaseHTTPMiddleware):
    """
    Extrae tenant_id del JWT o X-Tenant-ID header y lo inyecta en:
    1. Context variable de Python (para código de la app)
    2. SET LOCAL de PostgreSQL (para RLS)
    """

    # Rutas que no requieren tenant (health, docs, login)
    TENANT_FREE_PATHS = {"/health", "/docs", "/openapi.json", "/login", "/register"}

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Rutas públicas no necesitan tenant
        if any(path.startswith(p) for p in self.TENANT_FREE_PATHS):
            return await call_next(request)

        # Extraer tenant_id del JWT (inyectado por auth middleware)
        tenant_id = getattr(request.state, "tenant_id", None)

        if not tenant_id:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=403,
                content={"detail": "Tenant no especificado o inválido"},
            )

        # Setear context var
        token = _current_tenant_id.set(tenant_id)

        # Inyectar en la conexión PG para RLS
        db = request.app.state.db
        if db and hasattr(db, "conn") and db.conn:
            try:
                db.conn.execute(
                    "SET LOCAL app.current_tenant_id = %s", [str(tenant_id)]
                )
            except Exception:
                pass  # SQLite: ignora SET LOCAL

        try:
            response = await call_next(request)
            return response
        finally:
            _current_tenant_id.reset(token)
```

### 1.2 Datos Fiscales Sensibles — Manejo

Los datos fiscales en México (RFC, nómina, CFDI) tienen clasificación especial bajo LFPDPPP y el CFF:

| Dato | Clasificación | Cifrado | Retención |
|------|--------------|---------|-----------|
| RFC (Registro Federal de Contribuyentes) | Dato personal identificativo | AES-256-GCM en reposo | 5 años (CFF Art. 30) |
| CFDI (XML firmado) | Documento fiscal | Integridad SHA-256 + firma digital SAT | 5 años (CFF Art. 30) |
| Nómina (percepciones/deducciones) | Dato personal sensible | AES-256-GCM en reposo | 5 años (CFF Art. 30) |
| FIEL/CSD (certificados digitales) | Dato crítico (acceso fiscal) | AES-256-GCM + HSM | Vigencia del certificado |
| Curp | Dato biométrico (equiparado) | AES-256-GCM en reposo | 5 años |
| Salario / compensación | Dato personal sensible | AES-256-GCM en reposo | 5 años |

#### Modelo de cifrado en reposo:

```python
# b2b_ai/api/security.py (ya existe en el proyecto — extender para fiscal)
"""
Encriptación AES-256-GCM para campos sensibles en la DB.

Usa B2B_ENCRYPTION_KEY (env var, 32 bytes base64) como key master.
Cada campo cifrado almacena: nonce (12 bytes) + tag (16 bytes) + ciphertext.
"""
from __future__ import annotations

import base64
import os
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_KEY_ENV = "B2B_ENCRYPTION_KEY"

def _get_key() -> bytes:
    """Lee la key de entorno. Debe ser base64 de 32 bytes."""
    raw = os.environ.get(_KEY_ENV, "")
    if not raw:
        raise RuntimeError(f"{_KEY_ENV} no configurada. Genera con: openssl rand -base64 32")
    return base64.b64decode(raw)


def encrypt_field(plaintext: str) -> str:
    """Cifra un string y devuelve base64(nonce + tag + ciphertext)."""
    key = _get_key()
    aes = AESGCM(key)
    nonce = os.urandom(12)  # 96 bits, recomendado por NIST
    ct = aes.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt_field(token: str) -> str:
    """Descifra un token generado por encrypt_field()."""
    key = _get_key()
    aes = AESGCM(key)
    raw = base64.b64decode(token)
    nonce, ct = raw[:12], raw[12:]
    return aes.decrypt(nonce, ct, None).decode("utf-8")


# --- Extensión para campos fiscales ---

FISCAL_SENSITIVE_FIELDS = {
    "rfc",              # Registro Federal de Contribuyentes
    "curp",             # Clave Única de Registro de Población
    "salary",           # Salario bruto
    "csd_password",     # Contraseña del CSD (certificado de sello digital)
    "fiel_password",    # Contraseña de la FIEL
    "bank_account",     # CLABE / cuenta bancaria
    "tax_id",           # ID fiscal extranjero
}

def encrypt_fiscal_field(field_name: str, value: str) -> str:
    """Cifra un campo fiscal sensible. Lanza si no hay key."""
    if field_name not in FISCAL_SENSITIVE_FIELDS:
        return value  # No sensible: se guarda en claro
    return encrypt_field(value)


def decrypt_fiscal_field(field_name: str, value: str) -> str:
    """Descifra un campo fiscal sensible."""
    if field_name not in FISCAL_SENSITIVE_FIELDS:
        return value
    return decrypt_field(value)
```

### 1.3 Auditoría Completa — Quién, Qué, Cuándo

El sistema ya tiene un `AuditTrail` en `b2b_ai/audit/trail.py`. Para producción, extender con:

```python
# b2b_ai/audit/models.py — Modelo de auditoría para cumplimiento fiscal
"""
Tabla audit_entries almacena TODA acción sobre datos fiscales.

Campos:
  - id: serial PK
  - tenant_id: uuid FK → tenants (RLS filtrado)
  - user_id: uuid FK → client_users
  - action: varchar — CREATE, READ, UPDATE, DELETE, APPROVE, EXPORT, SIGN
  - resource: varchar — 'invoice', 'cfdi', 'payroll', 'report', 'config'
  - resource_id: varchar — ID del recurso afectado
  - details: jsonb — diff antes/después, metadata
  - ip: inet — IP del cliente
  - user_agent: varchar
  - session_id: varchar — para correlación
  - created_at: timestamptz DEFAULT now()

Índices:
  - (tenant_id, created_at) — queries de auditoría por tenant
  - (user_id, created_at) — trazabilidad por usuario
  - (resource, resource_id) — historial de un recurso
"""
from __future__ import annotations
import enum
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class Actions(str, enum.Enum):
    """Acciones auditables."""
    CREATE = "CREATE"
    READ = "READ"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    EXPORT = "EXPORT"
    SIGN = "SIGN"          # Firma digital CFDI
    CANCEL = "CANCEL"      # Cancelación de CFDI
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    DOWNLOAD = "DOWNLOAD"
    UPLOAD = "UPLOAD"
    CONFIG_CHANGE = "CONFIG_CHANGE"
    ROLE_CHANGE = "ROLE_CHANGE"
    BULK_OPERATION = "BULK_OPERATION"


@dataclass
class AuditEntry:
    """Entrada de auditoría."""
    id: Optional[int] = None
    tenant_id: str = ""
    user_id: str = ""
    action: str = ""
    resource: str = ""
    resource_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    ip: Optional[str] = None
    user_agent: Optional[str] = None
    session_id: Optional[str] = None
    created_at: Optional[str] = None


# --- SQL de creación de tabla (PostgreSQL) ---
AUDIT_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS audit_entries (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     UUID NOT NULL REFERENCES tenants(id),
    user_id       UUID NOT NULL,
    action        VARCHAR(32) NOT NULL,
    resource      VARCHAR(64) NOT NULL,
    resource_id   VARCHAR(128),
    details       JSONB,
    ip            INET,
    user_agent    TEXT,
    session_id    VARCHAR(64),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Índices para queries de auditoría
CREATE INDEX IF NOT EXISTS idx_audit_tenant_created
    ON audit_entries (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_user_created
    ON audit_entries (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_resource
    ON audit_entries (resource, resource_id);

CREATE INDEX IF NOT EXISTS idx_audit_action
    ON audit_entries (action, created_at DESC);

-- Habilitar RLS
ALTER TABLE audit_entries ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_audit ON audit_entries
    USING (tenant_id = current_tenant_id());

-- La tabla de auditoría es APPEND-ONLY: no se permite UPDATE ni DELETE
CREATE OR REPLACE FUNCTION prevent_audit_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_entries es append-only: no se permite UPDATE ni DELETE';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_no_update
    BEFORE UPDATE ON audit_entries
    FOR EACH ROW EXECUTE FUNCTION prevent_audit_mutation();

CREATE TRIGGER audit_no_delete
    BEFORE DELETE ON audit_entries
    FOR EACH ROW EXECUTE FUNCTION prevent_audit_mutation();
"""
```

### 1.4 Backup y Disaster Recovery

```yaml
# scripts/backup-strategy.yml
# Estrategia de backup para datos fiscales

backup:
  # --- PostgreSQL (datos transaccionales) ---
  postgres:
    # Backup completo diario a las 2 AM (hora CDMX)
    full:
      schedule: "0 7 * * *"       # 7 UTC = 2 AM CDMX (UTC-5)
      retention_days: 30
      tool: pg_dump
      compression: gzip
      destination: s3://likida-backups/postgres/full/

    # WAL archiving continuo (point-in-time recovery)
    wal_archiving:
      enabled: true
      destination: s3://likida-backups/postgres/wal/
      retention_days: 7

    # Backup incremental cada 6 horas
    incremental:
      schedule: "0 */6 * * *"
      retention_days: 14
      tool: pg_basebackup

  # --- CFDI XMLs (documentos firmados) ---
  cfdi_documents:
    # Los XMLs firmados son inmutables: backup a S3 con versioning
    strategy: s3_versioning
    bucket: s3://likida-cfdi-archive/
    encryption: AES-256          # Server-side encryption
    retention_years: 5           # CFF Art. 30: mínimo 5 años
    lifecycle:
      - transition_glacier: 90d  # Mover a Glacier después de 90 días
      - expiration: never        # Nunca expirar (obligación legal)

  # --- Certificados FIEL/CSD ---
  csd_certificates:
    strategy: encrypted_vault
    # NUNCA en S3 plano. Usar AWS Secrets Manager o HashiCorp Vault
    tool: aws_secrets_manager
    rotation: on_renewal         # Rotar al renovar certificado

  # --- Claves de cifrado (B2B_ENCRYPTION_KEY) ---
  encryption_keys:
    strategy: hsm_or_kms
    tool: aws_kms
    rotation_days: 90
    # Si se pierde la key, los datos cifrados son IRRECUPERABLES
    # Mantener backup de la key en 2 ubicaciones físicas separadas

# --- Disaster Recovery ---
disaster_recovery:
  rpo: "1 hora"    # Recovery Point Objective: máximo 1 hora de datos perdidos
  rto: "4 horas"   # Recovery Time Objective: máximo 4 horas de downtime

  procedure:
    - step: "1. Activar réplica standby en región alterna"
      tool: "pg_promote"
      timeout: "5 min"

    - step: "2. Restaurar último WAL completo"
      tool: "pg_restore --target-time='latest'"
      timeout: "30 min"

    - step: "3. Verificar integridad de CFDIs (checksums)"
      tool: "python -m b2b_ai.scripts.verify_cfdi_integrity"
      timeout: "15 min"

    - step: "4. Actualizar DNS a nueva región"
      tool: "aws route53 change-resource-record-sets"
      timeout: "5 min (propagación DNS)"

    - step: "5. Notificar a despachos afectados"
      tool: "webhook + email"
```

#### Script de backup automatizado:

```bash
#!/usr/bin/env bash
# scripts/backup-postgres.sh — Backup diario de PostgreSQL
# Ejecutar via cron: 0 7 * * * /app/scripts/backup-postgres.sh

set -euo pipefail

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/backups/postgres"
S3_BUCKET="${BACKUP_S3_BUCKET:-s3://likida-backups/postgres/full}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

mkdir -p "$BACKUP_DIR"

echo "[$TIMESTAMP] Iniciando backup de PostgreSQL..."

# Backup con pg_dump (custom format para restore selectivo)
pg_dump \
  -h "$POSTGRES_HOST" \
  -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" \
  -Fc \
  -Z 9 \
  --verbose \
  -f "$BACKUP_DIR/backup_${TIMESTAMP}.dump" 2>&1

# Verificar integridad del dump
pg_restore -l "$BACKUP_DIR/backup_${TIMESTAMP}.dump" > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "[$TIMESTAMP] ✅ Backup verificado OK"
else
    echo "[$TIMESTAMP] ❌ ERROR: Backup corrupto" >&2
    exit 1
fi

# Comprimir y subir a S3
gzip "$BACKUP_DIR/backup_${TIMESTAMP}.dump"
aws s3 cp "$BACKUP_DIR/backup_${TIMESTAMP}.dump.gz" "$S3_BUCKET/" \
  --sse AES256 \
  --storage-class STANDARD_IA

echo "[$TIMESTAMP] ✅ Backup subido a $S3_BUCKET/"

# Limpiar backups locales antiguos
find "$BACKUP_DIR" -name "*.dump.gz" -mtime +$RETENTION_DAYS -delete
echo "[$TIMESTAMP] 🧹 Backups locales >${RETENTION_DAYS} días eliminados"

# Verificar que el backup en S3 es accesible
aws s3 ls "$S3_BUCKET/backup_${TIMESTAMP}.dump.gz" > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "[$TIMESTAMP] ✅ Backup en S3 verificado"
else
    echo "[$TIMESTAMP] ⚠️  WARNING: Backup no encontrado en S3" >&2
    exit 1
fi
```

### 1.5 Retención de Datos — CFF Art. 30

```python
# b2b_ai/services/data_retention.py
"""
Servicio de retención de datos conforme al Código Fiscal de la Federación.

CFF Art. 30: Los contribuyentes están obligados a conservar toda la
documentación relacionada con el cumplimiento de las disposiciones fiscales,
incluyendo contabilidad, CFDIs, y comprobantes de nómina, por un período
mínimo de 5 CONTANDO DESDE la fecha de presentación de la declaración
anual correspondiente.

En la práctica: los CFDIs de 2024 deben conservarse hasta abril de 2030
(la declaración anual de 2024 se presenta en abril 2025, + 5 años = 2030).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


class RetentionPolicy(str, Enum):
    """Políticas de retención por tipo de documento."""
    CFDI = "cfdi"                     # 5 años desde declaración anual
    NOMINA = "nomina"                 # 5 años desde declaración anual
    CONTABILIDAD = "contabilidad"     # 5 años desde declaración anial
    CONTRATOS = "contratos"           # 10 años (Ley Federal del Trabajo)
    FIEL_CSD = "fiel_csd"            # Vigencia del certificado + 5 años
    AUDITORIA = "auditoria"           # 5 años (o indefinido para compliance)


# Año fiscal → fecha límite de conservación (declaración anual + 5 años)
# Ejemplo: 2024 → declaración abril 2025 → conservar hasta abril 2030
RETENTION_YEARS = {
    RetentionPolicy.CFDI: 5,
    RetentionPolicy.NOMINA: 5,
    RetentionPolicy.CONTABILIDAD: 5,
    RetentionPolicy.CONTRATOS: 10,
    RetentionPolicy.FIEL_CSD: 8,      # 3 años vigencia + 5 retención
    RetentionPolicy.AUDITORIA: 5,
}


def retention_deadline(fiscal_year: int, policy: RetentionPolicy) -> datetime:
    """
    Calcula la fecha límite de conservación.

    Para CFDI/Nómina/Contabilidad: declaración anual (abril del año siguiente)
    + 5 años.
    """
    years = RETENTION_YEARS[policy]

    if policy in (RetentionPolicy.CFDI, RetentionPolicy.NOMINA,
                  RetentionPolicy.CONTABILIDAD):
        # Declaración anual: 30 de abril del año siguiente
        declaration_date = datetime(fiscal_year + 1, 4, 30, tzinfo=timezone.utc)
        return declaration_date + timedelta(days=365 * years)
    else:
        # Otras políticas: desde fin del año fiscal
        return datetime(fiscal_year + 1, 12, 31, tzinfo=timezone.utc) + timedelta(days=365 * years)


def check_documents_approaching_expiry(
    db, tenant_id: str, warning_days: int = 90
) -> List[Dict]:
    """
    Documentos que expiran pronto (para alertar al despacho).
    NUNCA auto-eliminar documentos fiscales — solo alertar.
    """
    now = datetime.now(timezone.utc)
    warning_date = now + timedelta(days=warning_days)

    # Query: documentos con fecha de retención próxima
    rows = db.conn.execute("""
        SELECT id, resource, resource_id, created_at, fiscal_year,
               retention_policy, retention_deadline
        FROM document_retention
        WHERE tenant_id = %s
          AND retention_deadline <= %s
          AND retention_deadline > %s
          AND status != 'archived'
        ORDER BY retention_deadline ASC
    """, [tenant_id, warning_date, now]).fetchall()

    return [dict(r) for r in rows]


def archive_expired_documents(db, tenant_id: str) -> Tuple[int, List[str]]:
    """
    Marca documentos expirados como 'archived' (soft delete).

    IMPORTANTE: NUNCA borrar documentos fiscales. Solo marcar como archived.
    La eliminación física solo se hace bajo orden judicial o autorización
    expresa del contribuyente, y se audita.
    """
    now = datetime.now(timezone.utc)

    result = db.conn.execute("""
        UPDATE document_retention
        SET status = 'archived',
            archived_at = %s,
            archived_reason = 'retention_policy_expired'
        WHERE tenant_id = %s
          AND retention_deadline <= %s
          AND status = 'active'
        RETURNING id, resource, resource_id
    """, [now, tenant_id, now])

    archived = result.fetchall()
    db.conn.commit()

    # Auditar cada archivo
    from b2b_ai.audit.trail import AuditTrail
    audit = AuditTrail(db)
    for row in archived:
        audit.log_action(
            user_id="system",
            tenant_id=tenant_id,
            action="ARCHIVE",
            resource=row["resource"],
            resource_id=row["resource_id"],
            details={"reason": "retention_policy_expired"},
        )

    logger.info(f"Archivados {len(archived)} documentos para tenant {tenant_id}")
    return len(archived), [r["resource_id"] for r in archived]
```

---

## 2. Escala para Despachos

### 2.1 Perfiles de Despacho

| Perfil | Clientes | CFDIs/mes | Nóminas/mes | DB estimada | Concurrent users |
|--------|----------|-----------|-------------|-------------|------------------|
| **Chico** | 10-50 | 100-500 | 50-200 | <1 GB | 2-5 |
| **Mediano** | 50-200 | 500-5,000 | 200-1,000 | 1-10 GB | 5-20 |
| **Grande** | 200-500 | 5,000-20,000 | 1,000-5,000 | 10-50 GB | 20-50 |
| **Enterprise** | 500+ | 20,000+ | 5,000+ | 50+ GB | 50+ |

### 2.2 Batch Processing — Miles de CFDIs Sin Colgar

```python
# b2b_ai/services/batch_processor.py
"""
Procesador batch de CFDIs con backpressure y resiliencia.

Estrategia:
  1. Recibir batch (100-10,000 CFDIs)
  2. Chunking: dividir en lotes de 50 (para no saturar DB ni API)
  3. Procesar cada chunk con retry exponencial
  4. Reportar progreso via WebSocket / polling endpoint
  5. Almacenar resultados parciales (no perder trabajo si falla)
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class BatchStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    PARTIAL = "partial"      # Algunos chunks fallaron
    FAILED = "failed"


@dataclass
class BatchJob:
    """Estado de un batch job."""
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str = ""
    total_items: int = 0
    processed_items: int = 0
    failed_items: int = 0
    status: BatchStatus = BatchStatus.PENDING
    errors: List[Dict[str, Any]] = field(default_factory=list)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    results: List[Any] = field(default_factory=list)


class BatchProcessor:
    """
    Procesador batch con concurrencia controlada y resiliencia.

    Configuración para diferentes escenarios:
      - Despacho chico (100 CFDIs): chunk_size=20, concurrency=2
      - Despacho mediano (5000 CFDIs): chunk_size=50, concurrency=5
      - Despacho grande (20000 CFDIs): chunk_size=100, concurrency=10
    """

    def __init__(
        self,
        chunk_size: int = 50,
        max_concurrency: int = 5,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        backoff_factor: float = 2.0,
    ):
        self.chunk_size = chunk_size
        self.max_concurrency = max_concurrency
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.backoff_factor = backoff_factor
        self._jobs: Dict[str, BatchJob] = {}
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def submit_batch(
        self,
        tenant_id: str,
        items: List[Any],
        processor: Callable,
    ) -> str:
        """
        Envía un batch para procesamiento asíncrono.
        Retorna job_id inmediatamente.
        """
        job = BatchJob(
            tenant_id=tenant_id,
            total_items=len(items),
        )
        self._jobs[job.job_id] = job

        # Disparar procesamiento en background
        asyncio.create_task(self._process_batch(job, items, processor))

        return job.job_id

    async def _process_batch(
        self, job: BatchJob, items: List[Any], processor: Callable
    ):
        """Procesa el batch completo en chunks."""
        job.status = BatchStatus.PROCESSING
        job.started_at = time.monotonic()

        # Dividir en chunks
        chunks = [
            items[i:i + self.chunk_size]
            for i in range(0, len(items), self.chunk_size)
        ]

        logger.info(
            f"Batch {job.job_id}: {len(items)} items → {len(chunks)} chunks "
            f"(chunk_size={self.chunk_size}, concurrency={self.max_concurrency})"
        )

        # Procesar chunks con concurrencia limitada
        tasks = [
            self._process_chunk(job, chunk_idx, chunk, processor)
            for chunk_idx, chunk in enumerate(chunks)
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

        # Determinar estado final
        job.completed_at = time.monotonic()
        if job.failed_items == 0:
            job.status = BatchStatus.COMPLETED
        elif job.processed_items > 0:
            job.status = BatchStatus.PARTIAL
        else:
            job.status = BatchStatus.FAILED

        duration = job.completed_at - job.started_at
        rate = job.processed_items / duration if duration > 0 else 0
        logger.info(
            f"Batch {job.job_id}: {job.status.value} — "
            f"{job.processed_items}/{job.total_items} OK, "
            f"{job.failed_items} fallos, "
            f"{duration:.1f}s ({rate:.0f} items/s)"
        )

    async def _process_chunk(
        self,
        job: BatchJob,
        chunk_idx: int,
        chunk: List[Any],
        processor: Callable,
    ):
        """Procesa un chunk con retry exponencial."""
        async with self._semaphore:
            for item_idx, item in enumerate(chunk):
                global_idx = chunk_idx * self.chunk_size + item_idx

                for attempt in range(self.max_retries):
                    try:
                        result = await processor(item)
                        job.processed_items += 1
                        job.results.append(result)
                        break
                    except Exception as e:
                        if attempt == self.max_retries - 1:
                            job.failed_items += 1
                            job.errors.append({
                                "index": global_idx,
                                "error": str(e),
                                "attempts": attempt + 1,
                            })
                            logger.warning(
                                f"Batch {job.job_id} item {global_idx}: "
                                f"FALLO después de {attempt + 1} intentos: {e}"
                            )
                        else:
                            delay = self.retry_delay * (self.backoff_factor ** attempt)
                            await asyncio.sleep(delay)

    def get_job(self, job_id: str) -> Optional[BatchJob]:
        """Obtiene el estado de un batch job."""
        return self._jobs.get(job_id)

    def get_progress(self, job_id: str) -> Dict[str, Any]:
        """Progreso del batch (para polling/WebSocket)."""
        job = self._jobs.get(job_id)
        if not job:
            return {"error": "Job not found"}

        elapsed = 0
        if job.started_at:
            end = job.completed_at or time.monotonic()
            elapsed = end - job.started_at

        return {
            "job_id": job.job_id,
            "status": job.status.value,
            "total": job.total_items,
            "processed": job.processed_items,
            "failed": job.failed_items,
            "progress_pct": round(
                (job.processed_items + job.failed_items) / max(job.total_items, 1) * 100, 1
            ),
            "elapsed_seconds": round(elapsed, 1),
            "rate_per_second": round(
                job.processed_items / max(elapsed, 0.001), 1
            ),
            "errors": job.errors[-10:],  # Últimos 10 errores
        }
```

### 2.3 Cola de Trabajo — Celery vs arq vs RQ

| Característica | Celery | arq | RQ |
|---------------|--------|-----|-----|
| **Async nativo** | No (usa threads/gevent) | ✅ Sí (asyncio) | No (fork-based) |
| **Redis backend** | ✅ | ✅ | ✅ |
| **PostgreSQL backend** | ✅ (django-celery) | ❌ | ❌ |
| **Scheduled tasks** | ✅ Celery Beat | ✅ built-in | ❌ (necesita rq-scheduler) |
| **Monitoring** | ✅ Flower | ❌ básico | ✅ rq-dashboard |
| **Retries** | ✅ avanzado | ✅ básico | ✅ básico |
| **Rate limiting** | ✅ built-in | ❌ manual | ❌ manual |
| **Result backend** | ✅ | ✅ | ✅ |
| **Chains/Groups** | ✅ Canvas | ❌ | ❌ |
| **Mature/SO** | Muy maduro | Joven, creciendo | Maduro |
| **Footprint** | Pesado (~100MB deps) | Liviano (~5MB) | Mediano |

#### Decisión: **Celery** para producción

Para despachos contables reales necesitamos:
- Retries avanzados con backoff (APIs del SAT son inconsistentes)
- Rate limiting (PACs tienen límites de timbrado)
- Scheduled tasks (declaraciones mensuales, recordatorios)
- Monitoring robusto (Flower)
- Chains (pipeline: parse → validate → classify → reconcile → report)

```python
# b2b_ai/tasks/celery_app.py
"""
Configuración de Celery para Likida AI.
Optimizada para workloads fiscales: batches de CFDIs, nómina, reportes.
"""
from __future__ import annotations

import os
from celery import Celery
from celery.schedules import crontab

# Broker y backend
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

app = Celery(
    "likida",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "b2b_ai.tasks.cfdi_tasks",
        "b2b_ai.tasks.payroll_tasks",
        "b2b_ai.tasks.report_tasks",
        "b2b_ai.tasks.sat_sync_tasks",
    ],
)

# --- Configuración ---
app.conf.update(
    # Serialización
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="America/Mexico_City",
    enable_utc=True,

    # Resultados: expirar después de 24 horas
    result_expires=86400,

    # Worker: prefetch 1 (para fairness entre tenants)
    worker_prefetch_multiplier=1,

    # Rate limits globales
    task_default_rate_limit="100/m",  # 100 tareas/minuto default

    # Retry policy
    task_default_retry_delay=30,      # 30 segundos entre reintentos
    task_max_retries=5,

    # Acknowledgement: acks_late para no perder tareas si worker muere
    task_acks_late=True,

    # Re-queue si worker muere con tarea en progreso
    task_reject_on_worker_lost=True,

    # Concurrency (workers por proceso)
    worker_concurrency=int(os.environ.get("CELERY_CONCURRENCY", "4")),

    # Prefetch: 1 para fairness (no un worker acapare todo un tenant)
    worker_prefetch_multiplier=1,
)

# --- Rate limits específicos por tarea ---
TASK_RATE_LIMITS = {
    # Timbrado PAC: máximo 100/min (la mayoría de PACs tienen este límite)
    "b2b_ai.tasks.cfdi_tasks.stamp_cfdi": "100/m",
    # Consulta SAT: máximo 30/min (el SAT limita agresivamente)
    "b2b_ai.tasks.sat_sync_tasks.query_sat_status": "30/m",
    # Cancelación SAT: máximo 20/min
    "b2b_ai.tasks.sat_sync_tasks.cancel_cfdi": "20/m",
    # Procesamiento batch: sin límite (workload interno)
    "b2b_ai.tasks.cfdi_tasks.process_cfdi_batch": "500/m",
    # Generación de reportes: 10/min (son pesados)
    "b2b_ai.tasks.report_tasks.generate_report": "10/m",
}

for task_name, rate_limit in TASK_RATE_LIMITS.items():
    app.conf.task_rate_limits = getattr(app.conf, "task_rate_limits", {})
    # Se aplica por tarea con el decorador @task(rate_limit=...)

# --- Scheduled tasks (Celery Beat) ---
app.conf.beat_schedule = {
    # Sincronización con SAT: cada 6 horas
    "sync-sat-cfdi-status": {
        "task": "b2b_ai.tasks.sat_sync_tasks.sync_all_pending_cfdi",
        "schedule": crontab(hour="*/6", minute=0),
        "kwargs": {"dry_run": False},
    },
    # Declaraciones mensuales: primer día de cada mes
    "monthly-declarations-reminder": {
        "task": "b2b_ai.tasks.report_tasks.send_declaration_reminders",
        "schedule": crontab(day_of_month=1, hour=9, minute=0),
    },
    # Backup de datos: diario a las 3 AM CDMX
    "daily-backup": {
        "task": "b2b_ai.tasks.maintenance_tasks.run_backup",
        "schedule": crontab(hour=8, minute=0),  # 8 UTC = 3 AM CDMX
    },
    # Limpieza de datos temporales: semanal
    "weekly-cleanup": {
        "task": "b2b_ai.tasks.maintenance_tasks.cleanup_temp_data",
        "schedule": crontab(day_of_week=0, hour=4, minute=0),
    },
    # Monitoreo de certificados CSD: diario
    "check-csd-expiry": {
        "task": "b2b_ai.tasks.sat_sync_tasks.check_certificate_expiry",
        "schedule": crontab(hour=10, minute=0),  # 10 UTC = 5 AM CDMX
    },
}
```

#### Tareas de CFDI con Celery:

```python
# b2b_ai/tasks/cfdi_tasks.py
"""
Tareas Celery para procesamiento de CFDIs.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from celery import shared_task, chain, group

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    rate_limit="100/m",       # PAC timbrado: max 100/min
    max_retries=5,
    default_retry_delay=60,   # 1 min entre reintentos
    acks_late=True,
    time_limit=300,           # 5 min timeout por CFDI
    soft_time_limit=240,      # Soft timeout: 4 min (lança SoftTimeLimitExceeded)
)
def stamp_cfdi(self, cfdi_data: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
    """
    Timbra un CFDI con el PAC.
    Rate limit: 100/min (la mayoría de PACs tienen este límite).
    """
    try:
        from b2b_ai.cfdi.validator import validate_cfdi_xml
        from b2b_ai.integrations.pac_client import PACClient

        # 1. Validar XML localmente antes de enviar al PAC
        validation = validate_cfdi_xml(cfdi_data["xml"])
        if not validation["valid"]:
            return {"status": "error", "errors": validation["errors"]}

        # 2. Enviar al PAC para timbrado
        pac = PACClient(tenant_id=tenant_id)
        result = pac.stamp(cfdi_data["xml"])

        # 3. Registrar resultado
        from b2b_ai.monitoring.metrics import metrics
        metrics.inc_invoices()

        return {
            "status": "stamped",
            "uuid": result["uuid"],
            "stamp_date": result["stamp_date"],
            "tfd": result["tfd"],  # Timbre Fiscal Digital
        }

    except Exception as exc:
        logger.error(f"Error timbrando CFDI: {exc}")
        # Reintentar con backoff exponencial
        raise self.retry(
            exc=exc,
            countdown=60 * (2 ** self.request.retries),  # 60s, 120s, 240s...
        )


@shared_task(
    bind=True,
    rate_limit="500/m",
    max_retries=3,
    time_limit=600,           # 10 min para batches grandes
)
def process_cfdi_batch(
    self, cfdi_ids: List[str], tenant_id: str
) -> Dict[str, Any]:
    """
    Procesa un batch de CFDIs: parse → validate → classify → store.
    """
    results = {"processed": 0, "failed": 0, "errors": []}

    for cfdi_id in cfdi_ids:
        try:
            # Crear pipeline: parse → validate → classify → store
            pipeline = chain(
                parse_cfdi.s(cfdi_id, tenant_id),
                validate_cfdi.s(tenant_id),
                classify_cfdi.s(tenant_id),
                store_cfdi.s(tenant_id),
            )
            pipeline.apply_async()
            results["processed"] += 1
        except Exception as e:
            results["failed"] += 1
            results["errors"].append({"cfdi_id": cfdi_id, "error": str(e)})

    return results


@shared_task(bind=True, rate_limit="500/m", time_limit=120)
def parse_cfdi(self, cfdi_id: str, tenant_id: str) -> Dict[str, Any]:
    """Parsea un XML de CFDI y extrae campos clave."""
    from b2b_ai.cfdi.parser import parse_cfdi_xml
    from b2b_ai.db.db import Database

    db = Database()
    row = db.conn.execute(
        "SELECT xml_content FROM cfdi_documents WHERE id = %s AND tenant_id = %s",
        [cfdi_id, tenant_id]
    ).fetchone()

    if not row:
        raise ValueError(f"CFDI {cfdi_id} no encontrado")

    return parse_cfdi_xml(row["xml_content"])


@shared_task(bind=True, rate_limit="500/m", time_limit=60)
def validate_cfdi(self, parsed: Dict, tenant_id: str) -> Dict:
    """Valida un CFDI parseado contra esquemas SAT."""
    from b2b_ai.cfdi.validator import validate_parsed_cfdi
    return validate_parsed_cfdi(parsed)


@shared_task(bind=True, rate_limit="500/m", time_limit=60)
def classify_cfdi(self, validated: Dict, tenant_id: str) -> Dict:
    """Clasifica un CFDI (tipo, categoría contable, régimen)."""
    from b2b_ai.services.classifier import classify_invoice
    return classify_invoice(validated, tenant_id)


@shared_task(bind=True, rate_limit="500/m", time_limit=60)
def store_cfdi(self, classified: Dict, tenant_id: str) -> Dict:
    """Almacena un CFDI clasificado en la base de datos."""
    from b2b_ai.db.db import Database

    db = Database()
    db.conn.execute("""
        INSERT INTO cfdi_documents
            (tenant_id, uuid, rfc_emisor, rfc_receptor, total, fecha,
             tipo, clasificacion, regimen, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'processed')
        ON CONFLICT (uuid) DO UPDATE SET
            clasificacion = EXCLUDED.clasificacion,
            status = 'processed',
            updated_at = now()
    """, [
        tenant_id, classified["uuid"], classified["rfc_emisor"],
        classified["rfc_receptor"], classified["total"], classified["fecha"],
        classified["tipo"], classified["clasificacion"], classified["regimen"],
    ])
    db.conn.commit()

    return {"status": "stored", "uuid": classified["uuid"]}
```

### 2.4 Rate Limits de APIs SAT / PACs

```python
# b2b_ai/services/rate_limiter.py
"""
Rate limiter distribuido con Redis para APIs del SAT y PACs.

Límites documentados:
  - SAT Consulta CFDI: ~30 req/min (no oficial, basado en experiencia)
  - SAT Cancelación: ~20 req/min
  - PAC Timbrado (Facturapi): 100 req/min (documentado)
  - PAC Timbrado (SW Sapien): 50 req/min (documentado)
  - PAC Timbrado (Finkok): 200 req/min (documentado)
"""
from __future__ import annotations

import time
import logging
from typing import Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class DistributedRateLimiter:
    """
    Rate limiter basado en sliding window con Redis.
    Thread-safe y multi-process safe.
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis: Optional[aioredis.Redis] = None
        self.redis_url = redis_url

    async def connect(self):
        self.redis = aioredis.from_url(self.redis_url, decode_responses=True)

    async def check_rate_limit(
        self,
        key: str,
        max_requests: int,
        window_seconds: int = 60,
    ) -> bool:
        """
        Verifica si una request está dentro del rate limit.
        Retorna True si permitido, False si limit exceeded.
        """
        if not self.redis:
            await self.connect()

        now = time.time()
        pipe = self.redis.pipeline()

        # Sliding window: eliminar entradas viejas y agregar la actual
        window_start = now - window_seconds
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, window_seconds)

        results = await pipe.execute()
        current_count = results[2]

        if current_count > max_requests:
            logger.warning(
                f"Rate limit excedido para {key}: "
                f"{current_count}/{max_requests} en {window_seconds}s"
            )
            return False

        return True

    async def wait_for_slot(
        self,
        key: str,
        max_requests: int,
        window_seconds: int = 60,
        max_wait: float = 30.0,
    ) -> bool:
        """Espera hasta que haya un slot disponible."""
        start = time.time()
        while time.time() - start < max_wait:
            if await self.check_rate_limit(key, max_requests, window_seconds):
                return True
            await asyncio.sleep(0.5)  # Esperar 500ms antes de reintentar
        return False


# Límites por servicio
RATE_LIMITS = {
    "sat:consulta": {"max": 30, "window": 60},
    "sat:cancelacion": {"max": 20, "window": 60},
    "pac:facturapi:stamp": {"max": 100, "window": 60},
    "pac:swsapien:stamp": {"max": 50, "window": 60},
    "pac:finkok:stamp": {"max": 200, "window": 60},
}


async def check_sat_rate_limit(operation: str = "consulta") -> bool:
    """Shortcut para verificar límites del SAT."""
    limiter = DistributedRateLimiter()
    config = RATE_LIMITS.get(f"sat:{operation}", {"max": 30, "window": 60})
    return await limiter.check_rate_limit(
        f"sat:{operation}", config["max"], config["window"]
    )
```

---

## 3. Seguridad Financiera

### 3.1 Encriptación de Datos

#### En tránsito:

```nginx
# nginx/nginx.conf — TLS 1.3 obligatorio
server {
    listen 443 ssl http2;
    server_name api.likida.ai;

    # TLS 1.3 only (eliminar TLS 1.2 para máxima seguridad)
    ssl_protocols TLSv1.3;
    ssl_ciphersuites TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256;
    ssl_prefer_server_ciphers on;

    # HSTS: forzar HTTPS por 1 año
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    # OCSP Stapling
    ssl_stapling on;
    ssl_stapling_verify on;

    # Certificados
    ssl_certificate /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/privkey.pem;

    # Rate limiting
    limit_req_zone $binary_remote_addr zone=api:10m rate=30r/s;
    limit_req zone=api burst=50 nodelay;

    # Headers de seguridad
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Content-Security-Policy "default-src 'self'" always;

    location / {
        proxy_pass http://api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

#### En reposo:

```python
# b2b_ai/api/security.py — Modelo completo de cifrado
"""
Capa de seguridad para Likida AI.

Cifra en reposo:
  - AES-256-GCM para campos sensibles (RFC, nómina, CLABE)
  - Key derivada de B2B_ENCRYPTION_KEY (env var, rotación trimestral)
  - Cada campo tiene su propio nonce (nunca reutilizar)

Cifra en tránsito:
  - TLS 1.3 (configurado en nginx)
  - Certificados Let's Encrypt con auto-renewal

Cifra de certificados CSD/FIEL:
  - Almacenados en AWS Secrets Manager o HashiCorp Vault
  - Nunca en disco plano
  - Acceso auditado
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class FieldEncryption:
    """Cifrado AES-256-GCM para campos de base de datos."""

    def __init__(self, master_key: str):
        """
        master_key: base64-encoded 32 bytes.
        Generar con: openssl rand -base64 32
        """
        self._key = base64.b64decode(master_key)

    def encrypt(self, plaintext: str) -> str:
        """
        Cifra un string. Retorna base64(nonce ‖ ciphertext ‖ tag).
        El nonce (12 bytes) es único por cada cifrado.
        """
        aes = AESGCM(self._key)
        nonce = os.urandom(12)
        ct = aes.encrypt(nonce, plaintext.encode("utf-8"), None)
        # Formato: nonce (12 bytes) + ciphertext + tag (16 bytes)
        return base64.b64encode(nonce + ct).decode("ascii")

    def decrypt(self, token: str) -> str:
        """Descifra un token generado por encrypt()."""
        aes = AESGCM(self._key)
        raw = base64.b64decode(token)
        nonce, ct = raw[:12], raw[12:]
        return aes.decrypt(nonce, ct, None).decode("utf-8")


class DataIntegrity:
    """HMAC-SHA256 para verificación de integridad de CFDIs."""

    def __init__(self, signing_key: str):
        self._key = base64.b64decode(signing_key)

    def sign(self, data: bytes) -> str:
        """Genera HMAC-SHA256 de los datos."""
        sig = hmac.new(self._key, data, hashlib.sha256).digest()
        return base64.b64encode(sig).decode("ascii")

    def verify(self, data: bytes, signature: str) -> bool:
        """Verifica que los datos coincidan con la firma."""
        expected = self.sign(data)
        return hmac.compare_digest(expected, signature)
```

### 3.2 Manejo de FIEL/CSD (Certificados Digitales)

```python
# b2b_ai/services/csd_manager.py
"""
Gestión segura de Certificados de Sello Digital (CSD) y FIEL.

Los CSD son la llave del contribuyente para timbrar CFDIs.
Compromiso del CSD = cualquiera puede facturar a nombre del contribuyente.

Almacenamiento:
  - Certificado (.cer): público, puede almacenarse en DB cifrado
  - Llave privada (.key): SECRETO CRÍTICO, solo en vault (AWS Secrets Manager)
  - Contraseña del .key: SECRETO CRÍTICO, solo en vault

Flujo de vida:
  1. Despacho sube CSD al portal (HTTPS, archivos encriptados)
  2. App almacena .cer en S3 cifrado, .key + password en Secrets Manager
  3. Para timbrar: app lee .key de vault, firma, descarga de memoria
  4. .key NUNCA se escribe a disco temporal
"""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CSDInfo:
    """Información del certificado (sin datos sensibles)."""
    tenant_id: str
    serial_number: str
    rfc: str
    valid_from: datetime
    valid_until: datetime
    issuer: str
    is_active: bool


class CSDManager:
    """
    Gestor seguro de CSD/FIEL.

    Principios de seguridad:
    1. La llave privada NUNCA se almacena en la DB
    2. La llave privada NUNCA se escribe a disco
    3. La llave privada solo existe en memoria durante el timbrado
    4. Toda operación con CSD se audita
    5. Alerta 30 días antes de la expiración
    """

    def __init__(self, vault_client=None, s3_client=None):
        self.vault = vault_client  # AWS Secrets Manager / HashiCorp Vault
        self.s3 = s3_client

    async def store_csd(
        self,
        tenant_id: str,
        cer_bytes: bytes,
        key_bytes: bytes,
        key_password: str,
    ) -> CSDInfo:
        """
        Almacena un CSD de forma segura.

        .cer → S3 cifrado (público, pero encriptado por consistencia)
        .key → Secrets Manager (secreto)
        password → Secrets Manager (secreto)
        """
        # 1. Parsear certificado para obtener metadata
        cert_info = self._parse_certificate(cer_bytes)

        # 2. Almacenar .cer en S3 cifrado (AES-256 SSE)
        cer_key = f"csd/{tenant_id}/{cert_info.serial_number}.cer"
        await self.s3.put_object(
            Bucket="likida-csd-store",
            Key=cer_key,
            Body=cer_bytes,
            ServerSideEncryption="AES256",
        )

        # 3. Almacenar .key + password en Secrets Manager
        secret_id = f"likida/csd/{tenant_id}/{cert_info.serial_number}"
        await self.vault.put_secret(
            Name=secret_id,
            SecretString={
                "key_pem": base64.b64encode(key_bytes).decode(),
                "password": key_password,
            },
            Description=f"CSD para RFC {cert_info.rfc} (tenant {tenant_id})",
        )

        # 4. Registrar metadata en DB (sin datos sensibles)
        from b2b_ai.db.db import Database
        db = Database()
        db.conn.execute("""
            INSERT INTO csd_certificates
                (tenant_id, serial_number, rfc, valid_from, valid_until,
                 issuer, vault_secret_id, s3_cer_key, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true)
            ON CONFLICT (tenant_id, serial_number) DO UPDATE SET
                vault_secret_id = EXCLUDED.vault_secret_id,
                s3_cer_key = EXCLUDED.s3_cer_key,
                is_active = true
        """, [
            tenant_id, cert_info.serial_number, cert_info.rfc,
            cert_info.valid_from, cert_info.valid_until,
            cert_info.issuer, secret_id, cer_key,
        ])
        db.conn.commit()

        # 5. Auditar
        from b2b_ai.audit.trail import AuditTrail
        audit = AuditTrail(db)
        audit.log_action(
            user_id="system",
            tenant_id=tenant_id,
            action="CSD_STORED",
            resource="csd_certificate",
            resource_id=cert_info.serial_number,
            details={
                "rfc": cert_info.rfc,
                "valid_until": cert_info.valid_until.isoformat(),
            },
        )

        logger.info(
            f"CSD almacenado para tenant {tenant_id}: "
            f"RFC={cert_info.rfc}, vence={cert_info.valid_until}"
        )

        return cert_info

    async def get_signing_credentials(
        self, tenant_id: str, serial_number: str
    ) -> Tuple[bytes, bytes, str]:
        """
        Obtiene credenciales de firma para timbrado.

        IMPORTANTE: Los datos se leen de vault, se usan en memoria,
        y se borran de la memoria lo antes posible (best effort en Python).

        Returns: (cer_bytes, key_bytes, key_password)
        """
        secret_id = f"likida/csd/{tenant_id}/{serial_number}"

        # Leer de Secrets Manager
        secret = await self.vault.get_secret_value(SecretId=secret_id)
        secret_data = secret["SecretString"]

        key_bytes = base64.b64decode(secret_data["key_pem"])
        password = secret_data["password"]

        # Leer .cer de S3
        csd_record = await self._get_csd_record(tenant_id, serial_number)
        cer_obj = await self.s3.get_object(
            Bucket="likida-csd-store",
            Key=csd_record["s3_cer_key"],
        )
        cer_bytes = await cer_obj["Body"].read()

        # Auditar acceso
        from b2b_ai.db.db import Database
        from b2b_ai.audit.trail import AuditTrail
        db = Database()
        audit = AuditTrail(db)
        audit.log_action(
            user_id="system",
            tenant_id=tenant_id,
            action="CSD_ACCESSED",
            resource="csd_certificate",
            resource_id=serial_number,
        )

        return cer_bytes, key_bytes, password

    def check_expiry_alerts(self, tenant_id: str) -> list:
        """Certificados que vencen en los próximos 30 días."""
        from b2b_ai.db.db import Database
        db = Database()
        rows = db.conn.execute("""
            SELECT serial_number, rfc, valid_until
            FROM csd_certificates
            WHERE tenant_id = %s
              AND is_active = true
              AND valid_until <= NOW() + INTERVAL '30 days'
            ORDER BY valid_until ASC
        """, [tenant_id]).fetchall()

        return [dict(r) for r in rows]
```

### 3.3 RBAC — Roles y Permisos

El proyecto ya tiene un RBAC completo en `b2b_ai/auth/roles.py` con 4 roles. Para producción, extender con permisos fiscales granulares:

```python
# b2b_ai/auth/fiscal_permissions.py
"""
Permisos fiscales granulares para despachos contables.

Jerarquía de roles:
  socio/admin     → acceso total + gestión fiscal + firma
  contador        → operativa contable + aprobación + reportes
  auxiliar        → carga de datos + visualización propia
  auditor         → solo lectura + auditoría

Permisos adicionales para operaciones fiscales críticas:
"""
from __future__ import annotations

from typing import FrozenSet

# Permisos fiscales extendidos
FISCAL_PERMISSIONS: dict = {
    "admin": frozenset({
        # Permisos base (ya en roles.py)
        "users.manage",
        "invoices.view",
        "invoices.upload",
        "invoices.approve",
        "reports.generate",
        "audit.view",
        "settings.manage",
        # Permisos fiscales
        "fiscal.csd.manage",        # Gestionar certificados CSD
        "fiscal.csd.sign",          # Timbrar CFDIs (usar CSD)
        "fiscal.csd.cancel",        # Cancelar CFDIs ante SAT
        "fiscal.declarations.view", # Ver declaraciones
        "fiscal.declarations.file", # Presentar declaraciones
        "fiscal.nominas.process",   # Procesar nómina
        "fiscal.sat.sync",          # Sincronizar con SAT
        "fiscal.reports.tax",       # Reportes fiscales (DIOT, DIM)
        "fiscal.config.manage",     # Configurar parámetros fiscales
        "billing.manage",           # Gestión de cobro del servicio
    }),
    "contador": frozenset({
        "invoices.view",
        "invoices.upload",
        "invoices.approve",
        "reports.generate",
        # Permisos fiscales
        "fiscal.csd.sign",
        "fiscal.csd.cancel",
        "fiscal.declarations.view",
        "fiscal.declarations.file",
        "fiscal.nominas.process",
        "fiscal.sat.sync",
        "fiscal.reports.tax",
    }),
    "auxiliar": frozenset({
        "invoices.upload",
        "invoices.view_own",
        # Sin permisos fiscales directos
    }),
    "auditor": frozenset({
        "invoices.view",
        "audit.view",
        "fiscal.declarations.view",
        "fiscal.reports.tax",
    }),
}


def has_fiscal_permission(role: str, permission: str) -> bool:
    """Verifica si un rol tiene un permiso fiscal específico."""
    perms = FISCAL_PERMISSIONS.get(role.lower(), frozenset())
    return permission in perms
```

### 3.4 LFPDPPP Compliance Completo

```python
# b2b_ai/compliance/lfpdppp.py
"""
Cumplimiento de la Ley Federal de Protección de Datos Personales
en Posesión de los Particulares (LFPDPPP).

Obligaciones del despacho contable (como responsable):
  1. Aviso de privacidad (publicado y accesible)
  2. Consentimiento para tratamiento de datos personales
  3. Principios: información, consentimiento, calidad, finalidad, lealtad
  4. Derechos ARCO (Acceso, Rectificación, Cancelación, Oposición)
  5. Seguridad de datos personales
  6. Notificación de brechas de seguridad
  7. Registro ante INAI (si maneja >5000 sujetos)

Para Likida AI (como encargado del despacho):
  - Procesamos datos personales EN NOMBRE del despacho
  - El despacho sigue siendo el responsable
  - Nosotros somos encargados bajo contrato de tratamiento
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class DataCategory(str, Enum):
    """Categorías de datos personales según LFPDPPP."""
    PERSONAL = "personal"              # Nombre, dirección, teléfono
    IDENTIFICATION = "identification"  # RFC, CURP, INE
    FINANCIAL = "financial"           # Cuentas bancarias, ingresos
    EMPLOYMENT = "employment"         # Nómina, puesto, antigüedad
    FISCAL = "fiscal"                # Declaraciones, CFDIs
    SENSITIVE = "sensitive"           # Salud, biométricos (no aplica mucho en contabilidad)


class Purpose(str, Enum):
    """Finalidades del tratamiento de datos."""
    FISCAL_COMPLIANCE = "fiscal_compliance"     # Cumplimiento de obligaciones fiscales
    PAYROLL_PROCESSING = "payroll_processing"   # Procesamiento de nómina
    ACCOUNTING = "accounting"                   # Contabilidad general
    LEGAL = "legal"                            # Obligaciones legales
    MARKETING = "marketing"                   # Publicidad (requiere consentimiento explícito)


class LFPDPPPCompliance:
    """
    Servicio de cumplimiento LFPDPPP.

    Implementa:
    - Registro de consentimientos
    - Manejo de solicitudes ARCO
    - Notificación de brechas
    - Aviso de privacidad
    """

    # Mapeo: qué datos se necesitan para cada finalidad
    PURPOSE_DATA_MAP: Dict[Purpose, set] = {
        Purpose.FISCAL_COMPLIANCE: {
            DataCategory.PERSONAL,
            DataCategory.IDENTIFICATION,
            DataCategory.FISCAL,
        },
        Purpose.PAYROLL_PROCESSING: {
            DataCategory.PERSONAL,
            DataCategory.IDENTIFICATION,
            DataCategory.EMPLOYMENT,
            DataCategory.FINANCIAL,
        },
        Purpose.ACCOUNTING: {
            DataCategory.PERSONAL,
            DataCategory.IDENTIFICATION,
            DataCategory.FINANCIAL,
        },
    }

    def __init__(self, db):
        self.db = db

    def register_consent(
        self,
        tenant_id: str,
        subject_id: str,
        purposes: List[Purpose],
        data_categories: List[DataCategory],
        method: str = "digital_form",
    ) -> str:
        """
        Registra el consentimiento del titular de los datos.

        Art. 17 LFPDPPP: El consentimiento puede ser por cualquier medio
        que permita acreditar su manifestación.
        """
        consent_id = self.db.conn.execute("""
            INSERT INTO consent_records
                (tenant_id, subject_id, purposes, data_categories,
                 consent_method, consented_at, is_active, ip_address)
            VALUES (%s, %s, %s, %s, %s, now(), true, %s)
            RETURNING id
        """, [
            tenant_id, subject_id,
            [p.value for p in purposes],
            [dc.value for dc in data_categories],
            method,
            None,  # IP se captura en el middleware
        ]).fetchone()["id"]

        self.db.conn.commit()
        logger.info(f"Consentimiento registrado: {consent_id}")
        return consent_id

    def handle_arco_request(
        self,
        tenant_id: str,
        subject_id: str,
        request_type: str,  # "acceso", "rectificacion", "cancelacion", "oposicion"
        details: str = "",
    ) -> Dict:
        """
        Procesa una solicitud ARCO del titular.

        Art. 28-35 LFPDPPP: El responsable debe responder en 20 días hábiles.
        """
        request_id = self.db.conn.execute("""
            INSERT INTO arco_requests
                (tenant_id, subject_id, request_type, details,
                 status, requested_at, deadline)
            VALUES (%s, %s, %s, %s, 'pending', now(), now() + interval '20 days')
            RETURNING id
        """, [tenant_id, subject_id, request_type, details]).fetchone()["id"]

        self.db.conn.commit()

        # Notificar al despacho para que responda
        self._notify_arco_request(tenant_id, request_id, request_type)

        return {
            "request_id": request_id,
            "status": "pending",
            "deadline_days": 20,
            "message": f"Solicitud {request_type} recibida. "
                       f"El despacho tiene 20 días hábiles para responder.",
        }

    def notify_data_breach(
        self,
        tenant_id: str,
        breach_description: str,
        affected_subjects: int,
        data_categories: List[DataCategory],
    ) -> str:
        """
        Notificación de brecha de seguridad.

        Art. 20 LFPDPPP: Notificar INAI en 72 horas si afecta derechos.
        Art. 16: Notificar a los titulares afectados.
        """
        breach_id = self.db.conn.execute("""
            INSERT INTO data_breaches
                (tenant_id, description, affected_count, data_categories,
                 discovered_at, inai_notified, subjects_notified,
                 status)
            VALUES (%s, %s, %s, %s, now(), false, false, 'investigating')
            RETURNING id
        """, [
            tenant_id, breach_description, affected_subjects,
            [dc.value for dc in data_categories],
        ]).fetchone()["id"]

        self.db.conn.commit()

        # ALERTA CRÍTICA: Notificar inmediatamente al equipo
        logger.critical(
            f"🔒 BRECHA DE DATOS detectada: {breach_id} | "
            f"Tenant: {tenant_id} | Afectados: {affected_subjects}"
        )

        return breach_id

    def generate_privacy_notice(self, tenant_id: str) -> str:
        """
        Genera el aviso de privacidad del despacho.

        Art. 15 LFPDPPP: Debe contener:
        1. Identidad y domicilio del responsable
        2. Finalidades del tratamiento
        3. Mecanismos para ejercer derechos ARCO
        4. Transferencias de datos
        5. Medios para conocer cambios al aviso
        """
        template = """
        AVISO DE PRIVACIDAD

        {despacho_name}
        RFC: {despacho_rfc}
        Domicilio: {despacho_address}

        1. DATOS PERSONALES QUE RECABAMOS
        Para cumplir con las finalidades descritas, recabamos:
        - Datos de identificación (nombre, RFC, CURP)
        - Datos fiscales (declaraciones, CFDIs)
        - Datos laborales (nómina, puesto)
        - Datos financieros (cuentas bancarias, CLABE)

        2. FINALIDADES
        {purposes_text}

        3. DERECHOS ARCO
        Para ejercer sus derechos de Acceso, Rectificación, Cancelación
        u Oposición, contacte a nuestro Oficial de Privacidad:
        Email: {privacy_email}
        Teléfono: {privacy_phone}

        4. TRANSFERENCIAS
        Sus datos pueden ser transferidos al SAT para cumplimiento fiscal.
        No realizamos transferencias a terceros sin su consentimiento.

        5. CAMBIOS AL AVISO
        {update_url}

        Última actualización: {date}
        """
        # TODO: poblar con datos reales del despacho desde DB
        return template
```

### 3.5 SOC 2 / ISO 27001 — Roadmap

```markdown
## Roadmap SOC 2 / ISO 27001 para Likida AI

### Fase 1 (0-3 meses): Fundamentos
- [ ] Políticas de seguridad documentadas
- [ ] RBAC implementado y auditado
- [ ] Logging centralizado (ELK/Loki)
- [ ] Backup automatizado con verificación
- [ ] Incident response plan documentado
- [ ] Employee security training
- [ ] Vendor risk assessment (proveedores cloud)

### Fase 2 (3-6 meses): Controles técnicos
- [ ] Encryption at rest (AES-256-GCM) ✅
- [ ] Encryption in transit (TLS 1.3) ✅
- [ ] MFA obligatorio para acceso admin
- [ ] Secret scanning en CI/CD
- [ ] Vulnerability scanning (Snyk/Trivy)
- [ ] Penetration testing (externo)
- [ ] Access reviews trimestrales
- [ ] Change management process

### Fase 3 (6-9 meses): Auditoría
- [ ] Gap analysis con auditor externo
- [ ] Remediation de findings
- [ ] Evidence collection automatizada
- [ ] Trust service criteria mapping
- [ ] Type I audit preparation

### Fase 4 (9-12 meses): Certificación
- [ ] SOC 2 Type I audit
- [ ] ISO 27001 Stage 1 audit
- [ ] Remediation post-audit
- [ ] Continuous monitoring setup

### Trust Service Criteria Mapping (SOC 2)

| Criterio | Control Likida AI | Estado |
|----------|-------------------|--------|
| CC6.1 | RBAC + permisos granulares | ✅ Implementado |
| CC6.2 | Autenticación JWT + MFA | 🔶 JWT ✅, MFA pendiente |
| CC6.3 | Authorization en cada endpoint | ✅ Middleware |
| CC6.6 | Encryption en tránsito (TLS 1.3) | ✅ nginx config |
| CC6.7 | Encryption en reposo (AES-256-GCM) | ✅ security.py |
| CC7.1 | Monitoring + alertas | ✅ monitoring/ |
| CC7.2 | Incident detection + response | 🔶 Básico, necesita plan formal |
| CC8.1 | Change management | 🔶 CI/CD, falta proceso formal |
| CC9.1 | Risk assessment | ❌ Pendiente |
| A1.2 | Availability (SLA 99.9%) | 🔶 Healthcheck, falta SLO tracking |
```

---

## 4. Monitoring y Observability

### 4.1 Arquitectura de Monitoring

```yaml
# Arquitectura observability para Likida AI

components:
  # Métricas (ya existe b2b_ai/monitoring/metrics.py)
  metrics:
    type: prometheus
    endpoint: /metrics/prometheus
    scrape_interval: 15s
    custom_metrics:
      - b2b_cfdi_processing_duration_seconds
      - b2b_cfdi_accuracy_ratio
      - b2b_sat_api_errors_total
      - b2b_reconciliation_accuracy
      - b2b_agent_task_duration_seconds

  # Logging (extender el logger existente)
  logging:
    type: loki + grafana
    format: JSON structured
    levels:
      - DEBUG (desarrollo)
      - INFO (producción default)
      - WARNING (alertas)
      - ERROR (requiere atención)
      - CRITICAL (brechas, datos fiscales)

  # Alertas
  alerting:
    type: prometheus_alertmanager + pagerduty
    channels:
      - slack: #likida-alerts
      - pagerduty: likida-oncall
      - email: ops@likida.ai

  # Tracing (futuro)
  tracing:
    type: opentelemetry
    status: planned
```

### 4.2 Dashboard de Salud del Agente

```python
# b2b_ai/monitoring/agent_health.py
"""
Dashboard de salud del agente contable.

Métricas clave que los despachos necesitan ver:
  1. CFDIs procesados hoy / este mes
  2. Tasa de éxito del procesamiento
  3. Errores por tipo (SAT, PAC, validación, clasificación)
  4. Tiempo promedio de procesamiento
  5. Cola de trabajo pendiente
  6. Estado de conexiones (SAT, PAC, ERP)
  7. Alertas activas
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AgentHealthSnapshot:
    """Snapshot de salud del agente para un tenant."""
    tenant_id: str
    timestamp: float = field(default_factory=time.time)

    # CFDIs
    cfdi_processed_today: int = 0
    cfdi_processed_month: int = 0
    cfdi_success_rate: float = 0.0
    cfdi_errors_by_type: Dict[str, int] = field(default_factory=dict)
    cfdi_avg_processing_ms: float = 0.0

    # Nómina
    nomina_processed_month: int = 0
    nomina_success_rate: float = 0.0

    # Cola de trabajo
    queue_pending: int = 0
    queue_processing: int = 0
    queue_failed: int = 0

    # Conexiones externas
    sat_status: str = "unknown"       # ok, degraded, down
    pac_status: str = "unknown"
    erp_status: str = "unknown"

    # Clasificación IA
    classification_accuracy: float = 0.0
    classification_total: int = 0
    classification_corrections: int = 0

    # Alertas
    active_alerts: List[Dict[str, Any]] = field(default_factory=list)
    csd_expiring_days: Optional[int] = None  # Días hasta expiración del CSD


def get_agent_health(db, tenant_id: str) -> AgentHealthSnapshot:
    """Genera un snapshot de salud del agente."""
    from b2b_ai.monitoring.metrics import metrics

    snapshot = AgentHealthSnapshot(tenant_id=tenant_id)

    # CFDIs hoy
    row = db.conn.execute("""
        SELECT COUNT(*) as total,
               COUNT(*) FILTER (WHERE status = 'processed') as success,
               COUNT(*) FILTER (WHERE status = 'error') as errors,
               AVG(processing_time_ms) as avg_ms
        FROM cfdi_documents
        WHERE tenant_id = %s AND created_at::date = CURRENT_DATE
    """, [tenant_id]).fetchone()

    if row:
        snapshot.cfdi_processed_today = row["total"]
        snapshot.cfdi_success_rate = (
            row["success"] / max(row["total"], 1)
        )
        snapshot.cfdi_avg_processing_ms = row["avg_ms"] or 0

    # CFDIs este mes
    row = db.conn.execute("""
        SELECT COUNT(*) as total
        FROM cfdi_documents
        WHERE tenant_id = %s
          AND created_at >= date_trunc('month', CURRENT_DATE)
    """, [tenant_id]).fetchone()
    snapshot.cfdi_processed_month = row["total"] if row else 0

    # Errores por tipo
    rows = db.conn.execute("""
        SELECT error_type, COUNT(*) as count
        FROM cfdi_documents
        WHERE tenant_id = %s
          AND status = 'error'
          AND created_at >= date_trunc('month', CURRENT_DATE)
        GROUP BY error_type
        ORDER BY count DESC
    """, [tenant_id]).fetchall()
    snapshot.cfdi_errors_by_type = {r["error_type"]: r["count"] for r in rows}

    # Cola de trabajo (Celery)
    try:
        from b2b_ai.tasks.celery_app import app as celery_app
        inspector = celery_app.control.inspect()
        active = inspector.active() or {}
        reserved = inspector.reserved() or {}
        snapshot.queue_processing = sum(
            len(tasks) for tasks in active.values()
        )
        snapshot.queue_pending = sum(
            len(tasks) for tasks in reserved.values()
        )
    except Exception:
        pass

    # Clasificación
    row = db.conn.execute("""
        SELECT
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE classification_corrected = true) as corrections
        FROM cfdi_documents
        WHERE tenant_id = %s
          AND created_at >= date_trunc('month', CURRENT_DATE)
    """, [tenant_id]).fetchone()
    if row and row["total"] > 0:
        snapshot.classification_total = row["total"]
        snapshot.classification_corrections = row["corrections"]
        snapshot.classification_accuracy = 1 - (row["corrections"] / row["total"])

    # CSD expiry
    from b2b_ai.services.csd_manager import CSDManager
    csd = CSDManager()
    alerts = csd.check_expiry_alerts(tenant_id)
    if alerts:
        snapshot.csd_expiring_days = (
            alerts[0]["valid_until"] - datetime.now(timezone.utc)
        ).days

    return snapshot


def format_health_dashboard(snapshot: AgentHealthSnapshot) -> Dict[str, Any]:
    """Formatea el snapshot como JSON para el dashboard."""
    return {
        "overview": {
            "status": "healthy" if not snapshot.active_alerts else "degraded",
            "cfdi_today": snapshot.cfdi_processed_today,
            "cfdi_month": snapshot.cfdi_processed_month,
            "success_rate": f"{snapshot.cfdi_success_rate:.1%}",
            "avg_processing": f"{snapshot.cfdi_avg_processing_ms:.0f}ms",
        },
        "classification": {
            "accuracy": f"{snapshot.classification_accuracy:.1%}",
            "total": snapshot.classification_total,
            "corrections": snapshot.classification_corrections,
        },
        "queue": {
            "pending": snapshot.queue_pending,
            "processing": snapshot.queue_processing,
            "failed": snapshot.queue_failed,
        },
        "connections": {
            "sat": snapshot.sat_status,
            "pac": snapshot.pac_status,
            "erp": snapshot.erp_status,
        },
        "alerts": snapshot.active_alerts,
        "csd_expiring_days": snapshot.csd_expiring_days,
    }
```

### 4.3 Métricas Clave (KPIs)

```python
# b2b_ai/monitoring/kpis.py
"""
KPIs que los despachos contables necesitan trackear.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class FiscalKPIs:
    """KPIs fiscales por tenant."""

    # Eficiencia operativa
    cfdis_per_hour: float = 0.0
    cost_per_cfdi: float = 0.0           # Costo de AI + PAC por CFDI
    auto_classification_rate: float = 0.0 # % clasificados sin intervención humana

    # Calidad
    cfdi_error_rate: float = 0.0          # % de CFDIs con error
    sat_rejection_rate: float = 0.0       # % rechazados por SAT
    reconciliation_accuracy: float = 0.0  # % conciliación correcta

    # Cumplimiento
    on_time_filing_rate: float = 0.0      # % declaraciones a tiempo
    pending_declarations: int = 0
    overdue_invoices: int = 0

    # Agente AI
    agent_task_success_rate: float = 0.0
    agent_avg_response_ms: float = 0.0
    agent_cost_usd: float = 0.0           # Costo de API de LLM

    # Satisfacción
    client_portal_usage: float = 0.0      # % de clientes usando el portal
    support_tickets_per_client: float = 0.0


# Queries SQL para cada KPI
KPI_QUERIES = {
    "cfdis_per_hour": """
        SELECT
            tenant_id,
            COUNT(*) / GREATEST(
                EXTRACT(EPOCH FROM (MAX(created_at) - MIN(created_at))) / 3600,
                1
            ) as cfdis_per_hour
        FROM cfdi_documents
        WHERE created_at >= NOW() - INTERVAL '7 days'
        GROUP BY tenant_id
    """,

    "auto_classification_rate": """
        SELECT
            tenant_id,
            1.0 - (COUNT(*) FILTER (WHERE classification_corrected)::float
                   / GREATEST(COUNT(*), 1)) as auto_rate
        FROM cfdi_documents
        WHERE created_at >= NOW() - INTERVAL '30 days'
        GROUP BY tenant_id
    """,

    "cfdi_error_rate": """
        SELECT
            tenant_id,
            COUNT(*) FILTER (WHERE status = 'error')::float
            / GREATEST(COUNT(*), 1) as error_rate
        FROM cfdi_documents
        WHERE created_at >= NOW() - INTERVAL '30 days'
        GROUP BY tenant_id
    """,
}
```

### 4.4 Logging para Auditoría Fiscal

```python
# b2b_ai/monitoring/fiscal_logger.py
"""
Logger estructurado para operaciones fiscales.

Formato JSON para ingestión en Loki/ELK.
Cada entrada incluye todos los campos necesarios para auditoría fiscal.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class FiscalJSONFormatter(logging.Formatter):
    """
    Formateador JSON para logs fiscales.

    Cada línea es un JSON válido (NDJSON) con campos estándar:
      - timestamp: ISO 8601
      - level: INFO/WARNING/ERROR/CRITICAL
      - service: "likida"
      - tenant_id: UUID del tenant
      - user_id: UUID del usuario
      - action: acción fiscal (STAMP, CANCEL, VALIDATE, etc.)
      - resource: tipo de recurso (cfdi, nomina, declaration)
      - resource_id: ID del recurso
      - details: dict con contexto adicional
      - ip: IP del cliente
      - duration_ms: duración de la operación
      - error: mensaje de error (si aplica)
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": "likida",
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Agregar campos fiscales si existen
        for field in [
            "tenant_id", "user_id", "action", "resource", "resource_id",
            "ip", "duration_ms", "details", "error", "session_id",
        ]:
            value = getattr(record, field, None)
            if value is not None:
                log_entry[field] = value

        return json.dumps(log_entry, default=str, ensure_ascii=False)


def setup_fiscal_logging():
    """Configura logging estructurado para producción."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(FiscalJSONFormatter())

    # Root logger
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    # Logger fiscal específico
    fiscal = logging.getLogger("likida.fiscal")
    fiscal.setLevel(logging.DEBUG)
    fiscal.addHandler(handler)


def log_fiscal_operation(
    action: str,
    resource: str,
    resource_id: str,
    tenant_id: str,
    user_id: str = "system",
    details: Optional[Dict[str, Any]] = None,
    duration_ms: Optional[float] = None,
    error: Optional[str] = None,
    ip: Optional[str] = None,
):
    """
    Helper para loggear una operación fiscal con todos los campos.
    """
    logger = logging.getLogger("likida.fiscal")

    extra = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "action": action,
        "resource": resource,
        "resource_id": resource_id,
        "details": details or {},
        "duration_ms": duration_ms,
        "error": error,
        "ip": ip,
    }

    if error:
        logger.error(f"{action} {resource}/{resource_id}: {error}", extra=extra)
    else:
        logger.info(f"{action} {resource}/{resource_id}", extra=extra)
```

### 4.5 Alertas Configuradas

```yaml
# monitoring/alerts.yml — Reglas de alerta para Prometheus/Alertmanager

groups:
  - name: likida_fiscal_alerts
    rules:
      # --- Disponibilidad ---
      - alert: ServiceDown
        expr: up{job="likida"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Likida API está caída"
          description: "El servicio no responde en {{ $labels.instance }}"

      - alert: HighErrorRate
        expr: rate(b2b_errors_total[5m]) / rate(b2b_requests_total[5m]) > 0.05
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Tasa de error > 5% en los últimos 5 minutos"

      # --- Procesamiento fiscal ---
      - alert: CFDIProcessingStalled
        expr: rate(b2b_invoices_processed_total[30m]) == 0
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "No se han procesado CFDIs en 30 minutos"

      - alert: SATAPIDegraded
        expr: rate(b2b_sat_api_errors_total[5m]) > 0.3
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "API del SAT con >30% errores"

      - alert: PACRateLimitHit
        expr: rate(b2b_pac_rate_limit_total[5m]) > 0
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Rate limit del PAC alcanzado"

      # --- Clasificación ---
      - alert: ClassificationAccuracyDrop
        expr: b2b_classification_accuracy < 0.85
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Accuracy de clasificación IA < 85%"

      # --- CSD ---
      - alert: CSDExpiringSoon
        expr: b2b_csd_days_until_expiry < 30
        for: 1d
        labels:
          severity: warning
        annotations:
          summary: "CSD vence en {{ $value }} días"

      - alert: CSDExpired
        expr: b2b_csd_days_until_expiry < 0
        labels:
          severity: critical
        annotations:
          summary: "⚠️ CSD EXPIRADO — No se pueden timbrar CFDIs"

      # --- Seguridad ---
      - alert: UnauthorizedCrossTenantAccess
        expr: rate(b2b_cross_tenant_blocked_total[5m]) > 0
        labels:
          severity: critical
        annotations:
          summary: "Intento de acceso cross-tenant detectado"

      - alert: DataBreachDetected
        expr: b2b_data_breach_total > 0
        labels:
          severity: critical
        annotations:
          summary: "🔒 BRECHA DE DATOS — Verificar inmediatamente"
```

---

## 5. Deployment

### 5.1 Docker + Docker Compose (Desarrollo)

El proyecto ya tiene `docker-compose.yml`. Para producción:

```yaml
# docker-compose.prod.yml — Stack de producción
# Incluye: app, postgres (con RLS), redis, nginx (TLS), celery, celery-beat, flower

name: likida-prod

services:
  # --- API ---
  app:
    build: .
    image: likida:latest
    restart: unless-stopped
    env_file: .env.production
    environment:
      - B2B_ENV=production
      - B2B_WORKERS=4
      - DATABASE_URL=postgresql://likida:${POSTGRES_PASSWORD}@postgres:5432/likida
      - REDIS_URL=redis://redis:6379/0
    volumes:
      - app-data:/data
    expose:
      - "8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://127.0.0.1:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
    networks:
      - internal
    deploy:
      resources:
        limits:
          cpus: "2.0"
          memory: 2G

  # --- PostgreSQL con RLS ---
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: likida
      POSTGRES_USER: likida
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_INITDB_ARGS: "--data-checksums"
    volumes:
      - postgres-data:/var/lib/postgresql/data
      - ./scripts/init-rls.sql:/docker-entrypoint-initdb.d/01-rls.sql:ro
      - ./scripts/backup-postgres.sh:/scripts/backup.sh:ro
    expose:
      - "5432"
    networks:
      - internal
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U likida -d likida"]
      interval: 10s
      timeout: 5s
      retries: 5
    deploy:
      resources:
        limits:
          cpus: "2.0"
          memory: 4G
    # WAL archiving para PITR
    command: >
      postgres
        -c wal_level=replica
        -c archive_mode=on
        -c archive_command='aws s3 cp %p s3://likida-backups/postgres/wal/%f'
        -c max_wal_senders=3
        -c log_statement=mod
        -c log_min_duration_statement=1000

  # --- Redis (cache + Celery broker) ---
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: >
      redis-server
        --appendonly yes
        --maxmemory 512mb
        --maxmemory-policy allkeys-lru
        --requirepass ${REDIS_PASSWORD}
    volumes:
      - redis-data:/data
    expose:
      - "6379"
    networks:
      - internal
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
      interval: 10s
      timeout: 5s

  # --- Celery Worker (procesamiento de CFDIs) ---
  celery-worker:
    build: .
    restart: unless-stopped
    env_file: .env.production
    environment:
      - DATABASE_URL=postgresql://likida:${POSTGRES_PASSWORD}@postgres:5432/likida
      - REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
      - CELERY_CONCURRENCY=4
    command: >
      celery -A b2b_ai.tasks.celery_app worker
        --loglevel=info
        --concurrency=4
        --max-tasks-per-child=1000
        --without-heartbeat
        --without-mingle
    depends_on:
      - postgres
      - redis
    networks:
      - internal
    deploy:
      resources:
        limits:
          cpus: "2.0"
          memory: 2G

  # --- Celery Beat (tareas programadas) ---
  celery-beat:
    build: .
    restart: unless-stopped
    env_file: .env.production
    environment:
      - DATABASE_URL=postgresql://likida:${POSTGRES_PASSWORD}@postgres:5432/likida
      - REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
    command: >
      celery -A b2b_ai.tasks.celery_app beat
        --loglevel=info
        --schedule=/data/celerybeat-schedule
    volumes:
      - app-data:/data
    depends_on:
      - redis
    networks:
      - internal

  # --- Flower (monitoring de Celery) ---
  flower:
    build: .
    restart: unless-stopped
    environment:
      - REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
    command: >
      celery -A b2b_ai.tasks.celery_app flower
        --port=5555
        --basic_auth=${FLOWER_USER}:${FLOWER_PASSWORD}
    expose:
      - "5555"
    depends_on:
      - redis
    networks:
      - internal

  # --- Nginx (reverse proxy + TLS) ---
  nginx:
    image: nginx:1.27-alpine
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - ./nginx/certs:/etc/nginx/certs:ro
      - certbot-etc:/etc/letsencrypt:ro
    depends_on:
      - app
    networks:
      - internal

  # --- Prometheus (métricas) ---
  prometheus:
    image: prom/prometheus:v2.51.0
    restart: unless-stopped
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus-data:/prometheus
    expose:
      - "9090"
    networks:
      - internal

  # --- Grafana (dashboards) ---
  grafana:
    image: grafana/grafana:10.4.0
    restart: unless-stopped
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASSWORD}
    volumes:
      - grafana-data:/var/lib/grafana
      - ./monitoring/grafana/dashboards:/etc/grafana/provisioning/dashboards:ro
      - ./monitoring/grafana/datasources:/etc/grafana/provisioning/datasources:ro
    ports:
      - "3001:3000"
    depends_on:
      - prometheus
    networks:
      - internal

volumes:
  app-data:
  postgres-data:
  redis-data:
  certbot-etc:
  prometheus-data:
  grafana-data:

networks:
  internal:
    driver: bridge
```

### 5.2 Railway (Producción managed)

```toml
# railway.toml — Configuración de Railway para Likida AI
[build]
builder = "DOCKERFILE"
dockerfilePath = "Dockerfile"

[deploy]
startCommand = "uvicorn b2b_ai.api.app:app --host 0.0.0.0 --port $PORT --workers 4 --proxy-headers"
healthcheckPath = "/health"
healthcheckTimeout = 300
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 3

[environments.production]
# Variables de entorno (setear en Railway dashboard)
# DATABASE_URL → PostgreSQL add-on
# REDIS_URL → Redis add-on
# B2B_ENCRYPTION_KEY → generate con openssl rand -base64 32
# B2B_API_KEY → generate con openssl rand -hex 32
```

### 5.3 CI/CD Pipeline

```yaml
# .github/workflows/deploy.yml — Pipeline de CI/CD completo

name: Deploy Likida AI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}

jobs:
  # --- Lint + Type Check ---
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install ruff mypy
      - run: ruff check b2b_ai/
      - run: ruff format --check b2b_ai/
      - run: mypy b2b_ai/ --ignore-missing-imports

  # --- Tests ---
  test:
    runs-on: ubuntu-latest
    needs: lint
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_DB: likida_test
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432
      redis:
        image: redis:7-alpine
        ports:
          - 6379:6379
    env:
      DATABASE_URL: postgresql://test:test@localhost:5432/likida_test
      REDIS_URL: redis://localhost:6379/0
      B2B_ENCRYPTION_KEY: dGVzdGtleTEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - run: pip install -r requirements-production.txt
      - run: pip install pytest pytest-cov pytest-asyncio httpx
      - run: pytest tests/ -v --cov=b2b_ai --cov-report=xml --cov-report=term-missing
      - uses: codecov/codecov-action@v4
        with:
          file: coverage.xml

  # --- Security Scan ---
  security:
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install pip-audit safety
      - run: pip-audit --strict --desc
      - run: safety check --full-report

  # --- Docker Build ---
  build:
    runs-on: ubuntu-latest
    needs: [test, security]
    if: github.ref == 'refs/heads/main'
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: |
            ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:latest
            ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

  # --- Deploy to Railway ---
  deploy-staging:
    runs-on: ubuntu-latest
    needs: build
    environment: staging
    steps:
      - uses: actions/checkout@v4
      - uses: railwayapp/deploy-action@v1
        with:
          railway_token: ${{ secrets.RAILWAY_STAGING_TOKEN }}
          service: likida-staging

  # --- Deploy to Production (manual approval) ---
  deploy-production:
    runs-on: ubuntu-latest
    needs: deploy-staging
    environment: production  # Requiere approval manual
    steps:
      - uses: actions/checkout@v4
      - uses: railwayapp/deploy-action@v1
        with:
          railway_token: ${{ secrets.RAILWAY_PROD_TOKEN }}
          service: likida-production
      # Smoke test post-deploy
      - run: |
          sleep 30
          curl -fsS https://api.likida.ai/health || exit 1
```

### 5.4 Database Migrations Seguras

```python
# migrations/env.py — Alembic configurado para PostgreSQL con RLS
"""
Migraciones seguras para Likida AI.

Reglas:
  1. TODAS las migraciones deben ser reversibles (downgrade)
  2. NUNCA hacer DROP TABLE en producción (soft delete con rename)
  3. NUNCA hacer ALTER TABLE con LOCK en tablas grandes (usar CREATE INDEX CONCURRENTLY)
  4. Las migraciones de datos se hacen en scripts separados (no en schema migrations)
  5. Cada migración se prueba en staging antes de production
  6. Backup automático antes de cada migración
"""

# Script de migración segura
MIGRATION_SAFETY_RULES = """
-- REGLAS DE SEGURIDAD PARA MIGRACIONES:

-- ✅ SEGURO: CREATE TABLE (no bloquea)
-- ✅ SEGURO: CREATE INDEX CONCURRENTLY (no bloquea lecturas/escrituras)
-- ✅ SEGURO: ALTER TABLE ADD COLUMN (si tiene DEFAULT, PG 11+ es seguro)
-- ✅ SEGURO: ALTER TABLE ADD CONSTRAINT con NOT VALID (validar después)

-- ⚠️  PELIGROSO: DROP TABLE (irreversible)
-- ⚠️  PELIGROSO: ALTER TABLE DROP COLUMN (irreversible sin backup)
-- ⚠️  PELIGROSO: CREATE UNIQUE INDEX (sin CONCURRENTLY, bloquea escrituras)
-- ⚠️  PELIGROSO: ALTER TABLE ALTER TYPE (puede bloquear la tabla entera)
-- ⚠️  PELIGROSO: DELETE FROM (sin WHERE, borra todo)

-- ❌ PROHIBIDO en producción:
-- DROP DATABASE
-- TRUNCATE (sin confirmación explícita)
"""

# Ejemplo de migración segura:
SAFE_MIGRATION_EXAMPLE = """
-- migrations/versions/002_add_payroll_table.py
\"\"\"Add payroll_entries table for nómina processing.

Revision ID: 002
Revises: 001
Create Date: 2026-08-01
\"\"\"
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

def upgrade():
    # 1. Crear tabla (no bloquea)
    op.create_table(
        'payroll_entries',
        sa.Column('id', UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', UUID, sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('employee_rfc', sa.String(13), nullable=False),
        sa.Column('period_start', sa.Date, nullable=False),
        sa.Column('period_end', sa.Date, nullable=False),
        sa.Column('gross_salary', sa.Numeric(12, 2), nullable=False),
        sa.Column('deductions', JSONB, server_default='{}'),
        sa.Column('perceptions', JSONB, server_default='{}'),
        sa.Column('net_pay', sa.Numeric(12, 2), nullable=False),
        sa.Column('cfdi_uuid', sa.String(36)),
        sa.Column('status', sa.String(20), server_default='draft'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 2. Índices CONCURRENTLY (no bloquea)
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_payroll_tenant ON payroll_entries (tenant_id)")
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_payroll_employee ON payroll_entries (tenant_id, employee_rfc)")
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_payroll_period ON payroll_entries (tenant_id, period_start, period_end)")

    # 3. Habilitar RLS
    op.execute("ALTER TABLE payroll_entries ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation_payroll ON payroll_entries
        USING (tenant_id = current_tenant_id())
    """)

def downgrade():
    op.drop_table('payroll_entries')
"""
```

### 5.5 Feature Flags para Rollout Gradual

```python
# b2b_ai/features/feature_flags.py
"""
Feature flags para rollout gradual a despachos.

Uso:
  1. Definir flag en FEATURE_FLAGS
  2. Verificar en código: if is_enabled("new_classifier", tenant_id)
  3. Rollout gradual: percentage, whitelist, or environment-based

Flags actuales:
  - new_cfdi_parser: Nuevo parser XML más rápido
  - ai_classification: Clasificación automática con IA
  - sat_direct_sync: Sincronización directa con SAT (vs via PAC)
  - payroll_module: Módulo de nómina
  - advanced_reports: Reportes avanzados (conciliación, DIOT)
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set


class FlagStrategy(str, Enum):
    """Estrategia de activación del flag."""
    ENVIRONMENT = "environment"    # Solo en ciertos ambientes (dev, staging)
    WHITELIST = "whitelist"        # Solo tenants específicos
    PERCENTAGE = "percentage"      # % gradual de tenants
    ALL = "all"                    # Activado para todos


@dataclass
class FeatureFlag:
    """Definición de un feature flag."""
    name: str
    description: str
    strategy: FlagStrategy
    enabled: bool = True
    # Para WHITELIST
    whitelist_tenants: Set[str] = field(default_factory=set)
    # Para PERCENTAGE (0-100)
    percentage: int = 0
    # Para ENVIRONMENT
    environments: Set[str] = field(default_factory=set)
    # Metadata
    created_at: str = ""
    owner: str = ""


# --- Flags definidos ---
FEATURE_FLAGS: Dict[str, FeatureFlag] = {
    "new_cfdi_parser": FeatureFlag(
        name="new_cfdi_parser",
        description="Nuevo parser XML CFDI 4.0 (2x más rápido)",
        strategy=FlagStrategy.PERCENTAGE,
        percentage=50,  # 50% de despachos
        owner="backend-team",
    ),
    "ai_classification": FeatureFlag(
        name="ai_classification",
        description="Clasificación automática de CFDIs con IA",
        strategy=FlagStrategy.WHITELIST,
        whitelist_tenants={"tenant_demo", "tenant_piloto_1"},
        owner="ml-team",
    ),
    "sat_direct_sync": FeatureFlag(
        name="sat_direct_sync",
        description="Sincronización directa con SAT (sin PAC intermediario)",
        strategy=FlagStrategy.ENVIRONMENT,
        environments={"development", "staging"},
        owner="integrations-team",
    ),
    "payroll_module": FeatureFlag(
        name="payroll_module",
        description="Módulo de nómina electrónica",
        strategy=FlagStrategy.WHITELIST,
        whitelist_tenants={"tenant_demo"},
        owner="product-team",
    ),
    "advanced_reports": FeatureFlag(
        name="advanced_reports",
        description="Reportes avanzados (DIOT, conciliación fiscal)",
        strategy=FlagStrategy.PERCENTAGE,
        percentage=25,
        owner="product-team",
    ),
}


def is_enabled(
    flag_name: str,
    tenant_id: Optional[str] = None,
    environment: Optional[str] = None,
) -> bool:
    """
    Verifica si un feature flag está activado para un tenant.

    Orden de verificación:
    1. Flag no existe → False
    2. Flag.enabled == False → False
    3. Strategy ALL → True
    4. Strategy ENVIRONMENT → check environment
    5. Strategy WHITELIST → check tenant_id in whitelist
    6. Strategy PERCENTAGE → hash(tenant_id) % 100 < percentage
    """
    flag = FEATURE_FLAGS.get(flag_name)
    if not flag or not flag.enabled:
        return False

    if flag.strategy == FlagStrategy.ALL:
        return True

    if flag.strategy == FlagStrategy.ENVIRONMENT:
        env = environment or os.environ.get("B2B_ENV", "development")
        return env in flag.environments

    if flag.strategy == FlagStrategy.WHITELIST:
        return tenant_id in flag.whitelist_tenants

    if flag.strategy == FlagStrategy.PERCENTAGE:
        if not tenant_id:
            return False
        # Hash determinista por tenant (mismo tenant siempre da mismo resultado)
        hash_val = int(hashlib.md5(tenant_id.encode()).hexdigest(), 16)
        return (hash_val % 100) < flag.percentage

    return False


def get_flag_status(tenant_id: str) -> Dict[str, bool]:
    """Retorna el estado de todos los flags para un tenant."""
    return {
        name: is_enabled(name, tenant_id)
        for name in FEATURE_FLAGS
    }
```

---

## 6. Checklists de Producción

### 6.1 Checklist Pre-Launch (Antes de Primer Despacho Real)

#### Multi-Tenancy y Datos
- [ ] RLS habilitado en TODAS las tablas de negocio en PostgreSQL
- [ ] Middleware de tenant context activo y testeado
- [ ] Test de aislamiento: intentar leer datos de otro tenant → debe fallar
- [ ] Encryption key (`B2B_ENCRYPTION_KEY`) generada y en vault
- [ ] Campos sensibles (RFC, nómina, CLABE) cifrados en DB
- [ ] CFDIs XML almacenados con checksum de integridad
- [ ] Backup PostgreSQL automatizado (cron + verificación)
- [ ] WAL archiving habilitado para PITR

#### Seguridad
- [ ] TLS 1.3 configurado en nginx (SSL Labs grade A+)
- [ ] HSTS habilitado
- [ ] Rate limiting activo (nginx + Celery task rate limits)
- [ ] CORS configurado (solo dominios permitidos)
- [ ] Security headers (X-Content-Type-Options, CSP, etc.)
- [ ] API keys rotadas y en vault (no en .env)
- [ ] RBAC testeado: cada rol solo accede a lo que debe
- [ ] MFA habilitado para roles admin/contador
- [ ] .env.production NO commiteado al repo
- [ ] Dependencias auditadas (pip-audit, 0 vulnerabilidades)

#### Cumplimiento Fiscal
- [ ] CFF Art. 30: retención de datos configurada (mínimo 5 años)
- [ ] LFPDPPP: aviso de privacidad generado
- [ ] LFPDPPP: consentimientos registrados para cada titular
- [ ] LFPDPPP: flujo ARCO implementado
- [ ] LFPDPPP: plan de notificación de brechas documentado
- [ ] Auditoría: toda operación fiscal se audita (audit_entries)
- [ ] Auditoría: tabla es append-only (trigger previene UPDATE/DELETE)
- [ ] Exportación de auditoría a JSON/CSV funcional

#### Procesamiento
- [ ] Celery worker corriendo y conectado a Redis
- [ ] Celery Beat corriendo (tareas programadas)
- [ ] Batch processing testeado con 1000+ CFDIs
- [ ] Rate limits de PAC verificados (no exceder 100/min)
- [ ] Retry con backoff exponencial funcional
- [ ] Dead letter queue para tareas que fallan 5 veces
- [ ] Procesamiento de nómina funcional

#### Monitoring
- [ ] Prometheus scrapeando /metrics/prometheus
- [ ] Grafana dashboard configurado
- [ ] Alertas críticas: ServiceDown, CSDExpired, DataBreach
- [ ] Alertas warning: HighErrorRate, CFDIStalled, ClassificationDrop
- [ ] Logging estructurado (JSON) para Loki/ELK
- [ ] Health check endpoint funcional (/health, /health/detailed)
- [ ] Flower dashboard accesible (monitoreo de Celery)

#### Deployment
- [ ] CI/CD pipeline funcional (lint → test → security → build → deploy)
- [ ] Docker image construida y testeada
- [ ] docker-compose.prod.yml funcional
- [ ] Database migrations reversibles y testeas
- [ ] Feature flags configurados para rollout gradual
- [ ] Rollback plan documentado
- [ ] Runbook de incidentes creado

### 6.2 Checklist Mensual (Mantenimiento)

- [ ] Revisar métricas de error rate (debe ser < 1%)
- [ ] Verificar que backups se están ejecutando correctamente
- [ ] Probar restore de backup (al menos 1 vez al trimestre)
- [ ] Revisar alertas activas en Grafana
- [ ] Actualizar dependencias (pip-audit)
- [ ] Revisar logs de acceso cross-tenant (debe ser 0)
- [ ] Verificar expiración de CSDs (alertar 30 días antes)
- [ ] Revisar usage por tenant (detectar anomalías)
- [ ] Actualizar rate limits si es necesario
- [ ] Documentar incidentes del mes

### 6.3 Checklist Trimestral

- [ ] Rotación de B2B_ENCRYPTION_KEY (si es necesario)
- [ ] Penetration test (o al menos OWASP ZAP scan)
- [ ] Access review: revisar que los usuarios activos sean correctos
- [ ] Review de feature flags: activar/desactivar según adoption
- [ ] Capacity planning: ¿necesitamos más workers/memoria/CPU?
- [ ] Disaster recovery drill (simular failover)
- [ ] Compliance review: ¿seguimos cumpliendo CFF Art. 30 y LFPDPPP?

---

## 7. Configuración de Entorno Completa

```bash
# .env.production.example — Variables de entorno de producción
# Copiar a .env.production y llenar valores reales

# === Entorno ===
B2B_ENV=production
B2B_DEBUG=false
B2B_HOST=0.0.0.0
B2B_PORT=8000
B2B_WORKERS=4
B2B_TRUST_PROXY=true

# === Base de datos PostgreSQL ===
DATABASE_URL=postgresql://likida:PASSWORD@postgres:5432/likida
POSTGRES_DB=likida
POSTGRES_USER=likida
POSTGRES_PASSWORD=CHANGE_ME_STRONG_PASSWORD

# === Redis ===
REDIS_URL=redis://:PASSWORD@redis:6379/0
REDIS_PASSWORD=CHANGE_ME_REDIS_PASSWORD

# === Seguridad ===
B2B_API_KEY=GENERAR_CON_openssl_rand_hex_32
B2B_ENCRYPTION_KEY=GENERAR_CON_openssl_rand_base64_32
JWT_SECRET=GENERAR_CON_openssl_rand_hex_64
JWT_ALGORITHM=HS256
JWT_EXPIRATION_HOURS=24

# === SAT / PAC ===
SAT_RFC=EKU9003173C9  # RFC del SAT para consulta (pruebas)
PAC_PROVIDER=facturapi  # facturapi | swsapien | finkok
PAC_API_KEY=TU_API_KEY_DEL_PAC
PAC_API_SECRET=TU_SECRET_DEL_PAC

# === Celery ===
CELERY_CONCURRENCY=4
FLOWER_USER=admin
FLOWER_PASSWORD=CHANGE_ME_FLOWER_PASSWORD

# === Alertas ===
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/xxx/yyy/zzz
PAGERDUTY_SERVICE_KEY=TU_PAGERDUTY_KEY
ALERT_EMAIL=ops@likida.ai

# === Backup ===
BACKUP_S3_BUCKET=s3://likida-backups/postgres/full
BACKUP_RETENTION_DAYS=30
AWS_ACCESS_KEY_ID=TU_AWS_KEY
AWS_SECRET_ACCESS_KEY=TU_AWS_SECRET
AWS_DEFAULT_REGION=us-east-1

# === Vault (Secrets Manager) ===
VAULT_TYPE=aws_secrets_manager  # aws_secrets_manager | hashicorp_vault
VAULT_ENDPOINT=  # Solo para HashiCorp Vault

# === Feature Flags ===
FEATURE_FLAGS_CONFIG=  # JSON override (opcional)

# === Monitoring ===
PROMETHEUS_ENABLED=true
GRAFANA_PASSWORD=CHANGE_ME_GRAFANA_PASSWORD
LOG_LEVEL=info
```

---

## 8. Costos Estimados (Despacho Mediano: 100 clientes)

| Componente | Tier | Costo/mes estimado |
|-----------|------|-------------------|
| Railway (app + worker) | Pro | $20-50 |
| Railway PostgreSQL | Pro | $10-20 |
| Railway Redis | Pro | $5-10 |
| S3 (backups + CFDIs) | Standard | $5-15 |
| AWS Secrets Manager | Standard | $1-5 |
| Dominio + TLS | Let's Encrypt | $0 (gratis) |
| Sentry (errores) | Team | $26 |
| **Total** | | **$67-126/mes** |

Con AWS directo (EC2 + RDS + ElastiCache): $150-300/mes pero más control.

---

## Referencias Legales

- **CFF Art. 30**: Obligación de conservar contabilidad y CFDIs por 5 años
- **LFPDPPP**: Ley Federal de Protección de Datos Personales en Posesión de los Particulares
- **CFF Art. 29**: Timbrado de CFDIs a través de PAC autorizados
- **Ley del ISR Art. 76**: Obligaciones de conservación de nómina
- **Reglamento del CFF Art. 39**: Especificaciones técnicas de CFDI 4.0
- **INAI**: Instituto Nacional de Transparencia, Acceso a la Información y Protección de Datos Personales

---

*Documento generado para Likida AI Enterprise · 2026-08-01*
