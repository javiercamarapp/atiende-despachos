# AUDIT-FINAL-TESTING.md — Auditoría Exhaustiva de Cobertura de Tests

**Proyecto**: likida-ai-enterprise  
**Fecha**: 2026-08-01  
**Auditor**: Testing Specialist (subagent)  
**Stack**: pytest, FastAPI TestClient, SQLite in-memory/tmp  
**Métricas globales**: ~7,048 funciones `test_` en 195 archivos, ~108K LOC fuente

---

## Resumen Ejecutivo

| Dimensión | Calificación | Hallazgos clave |
|---|---|---|
| Cobertura de módulos | ⚠️ MEDIA | 69 módulos sin referencia alguna en tests |
| Calidad de assertions | ⚠️ MEDIA | 769 assertions solo verifican status_code; muchos tests smoke |
| Edge cases | ✅ BUENA | test_edge_cases_contract.py y test_diot.py cubren montos extremos, fechas |
| Fixtures | ✅ BUENA | conftest.py y conftest_enterprise.py proveen db, client, tenant, fixtures CFDI |
| Factories | ✅ EXISTEN | tests/factories.py con CFDIFactory y BankTransactionFactory |
| Integración CFDI→ERP | ✅ BUENA | test_full_pipeline.py + test_erp_integration.py cubren flujo completo |
| Error paths | ✅ BUENA | 300 assertions de errores HTTP (401/403/404/422/500) |
| Concurrency | ⚠️ BAJA | Solo 3 tests de concurrencia (threading), sin multi-tenant race conditions |
| Performance | ❌ MÍNIMA | 1 test de "performance" (test_analytics.py:1029), sin benchmarks reales |
| Snapshot XML | ⚠️ BAJA | Solo 2 snapshot tests en test_enterprise_hardening.py |

---

## 1. COBERTURA: Módulos sin tests (69 módulos)

### Severidad: MEDIA — Muchos son adapters de integración que requieren mocking externo

| Módulo | Categoría | Severidad | Test propuesto |
|---|---|---|---|
| `b2b_ai/api/middleware.py` | Core API | 🔴 ALTA | `test_api_middleware.py` — auth header parsing, rate limit bypass, CORS |
| `b2b_ai/api/errors 2.py` | Core API | 🟡 MEDIA | Consolidar con errors.py, test de error handlers |
| `b2b_ai/audit/middleware.py` | Core Audit | 🔴 ALTA | `test_audit_middleware.py` — audit trail persistence, request logging |
| `b2b_ai/cfdi/xml_security.py` | Core CFDI | 🔴 ALTA | `test_xml_security.py` — XSD validation, signature verification |
| `b2b_ai/fiscal_tables.py` | Core Fiscal | 🟡 MEDIA | `test_fiscal_tables.py` — tablas ISR/IVA, catálogos SAT |
| `b2b_ai/portal/routes.py` | Core Portal | 🟡 MEDIA | `test_portal_routes.py` — portal endpoints, auth |
| `b2b_ai/services/timeouts.py` | Core Services | 🟡 MEDIA | `test_service_timeouts.py` — timeout enforcement |
| `b2b_ai/sat/efos_69b.py` | Core SAT | 🟡 MEDIA | `test_efos_69b.py` — EFOS list matching |
| **b2b_ai/features/close_management/routes.py** | Feature | 🔴 ALTA | Close management API endpoints sin test |
| **b2b_ai/features/declaraciones/declaration_api.py** | Feature | 🔴 ALTA | Declaration API endpoints sin test |
| **b2b_ai/features/declaraciones/fiel_signer.py** | Feature | 🔴 ALTA | FIEL digital signing — crítico fiscal |
| `b2b_ai/features/vencimientos/routes.py` | Feature | 🟡 MEDIA | Vencimientos API endpoints |
| `b2b_ai/features/conciliacion/routes.py` | Feature | 🟡 MEDIA | Conciliación API endpoints |
| `b2b_ai/features/devolucion_iva/routes.py` | Feature | 🟡 MEDIA | Devolución IVA endpoints |
| `b2b_ai/features/diot/routes.py` | Feature | 🟡 MEDIA | DIOT endpoints |
| `b2b_ai/features/reconciliacion_ingresos_egresos/routes.py` | Feature | 🟡 MEDIA | R&E reconciliation endpoints |
| `b2b_ai/features/reconciliation_agent/routes.py` | Feature | 🟡 MEDIA | Reconciliation agent endpoints |
| `b2b_ai/integrations/ai/anthropic_adapter.py` | Integration | 🟢 BAJA | Mock de API Anthropic |
| `b2b_ai/integrations/ai/openai_adapter.py` | Integration | 🟢 BAJA | Mock de API OpenAI |
| **Todos los adapters de compliance** (6 módulos: cff, lfpdppp, lft, lisr, liva, nom151) | Integration | 🟡 MEDIA | `test_compliance_adapters.py` — mock de leyes fiscales MX |
| **Todos los adapters de CRM** (4: hubspot, pipedrive, salesforce, zoho) | Integration | 🟢 BAJA | `test_crm_adapters.py` — mock de APIs CRM |
| **Todos los adapters de storage** (6: box, dropbox, gcs, gdrive, onedrive, s3) | Integration | 🟢 BAJA | `test_storage_adapters.py` — mock de cloud storage |
| **Todos los adapters de comunicación** (4: aws_ses, mailgun, messagebird, vonage) | Integration | 🟢 BAJA | `test_comunicacion_adapters_extra.py` |
| **Todos los adapters de gobierno** (4: condusef, imss, infonavit, sar) | Integration | 🟡 MEDIA | `test_gobierno_adapters.py` |
| **Todos los adapters de firmas** (3: adobe_sign, docusign, fiel) | Integration | 🟡 MEDIA | `test_firmas_adapters.py` |
| `b2b_ai/computer_use/aspel_real_driver.py` | Desktop | 🟢 BAJA | Tests de driver Aspel |
| `b2b_ai/computer_use/contpaqi_real_driver.py` | Desktop | 🟢 BAJA | Tests de driver ContPAQI real |
| `b2b_ai/computer_use/playwright_desktop.py` | Desktop | 🟢 BAJA | Tests de Playwright desktop |

