# Security Audit Report — Likida AI Enterprise

**Date:** 2026-08-01  
**Auditor:** Sam (Calidad)  
**Scope:** Full codebase `b2b_ai/` — Python, HTML, JS  
**Severity Scale:** 🔴 Critical | 🟠 High | 🟡 Medium | 🟢 Low | ⚪ Info

---

## Executive Summary

| Category | Critical | High | Medium | Low | Info |
|----------|----------|------|--------|-----|------|
| Auth Bypass | 0 | 0 | 2 | 1 | 0 |
| Injection | 0 | 0 | 2 | 0 | 0 |
| Secrets Exposure | 0 | 0 | 1 | 2 | 1 |
| Data Leakage | 0 | 1 | 1 | 1 | 0 |
| Crypto Issues | 0 | 0 | 2 | 1 | 0 |
| Race Conditions | 0 | 0 | 0 | 1 | 0 |
| Resource Exhaustion | 0 | 0 | 1 | 0 | 1 |
| **Total** | **0** | **1** | **9** | **6** | **2** |

**Overall risk level: MEDIUM** — No critical vulnerabilities found. The codebase has good security fundamentals (JWT auth, RBAC, path traversal defense, AES-GCM encryption at rest). Issues are mostly defense-in-depth improvements and information hardening.

---

## 1. AUTH BYPASS

### ✅ PASS — JWT Authentication Well Implemented

All API endpoints are protected by `require_api_key` dependency. The auth middleware:
- Uses HS256 with HMAC-SHA256 (stdlib)
- Constant-time signature comparison via `hmac.compare_digest()`
- Requires min 32-char secret; fails fast in production without `B2B_JWT_SECRET`
- Generates ephemeral secret only in dev environments
- Tenant isolation enforced (tenant_id check in `require_tenant_admin`)
- Blocked tenants are rejected

### ✅ PASS — RBAC Implemented

Role-based access control via `has_permission()` in `b2b_ai/auth/roles.py`. `require_permission(perm)` and `require_tenant_admin()` are available as FastAPI dependencies.

### 🟡 MEDIUM — Health/Metrics Endpoints Public Without Auth

**Files:** `b2b_ai/api/app.py:571-609`

`/health`, `/health/detailed`, `/metrics`, `/metrics/prometheus` are public endpoints with no authentication. While common for monitoring, they expose:
- Database backend type (`postgresql` vs `sqlite`)
- Database path (`db_path`)
- Schema version
- Invoice count, tenant count
- Uptime, total requests
- Detailed system health (disk, memory, Redis status)

**Risk:** Information disclosure to unauthenticated users. An attacker can fingerprint the stack.

**Recommendation:** Either require auth on `/health/detailed` and `/metrics`, or restrict to internal network only (IP allowlist).

### 🟡 MEDIUM — Public Lead Endpoint Has No Rate Limiting

**File:** `b2b_ai/api/app.py:741-752`

`POST /api/v1/leads` is public (no auth required, as designed for landing page). No per-IP rate limiting visible on this specific endpoint (global rate limiter at line 486 applies, but per-tenant limit may not cover unauthenticated requests).

**Recommendation:** Add per-IP rate limiting specifically for public endpoints.

### 🟢 LOW — Legacy Endpoints Use Same Auth

**File:** `b2b_ai/api/app.py:1209-1259`

Legacy endpoints (`/tools`, `/invoices`, `/stats`, `/process`) all properly use `require_api_key`. No bypass risk here.

---

## 2. INJECTION ATTACKS

### ✅ PASS — SQL Injection Prevention

Parameterized queries (`?` placeholders) used throughout `b2b_ai/db/db.py`. No user-controlled string interpolation in SQL.

### 🟡 MEDIUM — Dynamic Column Names in SQL (nosec B608)

**File:** `b2b_ai/db/db.py:558, 660, 1097, 1517`

Four instances of f-string SQL with dynamic table/column names, all annotated with `# nosec B608`:

