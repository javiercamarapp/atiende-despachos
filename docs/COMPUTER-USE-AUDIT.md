# AUDITORÍA COMPLETA — COMPUTER USE / ERP DRIVERS

**Fecha:** 2026-08-01  
**Alcance:** `b2b_ai/computer_use/`, `b2b_ai/erp/`, `b2b_ai/agent/`, `b2b_ai/tools/`, `b2b_ai/integrations/`, `b2b_ai/services/`, `b2b_ai/api/`, Dockerfile, docker-compose*.yml, tests  
**Método:** Solo lectura. No se modificó ningún archivo.

---

## RESUMEN EJECUTIVO

El proyecto tiene **dos capas paralelas de abstracción ERP** que no están conectadas entre sí:

1. **Capa `computer_use/`** — ABC `DesktopAutomation` + `BrowserAutomation` con mocks y drivers reales Playwright. Diseñada para ERPs sin API (CONTPAQi on-premise, Aspel SAE).
2. **Capa `erp/`** — ABC `ERPInterface` + `AbstractERPConnector` con mocks en memoria y CSV. Diseñada para ERPs con API o fallback CSV.

**Problema central:** Los drivers reales (`PlaywrightDesktop`, `CONTPAQiRealDriver`, `AspelRealDriver`) existen y están bien construidos, pero **ningún punto del flujo productivo los usa**. El pipeline real (`agent/loop.py` → `tools/tools.py` → `tenants.erp_factory()`) siempre devuelve `MockCONTPAQi()` o `CSVErp()`. Las URLs de los drivers reales son placeholder (`example.com`).

---

## 1. ARCHIVOS EN `b2b_ai/computer_use/`

### 1.1 `browser.py` (485 líneas) — BrowserAutomation + MockBrowser

| Línea | Clase/Función | Driver | Mock/Real | Riesgo | Cambio necesario |
|-------|---------------|--------|-----------|--------|------------------|
| 86–126 | `BrowserAutomation` (ABC) | N/A (interfaz) | — | Ninguno | Ninguno |
| 132–175 | `MockBrowser` | Mock en memoria | **MOCK** | Bajo (solo tests) | Documentar que es mock |
| 140 | `DEFAULT_ERP_URL = "https://contaqiweb.example.com/app"` | Placeholder | **MOCK** | Medio: URL hardcodeada sin config real | Reemplazar con env var `ERP_URL` |
| 200+ | `navigate_to_erp()`, `login_contpaqi()`, `upload_cfdi()`, `read_screen()` | Delegan a BrowserAutomation | **MOCK** por defecto | Medio: sin real driver | Crear `RealBrowser` con Playwright |
| 300+ | `form_fill()`, `select_dropdown()`, `extract_table()`, `retry_action()` | Helpers genéricos | N/A | Bajo | Reutilizables con driver real |

### 1.2 `contpaqi_driver.py` (259 líneas) — DesktopAutomation + MockDesktop + ContpaqiDriver

| Línea | Clase/Función | Driver | Mock/Real | Riesgo | Cambio necesario |
|-------|---------------|--------|-----------|--------|------------------|
| 38–67 | `DesktopAutomation` (ABC) | N/A (interfaz) | — | Ninguno | Ninguno |
| 72–120 | `MockDesktop` | Mock en memoria | **MOCK** | Bajo (solo tests) | Documentar |
| 125–200 | `ContpaqiDriver` | Usa `DesktopAutomation` (default=`MockDesktop`) | **MOCK** por defecto | **ALTO**: `__init__` crea `MockDesktop()` si no se inyecta | Inyectar driver real en producción |
| 150–170 | `ContpaqiDriver.login()` | Llama `self.desktop.type_text()` | **MOCK** | Alto: en mock siempre retorna ok | Necesita selector real de CONTPAQi |
| 180–200 | `ContpaqiDriver.capture_invoice_grid()` | Llama `self.desktop.screenshot()` | **MOCK** | Alto: datos inventados | Necesita parsing real de grid |
| 210–230 | `ContpaqiDriver.register_invoice()` | Llama `self.desktop.type_text()` + `click()` | **MOCK** | Alto: nunca registra en ERP real | Necesita flujo real de CONTPAQi |

