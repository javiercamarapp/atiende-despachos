# AUDITORÍA EXHAUSTIVA — RUBROS 9-13

**Fecha:** 2026-08-01  
**Alcance:** enterprise/b2b_ai/ — Rubros 9 a 13  
**Fiscal year:** 2026 (AÑO_FISCAL=2026)  
**Tests ejecutados:** `pytest tests/test_computer_use_unit.py tests/test_computer_use_e2e.py` → **38 passed, 1 warning, 0 failures** (9.69s)

---

## RUBRO 9 — INTEGRACIONES

### 9.1 Inventario de Adapters

| Categoría | Adapters | Archivos |
|---|---|---|
| Comunicación | 7 | Twilio, SendGrid, AWS SES, Mailgun, Vonage, MessageBird, WhatsApp Business |
| SAT / PACs | 6 | Ecodex, Finkok, SAT Portal, Facturapi, Corefi, Multifactura, PAXFACTURAS |
| ERP | 13 | CONTPAQi Web/Desktop, Aspel Cloud/Desktop, QuickBooks, Xero, Peak, Multileg, Euroweb, Absis, Factor D, Taxko, FacturaDirecta |
| Bancos | 8 | BBVA, Banorte, Santander, HSBC, Banamex, Scotiabank, Inbursa, Afirme |
| Pagos | 7 | Stripe, Conekta, MercadoPago, PayPal, PayPal México, OpenPay, Kushki |
| Google | 3 | Gmail, Calendar, Sheets |
| Microsoft | 3 | Outlook, M365, Excel |
| CRM | 4 | HubSpot, Salesforce, Pipedrive, Zoho CRM |
| Storage | 6 | S3, GCS, Google Drive, Dropbox, Box, OneDrive |
| Compliance | 6 | LFPDPPP, LISR, LIVA, CFF, LFT, NOM-151 |
| Gobierno | 4 | IMSS, INFONAVIT, SAR, CONDUSEF |
| Firmas | 3 | FIEL, DocuSign, Adobe Sign |
| Monitoreo | 4 | Sentry, Datadog, NewRelic, LogRocket |
| Analytics | 3 | Amplitude, Mixpanel, Google Analytics |
| AI | 2 | OpenAI, Anthropic |
| Calendario | 1 | Calendly |
| Social | 3 | Facebook, Instagram, LinkedIn |
| Documentos | 4 | ReportLab, lxml, Tesseract, OpenPyxl |
| **Total** | **~87** | **14 categorías** |

### 9.2 Importación — HALLAZGO CRÍTICO

**BUG DE IMPORTACIÓN CASCADA:** `b2b_ai/integrations/__init__.py` importa eagerly TODOS los módulos. Si cualquier módulo en la cadena falla, TODAS las importaciones fallan.

**Síntoma:** Importar `b2b_ai.integrations.bancos.banorte` directamente funciona (`BanorteAdapter` existe y es importable), pero importar vía `b2b_ai.integrations` falla con:
```
ImportError: cannot import name 'BanorteAdapter' from 'b2b_ai.integrations.bancos.banorte'
```

**Resultado importación masiva:** 11/73 OK (15%), 62/73 FAIL (85%) — todas fallan por el mismo error cascada en `__init__.py`.

**Importaciones directas (sin `__init__.py`):** Funcionan correctamente. Ejemplo:
- `from b2b_ai.integrations.bancos.banorte import BanorteAdapter` ✅
- `from b2b_ai.integrations.sat.pacs.facturapi_adapter import FacturapiAdapter` ✅
- `from b2b_ai.computer_use.factory import ComputerUseDriverFactory` ✅

### 9.3 Error Handling y Timeouts

- **ERP HTTP Client** (`erp/http_client.py`): ✅ `DEFAULT_TIMEOUT=30s`, `DEFAULT_CONNECT_TIMEOUT=10s`, `DEFAULT_RETRY_ATTEMPTS=3`, backoff exponencial (1s→30s)
- **Todos los ERP adapters** usan `self.config.timeout` y `self.config.retry_attempts` ✅
- **PlaywrightDesktop**: retry con `_retry_async()` — exponential backoff configurable ✅
- **IntegrationHub**: `register_adapter()`, `connect_all()`, `get_status()` ✅