### Prioridad de cobertura:
1. **URGENTE**: `api/middleware.py`, `audit/middleware.py`, `cfdi/xml_security.py`, `fiel_signer.py`, feature routes
2. **IMPORTANTE**: `fiscal_tables.py`, compliance adapters, gobierno adapters
3. **NORMAL**: CRM, storage, comunicación adapters (solo mock testing)

---

## 2. CALIDAD: Smoke tests vs assertions reales

### Severidad: MEDIA

**Hallazgos**:
- **769 assertions** son solo `assert response.status_code == XXX` — verifican HTTP status pero no contenido
- Muchos tests en `tests/test_*.py` son "fuegos artificiales" — pasan pero no prueban comportamiento

**Ejemplos de assertions débiles**:

| Archivo | Línea | Assertion débil | Test propuesto |
|---|---|---|---|
| `tests/test_api.py` | 27 | `assert r.status_code == 200` (health) | Ya complementa con `body["status"]` — OK |
| `tests/test_dashboard.py` | ~50 | Solo `status_code == 200` en dashboard data | Añadir: verificar estructura JSON, campos requeridos |
| `tests/test_reportes.py` | ~80 | Solo `status_code == 200` en reportes | Añadir: verificar contenido del reporte, totales |
| `tests/test_notifications.py` | ~30 | Solo verificación de status | Añadir: verificar template renderizado, destinatarios |
| `tests/services/test_analytics.py` | ~100 | Solo smoke en endpoints analytics | Añadir: verificar métricas calculadas, rangos de fecha |

**Tests con assertions FUERTES (ejemplares)**:
- `tests/test_auth_rbac.py` — Verifica permisos exactos por rol, JWT tamper, expiración
- `tests/test_edge_cases_contract.py` — Verifica respuestas detalladas, campos específicos
- `tests/cfdi/test_validator.py` — Verifica códigos de error específicos, conteo de issues
- `tests/integration/test_full_pipeline.py` — Verifica categorías, campos de salida, dedup

---

## 3. EDGE CASES: Límites y casos extremos

### Severidad: ✅ BUENA (con gaps)

**Cubierto**:
- ✅ Montos negativos: `tests/test_diot.py:157` — `test_negative_monto_raises`
- ✅ Montos muy grandes: `test_edge_cases_contract.py` — montos > 99,999,999
- ✅ Campos faltantes en CFDI: `test_edge_cases_contract.py` — Fecha, RFC, SubTotal/Total
- ✅ Caracteres de control inválidos: 422 controlado
- ✅ CFDI corrupto: `test_full_pipeline.py:73` — graceful error handling
- ✅ Duplicados: `test_full_pipeline.py:125` — dedup verification
- ✅ XML malformado: múltiples tests