### 1.3 `aspel_driver.py` (144 líneas) — AspelDriver

| Línea | Clase/Función | Driver | Mock/Real | Riesgo | Cambio necesario |
|-------|---------------|--------|-----------|--------|------------------|
| 28–63 | `AspelDriver` | Usa `DesktopAutomation` (default=`MockDesktop`) | **MOCK** por defecto | **ALTO**: mismo problema que ContpaqiDriver | Inyectar driver real |
| 40 | `self.desktop = desktop or MockDesktop()` | MockDesktop | **MOCK** | Alto: fallback silencioso a mock | Fail loud si no hay driver real |
| 82–100 | `AspelDriver.register_invoice()` | MockDesktop | **MOCK** | Alto | Necesita flujo real de Aspel SAE |
| 140–144 | `aspel_register()` helper | Delega a `get_default_aspel()` | **MOCK** | Medio | Helper no se usa en producción |

### 1.4 `playwright_desktop.py` (477 líneas) — PlaywrightDesktop ✅

| Línea | Clase/Función | Driver | Mock/Real | Riesgo | Cambio necesario |
|-------|---------------|--------|-----------|--------|------------------|
| 52–85 | `_retry_async()` | Async retry helper | **REAL** | Ninguno | — |
| 88–477 | `PlaywrightDesktop` | Playwright Chromium | **REAL** | Ninguno (bien implementado) | **No se usa en ningún flujo productivo** |
| 27 | Docstring: `await desktop.launch("https://contpaqiweb.example.com/app")` | Placeholder | — | Bajo (docstring) | Actualizar ejemplo |
| 100+ | `launch()`, `click()`, `type_text()`, `screenshot()`, `press_key()` | Playwright real | **REAL** | Ninguno | Conectar al pipeline |
| 200+ | `fill_form()`, `select_dropdown()`, `extract_table()` | Playwright real | **REAL** | Ninguno | Conectar al pipeline |

### 1.5 `contpaqi_real_driver.py` (498 líneas) — CONTPAQiRealDriver ✅

| Línea | Clase/Función | Driver | Mock/Real | Riesgo | Cambio necesario |
|-------|---------------|--------|-----------|--------|------------------|
| 22 | Docstring: `erp_url="https://contpaqiweb.example.com"` | Placeholder | — | Bajo (docstring) | Actualizar |
| 72–498 | `CONTPAQiRealDriver` | Hereda `DesktopAutomation`, usa `PlaywrightDesktop` | **REAL** | Bajo (bien implementado) | **No se usa en ningún flujo productivo** |
| 100 | `self.erp_url = erp_url or "https://contpaqiweb.example.com/app"` | Placeholder default | **Riesgo**: si no se pasa URL real, apunta a nada | **ALTO**: configurar URL real via env var |
| 150–200 | `connect()`, `login()` | Playwright real | **REAL** | Bajo | Conectar al pipeline |
| 300–350 | `extract_invoices()` | Playwright real + parsing | **REAL** | Bajo | Conectar al pipeline |
| 396–450 | `register_invoice()` | Playwright real | **REAL** | Bajo | Conectar al pipeline |

### 1.6 `aspel_real_driver.py` (506 líneas) — AspelRealDriver ✅

| Línea | Clase/Función | Driver | Mock/Real | Riesgo | Cambio necesario |
|-------|---------------|--------|-----------|--------|------------------|
| 20 | Docstring: `erp_url="https://aspelcloud.example.com"` | Placeholder | — | Bajo | Actualizar |
| 72–506 | `AspelRealDriver` | Hereda `DesktopAutomation`, usa `PlaywrightDesktop` | **REAL** | Bajo | **No se usa en ningún flujo productivo** |
| 105 | `self.erp_url = erp_url or "https://aspelcloud.example.com/app"` | Placeholder default | **Riesgo**: URL hardcodeada | **ALTO**: configurar via env var |