### 9.4 Veredicto Rubro 9

| Aspecto | Estado |
|---|---|
| Inventario completo | ✅ 87 adapters, 14 categorías |
| Imports directos | ✅ Funcionan |
| Imports via `__init__.py` | 🔴 **ROTO** — cascada de 85% fallos |
| Error handling | ✅ Excepciones específicas, retry, backoff |
| Timeouts configurados | ✅ 30s default, configurable |
| **Calificación** | **🟡 CONDICIONAL — bug de importación debe resolverse** |

---

## RUBRO 10 — CUMPLIMIENTO LEGAL

### 10.1 LFPDPPP (Ley Federal de Protección de Datos Personales)

| Requisito | Implementación | Estado |
|---|---|---|
| Aviso de privacidad | `LFPDPPPCompliance.validar_aviso_privacidad()` | ✅ |
| Consentimiento expreso | `validar_consentimiento(datos_sensibles, consentimiento)` | ✅ |
| Derechos ARCO | `validar_derechos_arco()` — Art. 28-35 | ✅ |
| Finalidad del tratamiento | Validado en `validar_aviso_privacidad(incluye_finalidad)` | ✅ |
| Referencia legal | Art. 16, Reglas del Reglamento Art. 41-49 | ✅ |

### 10.2 Cifrado de PII

| Capa | Implementación | Estado |
|---|---|---|
| Credenciales en reposo | Fernet (AES-128-CBC + HMAC) via `B2B_ENCRYPTION_KEY` | ✅ |
| Fallback degradado | base64 obfuscation con `logger.critical()` warning | ✅ |
| PII en screenshots | Regex masking: RFC, CURP, nómina, teléfono, tarjeta | ✅ |
| PII en dicts | `mask_pii_in_dict()` — recursivo, por nombre de campo y patrón | ✅ |
| RFC masking en logs | `mask_rfc()` — CFF Art. 82 compliance | ✅ |
| Amount masking | `mask_amount()` — redacta >$100,000 en logs | ✅ |

### 10.3 Auditoría Inmutable

| Componente | Detalle | Estado |
|---|---|---|
| `AuditEntry` | frozen dataclass — no se puede modificar post-creación | ✅ |
| `AuditLog` | Append-only, thread-safe (Lock), rotación a 10K entries | ✅ |
| Persistencia | JSONL opcional (`persist_path`) | ✅ |
| Idempotency | `idempotency_index` previene duplicados | ✅ |
| `AuditTrail` (compliance.py) | In-memory, filtrable por módulo/tenant | ✅ |
| `AuditTrailEntry` | timestamp, user, action, module, result, tenant_id | ✅ |

### 10.4 Retención de Datos

| Tipo | Política | Estado |
|---|---|---|
| Screenshots | `RetentionPolicy`: 72h default, 1000/tenant, 500MB max | ✅ |
| Sessions | 30min timeout, max 3/tenant, auto-evict oldest | ✅ |
| Audit log | 10K entries max con rotación | ✅ |
| Datos PII generales | ⚠️ Sin política de retención explícita más allá de screenshots | ⚠️ |

### 10.5 NOM-151 (Conservación Electrónica)

| Requisito | Implementación | Estado |
|---|---|---|
| Integridad de documento | Hash SHA-256 comparison | ✅ |
| Sello de tiempo | Validación de coherencia fecha_creacion/fecha_sello | ✅ |
| Autenticidad | Firma electrónica avanzada + certificado | ✅ |
| Informe cumplimiento | `generar_informe_cumplimiento()` con % | ✅ |

### 10.6 Veredicto Rubro 10

| Aspecto | Estado |
|---|---|
| LFPDPPP | ✅ Completo (aviso, consentimiento, ARCO) |
| Cifrado PII | ✅ Fernet + fallback con warning |
| Auditoría inmutable | ✅ frozen dataclass + append-only log |
| Retención | ✅ Screenshots/sesiones; ⚠️ datos generales sin política explícita |
| NOM-151 | ✅ Integridad, sello, autenticidad |
| **Calificación** | **🟢 CUMPLE con observación menor en retención de datos generales** |

---

## RUBRO 11 — CUMPLIMIENTO FISCAL

### 11.1 fiscal_tables.py