```python
# Line 558 — table/col from _RETENTION_TABLES (fixed allowlist)
f"DELETE FROM {table} WHERE {col} IS NOT NULL AND {col} < ?"

# Line 660 — tabla from literal constant
f"DELETE FROM {tabla}"

# Line 1097 — cols built from caller-provided dict keys
f"UPDATE outreach_campaign_leads SET {', '.join(cols)} WHERE id=?"

# Line 1517 — cols from _CLIENT_USER_EDITABLE allowlist
f"UPDATE client_users SET {sets} WHERE id=?"
```

**Risk assessment:**
- Lines 558, 660, 1517: **Low risk** — column names come from hardcoded allowlists in the code
- Line 1097: **Medium risk** — `cols` built from caller's dict keys. If `update_outreach_lead` is called with user-controlled keys, this could be exploitable. Need to verify all callers.

**Recommendation:** Add an allowlist check for line 1097's `cols` to match the pattern used in line 1517 (`_CLIENT_USER_EDITABLE`).

### 🟡 MEDIUM — exec()/eval() and subprocess Usage

**Files:**
- `b2b_ai/db/db.py:188-199` — `subprocess.run()` for Alembic migration
- `b2b_ai/monitoring/health.py:121-122` — `subprocess.run()` for `sysctl`

Both are **safe**:
- `subprocess.run()` uses list arguments (not `shell=True`)
- No user-controlled input in command construction
- `db.py:195`: runs `[sys.executable, "-m", "alembic", "upgrade", "head"]` — fixed command
- `health.py:122`: runs `["sysctl", "-n", "hw.memsize"]` — fixed command

No `eval()`, `exec()`, `os.system()`, or `os.popen()` found.

**Risk:** LOW — properly mitigated.

### ✅ PASS — Path Traversal Defense

**File:** `b2b_ai/api/security.py`

`validate_xml_path()` resolves symlinks and verifies the path is within allowed directories. The newer `_resolve_local_path()` in `app.py` is the active defense. The legacy `validate_xml_path()` is documented as unused but still present (could be confusing but not a vulnerability).

### ✅ PASS — XSS in HTML Templates

**Files:** `b2b_ai/api/static/*.html`, `b2b_ai/reports/templates/*.html`

Extensive `innerHTML` usage found (28+ instances). However, most use the `esc()` function for user data:
```javascript
esc(p.nombre)  // properly escaped
esc(p.rfc)     // properly escaped
```

The `esc()` function escapes HTML entities. User data is escaped before injection.

**Note:** The `innerHTML` pattern is risky by nature but currently well-mitigated by `esc()`.

---

## 3. SECRETS EXPOSURE

### ✅ PASS — No Hardcoded Secrets in Code