### 1.7 `interface.py` (216 líneas) — ComputerUseDriver ABC

| Línea | Clase/Función | Driver | Mock/Real | Riesgo | Cambio necesario |
|-------|---------------|--------|-----------|--------|------------------|
| 29–40 | `DriverResultStatus` enum | N/A | — | Ninguno | — |
| 43–100 | `DriverResult` dataclass | N/A | — | Ninguno | — |
| 110–216 | `ComputerUseDriver` (ABC) | N/A (interfaz) | — | Ninguno | **No es implementada por ningún driver existente**. Los drivers usan `DesktopAutomation`/`BrowserAutomation` como ABC, no `ComputerUseDriver`. |

### 1.8 `smoke_test.py` (169 líneas) — Playwright health check

| Línea | Clase/Función | Driver | Mock/Real | Riesgo | Cambio necesario |
|-------|---------------|--------|-----------|--------|------------------|
| 29–169 | `run_smoke_test()` | Playwright real | **REAL** | Ninguno | Integrar como endpoint `/health/playwright` |

### 1.9 `__init__.py` (91 líneas) — Re-exports

| Línea | Contenido | Riesgo |
|-------|-----------|--------|
| 21–55 | Re-exporta TODO (mock + real) desde `__all__` | **Medio**: importa `PlaywrightDesktop`, `CONTPAQiRealDriver`, `AspelRealDriver` pero nadie los usa |
| 53 | `from b2b_ai.computer_use.playwright_desktop import PlaywrightDesktop` | Si Playwright no está instalado, este import falla y rompe todo `computer_use` |

---

## 2. ARCHIVOS EN `b2b_ai/erp/`

### 2.1 `base.py` (36 líneas) — ERPInterface ABC

| Línea | Clase | Mock/Real | Riesgo |
|-------|-------|-----------|--------|
| 15–36 | `ERPInterface` (ABC) | — | Ninguno. Define `register_invoice`, `get_invoice`, `health` |

### 2.2 `contpaqi.py` (91 líneas) — MockCONTPAQi

| Línea | Clase | Driver | Mock/Real | Riesgo | Cambio necesario |
|-------|-------|--------|-----------|--------|------------------|
| 22–91 | `MockCONTPAQi` | En memoria | **MOCK** | **ALTO**: Es el ERP que usa el pipeline productivo. Datos se pierden al reiniciar. | Crear `RealCONTPAQiAPI` con REST |
| 30 | `register_invoice()` | Mock | **MOCK** | Alto | — |
| 49 | `_cuentas_para_categoria()` | Hardcoded | — | Medio | Catálogo configurable por tenant |

### 2.3 `connector.py` (311 líneas) — CONTPAQiConnector + AspelConnector + CSVExporter

| Línea | Clase | Driver | Mock/Real | Riesgo |
|-------|-------|--------|-----------|--------|
| 69–107 | `AbstractERPConnector` (ABC) | — | — | Ninguno |
| 110–174 | `CONTPAQiConnector` | En memoria | **MOCK** | Medio: `backend = "CONTPAQi contaDIGITAL (mock)"` |
| 131 | `api_base="https://api.contpaqi.com"` | Placeholder | **MOCK** | Bajo: no se usa realmente |
| 177–240 | `AspelConnector` | En memoria | **MOCK** | Medio |
| 240+ | `CSVExporter` | CSV real | **REAL** | Bajo |

### 2.4 `contpaqi_real.py` (87 líneas) — RealCONTPAQi (desktop)

| Línea | Clase | Driver | Mock/Real | Riesgo | Cambio necesario |
|-------|-------|--------|-----------|--------|------------------|
| 35–87 | `RealCONTPAQi` | `ContpaqiDriver(desktop=MockDesktop())` | **MOCK** por defecto | **ALTO**: Se llama "Real" pero usa MockDesktop. El nombre es engañoso. | Inyectar `PlaywrightDesktop` real |
| 45 | `driver = ContpaqiDriver(desktop=desktop or MockDesktop())` | MockDesktop default | **MOCK** | Alto | Debería fallar si no hay driver real |