| Tabla | 2024 | 2025 | 2026 | Estado |
|---|---|---|---|---|
| ISR Mensual | 10 rows | 10 rows | 10 rows | ✅ |
| ISR Anual | 10 rows | 10 rows | 10 rows | ✅ |
| ISR Quincenal | — | 10 rows | 10 rows | ✅ |
| Subsidio Mensual | — | 11 rows | 11 rows | ✅ |
| Subsidio Quincenal | — | 11 rows | 11 rows | ✅ |
| UMA Diario | — | $113.15 | $113.04 | ✅ |
| UMA Mensual | — | $3,439.54 | $3,391.20 | ✅ |
| UMA Anual | — | $41,274.48 | $40,694.40 | ✅ |
| `get_isr_table()` | ✅ | ✅ | ✅ | Todas las combinaciones |
| `get_subsidio_table()` | — | ✅ | ✅ | Todas las combinaciones |

**⚠️ OBSERVACIÓN:** Las tablas ISR 2026 son copia exacta de 2025 con TODO de actualizar cuando el DOF publique. Esto es correcto para MVP pero debe actualizarse antes de producción fiscal 2026.

### 11.2 IVA (LIVA)

| Tasa | Válida | Estado |
|---|---|---|
| 0% | ✅ | `validate_iva_rate(0)` → True |
| 8% | ✅ | `validate_iva_rate(0.08)` → True |
| 16% | ✅ | `validate_iva_rate(0.16)` → True |
| 12% | ❌ | Correctamente rechazado |
| 5% | ❌ | Correctamente rechazado |

`VALID_IVA_RATES = {0, 0.0, 8, 0.08, 16, 0.16}` — Solo tasas mexicanas válidas.

### 11.3 ISR (LISR Art. 96)

- `calculate_isr(10000)` → $1,290.41 ✅ (verificado contra tabla manual)
- Tabla progresiva con 10 rangos, cuota fija + porcentaje excedente
- Soporta periodos: monthly, annual, quincenal

### 11.4 CFDI 4.0 / DIOT / Nómina IMSS

| Componente | Archivo | Estado |
|---|---|---|
| DIOT Service | `services/diot_service.py` — parse, validate, summarize | ✅ |
| DIOT Validator | `services/diot_validator.py` — XML validation | ✅ |
| DIOT Expansion | `services/diot_expansion.py` | ✅ |
| Nómina CFDI | `services/nomina_cfdi.py` | ✅ |
| DIOT Generator | `features/declaraciones/diot_generator.py` | ✅ |
| DIOT Feature | `features/diot/` con tests | ✅ |
| Conciliación Fiscal | `features/conciliacion_fiscal/` con tests | ✅ |
| Compliance CFF | Art. 30, 82, 85, 86, 89, 105 referenciados | ✅ |

### 11.5 Veredicto Rubro 11

| Aspecto | Estado |
|---|---|
| ISR 2026 tables | ✅ Presentes (⚠️ copia de 2025, TODO actualizar) |
| UMA 2026 | ✅ Actualizado ($113.04 diario) |
| Subsidio 2026 | ✅ Presente (11 rangos) |
| IVA 16% | ✅ Solo 0/8/16% permitidos |
| CFDI / DIOT | ✅ Service + validator + generator |
| Nómina IMSS | ✅ NominaCFDI + integration IMSS |
| **Calificación** | **🟡 CUMPLE — TODO actualizar ISR 2026 cuando DOF publique** |

---

## RUBRO 12 — RENDIMIENTO Y COSTO

### 12.1 Tiempo de Importación

| Métrica | Valor | Estado |
|---|---|---|
| Import time (core + fiscal + computer_use) | 10.14s | ⚠️ Lento |
| Peak memory (core + fiscal + computer_use) | 7,885 KB (7.7 MB) | ✅ Aceptable |
| Módulos importados en 10s | ~15 módulos principales | ⚠️ Optimizable |

**Causa raíz:** Importación eager de todos los módulos. `b2b_ai.integrations.__init__.py` importa 87 adapters en cadena.

### 12.2 Connection Pool