**FALTA (gaps)**:

| Gap | Severidad | Test propuesto |
|---|---|---|
| Montos = 0.00 | 🟡 MEDIA | `test_monto_cero` — ¿acepta CFDI con subtotal=0? |
| Fechas edge: 29 Feb (bisiesto) | 🟡 MEDIA | `test_fecha_bisiesto` — CFDI con fecha 2024-02-29 |
| Fechas edge: 31 dic / 1 enero | 🟡 MEDIA | `test_cierre_anual` — CFDI en cambio de año |
| Fechas futuras | 🟡 MEDIA | `test_fecha_futura` — CFDI con fecha 2030-01-01 |
| RFC con caracteres especiales | 🟢 BAJA | Ya cubierto parcialmente en test_erp_integration |
| Decimal precision (rounding) | 🟡 MEDIA | `test_rounding_iva` — IVA 16% con montos que generan decimales largos |
| Total = Subtotal (tasa 0%) | 🟡 MEDIA | `test_tasa_cero` — CFDI exento de IVA |
| XML con namespace alterado | 🟢 BAJA | `test_namespace_modificado` |

---

## 4. FIXTURES: Infrastructure enterprise

### Severidad: ✅ BUENA

**`tests/conftest.py`** (147 líneas):
- ✅ `B2B_JWT_SECRET` configurado para CI
- ✅ `B2B_ENV=test` autouse
- ✅ `B2B_LOCAL_XML_DIRS` con confinement de paths
- ✅ Fixtures de CFDI XML (papeleria, consultoria, nomina, honorarios, pago, retenciones)
- ✅ `fixture_path()` helper
- ❌ NO tiene fixture de `authenticated_client` reutilizable
- ❌ NO tiene fixture de `db_session` con rollback automático

**`tests/production/conftest.py`** (136 líneas):
- ✅ `rate_limited_client` — TestClient con rate limit bajo, 2 tenants con API keys
- ✅ Fixtures de infra real (PostgreSQL, Redis) con skip si Docker no disponible
- ✅ `pg_engine` — SQLAlchemy engine real
- ✅ `redis_client` — Redis real
- ❌ NO tiene fixture de `admin_user` o `contador_user`

**`tests/conftest_enterprise.py`** (existe, no analizado en profundidad):
- Probablemente complementa con fixtures enterprise adicionales

**Fixtures faltantes recomendadas**:

| Fixture | Propósito | Test propuesto |
|---|---|---|
| `authenticated_client(role)` | TestClient con JWT de rol específico | Añadir a conftest.py |
| `db_session` | SQLAlchemy session con rollback | Añadir a conftest.py |
| `tenant_factory` | Crear N tenants con datos | Usar factories.py |
| `sample_cfdi_xml(tipo)` | Generar XML parametrizado | Ya existe en factories.py |

---

## 5. FACTORIES: Test data builders

### Severidad: ✅ EXISTEN

**`tests/factories.py`** (18,447 bytes — archivo robusto):
- ✅ `CFDIFactory` — `.gasto_operativo()`, `.nomina()`, `.honorarios()`, `.xml_content()`
- ✅ `BankTransactionFactory` — `.spei_transfer()`, `.batch()`
- Probablemente incluye más builders

**Tests que usan factories**:
- `tests/test_enterprise_hardening.py:749-789` — Tests de CFDIFactory y BankTransactionFactory

**Recomendación**: Expandir uso de factories a más tests en lugar de hardcodear datos inline.

---

## 6. INTEGRATION TESTS: Flujo CFDI → ERP

### Severidad: ✅ BUENA

**`tests/integration/test_full_pipeline.py`** (170 líneas, 5 tests):
- ✅ 5 tipos de CFDI → clasificación correcta (parametrizado)
- ✅ CFDI corrupto → graceful error
- ✅ Monto atípico → detección de anomalía
- ✅ Duplicado → no re-inserta
- ✅ Output integrity → todos los campos presentes

**`tests/test_erp_integration.py`** (~700 líneas, 50+ tests):
- ✅ Abstract ERP interface
- ✅ Mock ContPAQI → register, health, polizas
- ✅ CSV ERP → export, accumulate
- ✅ QuickBooks → bills, invoices, vendors, customers
- ✅ ERP Automation → retry, session management
- ✅ Edge cases: RFC con caracteres especiales, totales grandes, categorías desconocidas