### 2.5 `aspel_real.py` (84 líneas) — RealAspel (desktop)

| Línea | Clase | Driver | Mock/Real | Riesgo | Cambio necesario |
|-------|-------|--------|-----------|--------|------------------|
| 35–84 | `RealAspel` | `AspelDriver(desktop=MockDesktop())` | **MOCK** por defecto | **ALTO**: Mismo problema que `RealCONTPAQi` | Inyectar driver real |
| 43 | `driver = AspelDriver(desktop=desktop or MockDesktop())` | MockDesktop default | **MOCK** | Alto | — |

### 2.6 `erp_automation.py` (239 líneas) — DesktopERPBase

| Línea | Clase | Driver | Mock/Real | Riesgo |
|-------|-------|--------|-----------|--------|
| 44–239 | `DesktopERPBase` | Recibe `driver` por inyección | Depende del driver | Bajo: bien diseñado (audit log, retry, health) |

### 2.7 `csv_erp.py` (82 líneas) — CSVErp

| Línea | Clase | Driver | Mock/Real | Riesgo |
|-------|-------|--------|-----------|--------|
| 19–82 | `CSVErp` | CSV file | **REAL** | Bajo: fallback funcional |

### 2.8 `quickbooks.py` (238 líneas) — QuickBooksConnector (legacy shim)

| Línea | Clase | Driver | Mock/Real | Riesgo |
|-------|-------|--------|-----------|--------|
| 37–238 | `QuickBooksConnector` | Mock (QBO_MOCK_MODE=1 default) | **MOCK** | Medio |

---

## 3. PIPELINE PRODUCTIVO — Cómo se usa realmente

### 3.1 `agent/loop.py` — AgentLoop

| Línea | Operación | ERP usado | Mock/Real |
|-------|-----------|-----------|-----------|
| 64 | `__init__(erp=None)` | Si no se pasa, usa factory | — |
| 282 | `erp = self.tenants.erp_factory(tenant_id, erp=self.erp)` | `MockCONTPAQi()` o `CSVErp()` | **MOCK** |
| 283 | `self._call("register_erp", ..., erp=erp)` | Delega a tools | **MOCK** |

### 3.2 `tools/tools.py` — register_erp tool

| Línea | Operación | ERP usado | Mock/Real |
|-------|-----------|-----------|-----------|
| 73–77 | `register_erp(invoice, erp=None)` | Si no se inyecta, usa `_get_default_erp()` | **MOCK** |
| 83–87 | `_get_default_erp()` → `MockCONTPAQi()` | Hardcoded | **MOCK** |

### 3.3 `db/tenants.py` — erp_factory

| Línea | Operación | ERP usado | Mock/Real |
|-------|-----------|-----------|-----------|
| 163–178 | `erp_factory(tenant_id)` | `contpaqi` → `MockCONTPAQi()`, `csv` → `CSVErp()` | **MOCK** siempre |

### 3.4 `features/bookkeeping/pipeline.py` — BookkeepingPipeline

| Línea | Operación | ERP usado | Mock/Real |
|-------|-----------|-----------|-----------|
| 53 | `erp_registrar: Optional[ERPRegistrar]` | Default: `ERPRegistrar(erp_system=ERPSystem.MOCK)` | **MOCK** |
| 132 | `self._erp.register_batch(polizas)` | ERPRegistrar mock | **MOCK** |

---

## 4. URLs PLACEHOLDER (`example.com`)