All API keys, passwords, and secrets are loaded from environment variables:
- `B2B_JWT_SECRET` — JWT signing key
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` — LLM providers
- `STRIPE_SECRET_KEY`, `CONEKTA_KEY` — Payment processors
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` — Communication
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` — Storage
- `B2B_ENCRYPTION_KEY` — AES-GCM field encryption

No hardcoded secrets found. The codebase documents a previous `_DEV_SECRET` that was removed (see middleware.py comments).

### 🟢 LOW — API Key Fields in Models Default to Empty String

**Files:** `b2b_ai/integrations/*/models.py`

Many integration config models have:
```python
api_key: str = Field(default="", description="API key")
api_secret: str = Field(default="", description="API secret")
```

These are config objects, not exposed in responses. The empty defaults mean no accidental key leakage, but the `api_key`/`api_secret` field names in Pydantic models could appear in OpenAPI schema.

**Recommendation:** Mark sensitive fields with `exclude=True` in model configs if they shouldn't appear in generated docs.

### 🟡 MEDIUM — Encryption in Degraded Mode

**File:** `b2b_ai/api/security.py:18, 226-232`

If `B2B_ENCRYPTION_KEY` is not set or is <16 chars, `encrypt_field()` returns plaintext:
```python
if c is None:
    return value  # degraded mode: no encryption
```

The code documents this as "NUNCA rompe lecturas/existentes" but it means sensitive fields (webhook URLs, notification recipients) may be stored unencrypted in the database.

**Recommendation:** Log a warning at startup when encryption is in degraded mode. Consider requiring `B2B_ENCRYPTION_KEY` in production.

### 🟢 LOW — SMTP Password in Config

**File:** `b2b_ai/notifications/email_provider.py:45`

```python
self.password = password or env.get("B2B_SMTP_PASSWORD")
```

Loaded from environment (safe), but if the config object is serialized, the password could leak.

---

## 4. DATA LEAKAGE

### 🟠 HIGH — Health Endpoint Exposes Database Path

**File:** `b2b_ai/api/app.py:578`

```python
"db_path": db.path,
```

The unauthenticated `/health` endpoint exposes the full SQLite database path. This reveals:
- Filesystem structure
- Operating system type
- Deployment architecture

**Risk:** Stack fingerprinting for targeted attacks.

**Recommendation:** Remove `db_path` from the public health response, or only include it in the authenticated detailed health endpoint.

### 🟡 MEDIUM — Exception Messages May Leak Internal Details

**File:** `b2b_ai/api/security.py:103-105`

```python
raise ValueError(
    f"xml_path fuera de directorios permitidos: {xml_path}. "
    f"Directorios permitidos: {[str(d) for d in allowed]}"
)
```

The error message includes the full path list. If this is returned to the client (as documented — "el mensaje de error repite la ruta pedida Y la lista de directorios permitidos"), it leaks internal filesystem structure.

**Note:** The code itself acknowledges this was a bug and documents the fix. The function `validate_xml_path` is noted as unused ("no la llama nadie"), so the current risk is zero. But if someone uses it, the error message would leak.

### 🟢 LOW — Sentry Adapter Formats Full Tracebacks

**File:** `b2b_ai/integrations/monitoreo/sentry_adapter.py:74`

```python
stacktrace = "".join(traceback.format_exception(type(error), error, error.__traceback__))
```

Full tracebacks are captured and sent to Sentry. This is normal for error tracking but ensure Sentry is not in debug mode and doesn't expose stack traces in responses.

---

## 5. CRYPTO ISSUES

### 🟡 MEDIUM — SHA-1 Used for Non-Security Purposes

**Files:**
- `b2b_ai/services/contabilidad_electronica.py:61-67` — SAT electronic accounting hash
- `b2b_ai/services/bank_reconciliation.py:184` — Transaction ID generation
- `b2b_ai/features/contabilidad/electronica_routes.py:154-178` — SAT compliance

SHA-1 is used for:
1. **SAT compliance** — required by Mexican tax authority (SAT) for electronic accounting packages. This is a regulatory requirement, not a security choice.
2. **Transaction ID generation** — `hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]` — collision resistance not needed here (ID generation, not authentication).

**Risk:** LOW — SHA-1 is not used for security-sensitive operations.

### 🟡 MEDIUM — MD5 Used for UUID Generation

**File:** `b2b_ai/sat/downloader.py:62`

```python
return str(uuid.UUID(hashlib.md5(seed).hexdigest()))
```

MD5 used to generate deterministic UUIDs from seed data. Not used for security (just ID generation), but MD5 is cryptographically broken.

**Recommendation:** Consider using `hashlib.sha256` for consistency, though this is low risk.

### 🟢 LOW — Weak Random in Demo/Non-Critical Code

**File:** `b2b_ai/demo/firm_generator.py` — multiple instances

`random.randint()`, `random.choice()`, `random.random()` used for demo data generation. Not security-sensitive (generates fake invoices for demo).

**Risk:** None — this is demo/fixture code only.

### ⚪ INFO — AES-GCM Encryption Correctly Implemented

**File:** `b2b_ai/api/security.py:225-253`

AES-GCM with:
- 32-byte key derived via SHA-256
- 12-byte random nonce per encryption
- Proper encrypt/decrypt with authenticated encryption
- `os.urandom(12)` for nonce generation (CSPRNG)

This is correctly implemented.

---

## 6. RACE CONDITIONS

### 🟢 LOW — Thread-Local SQLite Connections

**File:** `b2b_ai/db/db.py:84-89`

SQLite connections are thread-local (`threading.local()`), which prevents concurrent access issues within a single process. The code documents this: "una sola sqlite3.Connection compartida entre hilos NO es segura."

**Risk:** LOW — properly mitigated with thread-local connections.

### ✅ PASS — Rate Limiters Exist

Rate limiting is implemented at multiple levels:
- Global: `RateLimiter` class in `api/app.py:272`
- Per-tenant: `TenantRateLimiter` in `api/v2.py:124`
- Alert store: `_check_rate_limit()` in `features/alertas/store.py:323`
- Notification scheduler: `RateLimiter` in `notifications/scheduler.py:34`

---

## 7. RESOURCE EXHAUSTION

### 🟡 MEDIUM — No Input Size Limit on POST Endpoints

Many POST endpoints accept request bodies without explicit size limits:
- `POST /api/v1/invoices/process` — accepts XML content
- `POST /api/v1/reconcile/run` — accepts CSV content
- `POST /api/v1/leads` — accepts form data

FastAPI/Starlette have default limits, but explicit limits would be defense-in-depth.

**Recommendation:** Add `max_body_size` or `max_upload_size` middleware.

### ⚪ INFO — Timeout Settings Present

- `subprocess.run(..., timeout=120)` in `db/db.py:198` — Alembic migration
- `urllib.request.urlopen(req, timeout=timeout)` in `webhooks.py:77` — configurable webhook timeout
- Rate limiter windows defined

---

## Positive Findings (What's Done Well)

1. **JWT Auth with Fail-Safe** — Production mode fails without `B2B_JWT_SECRET`; no hardcoded fallback
2. **Constant-Time Comparisons** — `hmac.compare_digest()` for token validation
3. **Path Traversal Defense** — Symlink resolution + allowed directory validation
4. **Encryption at Rest** — AES-GCM for sensitive fields with proper nonce generation
5. **PII Detection** — Comprehensive scan for RFC, CURP, email, phone, card numbers
6. **RBAC** — Role-based permissions with `require_permission()` and `require_tenant_admin()`
7. **Tenant Isolation** — Multi-tenant data isolation enforced at auth level
8. **Rate Limiting** — Multiple layers (global, per-tenant, per-feature)
9. **Thread-Local DB** — Proper SQLite concurrency handling
10. **CORS Configuration** — Configurable via `B2B_CORS_ORIGINS`, defaults to disabled (most secure)
11. **No shell=True in subprocess** — All subprocess calls use list arguments
12. **SQL Injection Prevention** — Parameterized queries throughout

---

## Recommendations Summary (Priority Order)

| # | Severity | Finding | Recommendation |
|---|----------|---------|----------------|
| 1 | 🟠 HIGH | Health endpoint leaks DB path | Remove `db_path` from public `/health` response |
| 2 | 🟡 MEDIUM | Dynamic SQL cols at line 1097 | Add allowlist check for `update_outreach_lead` |
| 3 | 🟡 MEDIUM | Health/metrics public without auth | Add IP allowlist or require auth |
| 4 | 🟡 MEDIUM | No body size limits on POST | Add upload size middleware |
| 5 | 🟡 MEDIUM | Encryption degraded mode silent | Log warning at startup when no encryption key |
| 6 | 🟡 MEDIUM | Public leads endpoint per-IP rate limit | Add per-IP rate limiting |
| 7 | 🟢 LOW | MD5 for UUID generation | Consider SHA-256 |
| 8 | 🟢 LOW | API keys in Pydantic models | Mark sensitive fields `exclude=True` |

---

*Audit completed. No critical vulnerabilities. Codebase has strong security fundamentals with room for defense-in-depth improvements.*