**`tests/test_integration_pipeline.py`** (~80 líneas, 6 tests):
- ✅ Pipeline completo una factura
- ✅ Audit trail de cada tool
- ✅ Multi-tenant aislamiento
- ✅ Batch completo
- ✅ Duplicado no re-inserta
- ✅ Nómina marca revisión humana

**Gap**: No hay test de **CFDI → ERP real** (ContPAQI/Aspel desktop) con `computer_use` — solo mocks.

---

## 7. ERROR PATHS: HTTP error codes

### Severidad: ✅ BUENA

**300 assertions** de errores HTTP verificados:
- ✅ 401 Unauthorized: tests/test_api.py, test_auth_api.py, test_e2e_security.py
- ✅ 403 Forbidden: test_edge_cases_contract.py (path traversal), test_security_hardening.py
- ✅ 404 Not Found: múltiples tests de endpoints inexistentes
- ✅ 422 Unprocessable Entity: test_edge_cases_contract.py (CFDI corrupto, payload inválido)
- ✅ 429 Rate Limit: production/conftest.py con rate_limited_client
- ✅ 500 Internal Server Error: verificado que NO ocurre (assert != 500)

**Tests de seguridad específicos**:
- `test_security_hardening.py` — XSS, auth bypass, secrets scan
- `test_security_hardening_2.py` — hardening adicional
- `test_e2e_security.py` — SQLi, path traversal, rate limiting
- `test_enterprise_hardening.py` — comprehensive hardening

---

## 8. CONCURRENCY: Multi-tenant concurrency

### Severidad: ⚠️ BAJA

**Tests existentes**:
- `test_multi_tenant.py:1267` — `test_concurrent_context_switches` (threading)
- `test_reports_integration.py:290` — `test_concurrent_register` (13 threads)
- `test_reports_integration.py:411` — `test_concurrent_report_generation`

**GAPS CRÍTICOS**:

| Gap | Severidad | Test propuesto |
|---|---|---|
| Race condition en inserción de facturas | 🔴 ALTA | `test_concurrent_invoice_insert` — N threads insertando al mismo tenant |
| Race condition en creación de tenants | 🔴 ALTA | `test_concurrent_tenant_creation` — nombres duplicados concurrentes |
| Database locked bajo carga | 🟡 MEDIA | `test_no_database_locked` — 50 writes simultáneos a SQLite |
| API key lookup concurrente | 🟡 MEDIA | `test_concurrent_api_key_validation` |
| Multi-tenant data leak bajo concurrencia | 🔴 ALTA | `test_no_tenant_data_leak_concurrent` — verificar aislamiento con N tenants concurrentes |

---

## 9. PERFORMANCE TESTS

### Severidad: ❌ MÍNIMA

**Solo 1 test remotamente de performance**:
- `tests/test_analytics.py:1029` — `test_many_invoices_performance` (inserta 100 facturas, mide tiempo)

**FALTA COMPLETAMENTE**:

| Gap | Severidad | Test propuesto |
|---|---|---|
| Benchmark de pipeline completo | 🔴 ALTA | `test_pipeline_throughput` — 1000 CFDIs, medir ops/sec |
| Latencia de API endpoints | 🟡 MEDIA | `test_api_latency_p99` — percentil 99 de response time |
| Batch processing scalability | 🟡 MEDIA | `test_batch_scalability` — 100, 500, 1000 CFDIs, medir curva |
| Memory leak en procesamiento batch | 🟡 MEDIA | `test_memory_batch` — tracemalloc durante batch grande |
| DB query performance | 🟡 MEDIA | `test_db_query_time` — queries de dashboard con 10K facturas |
| Rate limiter under load | 🟢 BAJA | `test_rate_limiter_accuracy` — verificar conteo exacto |

**Recomendación**: Añadir `pytest-benchmark` como dependencia de test y crear `tests/performance/` directory.

---

## 10. SNAPSHOT TESTS: XML generation verification

### Severidad: ⚠️ BAJA

**Tests existentes** (en `test_enterprise_hardening.py:919-950`):
- ✅ `test_cfdi_xml_snapshot` — XML de CFDI con inputs determinísticos → output determinístico
- ✅ `test_payroll_xml_snapshot` — XML de nómina snapshot

**GAPS**:

| Gap | Severidad | Test propuesto |
|---|---|---|
| Snapshot de contabilidad electrónica XML | 🟡 MEDIA | `test_contabilidad_electronica_xml_snapshot` |
| Snapshot de DIOT XML | 🟡 MEDIA | `test_diot_xml_snapshot` |
| Snapshot de declaración XML | 🟡 MEDIA | `test_declaracion_xml_snapshot` |
| Validación contra XSD oficial SAT | 🔴 ALTA | `test_cfdi_validates_against_xsd` — usar XSD 4.0 del SAT |
| Verificar namespaces y attributos requeridos | 🟡 MEDIA | `test_xml_required_attributes` |
| Snapshot de PDF reports | 🟢 BAJA | `test_pdf_report_snapshot` — hash del PDF generado |

**Recomendación**: Usar `pytest-snapshot` o `syrupy` para snapshots versionados.

---

## HALLAZGOS ESPECÍFICOS ADICIONALES

### H1: Archivos de test duplicados con " 2" en el nombre
- `b2b_ai/features/ap_ar/tests/test_ap_ar 2.py`
- `b2b_ai/features/close_management/tests/test_close_management 2.py`
- `b2b_ai/api/errors 2.py`
- `b2b_ai/cfdi/xml_security 2.py`
- `b2b_ai/db/migration 2.py`
- `b2b_ai/features/close_management/scheduler 2.py`
- **Severidad**: 🟡 MEDIA — Posible confusión, tests podrían no ejecutarse
- **Acción**: Consolidar o eliminar duplicados

### H2: Archivo test_multi_tenant.py está VACÍO (0 líneas)
- **Severidad**: 🔴 ALTA — Tests de multi-tenant están en otro archivo (test_multi_tenant.py tiene 2214 líneas, el vacío es otro)
- Verificar: `read_file` mostró 0 líneas para `tests/test_multi_tenant.py` pero grep encontró 2214 líneas — posible confusión de paths

### H3: test_probe_tmp.py (3 líneas)
- **Severidad**: 🟢 BAJA — Archivo temporal de debugging, eliminar

### H4: Sin markers de pytest para categorización
- No se ven `@pytest.mark.slow`, `@pytest.mark.integration`, `@pytest.mark.unit`
- **Severidad**: 🟡 MEDIA — Imposible ejecutar solo unit tests o solo integration tests
- **Acción**: Añadir markers y configurar en `pyproject.toml`

### H5: Sin conftest.py en subdirectorios de features
- Los tests en `b2b_ai/features/*/tests/` no tienen conftest.py propio
- Cada test crea su propia DB y fixtures inline
- **Severidad**: 🟡 MEDIA — Código duplicado de fixtures
- **Acción**: Crear `conftest.py` compartido en `b2b_ai/features/`

---

## PLAN DE ACCIÓN PRIORITIZADO

### P0 — Crítico (esta semana)
1. ~~Cobertura de `api/middleware.py`~~ → Crear `tests/test_api_middleware.py`
2. ~~Cobertura de `cfdi/xml_security.py`~~ → Crear `tests/test_xml_security.py`
3. ~~Cobertura de `fiel_signer.py`~~ → Crear `tests/test_fiel_signer.py`
4. ~~Tests de concurrencia multi-tenant~~ → Crear `tests/test_concurrent_multi_tenant.py`
5. Limpiar archivos " 2.py" duplicados

### P1 — Importante (próxima semana)
6. Añadir fixtures enterprise a conftest.py (authenticated_client, db_session)
7. Tests de edge cases faltantes (monto=0, bisiesto, tasa 0)
8. Snapshot tests de todos los XMLs generados
9. Añadir pytest markers (unit, integration, slow)

### P2 — Mejora (próximo sprint)
10. Performance benchmarks con pytest-benchmark
11. Cobertura de adapters de integración (mock testing)
12. Expansión de factories a más tests
13. Validación XSD contra schemas SAT oficiales

---

## MÉTRICAS FINALES

| Métrica | Valor |
|---|---|
| Archivos de test | 195 |
| Funciones de test | ~7,048 |
| Módulos fuente | ~250 |
| Módulos sin test alguno | 69 (27.6%) |
| Assertions de status_code solamente | 769 |
| Tests de concurrencia | 3 |
| Tests de performance | 1 |
| Tests de snapshot XML | 2 |
| Archivos duplicados " 2.py" | 6 |
| Fixtures en conftest.py | ~20 |
| Factories disponibles | CFDIFactory, BankTransactionFactory |