| Archivo | Línea | URL | Riesgo |
|---------|-------|-----|--------|
| `computer_use/browser.py` | 140 | `https://contaqiweb.example.com/app` | **ALTO**: default de MockBrowser |
| `computer_use/playwright_desktop.py` | 27 | `https://contpaqiweb.example.com/app` | Bajo (docstring) |
| `computer_use/contpaqi_real_driver.py` | 22 | `https://contpaqiweb.example.com` | Bajo (docstring) |
| `computer_use/contpaqi_real_driver.py` | 100 | `https://contpaqiweb.example.com/app` | **ALTO**: default del driver real |
| `computer_use/aspel_real_driver.py` | 20 | `https://aspelcloud.example.com` | Bajo (docstring) |
| `computer_use/aspel_real_driver.py` | 105 | `https://aspelcloud.example.com/app` | **ALTO**: default del driver real |
| `integrations/crm/hubspot_adapter.py` | 75,105 | `mock@example.com` | Bajo (mock data) |
| `integrations/crm/zoho_crm_adapter.py` | 75,103 | `mock@example.com` | Bajo |
| `integrations/crm/pipedrive_adapter.py` | 77,107 | `mock@example.com` | Bajo |
| `integrations/crm/salesforce_adapter.py` | 86,115 | `mock@example.com` | Bajo |
| `integrations/microsoft/m365_adapter.py` | 50 | `mock@example.com` | Bajo |

---

## 5. TESTS RELACIONADOS

| Archivo | Qué cubre | Usa mock o real |
|---------|-----------|-----------------|
| `tests/test_erp_integration.py` | `MockCONTPAQi`, `CSVErp`, `DesktopERPBase`, `QuickBooksConnector` | **MOCK** (MockDesktopDriver definido localmente) |
| `tests/test_erp_connector.py` | `CONTPAQiConnector`, `AspelConnector` (mocks) | **MOCK** |
| `tests/test_integration_pipeline.py` | Pipeline completo | **MOCK** (MockCONTPAQi inyectado) |
| `tests/test_e2e_suite.py` | E2E | **MOCK** |
| `tests/test_quickbooks.py` | QuickBooks mock | **MOCK** |
| `tests/test_router.py` | Router de tools | **MOCK** |
| `b2b_ai/features/ap_ar/tests/test_ap_ar.py` | AP/AR `register_invoice()` | **MOCK** |
| `b2b_ai/features/clientes/tests/test_clientes.py` | Clientes `register_invoice()` | **MOCK** |
| `b2b_ai/integrations/tests/test_integrations.py` | Integraciones | **MOCK** |

**No existe ningún test que use `PlaywrightDesktop`, `CONTPAQiRealDriver` o `AspelRealDriver`.**

---

## 6. DOCKER

### Dockerfile (130 líneas)

| Línea | Hallazgo | Riesgo |
|-------|----------|--------|
| 23 | `PLAYWRIGHT_BROWSERS_PATH=/opt/playwright` | Correcto |
| 45 | `pip install playwright` | Correcto |
| 50 | `RUN python -m playwright install --with-deps chromium` | Correcto: instala Chromium |
| 67 | `PLAYWRIGHT_BROWSERS_PATH=/opt/playwright` | Correcto en runtime |

**Conclusión Docker:** Playwright + Chromium están correctamente instalados en el contenedor. El problema es que **ningún código productivo los invoca**.

### docker-compose.yml (124 líneas)

- No hay configuración de variables de entorno para URLs de ERP (`CONTPAQI_URL`, `ASPEL_URL`).
- No hay volumen para screenshots de auditoría.
- No hay health check de Playwright.

---

## 7. HALLAZGOS CRÍTICOS

### 7.1 Drivers reales existen pero no se usan
- `PlaywrightDesktop` ✅ implementado, testeable, Playwright instalado en Docker
- `CONTPAQiRealDriver` ✅ implementado sobre PlaywrightDesktop
- `AspelRealDriver` ✅ implementado sobre PlaywrightDesktop
- **Ninguno** es invocado por `agent/loop.py`, `tools/tools.py`, `tenants.erp_factory()`, o `features/bookkeeping/`