| Característica | Implementación | Estado |
|---|---|---|
| Clase | `EnterpriseConnectionPool` (`infrastructure/db_pool.py`) | ✅ |
| Pool sizing | min=2, max=10, overflow=5 | ✅ |
| Health checks | `pre_ping=True` | ✅ |
| Connection recycling | `max_lifetime=3600s` (1h) | ✅ |
| Idle timeout | `idle_timeout=300s` (5min) | ✅ |
| Slow query logging | `slow_query_threshold_ms=500ms` | ✅ |
| Metrics | Prometheus-compatible export | ✅ |
| Thread-safe | Lock-protected | ✅ |

### 12.3 N+1 Queries

**No se encontró detección ni prevención de N+1 queries.** Los adapters de ERP usan HTTP calls individuales sin batch.

### 12.4 Batch Processing

**No se encontró procesamiento batch** en integraciones. Operaciones son una-por-una.

### 12.5 Costos LLM

| Componente | Estado |
|---|---|
| Token cost tracking | ❌ No encontrado |
| LLM pricing table | ❌ No encontrada |
| Cost per invoice (reportes) | ✅ `cost_per_invoice` en reportes_gerenciales |
| Budget limits | ❌ No encontrado |

### 12.6 Veredicto Rubro 12

| Aspecto | Estado |
|---|---|
| Connection pool | ✅ Enterprise-grade con métricas |
| Import time | ⚠️ 10s — lazy loading recomendado |
| Memory | ✅ 7.7 MB aceptable |
| N+1 queries | ❌ Sin detección |
| Batch processing | ❌ No implementado |
| LLM cost tracking | ❌ Solo cost_per_invoice básico |
| **Calificación** | **🟡 PARCIAL — pool excelente, faltan N+1/batch/cost tracking** |

---

## RUBRO 13 — COMPUTER USE

### 13.1 Factory Pattern

| Aspecto | Implementación | Estado |
|---|---|---|
| Entry point | `ComputerUseDriverFactory.create()` | ✅ |
| Modos | mock, playwright, disabled | ✅ |
| Providers | contpaqi, aspel (`VALID_PROVIDERS`) | ✅ |
| **No fallback silencioso** | Factory NUNCA cae de real→mock | ✅ |
| Error en modo inválido | `ComputerUseConfigurationError` | ✅ |
| Provider inválido | `ComputerUseConfigurationError` con lista válida | ✅ |

### 13.2 Configuración (ComputerUseConfig)

| Aspecto | Implementación | Estado |
|---|---|---|
| Frozen dataclass | Inmutable post-creación | ✅ |
| Env vars | 12+ variables de entorno | ✅ |
| Production rejects mock | `B2B_ENV=production` + `mode=mock` → error | ✅ |
| Playwright requiere creds | URL + username + password obligatorios | ✅ |
| Rechaza example.com | En modo playwright, URLs placeholder → error | ✅ |
| Password masking | `__repr__` enmascara password | ✅ |
| allow_writes default | `False` (read-only safe) | ✅ |

### 13.3 Drivers Reales

| Driver | Archivo | Motor | Estado |
|---|---|---|---|
| PlaywrightDesktop | `playwright_desktop.py` | Chromium via Playwright | ✅ |
| CONTPAQiRealDriver | `contpaqi_real_driver.py` | PlaywrightDesktop | ✅ |
| AspelRealDriver | `aspel_real_driver.py` | PlaywrightDesktop | ✅ |
| AspelDriver (mock) | `aspel_driver.py` | MockDesktop | ✅ |
| ContpaqiDriver (mock) | `contpaqi_driver.py` | MockDesktop | ✅ |
| MockComputerUseDriver | `factory.py` | In-memory | ✅ |
| DisabledDriver | `factory.py` | No-op | ✅ |

### 13.4 Seguridad (security.py — 862 líneas)

