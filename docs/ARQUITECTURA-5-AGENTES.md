# Arquitectura Técnica — 5 Agentes Likida AI Enterprise

**Versión:** 1.0 — Agosto 2026
**Autor:** Likida AI Architecture Team
**Estado:** Diseño técnico listo para implementación

---

## Tabla de Contenidos

1. [Resumen Ejecutivo](#1-resumen-ejecutivo)
2. [Lo que Ya Existe y se Puede Reutilizar](#2-lo-que-ya-existe)
3. [Lo que Hay que Construir Nuevo](#3-lo-que-hay-que-construir)
4. [Arquitectura Propuesta](#4-arquitectura-propuesta)
5. [Modelo de Datos Nuevo](#5-modelo-de-datos-nuevo)
6. [Flujos de Datos Principales](#6-flujos-de-datos)
7. [Stack Técnico](#7-stack-técnico)
8. [Roadmap de Implementación](#8-roadmap)

---

## 1. Resumen Ejecutivo

El proyecto Likida AI Enterprise ya cuenta con una base sólida: un pipeline CFDI
funcional, calculadora de nómina con ISR/IMSS/INFONAVIT, conciliación bancaria
con scoring, contabilidad electrónica (catálogo SAT + balanza), sistema de
declaraciones, pre-auditoría, cobranza automatizada, integración con +15 ERPs
vía IntegrationHub, y una DB multi-tenant con soporte SQLite/PostgreSQL.

El objetivo es orquestar **5 agentes especializados** sobre esta base existente,
conectándolos mediante un bus de eventos y una cola de trabajo asíncrona para
procesamiento masivo.

```
┌─────────────────────────────────────────────────────────────────────┐
│                     ORQUESTADOR CENTRAL                            │
│                   (AgentOrchestrator)                               │
│                                                                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │ AGENTE 1 │ │ AGENTE 2 │ │ AGENTE 3 │ │ AGENTE 4 │ │ AGENTE 5 │ │
│  │ Fiscal   │ │Contable  │ │  Close   │ │  AP/AR   │ │ Nómina   │ │
│  │SAT+Decl.│ │ Journal  │ │ Manager  │ │ Cobros   │ │ IMSS+ISR │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ │
│       │            │            │            │            │        │
│  ─────┴────────────┴────────────┴────────────┴────────────┴──────  │
│                     Event Bus (Redis Streams)                      │
│  ─────────────────────────────────────────────────────────────────  │
│                     Cola de Trabajo (Celery + Redis)               │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Lo que Ya Existe y se Puede Reutilizar

### 2.1 Pipeline CFDI (✅ Completo — Reutilizable al 100%)

| Componente | Archivo | Estado | Qué hace |
|---|---|---|---|
| Parser XML | `cfdi/parser.py` | ✅ Producción | Parseo CFDI 4.0, extracción de campos |
| Validador fiscal | `cfdi/validator.py` | ✅ Producción | Validación contra XSD SAT, UUID, totales |
| Catálogos SAT | `cfdi/catalogs.py` | ✅ Producción | Catálogos de claves SAT (c_UsoCFDI, etc.) |
| Cancelación | `cfdi/cancellation.py` | ✅ Producción | Flujo de cancelación CFDI |
| Clasificador | `services/classify.py` | ✅ Producción | Clasificación de gastos por categoría |
| Pipeline orquestador | `services/pipeline.py` | ✅ Producción | `parse → validate → classify → register → notify` |

**Reutilización:** El Agente 1 (Fiscal) invocará directamente el pipeline existente.
El classify.py alimentará el motor de reglas contables con la categoría detectada.

### 2.2 Servicio de Nómina (✅ Completo — Reutilizable al 100%)

| Componente | Archivo | Estado | Qué hace |
|---|---|---|---|
| Calculadora ISR | `features/compliance.py` | ✅ Producción | Tabla ISR progresiva Art. 96 LISR 2024 |
| Calculadora IMSS | `features/nomina_completa/service.py` | ✅ Producción | Cuota obrera (~1.20%) + patronal (~20.40%) |
| Subsidio empleo | `features/nomina_completa/service.py` | ✅ Producción | Tabla subsidio Art. 113 LISR |
| INFONAVIT | `features/nomina_completa/service.py` | ✅ Producción | 5% SBC (aportación patronal) |
| CFDI Nómina | `features/nomina_completa/service.py` | ✅ Producción | Generación de CFDI de nómina |
| Routes nómina | `features/nomina_completa/routes.py` | ✅ Producción | API REST para cálculo |

**Reutilización:** El Agente 5 (Nómina) será una capa de orquestación sobre este
servicio existente, añadiendo: procesamiento batch, scheduler de quincenas, y
declaración IMSS/INFONAVIT automática.

### 2.3 Conciliación Bancaria (✅ Completo — Reutilizable al 100%)

| Componente | Archivo | Estado | Qué hace |
|---|---|---|---|
| Parser CSV bancario | `services/reconcile.py` | ✅ Producción | Parser multi-formato (BBVA, Banorte, etc.) |
| Parser PDF bancario | `services/reconcile.py` | ✅ Producción | Extracción de movimientos desde PDF |
| Conciliación avanzada | `services/bank_reconciliation.py` | ✅ Producción | Matching 3 niveles (exact/partial/AI) + scoring |
| Reporte conciliación | `services/reconcile.py` | ✅ Producción | Reporte de conciliación estructurado |

**Reutilización:** El Agente 4 (AP/AR) usará `BankReconciliation` como motor
de cruce para cuentas por pagar/cobrar.

### 2.4 ERP CONTPAQi Mock + IntegrationHub (✅ Completo)

| Componente | Archivo | Estado | Qué hace |
|---|---|---|---|
| CONTPAQi Desktop | `integrations/erp/contpaqi_desktop.py` | ✅ Producción | Adapter SQL Server + mock fallback |
| IntegrationHub | `integrations/hub.py` | ✅ Producción | Registro central de +15 adaptadores ERP |
| Modelos ERP | `integrations/erp/models.py` | ✅ Producción | Poliza, CuentaContable, Balanza, Invoice |
| Otros ERPs | `integrations/erp/*.py` | ✅ Producción | Aspel, QuickBooks, Xero, Peak, etc. |

**Reutilización:** Todos los agentes escriben al ERP a través del IntegrationHub.
El adapter pattern ya permite cambiar de ERP sin tocar la lógica de negocio.

### 2.5 Sistema de Notificaciones (✅ Completo)

| Componente | Archivo | Estado | Qué hace |
|---|---|---|---|
| Email sender | `notifications/sender.py` | ✅ Producción | SMTP con fallback simulado |
| WhatsApp | `notifications/whatsapp.py` | ✅ Producción | Envío vía WhatsApp Business API |
| Scheduler | `notifications/scheduler.py` | ✅ Producción | Programación de notificaciones |
| Templates HTML | `notifications/templates/*.html` | ✅ Producción | Templates para 8 tipos de evento |
| API notificaciones | `notifications/api.py` | ✅ Producción | Router FastAPI para gestión |

**Reutilización:** Todos los agentes emiten notificaciones a través de este
sistema existente. Los templates cubren: factura procesada, anomalía, cobranza,
resumen diario/semanal, aprobación requerida.

### 2.6 Base de Datos Multi-Tenant (✅ Completo)

| Componente | Archivo | Estado | Qué hace |
|---|---|---|---|
| DB principal | `db/db.py` | ✅ Producción | SQLite/PG, thread-safe, migraciones |
| PostgreSQL adapter | `db/postgres_adapter.py` | ✅ Producción | Pool de conexiones PG |
| Adapter factory | `db/adapter_factory.py` | ✅ Producción | Switching SQLite ↔ PG |
| Tenant manager | `db/tenants.py` | ✅ Producción | CRUD tenants, config, aislamiento |
| Multi-tenant service | `features/multi_tenant/service.py` | ✅ Producción | Ciclo vida completo de tenants |
| Migraciones | `db/migration.py` | ✅ Producción | Migraciones versionadas automáticas |

**Reutilización:** Toda la capa de persistencia se reutiliza. Los nuevos agentes
añaden tablas a las migraciones existentes.

### 2.7 Servicios Complementarios Reutilizables

| Servicio | Archivo | Aplicación |
|---|---|---|
| Contabilidad electrónica | `services/contabilidad_electronica.py` | Agente 2: catálogo + balanza → XML SAT |
| Catálogo de cuentas | `services/catalogo_cuentas.py` | Agente 2: base para motor de reglas |
| Balanza comprobación | `services/balanza.py` | Agente 2: generación de balanza mensual |
| DIOT | `services/diot_service.py` | Agente 1: generación de DIOT |
| Pre-auditoría | `features/pre_auditoria/service.py` | Agente 3: checks de deducibilidad |
| Cobranza | `services/collections.py` | Agente 4: secuencia de recordatorios |
| AgentLoop existente | `agent/loop.py` | Base para el nuevo AgentOrchestrator |
| Compliance | `features/compliance.py` | Todos: ISR, auditoría, sanitización |
| LLM Service | `services/llm.py` | Todos: clasificación, matching, análisis |
| Tools registry | `tools/registry.py` | Todos: framework de tools con audit log |

---

## 3. Lo que Hay que Construir Nuevo

### 3.1 Motor de Reglas Contables (Agente 2 — Contable)

**Qué hace:** Mapea automáticamente la clasificación de un CFDI (de `classify.py`)
a una cuenta contable del catálogo SAT (de `catalogo_cuentas.py`), genera el
asiento contable (póliza) y lo registra en el ERP.

**Por qué es nuevo:** Hoy `classify.py` devuelve una categoría de gasto
("Servicios profesionales", "Materia prima", etc.) pero NO genera el asiento
contable. El catálogo de cuentas (`CatalogoCuentas`) y la balanza
(`BalanzaComprobacion`) existen pero no están conectados al pipeline de CFDI.

```
Archivo nuevo: b2b_ai/services/accounting_rules_engine.py

class AccountingRulesEngine:
    """
    Motor de reglas: categoría CFDI → cuenta contable → póliza.

    Flujo:
      1. Recibe: (categoría, tipo_cfdi, subtotal, iva, total, emisor/receptor)
      2. Busca en el catálogo de reglas: categoría → (cuenta_cargo, cuenta_abono)
      3. Genera el asiento contable (póliza de diario)
      4. Valida cuadratura (debe == haber)
      5. Registra en la balanza de comprobación
    """

    # Reglas por defecto (extensibles por tenant)
    DEFAULT_RULES = {
        # (tipo_cfdi, categoría) → (cuenta_cargo, cuenta_abono)
        ("I", "servicios_profesionales"): {
            "cargo": "6102",  # Gastos Administrativos
            "abono": "2101",  # Proveedores
            "iva_cargo": "1103",  # IVA Acreditable
        },
        ("I", "materia_prima"): {
            "cargo": "5100",  # Costo de Ventas
            "abono": "2101",  # Proveedores
            "iva_cargo": "1103",
        },
        ("E", "venta_servicios"): {
            "cargo": "1102",  # Clientes
            "abono": "4100",  # Ingresos por Servicios
            "iva_abono": "2103",  # IVA por Trasladar
        },
        # ... más reglas
    }
```

### 3.2 Motor de Declaraciones (Agente 1 — Fiscal)

**Qué hace:** Calcula, genera y prepara el envío de declaraciones periódicas
(IVA mensual, ISR provisional, ISR anual, DIOT) conectando los datos del
pipeline CFDI con el servicio de declaraciones existente.

**Estado actual:** `features/declaraciones/service.py` ya tiene la lógica de
cálculo (IVA, ISR) y generación, pero opera con datos en memoria y no está
conectado al pipeline CFDI para auto-alimentarse.

**Lo que falta construir:**

```
Archivo nuevo: b2b_ai/services/declaration_engine.py

class DeclarationEngine:
    """
    Orquestador de declaraciones fiscales.

    Flujo:
      1. Scheduler dispara evento "mes_fiscal_cerrado"
      2. Agrega datos del mes desde DB (facturas procesadas, nóminas)
      3. Calcula IVA (cobrado - pagado) y ISR provisional
      4. Genera DIOT si hay operaciones con terceros
      5. Prepara XML para envío al SAT (mock → real con e.firma)
      6. Notifica al contador para revisión y firma
    """
```

### 3.3 Close Management Scheduler (Agente 3 — Cierre)

**Qué hace:** Orquesta el proceso de cierre contable mensual/anual,
verificando que todas las partidas estén registradas, conciliadas y auditadas
antes de generar los reportes finales.

```
Archivo nuevo: b2b_ai/services/close_manager.py

class CloseManager:
    """
    Gestor de cierre contable.

    Checklist de cierre mensual:
      1. Verificar que todos los CFDI del mes están procesados
      2. Verificar conciliación bancaria completada
      3. Verificar nóminas del mes registradas
      4. Verificar pólizas contables cuadradas
      5. Ejecutar pre-auditoría (deducibilidad, CFF)
      6. Generar balanza de comprobación
      7. Generar paquete de contabilidad electrónica
      8. Generar borrador de declaración IVA/ISR
      9. Enviar resumen al contador para aprobación
     10. Marcar mes como "cerrado" tras aprobación
    """
```

### 3.4 AP/AR Pipeline (Agente 4 — Cobros/Pagos)

**Qué hace:** Gestiona cuentas por cobrar (AR) y por pagar (AP) de forma
automatizada: matching de pagos, aging reports, secuencia de cobranza, y
programación de pagos.

**Reutiliza:** `services/collections.py` (secuencia de cobranza) y
`services/bank_reconciliation.py` (matching de pagos).

```
Archivo nuevo: b2b_ai/services/apar_manager.py

class APARManager:
    """
    Gestor de cuentas por pagar y cobrar.

    AR (Accounts Receivable):
      1. Detecta facturas emitidas sin pago (matching bancario)
      2. Clasifica por antigüedad (0-30, 31-60, 61-90, 90+)
      3. Ejecuta secuencia de cobranza (collections.py)
      4. Genera reporte de aging

    AP (Accounts Payable):
      1. Detecta facturas de proveedor sin pago
      2. Programa pagos según política (net 30, etc.)
      3. Genera órdenes de pago
      4. Concilia pagos con facturas
    """
```

### 3.5 Agent Orchestrator (Núcleo Central)

**Qué hace:** Coordina los 5 agentes, gestiona el flujo de trabajo,
propaga eventos, y expone la API unificada.

**Base:** Extiende `agent/loop.py` (el AgentLoop existente).

```
Archivo nuevo: b2b_ai/agent/orchestrator.py

class AgentOrchestrator:
    """
    Orquestador central de los 5 agentes.

    Responsabilidades:
      - Registrar y gestionar los 5 agentes
      - Propagar eventos entre agentes (event bus)
      - Gestionar prioridades y conflictos
      - Exponer API unificada para el frontend
      - Coordinar el cierre mensual
      - Manejar escalación humana (HITL)
    """
```

### 3.6 Infraestructura Nueva

| Componente | Archivo | Propósito |
|---|---|---|
| Event Bus | `b2b_ai/infra/event_bus.py` | Redis Streams para comunicación entre agentes |
| Celery Workers | `b2b_ai/infra/workers.py` | Tareas asíncronas (batch CFDI, nómina masiva) |
| Task Queue Config | `b2b_ai/infra/celery_app.py` | Configuración Celery + Redis |
| Scheduler | `b2b_ai/infra/scheduler.py` | APScheduler para tareas periódicas |
| Health Monitor | `b2b_ai/infra/health.py` | Monitoreo de salud de los agentes |

---

## 4. Arquitectura Propuesta

### 4.1 Diagrama de Componentes

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          CAPA DE API (FastAPI)                         │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────────┐  │
│  │ /api/v1/    │ │ /api/v1/    │ │ /api/v1/    │ │ /api/v1/        │  │
│  │ invoices    │ │ accounting  │ │ payroll     │ │ declarations    │  │
│  │ /process    │ │ /catalog    │ │ /calculate  │ │ /generate       │  │
│  │ /batch      │ │ /balance    │ │ /batch      │ │ /status         │  │
│  └──────┬──────┘ └──────┬──────┘ └──────┬──────┘ └────────┬────────┘  │
│         │               │               │                 │            │
│  ───────┴───────────────┴───────────────┴─────────────────┴──────────  │
│                      AgentOrchestrator                                  │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Orchestrator Core                              │  │
│  │  • Registro de agentes        • Event routing                    │  │
│  │  • Estado global              • Escalación HITL                  │  │
│  │  • API unificada              • Métricas y health                │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                     5 AGENTES ESPECIALIZADOS                      │  │
│  │                                                                    │  │
│  │  ┌────────────┐ ┌────────────┐ ┌────────────┐                    │  │
│  │  │  AGENTE 1  │ │  AGENTE 2  │ │  AGENTE 3  │                    │  │
│  │  │   Fiscal   │ │  Contable  │ │   Close    │                    │  │
│  │  │            │ │            │ │  Manager   │                    │  │
│  │  │ •CFDI pipe │ │ •Rules eng │ │ •Checklist │                    │  │
│  │  │ •Decl eng  │ │ •Journal   │ │ •Scheduler │                    │  │
│  │  │ •DIOT gen  │ │ •Balance   │ │ •Audit     │                    │  │
│  │  │ •SAT comm  │ │ •CE SAT    │ │ •Approval  │                    │  │
│  │  └────────────┘ └────────────┘ └────────────┘                    │  │
│  │                                                                    │  │
│  │  ┌────────────┐ ┌────────────┐                                    │  │
│  │  │  AGENTE 4  │ │  AGENTE 5  │                                    │  │
│  │  │   AP/AR    │ │   Nómina   │                                    │  │
│  │  │            │ │            │                                    │  │
│  │  │ •Cobranza  │ │ •ISR/IMSS  │                                    │  │
│  │  │ •BankRec   │ │ •CFDI Nom  │                                    │  │
│  │  │ •Aging     │ │ •Batch     │                                    │  │
│  │  │ •Pagos     │ │ •Scheduler │                                    │  │
│  │  └────────────┘ └────────────┘                                    │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ─────────────────────────────────────────────────────────────────────  │
│                    CAPA DE INFRAESTRUCTURA                              │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐  │
│  │  Redis       │ │   Celery     │ │  PostgreSQL  │ │  Integration │  │
│  │  • Streams   │ │   Workers    │ │  • Multi-    │ │  Hub         │  │
│  │  • Cache     │ │   • Batch    │ │    tenant    │ │  • ERP       │  │
│  │  • Queue     │ │   • Async    │ │  • Migrated  │ │  • SAT PAC  │  │
│  └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘  │
│                                                                         │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐                    │
│  │ Notificacio- │ │  Monitoring  │ │  LLM Service │                    │
│  │ nes          │ │  • Audit log │ │  • Classify  │                    │
│  │ • Email      │ │  • Metrics   │ │  • Match AI  │                    │
│  │ • WhatsApp   │ │  • Alerts    │ │  • Anomaly   │                    │
│  └──────────────┘ └──────────────┘ └──────────────┘                    │
└─────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Decisiones de Arquitectura

#### 4.2.1 Event-Driven para Comunicación Entre Agentes

**Decisión:** Redis Streams como bus de eventos ligero.

**Por qué:**
- Redis ya se necesita para Celery (cola de trabajo), un solo componente cubre dos necesidades
- Redis Streams ofrece: persistencia, consumer groups, acknowledgements
- Más simple que Kafka para el volumen esperado (<10K eventos/día)
- Permite desacoplamiento: un agente publica, otros consumen

**Alternativas descartadas:**
- RabbitMQ: Más pesado, otro componente a operar
- Kafka: Overkill para el volumen, operacionalmente complejo
- PostgreSQL LISTEN/NOTIFY: Limitado, bloquea conexiones

**Modelo de eventos:**

```
Eventos del bus:

cfdi.processed          → {tenant_id, invoice_id, categoria, monto, tipo}
cfdi.batch.completed    → {tenant_id, batch_id, total, procesados, errores}
journal.entry.created   → {tenant_id, poliza_id, periodo, total_debe, total_haber}
bank.statement.uploaded → {tenant_id, bank, movements_count}
bank.match.completed    → {tenant_id, matched, unmatched, confidence_avg}
payroll.calculated      → {tenant_id, periodo, employees, total_bruto, total_neto}
payroll.batch.completed → {tenant_id, periodo, cfdis_generated}
close.checklist.step    → {tenant_id, mes, step, status, details}
close.month.approved    → {tenant_id, mes, approved_by}
declaration.generated   → {tenant_id, tipo, periodo, monto}
declaration.submitted   → {tenant_id, tipo, periodo, acuse}
ap.payment.due          → {tenant_id, proveedor_id, factura_id, fecha_vencimiento}
ar.invoice.overdue      → {tenant_id, cliente_id, factura_id, dias_vencido}
anomaly.detected        → {tenant_id, tipo, severidad, descripcion}
human.review.required   → {tenant_id, entity_type, entity_id, reason}
```

#### 4.2.2 Batch Processing con Celery

**Decisión:** Celery con Redis broker para procesamiento asíncrono.

**Por qué:**
- Procesamiento masivo de CFDI (cientos/miles por lote)
- Cálculo de nómina quincenal para todos los empleados
- Generación de declaraciones mensuales
- Conciliación bancaria con miles de movimientos

**Tareas Celery principales:**

```python
# b2b_ai/infra/tasks.py

@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def task_process_cfdi_batch(self, tenant_id: str, xml_paths: list[str]):
    """Procesa un lote de CFDIs de forma asíncrona."""

@celery_app.task(bind=True, max_retries=2)
def task_calculate_payroll_batch(self, tenant_id: str, periodo: str,
                                  employees: list[dict]):
    """Calcula nómina para todos los empleados de un periodo."""

@celery_app.task(bind=True)
def task_generate_declaration(self, tenant_id: str, tipo: str,
                               periodo: str):
    """Genera una declaración fiscal (IVA/ISR/DIOT)."""

@celery_app.task(bind=True)
def task_reconcile_bank(self, tenant_id: str, statement_path: str,
                         bank: str):
    """Concilia un estado de cuenta bancario contra facturas."""

@celery_app.task(bind=True)
def task_run_close_checklist(self, tenant_id: str, mes: str):
    """Ejecuta el checklist de cierre mensual paso a paso."""

@celery_app.task(bind=True)
def task_generate_aging_report(self, tenant_id: str, tipo: str):
    """Genera reporte de antigüedad de saldos (AR o AP)."""
```

#### 4.2.3 Real-Time para API y Webhooks

**Decisión:** FastAPI síncrono para operaciones de baja latencia (<2s).

**Operaciones real-time (API directa):**
- Consulta de estado de factura
- Búsqueda en catálogo de cuentas
- Health check de agentes
- Webhooks de notificación

**Operaciones batch (vía Celery):**
- Procesamiento de lote de CFDI
- Cálculo de nómina
- Generación de declaraciones
- Conciliación bancaria masiva

### 4.3 Flujo de Datos: CFDI → Contabilidad → Declaraciones

```
                    FLUJO PRINCIPAL DE DATOS

  [XML CFDI]        [Estado Cuenta]      [Empleados]
      │                    │                    │
      ▼                    ▼                    ▼
  ┌─────────┐       ┌──────────┐        ┌──────────┐
  │ Parser  │       │  Parser  │        │ Nómina   │
  │ CFDI 4.0│       │  CSV/PDF │        │ Service  │
  └────┬────┘       └────┬─────┘        └────┬─────┘
       │                 │                    │
       ▼                 ▼                    ▼
  ┌─────────┐       ┌──────────┐        ┌──────────┐
  │Validator│       │  Bank    │        │ ISR/IMSS │
  │  SAT    │       │  Rec.    │        │ Calc     │
  └────┬────┘       └────┬─────┘        └────┬─────┘
       │                 │                    │
       ▼                 ▼                    ▼
  ┌─────────┐       ┌──────────┐        ┌──────────┐
  │Classify │       │  Match   │        │ CFDI     │
  │  LLM    │       │  Score   │        │ Nómina   │
  └────┬────┘       └────┬─────┘        └────┬─────┘
       │                 │                    │
       ▼                 ▼                    ▼
  ┌─────────────────────────────────────────────────┐
  │           MOTOR DE REGLAS CONTABLES              │
  │  (AccountingRulesEngine)                         │
  │                                                  │
  │  categoría + tipo_CFDI → cuenta_cargo/abono      │
  │  genera póliza → valida cuadratura               │
  └──────────────────────┬──────────────────────────┘
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
        ┌──────────┐ ┌────────┐ ┌─────────┐
        │ Register │ │Balance │ │  DIOT   │
        │   ERP    │ │  SAT   │ │ Generate│
        └──────────┘ └────────┘ └─────────┘
              │          │          │
              └──────────┼──────────┘
                         ▼
              ┌─────────────────────┐
              │  DECLARATION ENGINE │
              │  (Agente 1)         │
              │                     │
              │  IVA mensual        │
              │  ISR provisional    │
              │  ISR anual          │
              │  DIOT               │
              └──────────┬──────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │  SAT (envío mock    │
              │  → real con e.firma)│
              └─────────────────────┘
```

### 4.4 Diagrama de Secuencia: Procesamiento de un CFDI

```
    Cliente        API           Orchestrator     Agente 1     Agente 2     Agente 3
       │            │                │               │            │            │
       │ POST /cfdi │                │               │            │            │
       │───────────►│                │               │            │            │
       │            │ process(xml)   │               │            │            │
       │            │───────────────►│               │            │            │
       │            │                │               │            │            │
       │            │                │ parse+validate│            │            │
       │            │                │──────────────►│            │            │
       │            │                │               │            │            │
       │            │                │ classify(LLM) │            │            │
       │            │                │──────────────►│            │            │
       │            │                │               │            │            │
       │            │                │ map_to_account│            │            │
       │            │                │───────────────────────────►│            │
       │            │                │               │            │            │
       │            │                │ create_journal│            │            │
       │            │                │───────────────────────────►│            │
       │            │                │               │            │            │
       │            │                │ register_erp  │            │            │
       │            │                │──────────────►│            │            │
       │            │                │               │            │            │
       │            │                │── event: cfdi.processed ──────────────►│
       │            │                │               │            │            │
       │            │   200 OK       │               │            │            │
       │◄───────────│◄───────────────│               │            │            │
       │            │                │               │            │            │
```

---

## 5. Modelo de Datos Nuevo

### 5.1 Diagrama Entidad-Relación de las Nuevas Tablas

```
┌─────────────────────────────────────────────────────────────────────┐
│                     NUEVAS TABLAS (PostgreSQL)                       │
│                                                                      │
│  ┌───────────────────────┐       ┌───────────────────────┐          │
│  │ accounting_rules      │       │ journal_entries       │          │
│  │───────────────────────│       │───────────────────────│          │
│  │ id (PK)               │       │ id (PK)               │          │
│  │ tenant_id (FK)        │──────►│ tenant_id (FK)        │          │
│  │ categoria_cfdi        │       │ rule_id (FK)          │          │
│  │ tipo_cfdi (I/E/T)     │       │ invoice_id (FK)       │          │
│  │ cuenta_cargo          │       │ periodo (YYYY-MM)     │          │
│  │ cuenta_abono          │       │ fecha                 │          │
│  │ iva_cuenta_cargo      │       │ concepto              │          │
│  │ iva_cuenta_abono      │       │ debe (DECIMAL)        │          │
│  │ prioridad             │       │ haber (DECIMAL)       │          │
│  │ activo (bool)         │       │ estado                │          │
│  │ created_at            │       │ erp_poliza_id         │          │
│  └───────────────────────┘       │ created_at            │          │
│                                  └───────────────────────┘          │
│  ┌───────────────────────┐       ┌───────────────────────┐          │
│  │ declarations          │       │ close_periods         │          │
│  │───────────────────────│       │───────────────────────│          │
│  │ id (PK)               │       │ id (PK)               │          │
│  │ tenant_id (FK)        │       │ tenant_id (FK)        │          │
│  │ tipo (iva/isr/annual) │       │ periodo (YYYY-MM)     │          │
│  │ periodo (YYYY-MM)     │       │ estado                │          │
│  │ estado                │       │ checklist_json        │          │
│  │ iva_cobrado           │       │ cfdis_procesados      │          │
│  │ iva_pagado            │       │ cfdis_total           │          │
│  │ isr_base              │       │ conciliado (bool)     │          │
│  │ isr_retenido          │       │ auditado (bool)       │          │
│  │ monto_pagar           │       │ approved_by           │          │
│  │ xml_generado (TEXT)   │       │ approved_at           │          │
│  │ acuse_recibo          │       │ created_at            │          │
│  │ deadline              │       └───────────────────────┘          │
│  │ submitted_at          │                                           │
│  │ created_at            │       ┌───────────────────────┐          │
│  └───────────────────────┘       │ ap_invoices           │          │
│                                  │───────────────────────│          │
│  ┌───────────────────────┐       │ id (PK)               │          │
│  │ ar_invoices           │       │ tenant_id (FK)        │          │
│  │───────────────────────│       │ proveedor_rfc         │          │
│  │ id (PK)               │       │ proveedor_nombre      │          │
│  │ tenant_id (FK)        │       │ cfdi_uuid             │          │
│  │ cliente_rfc           │       │ monto (DECIMAL)       │          │
│  │ cliente_nombre        │       │ fecha_emision         │          │
│  │ cfdi_uuid             │       │ fecha_vencimiento     │          │
│  │ monto (DECIMAL)       │       │ estado                │          │
│  │ fecha_emision         │       │ fecha_pago            │          │
│  │ fecha_vencimiento     │       │ banco_movimiento_id   │          │
│  │ estado                │       │ conciliado (bool)     │          │
│  │ fecha_pago            │       │ confidence_score      │          │
│  │ banco_movimiento_id   │       │ created_at            │          │
│  │ conciliado (bool)     │       └───────────────────────┘          │
│  │ confidence_score      │                                           │
│  │ aging_bucket          │       ┌───────────────────────┐          │
│  │ created_at            │       │ agent_state           │          │
│  └───────────────────────┘       │───────────────────────│          │
│                                  │ id (PK)               │          │
│  ┌───────────────────────┐       │ agent_name            │          │
│  │ event_log             │       │ tenant_id (FK)        │          │
│  │───────────────────────│       │ estado                │          │
│  │ id (PK)               │       │ last_heartbeat        │          │
│  │ tenant_id (FK)        │       │ last_task_id          │          │
│  │ event_type            │       │ metrics_json          │          │
│  │ source_agent          │       │ error_count           │          │
│  │ payload_json (TEXT)   │       │ updated_at            │          │
│  │ created_at            │       └───────────────────────┘          │
│  └───────────────────────┘                                           │
└─────────────────────────────────────────────────────────────────────┘
```

### 5.2 SQL de las Nuevas Tablas

```sql
-- ============================================================
-- MIGRACIÓN: Tablas para los 5 agentes
-- Versión: 027 (siguiente disponible en db/models.py)
-- ============================================================

-- Reglas contables: categoría CFDI → cuenta contable
CREATE TABLE IF NOT EXISTS accounting_rules (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id),
    categoria_cfdi  TEXT NOT NULL,          -- de classify.py
    tipo_cfdi       TEXT NOT NULL DEFAULT 'I',  -- I=Ingreso, E=Egreso, T=Traslado
    cuenta_cargo    TEXT NOT NULL,          -- código SAT (ej: "6102")
    cuenta_abono    TEXT NOT NULL,          -- código SAT (ej: "2101")
    iva_cuenta_cargo TEXT,                  -- cuenta para IVA acreditable
    iva_cuenta_abono TEXT,                  -- cuenta para IVA trasladado
    prioridad       INTEGER DEFAULT 1,      -- mayor = más específica
    activo          BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, categoria_cfdi, tipo_cfdi, prioridad)
);

-- Asientos contables (pólizas de diario)
CREATE TABLE IF NOT EXISTS journal_entries (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id),
    rule_id         INTEGER REFERENCES accounting_rules(id),
    invoice_id      INTEGER REFERENCES invoices(id),
    periodo         TEXT NOT NULL,          -- YYYY-MM
    fecha           DATE NOT NULL,
    tipo_poliza     TEXT DEFAULT 'DIARIO',  -- DIARIO, INGRESO, EGRESO
    concepto        TEXT NOT NULL,
    cuenta          TEXT NOT NULL,          -- código SAT
    debe            DECIMAL(15,2) DEFAULT 0,
    haber           DECIMAL(15,2) DEFAULT 0,
    estado          TEXT DEFAULT 'borrador', -- borrador|contabilizada|cancelada
    erp_poliza_id   TEXT,                   -- ID en el ERP externo
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_journal_tenant_periodo ON journal_entries(tenant_id, periodo);

-- Declaraciones fiscales
CREATE TABLE IF NOT EXISTS declarations (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id),
    tipo            TEXT NOT NULL,          -- 'iva_mensual', 'isr_provisional', 'isr_anual', 'diot'
    periodo         TEXT NOT NULL,          -- YYYY-MM o YYYY para anual
    estado          TEXT DEFAULT 'borrador', -- borrador|calculada|generada|enviada|aceptada
    iva_cobrado     DECIMAL(15,2),
    iva_pagado      DECIMAL(15,2),
    iva_saldo       DECIMAL(15,2),
    isr_base        DECIMAL(15,2),
    isr_retenido    DECIMAL(15,2),
    isr_pagar       DECIMAL(15,2),
    monto_pagar     DECIMAL(15,2),
    xml_generado    TEXT,
    acuse_recibo    TEXT,
    deadline        DATE,
    submitted_at    TIMESTAMP,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, tipo, periodo)
);

-- Periodos de cierre contable
CREATE TABLE IF NOT EXISTS close_periods (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id),
    periodo         TEXT NOT NULL,          -- YYYY-MM
    estado          TEXT DEFAULT 'abierto', -- abierto|en_cierre|cerrado|aprobado
    checklist_json  TEXT,                   -- JSON con estado de cada paso
    cfdis_procesados INTEGER DEFAULT 0,
    cfdis_total     INTEGER DEFAULT 0,
    conciliado      BOOLEAN DEFAULT FALSE,
    auditado        BOOLEAN DEFAULT FALSE,
    approved_by     TEXT,
    approved_at     TIMESTAMP,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, periodo)
);

-- Facturas por cobrar (AR)
CREATE TABLE IF NOT EXISTS ar_invoices (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id),
    cliente_rfc     TEXT,
    cliente_nombre  TEXT,
    cfdi_uuid       TEXT,
    monto           DECIMAL(15,2) NOT NULL,
    fecha_emision   DATE NOT NULL,
    fecha_vencimiento DATE,
    estado          TEXT DEFAULT 'pendiente', -- pendiente|parcial|pagada|vencida|incobrable
    fecha_pago      DATE,
    monto_pagado    DECIMAL(15,2) DEFAULT 0,
    banco_movimiento_id INTEGER,
    conciliado      BOOLEAN DEFAULT FALSE,
    confidence_score INTEGER DEFAULT 0,
    aging_bucket    TEXT,                     -- 0-30, 31-60, 61-90, 90+
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_ar_tenant_estado ON ar_invoices(tenant_id, estado);
CREATE INDEX idx_ar_vencimiento ON ar_invoices(fecha_vencimiento);

-- Facturas por pagar (AP)
CREATE TABLE IF NOT EXISTS ap_invoices (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id),
    proveedor_rfc   TEXT,
    proveedor_nombre TEXT,
    cfdi_uuid       TEXT,
    monto           DECIMAL(15,2) NOT NULL,
    fecha_emision   DATE NOT NULL,
    fecha_vencimiento DATE,
    estado          TEXT DEFAULT 'pendiente', -- pendiente|programada|pagada|vencida
    fecha_pago      DATE,
    monto_pagado    DECIMAL(15,2) DEFAULT 0,
    banco_movimiento_id INTEGER,
    conciliado      BOOLEAN DEFAULT FALSE,
    confidence_score INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_ap_tenant_estado ON ap_invoices(tenant_id, estado);

-- Log de eventos del bus
CREATE TABLE IF NOT EXISTS event_log (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id),
    event_type      TEXT NOT NULL,
    source_agent    TEXT,
    payload_json    TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_events_tenant_type ON event_log(tenant_id, event_type);
CREATE INDEX idx_events_created ON event_log(created_at);

-- Estado de los agentes
CREATE TABLE IF NOT EXISTS agent_state (
    id              SERIAL PRIMARY KEY,
    agent_name      TEXT NOT NULL,           -- 'fiscal', 'contable', 'close', 'apar', 'nomina'
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id),
    estado          TEXT DEFAULT 'idle',     -- idle|processing|error|maintenance
    last_heartbeat  TIMESTAMP,
    last_task_id    TEXT,
    metrics_json    TEXT,
    error_count     INTEGER DEFAULT 0,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(agent_name, tenant_id)
);
```

---

## 6. Flujos de Datos Principales

### 6.1 Flujo 1: CFDI → Contabilidad Automática

```
PSEUDOCÓDIGO:

def flujo_cfdi_a_contabilidad(xml_path, tenant_id):
    """Procesa un CFDI y genera el asiento contable automático."""

    # PASO 1: Pipeline CFDI existente (reutiliza 100%)
    resultado = pipeline.process_file(xml_path, db, tenant_id)
    # resultado = {categoria, subtotal, iva, total, uuid, tipo_cfdi}

    # PASO 2: Buscar regla contable (NUEVO)
    regla = accounting_rules_engine.find_rule(
        tenant_id=tenant_id,
        categoria=resultado['categoria'],
        tipo_cfdi=resultado['tipo_cfdi']  # I=Ingreso, E=Egreso
    )

    if not regla:
        # Escalar a humano: categoría sin mapeo contable
        orchestrator.escalate("sin_regla_contable", resultado)
        return

    # PASO 3: Generar asiento contable (NUEVO)
    asiento = accounting_rules_engine.generar_asiento(
        regla=regla,
        subtotal=resultado['subtotal'],
        iva=resultado['iva'],
        total=resultado['total'],
        concepto=resultado['concepto'],
        fecha=resultado['fecha']
    )
    # asiento = [
    #   {cuenta: "6102", debe: 1000, haber: 0, concepto: "Servicios profesionales"},
    #   {cuenta: "1103", debe: 160,  haber: 0, concepto: "IVA acreditable"},
    #   {cuenta: "2101", debe: 0,    haber: 1160, concepto: "Proveedores"},
    # ]

    # PASO 4: Validar cuadratura
    assert sum(a['debe'] for a in asiento) == sum(a['haber'] for a in asiento)

    # PASO 5: Registrar en DB y ERP
    for linea in asiento:
        db.insert_journal_entry(tenant_id, linea)

    # PASO 6: Registrar en ERP vía IntegrationHub
    erp_adapter = hub.get_adapter(tenant_config['erp_type'])
    erp_adapter.create_poliza(asiento)

    # PASO 7: Actualizar balanza de comprobación
    balanza.agregar_movimientos(asiento, periodo=resultado['periodo'])

    # PASO 8: Emitir evento
    event_bus.publish("journal.entry.created", {
        "tenant_id": tenant_id,
        "invoice_id": resultado['invoice_id'],
        "total_debe": sum(a['debe'] for a in asiento),
    })
```

### 6.2 Flujo 2: Cierre Mensual

```
PSEUDOCÓDIGO:

def flujo_cierre_mensual(tenant_id, mes):
    """Ejecuta el checklist de cierre contable mensual."""

    close = CloseManager(db, tenant_id)

    # PASO 1: Verificar CFDI procesados
    stats = close.check_cfdis_procesados(mes)
    # stats = {total: 150, procesados: 148, pendientes: 2}
    if stats['pendientes'] > 0:
        close.notify("Hay CFDI sin procesar", stats)
        return {"status": "bloqueado", "reason": "cfdi_pendientes"}

    # PASO 2: Verificar conciliación bancaria
    conc = close.check_conciliacion(mes)
    # conc = {conciliados: 95, sin_match: 5, total_movimientos: 100}
    if conc['sin_match'] > 0:
        close.notify("Movimientos bancarios sin conciliar", conc)

    # PASO 3: Verificar nóminas registradas
    nom = close.check_nominas(mes)
    # nom = {quincena_1: true, quincena_2: true, empleados: 25}

    # PASO 4: Verificar pólizas cuadradas
    pol = close.check_cuadratura(mes)
    # pol = {total_polizas: 200, cuadradas: 198, desfase: 2}

    # PASO 5: Ejecutar pre-auditoría
    audit = pre_auditoria.run_checks(invoices_del_mes, tenant_id)
    # audit = {deducibles: 140, no_deducibles: 5, warnings: 3}

    # PASO 6: Generar balanza de comprobación
    balanza.generar(asientos_del_mes, periodo=mes)
    xml_balanza = balanza.generar_xml(rfc=tenant.rfc, ejercicio=year, mes=month)

    # PASO 7: Generar paquete de contabilidad electrónica
    paquete = contabilidad_electronica.generar_paquete(asientos_del_mes)

    # PASO 8: Generar borradores de declaraciones
    decl_iva = declaration_engine.generar_borrador_iva(mes, tenant_id)
    decl_isr = declaration_engine.generar_borrador_isr(mes, tenant_id)

    # PASO 9: Notificar al contador
    notifications.send("close_ready_for_review", {
        "mes": mes,
        "resumen": {stats, conc, nom, pol, audit},
        "declaraciones": [decl_iva, decl_isr],
    })

    # PASO 10: Esperar aprobación humana (HITL)
    close.marcar_estado(mes, "en_cierre")

    return {"status": "pendiente_aprobacion", "checklist": checklist}
```

### 6.3 Flujo 3: Nómina Quincenal

```
PSEUDOCÓDIGO:

def flujo_nomina_quincenal(tenant_id, periodo, empleados):
    """Calcula nómina para una quincena completa."""

    # PASO 1: Calcular nómina por empleado (reutiliza service existente)
    resultados = []
    for emp in empleados:
        taxes = nomina_service.calculate_taxes(
            salary=emp['salario_mensual'],
            salary_per_day=emp['salario_diario'],
            dias_pagados=15,
            periodicidad="quincenal"
        )
        cfdi = nomina_service.generate_payroll_cfdi(emp, taxes)
        resultados.append({"empleado": emp, "taxes": taxes, "cfdi": cfdi})

    # PASO 2: Generar asientos contables de nómina
    asiento_nomina = accounting_rules_engine.generar_asiento_nomina(resultados)
    # Cargo: 6101 Sueldos y Salarios
    # Abono: 2104 Impuestos por pagar (ISR retenido)
    # Abono: 2104 IMSS (cuota obrera)
    # Abono: 1101 Bancos (neto a pagar)

    # PASO 3: Registrar en DB y ERP
    for linea in asiento_nomina:
        db.insert_journal_entry(tenant_id, linea)

    # PASO 4: Emitir eventos
    event_bus.publish("payroll.batch.completed", {
        "tenant_id": tenant_id,
        "periodo": periodo,
        "empleados": len(empleados),
        "total_bruto": sum(r['taxes'].gross for r in resultados),
        "total_neto": sum(r['taxes'].net for r in resultados),
    })

    return resultados
```

### 6.4 Flujo 4: Conciliación Bancaria → AP/AR

```
PSEUDOCÓDIGO:

def flujo_conciliacion_apar(tenant_id, statement_path, bank):
    """Concilia estado de cuenta contra facturas AP y AR."""

    # PASO 1: Parsear estado de cuenta (reutiliza bank_reconciliation)
    session = BankReconciliation(llm=llm_service)
    session.upload_statement(statement_path, bank=bank)
    movimientos = session.movements

    # PASO 2: Match contra facturas emitidas (AR)
    ar_pendientes = db.get_ar_invoices(tenant_id, estado='pendiente')
    ar_matches = session.match_against_invoices(movimientos, ar_pendientes)
    # ar_matches = [{movimiento_id, invoice_id, score, tipo_match}]

    # PASO 3: Match contra facturas recibidas (AP)
    ap_pendientes = db.get_ap_invoices(tenant_id, estado='pendiente')
    ap_matches = session.match_against_invoices(movimientos, ap_pendientes)

    # PASO 4: Actualizar estado de facturas conciliadas
    for match in ar_matches:
        if match['score'] >= 80:  # auto-confirm
            db.update_ar_invoice(match['invoice_id'], estado='pagada',
                                 banco_movimiento_id=match['movimiento_id'])
        else:
            db.update_ar_invoice(match['invoice_id'], estado='parcial',
                                 confidence_score=match['score'])

    # PASO 5: Generar aging report
    aging = collections_manager.analyze(ar_pendientes)
    # aging = {"0-30": 15, "31-60": 8, "61-90": 3, "90+": 2}

    # PASO 6: Ejecutar secuencia de cobranza para vencidos
    for inv in ar_pendientes:
        if inv['estado'] == 'vencida':
            collections_manager.send_reminder(inv, stage=reminder_stage(inv))

    # PASO 7: Emitir eventos
    event_bus.publish("bank.match.completed", {
        "tenant_id": tenant_id,
        "ar_matched": len(ar_matches),
        "ap_matched": len(ap_matches),
    })
```

---

## 7. Stack Técnico

### 7.1 Stack Completo

```
┌─────────────────────────────────────────────────────────────────┐
│                      STACK TÉCNICO                               │
│                                                                   │
│  CAPA                 TECNOLOGÍA          ESTADO    USO          │
│  ─────────────────    ──────────────      ────────  ──────────   │
│  API Framework        FastAPI              ✅ Existe  REST API    │
│  Task Queue           Celery + Redis       🆕 Nuevo   Batch jobs │
│  Message Bus          Redis Streams        🆕 Nuevo   Eventos    │
│  Cache                Redis                🆕 Nuevo   Cache      │
│  DB Dev               SQLite               ✅ Existe  Dev/test   │
│  DB Prod              PostgreSQL           ✅ Existe  Producción │
│  ORM/Query            psycopg (raw SQL)    ✅ Existe  Queries    │
│  XML Parsing          lxml/xml.etree       ✅ Existe  CFDI XML   │
│  SAT SOAP             zeep                 🆕 Nuevo   API SAT    │
│  PDF Parsing          pdfplumber           🆕 Nuevo   Bank stmts │
│  ML/Clasificación     scikit-learn         🆕 Nuevo   Accounts   │
│  LLM Service          OpenAI/mock          ✅ Existe  Classify   │
│  Scheduler            APScheduler          🆕 Nuevo   Cron-like  │
│  Monitoring           Custom audit_log     ✅ Existe  Auditoría  │
│  Testing              pytest               ✅ Existe  Tests      │
│  Containerization     Docker               🆕 Nuevo   Deploy     │
│  Process Manager      systemd/Docker       🆕 Nuevo   Workers    │
└─────────────────────────────────────────────────────────────────┘
```

### 7.2 Dependencias Nuevas (requirements.txt adicional)

```txt
# Task queue
celery[redis]>=5.3.0
redis>=5.0.0

# Scheduler
apscheduler>=3.10.0

# SAT SOAP client
zeep>=4.2.0

# PDF parsing for bank statements
pdfplumber>=0.10.0

# ML for account classification
scikit-learn>=1.3.0
numpy>=1.24.0

# Production database
psycopg[binary]>=3.1.0

# Docker (ya existe Dockerfile probablemente)
# No es dependencia Python, pero necesario para deploy
```

### 7.3 Configuración de Redis

```yaml
# docker-compose.yml (fragmento)
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes

  celery-worker:
    build: .
    command: celery -A b2b_ai.infra.celery_app worker -l info -c 4
    depends_on:
      - redis
      - postgres
    environment:
      - REDIS_URL=redis://redis:6379/0
      - DATABASE_URL=postgresql://likida:secret@postgres:5432/likida

  celery-beat:
    build: .
    command: celery -A b2b_ai.infra.celery_app beat -l info
    depends_on:
      - redis
```

### 7.4 Estructura de Archivos Nueva

```
b2b_ai/
├── agent/
│   ├── loop.py                    # ✅ Existente
│   └── orchestrator.py            # 🆕 AgentOrchestrator
│
├── agents/                        # 🆕 Directorio de agentes
│   ├── __init__.py
│   ├── base.py                    # 🆕 BaseAgent abstracto
│   ├── fiscal.py                  # 🆕 Agente 1: Fiscal
│   ├── contable.py                # 🆕 Agente 2: Contable
│   ├── close.py                   # 🆕 Agente 3: Close Manager
│   ├── apar.py                    # 🆕 Agente 4: AP/AR
│   └── nomina_agent.py            # 🆕 Agente 5: Nómina
│
├── services/
│   ├── pipeline.py                # ✅ Existente
│   ├── classify.py                # ✅ Existente
│   ├── payroll.py                 # ✅ Existente
│   ├── reconcile.py               # ✅ Existente
│   ├── bank_reconciliation.py     # ✅ Existente
│   ├── collections.py             # ✅ Existente
│   ├── accounting.py              # ✅ Existente
│   ├── catalogo_cuentas.py        # ✅ Existente
│   ├── balanza.py                 # ✅ Existente
│   ├── contabilidad_electronica.py # ✅ Existente
│   ├── diot_service.py            # ✅ Existente
│   ├── accounting_rules_engine.py # 🆕 Motor de reglas contables
│   ├── declaration_engine.py      # 🆕 Motor de declaraciones
│   ├── close_manager.py           # 🆕 Gestor de cierre
│   └── apar_manager.py            # 🆕 Gestor AP/AR
│
├── infra/                         # 🆕 Infraestructura
│   ├── __init__.py
│   ├── event_bus.py               # 🆕 Redis Streams event bus
│   ├── celery_app.py              # 🆕 Configuración Celery
│   ├── tasks.py                   # 🆕 Tareas Celery
│   ├── scheduler.py               # 🆕 APScheduler wrapper
│   └── health.py                  # 🆕 Health check agentes
│
├── db/
│   ├── db.py                      # ✅ Existente
│   ├── models.py                  # ✅ Existente (añadir nuevas tablas)
│   └── migrations/                # 🆕 Migraciones SQL
│       └── 027_agent_tables.sql   # 🆕 SQL de las nuevas tablas
│
├── integrations/                  # ✅ Todo existente
│   ├── hub.py
│   ├── erp/
│   ├── bancos/
│   ├── sat/
│   └── ...
│
├── notifications/                 # ✅ Todo existente
├── cfdi/                          # ✅ Todo existente
└── api/
    ├── app.py                     # ✅ Existente (añadir nuevos routers)
    └── v3_agents.py               # 🆕 API endpoints para agentes
```

---

## 8. Roadmap de Implementación

### Fase 1: Infraestructura Base (Semana 1-2)

```
Tareas:
  □ Instalar dependencias (celery, redis, zeep, pdfplumber, scikit-learn)
  □ Configurar Redis (docker-compose)
  □ Implementar EventBus (Redis Streams)
  □ Implementar Celery app + tasks base
  □ Crear migración 027 (tablas nuevas)
  □ Implementar BaseAgent abstracto
  □ Tests de infraestructura

Entregable: Cola de trabajo + eventos funcionando
```

### Fase 2: Agente 1 — Fiscal (Semana 3-4)

```
Tareas:
  □ Implementar AccountingRulesEngine
  □ Implementar DeclarationEngine
  □ Crear Agente 1 (fiscal.py) con:
    - Procesamiento CFDI (reutiliza pipeline)
    - Auto-asiento contable (nuevo)
    - Generación DIOT (reutiliza diot_service)
    - Borrador declaraciones (nuevo)
  □ Conectar con Event Bus
  □ Tests + integración con pipeline existente

Entregable: CFDI → asiento contable automático
```

### Fase 3: Agente 2 — Contable (Semana 5-6)

```
Tareas:
  □ Implementar motor de reglas por defecto (catálogo SAT)
  □ Implementar reglas extensibles por tenant
  □ Conectar con CatalogoCuentas existente
  □ Conectar con BalanzaComprobacion existente
  □ Conectar con ContabilidadElectronica existente
  □ Generación automática de XML SAT
  □ Tests de cuadratura y validación

Entregable: Asientos → balanza → XML contabilidad electrónica
```

### Fase 4: Agente 5 — Nómina (Semana 7-8)

```
Tareas:
  □ Crear Agente 5 (nomina_agent.py) sobre nomina_completa
  □ Implementar batch payroll (todos los empleados)
  □ Scheduler quincenal automático
  □ Generación de asientos contables de nómina
  □ CFDI Nómina batch
  □ Reports de nómina

Entregable: Nómina quincenal automática end-to-end
```

### Fase 5: Agente 4 — AP/AR (Semana 9-10)

```
Tareas:
  □ Implementar APARManager
  □ Conectar con BankReconciliation existente
  □ Conectar con CollectionsManager existente
  □ Implementar aging report automático
  □ Implementar secuencia de cobranza
  □ Implementar programación de pagos
  □ Tests de matching AP/AR

Entregable: Conciliación automática + cobranza programada
```

### Fase 6: Agente 3 — Close Manager + Orchestrator (Semana 11-12)

```
Tareas:
  □ Implementar CloseManager
  □ Implementar checklist de cierre
  □ Implementar AgentOrchestrator (conecta los 5)
  □ API unificada v3_agents.py
  □ Dashboard de estado de agentes
  □ End-to-end testing del flujo completo
  □ Documentación de operación

Entregable: Sistema completo de 5 agentes orquestados
```

---

## Apéndice A: API Endpoints Nuevos

```
# API v3 — Endpoints de Agentes

# Agente 1: Fiscal
POST   /api/v3/fiscal/cfdi/process         # Procesar CFDI individual
POST   /api/v3/fiscal/cfdi/batch           # Procesar lote de CFDI
POST   /api/v3/fiscal/declarations/generate # Generar declaración
GET    /api/v3/fiscal/declarations/{id}     # Estado de declaración
POST   /api/v3/fiscal/declarations/submit   # Enviar al SAT

# Agente 2: Contable
GET    /api/v3/accounting/rules             # Listar reglas contables
POST   /api/v3/accounting/rules             # Crear regla contable
GET    /api/v3/accounting/journal           # Libro diario
GET    /api/v3/accounting/balance           # Balanza de comprobación
GET    /api/v3/accounting/balance/xml       # XML para SAT

# Agente 3: Close Manager
POST   /api/v3/close/start                  # Iniciar cierre mensual
GET    /api/v3/close/{periodo}/status       # Estado del cierre
POST   /api/v3/close/{periodo}/approve      # Aprobar cierre

# Agente 4: AP/AR
GET    /api/v3/apar/aging                   # Reporte de antigüedad
POST   /api/v3/apar/reconcile               # Conciliación bancaria
GET    /api/v3/apar/ar/invoices             # Facturas por cobrar
GET    /api/v3/apar/ap/invoices             # Facturas por pagar

# Agente 5: Nómina
POST   /api/v3/payroll/calculate             # Calcular nómina
POST   /api/v3/payroll/batch                 # Nómina batch
GET    /api/v3/payroll/{periodo}/status      # Estado nómina

# Orchestrator
GET    /api/v3/agents/status                 # Estado de los 5 agentes
GET    /api/v3/agents/health                 # Health check
GET    /api/v3/agents/metrics                # Métricas agregadas
POST   /api/v3/agents/{name}/restart         # Reiniciar agente
```

---

## Apéndice B: Patrón BaseAgent

```python
# b2b_ai/agents/base.py

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from b2b_ai.db.db import Database
from b2b_ai.infra.event_bus import EventBus

class BaseAgent(ABC):
    """Clase base para los 5 agentes especializados."""

    name: str = "base"

    def __init__(self, db: Database, event_bus: EventBus,
                 tenant_id: int, config: Optional[Dict] = None):
        self.db = db
        self.event_bus = event_bus
        self.tenant_id = tenant_id
        self.config = config or {}
        self._estado = "idle"

    @abstractmethod
    def process(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Procesa una tarea y devuelve el resultado."""

    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        """Devuelve el estado de salud del agente."""

    def emit_event(self, event_type: str, payload: Dict[str, Any]):
        """Emite un evento al bus."""
        self.event_bus.publish(event_type, {
            "tenant_id": self.tenant_id,
            "source_agent": self.name,
            **payload
        })

    def escalate(self, reason: str, context: Dict[str, Any]):
        """Escala a revisión humana."""
        self.db.create_review(self.tenant_id, None, reason)
        self.emit_event("human.review.required", {
            "reason": reason,
            "context": context,
        })
```

---

## Apéndice C: Métricas y Monitoreo

```python
# Métricas clave por agente

METRICS = {
    "fiscal": {
        "cfdi_processed_total": "counter",
        "cfdi_processing_time_ms": "histogram",
        "cfdi_errors_total": "counter",
        "declarations_generated": "counter",
        "declarations_submitted": "counter",
    },
    "contable": {
        "journal_entries_created": "counter",
        "journal_auto_mapped": "counter",
        "journal_escalated": "counter",
        "balance_cuadratura_ok": "gauge",
        "balance_xml_generated": "counter",
    },
    "close": {
        "close_started": "counter",
        "close_completed": "counter",
        "close_duration_hours": "histogram",
        "close_blockers": "gauge",
    },
    "apar": {
        "ar_invoices_total": "gauge",
        "ar_invoices_overdue": "gauge",
        "ar_collected_amount": "counter",
        "ap_invoices_total": "gauge",
        "ap_payments_scheduled": "counter",
        "bank_matches_confidence_avg": "gauge",
    },
    "nomina": {
        "payroll_calculated": "counter",
        "payroll_employees_total": "gauge",
        "payroll_total_bruto": "counter",
        "payroll_total_neto": "counter",
        "payroll_cfdis_generated": "counter",
    },
}
```

---

*Documento generado automáticamente. Última actualización: Agosto 2026.*