### 7.2 "Real" classes usan Mock por defecto
- `RealCONTPAQi` (`erp/contpaqi_real.py:45`): `ContpaqiDriver(desktop=desktop or MockDesktop())`
- `RealAspel` (`erp/aspel_real.py:43`): `AspelDriver(desktop=desktop or MockDesktop())`
- Los nombres son **engañosos**: dicen "Real" pero caen en MockDesktop silenciosamente.

### 7.3 Tres ABCs no alineadas
1. `DesktopAutomation` (`contpaqi_driver.py:38`) — sync, coords-based
2. `BrowserAutomation` (`browser.py:86`) — sync, selector-based
3. `ComputerUseDriver` (`interface.py:110`) — sync+async, `DriverResult`-based

Ningún driver implementa `ComputerUseDriver`. `PlaywrightDesktop` implementa `DesktopAutomation` (async). `CONTPAQiRealDriver`/`AspelRealDriver` implementan `DesktopAutomation` pero son async. La ABC `ComputerUseDriver` está huérfana.

### 7.4 URLs placeholder en defaults de drivers reales
- `CONTPAQiRealDriver.erp_url` default: `https://contpaqiweb.example.com/app`
- `AspelRealDriver.erp_url` default: `https://aspelcloud.example.com/app`
- Si se activaran sin config, navegarían a URLs inexistentes.

### 7.5 Import frágil en `__init__.py`
- `computer_use/__init__.py:53` importa `PlaywrightDesktop` incondicionalmente. Si Playwright no está instalado (dev local sin Docker), todo `b2b_ai.computer_use` falla al importar.

---

## 8. MAPA DE CONEXIÓN NECESARIA

```
FLUJO ACTUAL (siempre mock):
  agent/loop.py → tools/tools.py::register_erp()
    → _get_default_erp() → MockCONTPAQi()  ← SIEMPRE MOCK

FLUJO NECESARIO:
  agent/loop.py → tools/tools.py::register_erp()
    → tenants.erp_factory(tenant_id)
      → según erp_type:
        "contpaqi_web"  → CONTPAQiRealDriver(erp_url=env.CONTPAQI_URL)
        "aspel_web"     → AspelRealDriver(erp_url=env.ASPEL_URL)
        "contpaqi_desktop" → RealCONTPAQi(desktop=PlaywrightDesktop())
        "aspel_desktop"    → RealAspel(desktop=PlaywrightDesktop())
        "csv"              → CSVErp()
        "mock"             → MockCONTPAQi()  ← solo para tests
```

---

## 9. TABLA RESUMEN DE RIESGOS

| # | Hallazgo | Severidad | Archivo(s) |
|---|----------|-----------|------------|
| 1 | Pipeline productivo siempre usa MockCONTPAQi | 🔴 CRÍTICO | tools/tools.py:86, tenants.py:178 |
| 2 | Drivers reales (Playwright, CONTPAQiReal, AspelReal) nunca invocados | 🔴 CRÍTICO | computer_use/*.py |
| 3 | "Real" classes fallback a MockDesktop silenciosamente | 🟠 ALTO | erp/contpaqi_real.py:45, erp/aspel_real.py:43 |
| 4 | URLs placeholder en defaults de drivers reales | 🟠 ALTO | contpaqi_real_driver.py:100, aspel_real_driver.py:105 |
| 5 | ABC `ComputerUseDriver` huérfana (nadie la implementa) | 🟡 MEDIO | computer_use/interface.py |
| 6 | Tres ABCs no alineadas (DesktopAutomation, BrowserAutomation, ComputerUseDriver) | 🟡 MEDIO | Múltiples |
| 7 | Import frágil de Playwright en `__init__.py` | 🟡 MEDIO | computer_use/__init__.py:53 |
| 8 | No hay tests para drivers reales | 🟡 MEDIO | tests/ |
| 9 | docker-compose sin env vars de ERP ni health de Playwright | 🟡 MEDIO | docker-compose.yml |
| 10 | Sin volumen Docker para screenshots de auditoría | 🟢 BAJO | docker-compose.yml |