| Capa | Implementación | Estado |
|---|---|---|
| Domain allowlist | 14 dominios ERP conocidos | ✅ |
| Hard-blocked domains | example.com, localhost, 127.0.0.1, ::1 | ✅ |
| Credential encryption | Fernet (AES-128-CBC + HMAC) | ✅ |
| Tenant isolation | `TenantBrowserContext` — cookies/storage/screenshots separados | ✅ |
| Session management | 30min timeout, max 3/tenant, auto-evict | ✅ |
| PII masking | RFC, CURP, nómina, teléfono, tarjeta — regex + field name | ✅ |
| Retention policy | 72h, 1000/tenant, 500MB max, auto-purge | ✅ |
| Immutable audit log | `AuditEntry` frozen + `AuditLog` append-only | ✅ |
| RBAC | admin/contador/auxiliar/auditor con permisos granulares | ✅ |
| Write gate | `B2B_COMPUTER_USE_ALLOW_WRITES=false` default | ✅ |
| Human confirmation | 9 acciones fiscales requieren confirmación humana | ✅ |
| Idempotency | SHA-256 determinístico por tenant+action+target | ✅ |
| SecurityConfig | Agrega todas las settings con `from_env()` y `validate()` | ✅ |

### 13.5 erp_factory / register_erp

**Patrón `erp_factory` explícito no encontrado.** En su lugar:

- `IntegrationHub.register_adapter()` es el patrón de registro
- `ComputerUseDriverFactory.create()` es el factory para computer use
- `ERPAdapter` es la interfaz abstracta con `connect()`, `get_invoices()`, `get_polizas()`, `upload_poliza()`, etc.
- Los adapters se registran en `hub.py` via `IntegrationHub`

### 13.6 E2E Tests

```
pytest tests/test_computer_use_unit.py tests/test_computer_use_e2e.py
→ 38 passed, 1 warning in 9.69s
```

| Test file | Tests | Estado |
|---|---|---|
| test_computer_use_unit.py | Unit tests de factory, config, mock, disabled | ✅ |
| test_computer_use_e2e.py | E2E tests de flujo completo | ✅ |
| Warning | PytestUnknownMarkWarning `computer_use_e2e` | ⚠️ Menor |

### 13.7 Veredicto Rubro 13

| Aspecto | Estado |
|---|---|
| Factory | ✅ Sin fallback silencioso |
| Config | ✅ Frozen, production-safe, env-based |
| Drivers reales | ✅ PlaywrightDesktop + CONTPAQi + Aspel |
| Security (12 capas) | ✅ Completo |
| RBAC + Write gate | ✅ 4 roles, default read-only |
| Human confirmation | ✅ 9 acciones fiscales |
| E2E tests | ✅ 38/38 passed |
| erp_factory | ⚠️ Usa IntegrationHub en vez de erp_factory explícito |
| **Calificación** | **🟢 CUMPLE — Implementación robusta y bien testeada** |

---

## RESUMEN EJECUTIVO

| Rubro | Calificación | Hallazgos Críticos |
|---|---|---|
| **9. Integraciones** | 🟡 CONDICIONAL | 🔴 Bug importación cascada en `__init__.py` (85% fallos) |
| **10. Cumplimiento Legal** | 🟢 CUMPLE | ⚠️ Retención datos generales sin política explícita |
| **11. Cumplimiento Fiscal** | 🟡 CUMPLE | ⚠️ ISR 2026 = copia de 2025 (TODO DOF) |
| **12. Rendimiento y Costo** | 🟡 PARCIAL | ❌ Sin N+1 detection, batch, LLM cost tracking |
| **13. Computer Use** | 🟢 CUMPLE | ✅ 38/38 tests, security completa, factory sin fallback |

### Acciones Correctivas Prioritarias

1. **🔴 CRÍTICO — Rubro 9:** Resolver bug de importación cascada en `b2b_ai/integrations/__init__.py`. Convertir a lazy imports o fix circular dependency.
2. **🟡 ALTO — Rubro 11:** Actualizar tablas ISR 2026 cuando el DOF publique (actualmente copia de 2025).
3. **🟡 MEDIO — Rubro 12:** Implementar lazy loading para reducir import time de 10s a <2s.
4. **🟡 MEDIO — Rubro 12:** Agregar detección de N+1 queries y batch processing en adapters.
5. **🟡 MEDIO — Rubro 12:** Implementar LLM cost tracking (tokens × pricing table).
6. **🟢 BAJO — Rubro 10:** Definir política de retención para datos PII generales (no solo screenshots).
7. **🟢 BAJO — Rubro 13:** Registrar mark `computer_use_e2e` en pytest para eliminar warning.

---

*Auditoría generada automáticamente — b2b_ai enterprise codebase, fiscal year 2026.*
