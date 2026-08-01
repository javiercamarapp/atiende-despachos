# BLUEPRINT DE PRODUCCIÓN — 5 Agentes Agenticos para Despachos Contables en México

> **Proyecto:** Likida AI Enterprise
> **Versión:** 1.0 — Agosto 2026
> **Estado:** Listo para ejecución por equipo de 3-4 ingenieros
> **Baseline existente:** Pipeline CFDI 4.0, nómina ISR/IMSS/INFONAVIT, conciliación bancaria, contabilidad electrónica, IntegrationHub (+15 ERPs), DB multi-tenant PostgreSQL/SQLite

---

## TABLA DE CONTENIDOS

1. [Stack Técnico Unificado](#1-stack-técnico-unificado)
2. [Agente 1: Close Management Agent](#2-agente-1-close-management-agent)
3. [Agente 2: Declaraciones Fiscales Autónomas](#3-agente-2-declaraciones-fiscales-autónomas)
4. [Agente 3: Conciliación Bancaria Inteligente](#4-agente-3-conciliación-bancaria-inteligente)
5. [Agente 4: AP/AR End-to-End](#5-agente-4-apar-end-to-end)
6. [Agente 5: Bookkeeping Completo Autónomo](#6-agente-5-bookkeeping-completo-autónomo)
7. [Timeline Global y Dependencias](#7-timeline-global-y-dependencias)
8. [MVP de Cada Agente](#8-mvp-de-cada-agente)
9. [Riesgos y Mitigaciones](#9-riesgos-y-mitigaciones)
10. [Infraestructura Compartida](#10-infraestructura-compartida)

---

## 1. STACK TÉCNICO UNIFICADO

### 1.1 Backend

| Componente | Tecnología | Versión | Propósito |
|---|---|---|---|
| **Framework API** | FastAPI | 0.110+ | API REST síncrona, webhooks, health checks |
| **Cola de tareas** | Celery | 5.3+ | Batch CFDI, nómina masiva, declaraciones, conciliación |
| **Broker + Cache** | Redis | 7.2+ | Celery broker, Redis Streams (event bus), cache TTL |
| **Base de datos** | PostgreSQL | 16+ | Multi-tenant, JSONB para checklist, full-text search |
| **ORM** | SQLAlchemy | 2.0+ | Async, modelos, migraciones |
| **Migraciones** | Alembic | 1.13+ | Schema versionado |
| **Scheduler** | APScheduler | 3.10+ | Tareas periódicas (cierre mensual, declaraciones) |
| **HTTP client** | httpx | 0.27+ | Async, APIs REST (Facturapi, Conekta, STP) |
| **SOAP client** | zeep | 4.2+ | Web services SAT (cancelación, descarga masiva) |

### 1.2 Procesamiento de Datos

| Componente | Tecnología | Propósito |
|---|---|---|
| **XML parsing** | lxml + xmlschema | Parseo CFDI 4.0, validación XSD SAT |
| **PDF parsing** | pdfplumber | Extracción de estados de cuenta bancarios PDF |
| **OCR** | Tesseract + pytesseract | Facturas escaneadas, recibos no digitales |
| **ML clasificación** | scikit-learn | Clasificación automática de CFDI → cuenta contable |
| **Fuzzy matching** | rapidfuzz | Matching bancario fuzzy (nombres, referencias) |
| **LLM** | OpenAI GPT-4o / Claude | Clasificación inteligente, análisis de anomalías, matching multi-línea |

### 1.3 Integraciones Externas

| Servicio | SDK/Cliente | Propósito | Pricing |
|---|---|---|---|
| **Facturapi** | REST (httpx) | Timbrado, cancelación, validación RFC, descarga masiva | $299 MXN/mes + $0.60/timbre |
| **FiscalAPI** | REST (httpx) | Alternativa PAC, descarga masiva | $199 MXN/mes + $0.49-1.71/timbre |
| **STP (SPEI)** | REST (httpx) | Envío transferencias interbancarias | Contrato directo |
| **Conekta** | REST (httpx) | Cobros (OXXO, SPEI, tarjetas) | 2.9% + $2.50 MXN/transacción |
| **Banxico** | REST (httpx) | Tipo de cambio diario (TC oficial) | Gratis |
| **CONTPAQi** | pyodbc (SQL Server) + COM via pythonnet | Lectura/escritura contabilidad | Licencia existente del despacho |
| **Aspel COI** | pyodbc (SQL Server/Btrieve) + COM | Lectura/escritura contabilidad | Licencia existente del despacho |
| **SAP B1** | REST (Service Layer) | CRUD contabilidad completo | Enterprise |
| **QuickBooks** | REST (OAuth 2.0) | CRUD contabilidad | Desde $280 MXN/mes |
| **Odoo** | JSON-RPC / REST | CRUD contabilidad, localización MX | Community gratis / Enterprise ~$25 USD/user/mes |

### 1.4 Infraestructura

| Componente | Tecnología | Propósito |
|---|---|---|
| **Containerización** | Docker + Docker Compose | Desarrollo local, CI/CD |
| **Orquestación** | Docker Compose (dev) / Kubernetes (prod) | Servicios, workers, DB |
| **CI/CD** | GitHub Actions | Tests, lint, deploy |
| **Monitoreo** | Prometheus + Grafana | Métricas de agentes, colas, latencias |
| **Logs** | structlog + Loki | Logs estructurados, audit trail |
| **Secrets** | HashiCorp Vault o env vars cifradas | FIEL/CSD, API keys, contraseñas DB |

### 1.5 Almacenamiento de Certificados FIEL/CSD

```
certificates/
├── {rfc}/
│   ├── csd.cer                    # Certificado de Sello Digital
│   ├── csd.key                    # Llave privada CSD
│   ├── csd_password.enc           # Contraseña (cifrado AES-256-GCM)
│   ├── fiel.cer                   # FIEL (e.firma)
│   ├── fiel.key                   # Llave privada FIEL
│   ├── fiel_password.enc          # Contraseña
│   └── metadata.json              # Vigencia, último uso, fingerprint
```

**Reglas de seguridad:**
- Archivos `.key` y contraseñas **nunca** se envían por API — solo se leen del filesystem cifrado en el servidor
- El agente firma localmente y envía el XML firmado
- Rotación de contraseñas cada 90 días (alerta automática)
- Vigencia de CSD: 4 años — alerta 30 días antes de vencimiento

---

## 2. AGENTE 1: CLOSE MANAGEMENT AGENT

### 2.1 Descripción

Orquesta el proceso de cierre contable mensual y anual. Verifica que todas las partidas estén registradas, conciliadas y auditadas antes de generar reportes finales. Genera un checklist interactivo para el contador y ejecuta tareas de cierre de forma autónoma.

**Benchmark global:** Numeric logra 90%+ automatización en cierre. FloQast (3,500+ equipos) orquesta el cierre completo.

### 2.2 Flujo Paso a Paso — Mes a Mes

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    CICLO DE CIERRE MENSUAL                              │
│                                                                         │
│  DÍA 1-25 DEL MES: OPERACIONES CONTINUAS                               │
│  ├── CFDIs se procesan en tiempo real (Agente 5 → Agente 2)            │
│  ├── Conciliación bancaria batch (Agente 3)                             │
│  ├── AP/AR tracking continuo (Agente 4)                                │
│  └── Pólizas se registran automáticamente al ERP                       │
│                                                                         │
│  DÍA 26: INICIO DE CIERRE (automático)                                 │
│  ├── PASO 1: Verificar CFDIs procesados del mes                        │
│  ├── PASO 2: Verificar conciliación bancaria completada                │
│  ├── PASO 3: Verificar nóminas quincenales registradas                 │
│  ├── PASO 4: Verificar pólizas cuadradas (debe == haber)               │
│  └── PASO 5: Ejecutar pre-auditoría (deducibilidad, CFF Art. 27)      │
│                                                                         │
│  DÍA 27: AJUSTES DE CIERRE (semi-automático)                           │
│  ├── PASO 6: Calcular depreciaciones del mes                           │
│  ├── PASO 7: Calcular provisiones (aguinaldo, vacaciones, PTU)         │
│  ├── PASO 8: Aplicar diferencias de cambio                             │
│  ├── PASO 9: Ajustar inventarios (si aplica)                           │
│  ├── PASO 10: Calcular ajuste por inflación (Art. 44-45 LISR)         │
│  └── PASO 11: Registrar pólizas de ajuste en ERP                       │
│                                                                         │
│  DÍA 28: REPORTES Y DECLARACIONES                                      │
│  ├── PASO 12: Generar balanza de comprobación (XML Anexo 24)           │
│  ├── PASO 13: Generar paquete de contabilidad electrónica              │
│  ├── PASO 14: Generar borrador declaración IVA mensual                 │
│  ├── PASO 15: Generar borrador declaración ISR provisional             │
│  ├── PASO 16: Generar borrador DIOT                                    │
│  └── PASO 17: Enviar resumen completo al contador vía email/WhatsApp   │
│                                                                         │
│  DÍA 29-30: APROBACIÓN HUMANA                                          │
│  ├── PASO 18: Contador revisa checklist en dashboard                   │
│  ├── PASO 19: Aprueba o solicita correcciones                          │
│  └── PASO 20: Marca periodo como "cerrado"                             │
│                                                                         │
│  DÍA 17 DEL MES SIGUIENTE: DECLARACIONES                               │
│  ├── PASO 21: Enviar IVA mensual al SAT                                │
│  ├── PASO 22: Enviar ISR provisional al SAT                            │
│  ├── PASO 23: Enviar DIOT al SAT                                       │
│  └── PASO 24: Enviar balanza de comprobación al SAT                    │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.3 Integración con ERPs

#### 2.3.1 CONTPAQi (SQL Server + COM)

```python
# Adapter para CONTPAQi — lectura y escritura de pólizas
class CONTPAQiAdapter:
    """
    Estrategia de integración:
    1. PRIMARIO: Conexión directa a SQL Server vía pyodbc
    2. FALLBACK: SDK COM vía pythonnet (para operaciones que requieren COM)
    3. NUBE: CONTPAQi Contabiliza API REST (si el despacho usa versión nube)
    """

    def __init__(self, config: dict):
        self.conn_str = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={config['server']};"
            f"DATABASE={config['database']};"
            f"UID={config['user']};PWD={config['password']}"
        )

    def leer_polizas(self, periodo: str) -> list[dict]:
        """Lee pólizas del periodo desde SQL Server."""
        query = """
            SELECT c.cNombreConcepto as tipo_poliza,
                   p.cFecha as fecha,
                   p.cReferencia as referencia,
                   m.cCuenta as cuenta_contable,
                   m.cImporte as importe,
                   m.cTipoMovto as tipo_movimiento  -- C=Cargo, A=Abono
            FROM ACONCEPTOS c
            JOIN APOLIZAS p ON c.cIdConcepto = p.cIdConcepto
            JOIN AMOVIMIENTOS m ON p.cIdPoliza = m.cIdPoliza
            WHERE p.cFecha BETWEEN ? AND ?
            ORDER BY p.cFecha, p.cIdPoliza
        """
        # Ejecutar con pyodbc

    def crear_poliza(self, poliza: dict) -> str:
        """
        Crea una póliza de diario en CONTPAQi.
        Dos vías:
        - SQL directo: INSERT en APOLIZAS + AMOVIMIENTOS (más rápido, menos seguro)
        - COM: Usa el SDK para validación automática (más seguro, más lento)
        """
        # Preferir COM para escritura (validación nativa)
        # Fallback a SQL si COM no disponible

    def leer_balanza(self, periodo: str) -> list[dict]:
        """Lee la balanza de comprobación para verificación."""

    def sincronizar_catalogo(self) -> dict:
        """Lee el catálogo de cuentas y lo sincroniza con el mapping SAT."""
        query = "SELECT cCuenta, cNombre, cTipo FROM ACUENTAS WHERE cNivel > 0"
```

**Tablas clave CONTPAQi:**
| Tabla | Contenido | Acción agente |
|---|---|---|
| `ACUENTAS` | Catálogo de cuentas | READ (sincronizar con SAT) |
| `ACONCEPTOS` | Tipos de póliza | READ (saber qué tipos existen) |
| `APOLIZAS` | Encabezados de pólizas | READ + CREATE |
| `AMOVIMIENTOS` | Movimientos contables | READ + CREATE |
| `APERIODO` | Periodos abiertos/cerrados | READ (verificar estado) |

#### 2.3.2 Aspel COI (Btrieve + COM)

```python
class AspelAdapter:
    """
    Estrategia de integración:
    1. PRIMARIO: pyodbc contra SQL Server (versiones recientes de Aspel)
    2. FALLBACK: Btrieve/Pervasive SQL vía ctypes o pywin32
    3. COM: SDK COM de Aspel para operaciones avanzadas

    NOTA: Aspel COI 8.0+ usa SQL Server. Versiones anteriores usan Btrieve.
    """
    def __init__(self, config: dict):
        self.engine_type = config.get('engine', 'sql')  # 'sql' o 'btrieve'

    def leer_polizas(self, periodo: str) -> list[dict]:
        if self.engine_type == 'sql':
            return self._read_sql(periodo)
        else:
            return self._read_btrieve(periodo)
```

#### 2.3.3 SAP Business One (REST Service Layer)

```python
class SAPB1Adapter:
    """
    SAP B1 Service Layer: API REST moderna.
    Documentación: SAP Business One Service Layer Reference
    """

    BASE_URL = "https://{server}:50000/b1s/v1"

    def authenticate(self, company_db: str, user: str, password: str):
        """POST /Login — obtiene session cookie."""
        resp = httpx.post(f"{self.BASE_URL}/Login", json={
            "CompanyDB": company_db,
            "UserName": user,
            "Password": password
        })
        self.session_id = resp.cookies.get("B1SESSION")

    def crear_journal_entry(self, entry: dict) -> str:
        """POST /JournalEntries — crea asiento contable."""
        return httpx.post(
            f"{self.BASE_URL}/JournalEntries",
            json=self._map_to_sap_format(entry),
            cookies={"B1SESSION": self.session_id}
        )

    def leer_chart_of_accounts(self) -> list[dict]:
        """GET /ChartOfAccounts — lee catálogo de cuentas."""
```

#### 2.3.4 QuickBooks Online (OAuth REST)

```python
class QuickBooksAdapter:
    """
    QuickBooks Online API v3.
    OAuth 2.0 con refresh tokens.
    Rate limit: 500 requests/minuto.
    """

    BASE_URL = "https://quickbooks.api.intuit.com/v3/company"

    def crear_journal_entry(self, entry: dict) -> str:
        """POST /{companyId}/journalentry — crea asiento contable."""
        qbo_format = {
            "Line": [
                {
                    "JournalEntryLineDetail": {
                        "PostingType": "Debit" if linea["debe"] > 0 else "Credit",
                        "AccountRef": {"value": self._map_cuenta_sat(linea["cuenta"])},
                        "Amount": linea["debe"] or linea["haber"]
                    },
                    "Description": linea["concepto"]
                }
                for linea in entry["lineas"]
            ],
            "TxnDate": entry["fecha"]
        }
        return httpx.post(
            f"{self.BASE_URL}/{self.company_id}/journalentry",
            json=qbo_format,
            headers={"Authorization": f"Bearer {self.access_token}"}
        )
```

#### 2.3.5 Odoo (JSON-RPC)

```python
class OdooAdapter:
    """
    Odoo JSON-RPC / REST API (15+).
    Localización MX: módulo l10n_mx.
    """

    def crear_poliza(self, poliza: dict) -> int:
        """Crea un account.move (asiento contable) en Odoo."""
        return self._call_kw(
            model="account.move",
            method="create",
            args=[{
                "move_type": "entry",
                "date": poliza["fecha"],
                "ref": poliza["concepto"],
                "line_ids": [
                    (0, 0, {
                        "account_id": self._map_cuenta_sat(linea["cuenta"]),
                        "debit": linea["debe"],
                        "credit": linea["haber"],
                        "name": linea["concepto"]
                    })
                    for linea in poliza["lineas"]
                ]
            }]
        )
```

### 2.4 Pólizas de Ajuste: Automáticas vs. Requieren Humano

| Póliza de Ajuste | ¿Automática? | Fundamento | Implementación |
|---|---|---|---|
| **Depreciación mensual** | ✅ AUTOMÁTICA | Fórmula fija: costo / vida útil / 12 | Calcula según LISR Art. 34-36 (porcentajes SAT por tipo de activo) |
| **Amortización intangibles** | ✅ AUTOMÁTICA | Fórmula fija: costo / vida útil / 12 | Máximo 10% anual (LISR Art. 41) |
| **Provisión aguinaldo** | ✅ AUTOMÁTICA | 15 días × salario diario / 12 meses | Basado en nómina registrada |
| **Provisión vacaciones + prima** | ✅ AUTOMÁTICA | Días × salario diario / 12 + 25% prima | Tabla LFT Art. 76-78 |
| **Provisión PTU** | ✅ AUTOMÁTICA | 10% utilidad fiscal / 12 | Solo en cierre mensual si hay utilidad |
| **Diferencias de cambio** | ✅ AUTOMÁTICA | TC Banco de México del día vs. TC del registro | API Banxico para TC oficial |
| **Ajuste por inflación** | ✅ AUTOMÁTICA | Factor INPC (Art. 44-45 LISR) | INPC mensual publicado por INEGI |
| **Ajuste inventarios** | ⚠️ SEMI-AUTOMÁTICA | Cálculo automático, validación humana | Valuación PEPS/Promedio, ajuste a NRV |
| **Valuación inversiones** | ⚠️ SEMI-AUTOMÁTICA | Datos de mercado automáticos, decisión humana | NIF C-9, requiere juicio contable |
| **Provisión incobrables** | ⚠️ SEMI-AUTOMÁTICA | % sobre cartera según antigüedad, validación | Art. 46 LISR: reglas específicas por antigüedad |
| **ISR diferido (DITL/DITR)** | ❌ REQUIERE HUMANO | Requiere juicio profesional sobre temporarias | NIF D-3 — complejidad alta |
| **Precios de transferencia** | ❌ REQUIERE HUMANO | Estudio documental, análisis funcional | LISR Art. 179-181 |
| **Consolidación fiscal** | ❌ REQUIERE HUMANO | Eliminación de intercompañías, participación | LISR Art. 61-71 |
| **Hechos posteriores** | ❌ REQUIERE HUMANO | Juicio sobre revelación y ajuste | NIF D-7 |

### 2.5 Checklist de Cierre que Genera el Agente

```json
{
  "periodo": "2026-07",
  "tenant_id": "despacho_abc",
  "rfc": "ABC123456XYZ",
  "estado": "en_cierre",
  "generated_at": "2026-07-26T08:00:00Z",
  "checklist": [
    {
      "step": 1,
      "nombre": "CFDIs procesados",
      "estado": "completado",
      "auto": true,
      "detalle": {
        "total_cfdis": 342,
        "procesados": 342,
        "errores": 0,
        "pendientes": 0
      }
    },
    {
      "step": 2,
      "nombre": "Conciliación bancaria",
      "estado": "completado",
      "auto": true,
      "detalle": {
        "movimientos_totales": 156,
        "conciliados": 149,
        "sin_match": 7,
        "porcentaje_match": 95.5,
        "alertas": [
          "Movimiento de $45,000 MXN del 15/jul sin CFDI asociado",
          "Transferencia entre cuentas propias no marcada"
        ]
      }
    },
    {
      "step": 3,
      "nombre": "Nóminas registradas",
      "estado": "completado",
      "auto": true,
      "detalle": {
        "quincena_1": {"empleados": 12, "total_neto": 156000, "registrada": true},
        "quincena_2": {"empleados": 12, "total_neto": 156000, "registrada": true}
      }
    },
    {
      "step": 4,
      "nombre": "Pólizas cuadradas",
      "estado": "completado",
      "auto": true,
      "detalle": {
        "total_polizas": 89,
        "cuadradas": 89,
        "desfase": 0
      }
    },
    {
      "step": 5,
      "nombre": "Pre-auditoría fiscal",
      "estado": "warning",
      "auto": true,
      "detalle": {
        "deducibles": 298,
        "no_deducibles": 12,
        "sin_cfdi": 3,
        "warnings": [
          "CFDI UUID abc123 cancelado — verificar sustituto",
          "RFC proveedor XYZ en lista 69-B (EFOS)",
          "Gasto personal detectado en cuenta 6020100 ($8,500)"
        ]
      }
    },
    {
      "step": 6,
      "nombre": "Depreciaciones del mes",
      "estado": "completado",
      "auto": true,
      "detalle": {
        "activos_depreciados": 15,
        "depreciacion_total": 42500.00,
        "póliza_generada": "DIARIO-2026-07-DEPR"
      }
    },
    {
      "step": 7,
      "nombre": "Provisiones laborales",
      "estado": "completado",
      "auto": true,
      "detalle": {
        "aguinaldo": 18000.00,
        "vacaciones": 12000.00,
        "prima_vacacional": 3000.00,
        "ptu_pendiente": 0
      }
    },
    {
      "step": 8,
      "nombre": "Diferencias de cambio",
      "estado": "completado",
      "auto": true,
      "detalle": {
        "cuentas_en_usd": 2,
        "tc_oficial": 17.25,
        "ajuste_total": -1200.00,
        "póliza_generada": "DIARIO-2026-07-FX"
      }
    },
    {
      "step": 9,
      "nombre": "Balanza de comprobación",
      "estado": "completado",
      "auto": true,
      "detalle": {
        "xml_generado": true,
        "total_debe": 2450000.00,
        "total_haber": 2450000.00,
        "cuadrada": true
      }
    },
    {
      "step": 10,
      "nombre": "Contabilidad electrónica",
      "estado": "completado",
      "auto": true,
      "detalle": {
        "paquete_generado": true,
        "incluye": ["catálogo", "balanza", "polizas"]
      }
    },
    {
      "step": 11,
      "nombre": "Borrador declaración IVA",
      "estado": "borrador",
      "auto": true,
      "detalle": {
        "iva_trasladado": 89000.00,
        "iva_acreditable": 45000.00,
        "iva_pagar": 44000.00,
        "deadline": "2026-08-17"
      }
    },
    {
      "step": 12,
      "nombre": "Borrador declaración ISR provisional",
      "estado": "borrador",
      "auto": true,
      "detalle": {
        "ingresos_acumulables": 556250.00,
        "deducciones_autorizadas": 412500.00,
        "utilidad_fiscal": 143750.00,
        "isr_pagar": 43125.00,
        "deadline": "2026-08-17"
      }
    },
    {
      "step": 13,
      "nombre": "Borrador DIOT",
      "estado": "borrador",
      "auto": true,
      "detalle": {
        "operaciones_terceros": 45,
        "total_operaciones": 281250.00,
        "iva_trasladado_total": 45000.00,
        "iva_acreditable_total": 28125.00
      }
    }
  ],
  "resumen": {
    "pasos_totales": 13,
    "pasos_completados": 10,
    "pasos_borrador": 3,
    "pasos_warning": 1,
    "pasos_pendientes": 0,
    "porcentaje_completado": 77,
    "requiere_aprobacion_humana": true,
    "deadline_aprobacion": "2026-07-30",
    "deadline_declaraciones": "2026-08-17"
  }
}
```

### 2.6 Datos de Input Necesarios del Despacho

| Dato | Formato | Frecuencia | Fuente | Obligatorio |
|---|---|---|---|---|
| **CFDIs (XML)** | XML CFDI 4.0 | Continuo | SAT vía PAC (Facturapi) | ✅ |
| **Estados de cuenta bancarios** | PDF, CSV, OFX | Mensual | Banco del cliente | ✅ |
| **Nómina (datos empleados)** | JSON/CSV | Quincenal | ERP nómina o input manual | ✅ |
| **Catálogo de cuentas del despacho** | XML/JSON | Una vez + cambios | CONTPAQi/Aspel/ERP | ✅ |
| **Reglas de clasificación propias** | JSON | Una vez + cambios | Input del contador | ✅ |
| **Configuración ERP** | JSON | Una vez | Despacho | ✅ |
| **Certificados FIEL/CSD** | .cer + .key + pwd | Una vez + renovación | Despacho | ✅ |
| **Nómina (CFDIs nómina)** | XML | Quincenal | ERP nómina | ✅ |
| **Inventarios (si aplica)** | CSV/JSON | Mensual | ERP | ⚠️ Opcional |
| **Contratos de arrendamiento** | PDF | Una vez + cambios | Despacho | ⚠️ Opcional |
| **Política de depreciación** | JSON | Anual | Despacho/contador | ⚠️ Opcional |

### 2.7 Estimación de Esfuerzo

| Fase | Semanas | Entregable | Equipo |
|---|---|---|---|
| **Fase 1: CloseManager core** | 3 semanas | Checklist engine, scheduler APScheduler, 10 pasos automáticos | 1 backend |
| **Fase 2: Integración ERPs** | 4 semanas | CONTPAQi + Aspel adapters (SQL + COM), SAP B1, QBO, Odoo | 1 backend |
| **Fase 3: Pólizas de ajuste automáticas** | 3 semanas | Depreciaciones, provisiones, FX, inflación | 1 backend + 1 contador |
| **Fase 4: Aprobación HITL + Dashboard** | 2 semanas | Checklist UI, approve/reject, notificaciones | 1 fullstack |
| **Fase 5: Testing + QA** | 2 semanas | Tests con datos reales de despacho piloto | 2 devs |
| **TOTAL** | **14 semanas** | | **2-3 ingenieros** |

**Dependencias:** Agente 3 (conciliación) para paso 2. Agente 2 (declaraciones) para pasos 11-13.

---

## 3. AGENTE 2: DECLARACIONES FISCALES AUTÓNOMAS

### 3.1 Descripción

Calcula, genera XML, firma con FIEL/CSD y prepara el envío de declaraciones fiscales al SAT: DIOT, IVA mensual, ISR provisional, IEPS, ISR anual.

**Benchmark global:** Tributi logra declaración de renta en 2 horas. Alegra Calcula hace IVA semi-automático.

### 3.2 Flujo Completo: CFDIs → Cálculo → XML → Firma → Envío

```
┌─────────────────────────────────────────────────────────────────────────┐
│              FLUJO DE DECLARACIÓN FISCAL                                │
│                                                                         │
│  PASO 1: RECOPILACIÓN DE DATOS                                         │
│  ├── CFDIs emitidos del mes (desde DB: tabla invoices WHERE tipo='E')  │
│  ├── CFDIs recibidos del mes (desde DB: WHERE tipo='I')                │
│  ├── Nóminas del mes (desde Agente Nómina)                             │
│  ├── Conciliación bancaria (desde Agente 3)                            │
│  └── Tipo de cambio del periodo (API Banco de México)                  │
│                                                                         │
│  PASO 2: CÁLCULO DE IMPUESTOS                                          │
│  ├── IVA:                                                                │
│  │   ├── IVA trasladado = Σ(CFDI emitidos × 16%)                      │
│  │   ├── IVA acreditable = Σ(CFDI recibidos × 16%) × proporción       │
│  │   │   proporción = ingresos_gravados / ingresos_totales              │
│  │   ├── IVA tasa 0% = Σ(CFDI con tasa 0%) → acreditable 100%        │
│  │   └── IVA a pagar = trasladado - acreditable                         │
│  ├── ISR provisional:                                                    │
│  │   ├── PM: Utilidad fiscal = ingresos - deducciones - PTU proporcional│
│  │   │   ISR = utilidad_fiscal × 30%                                    │
│  │   ├── PF: Según tabla Art. 96 o coeficiente Art. 14                  │
│  │   └── Restar pagos provisionales anteriores                          │
│  ├── IEPS (si aplica):                                                   │
│  │   ├── Identificar CFDIs con productos IEPS (bebidas, tabaco, etc.)   │
│  │   └── Calcular según tasa/tarifa por producto                        │
│  └── DIOT:                                                               │
│      ├── Agrupar por RFC proveedor/cliente                               │
│      ├── Tipo de operación (03=gravada 16%, 06=tasa 0%, etc.)           │
│      └── IVA trasladado/acreditable por tercero                          │
│                                                                         │
│  PASO 3: GENERACIÓN DE XML                                              │
│  ├── Generar XML conforme Anexo 24 RMF                                  │
│  ├── Validar contra XSD del SAT                                         │
│  └── Incluir: RFC, periodo, montos, catálogos SAT                       │
│                                                                         │
│  PASO 4: FIRMA DIGITAL (FIEL/CSD)                                      │
│  ├── Cargar certificado .cer + llave .key + contraseña                  │
│  ├── Firmar XML con FIEL (para declaraciones: FIEL, no CSD)            │
│  ├── Sellar con sello digital (SHA-256 + RSA)                          │
│  └── Agregar cadena original + sello al XML                             │
│                                                                         │
│  PASO 5: ENVÍO AL SAT                                                   │
│  ├── DIOT: Portal web SAT (formato TXT delimitado por pipes)           │
│  │   └── Opción: upload manual o scraping del portal                   │
│  ├── IVA/ISR provisional: DeclaraSAT o portal web                      │
│  │   └── Requiere FIEL para declaraciones con saldo a favor            │
│  └── NOTA: El SAT NO tiene API REST para declaraciones                 │
│      └── Opciones:                                                      │
│          a) Generar archivo listo para upload manual                    │
│          b) Selenium/Playwright sobre portal SAT (frágil)               │
│          c) Integración con software del despacho (CONTPAQi declara)    │
│                                                                         │
│  PASO 6: NOTIFICACIÓN                                                   │
│  ├── Email al contador: "Declaración lista para revisar"                │
│  ├── Adjuntar borrador PDF + XML + línea captura                       │
│  └── WhatsApp: recordatorio deadline día 17                             │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.3 Declaraciones Cubiertas

| Declaración | Periodicidad | Deadline | Fundamento | Autonomía |
|---|---|---|---|---|
| **DIOT** | Mensual | Día 17 mes siguiente | RMF 2.7.1.1 | ✅ Generación 100% autónoma. Envío requiere validación humana |
| **IVA mensual** | Mensual | Día 17 mes siguiente | LIVA Art. 5 | ✅ Cálculo autónomo. Envío requiere FIEL |
| **ISR provisional PM** | Mensual | Día 17 mes siguiente | LISR Art. 14 | ✅ Cálculo autónomo. Envío requiere FIEL |
| **ISR provisional PF** | Mensual | Día 17 mes siguiente | LISR Art. 116 | ✅ Cálculo autónomo. Envío requiere FIEL |
| **IEPS mensual** | Mensual | Día 17 mes siguiente | Ley IEPS | ⚠️ Solo si hay productos IEPS |
| **ISR anual PM** | Anual | 31 de marzo | LISR Art. 9 | ✅ Cálculo autónomo. Requiere revisión contador |
| **ISR anual PF** | Anual | 30 de abril | LISR Art. 150 | ✅ Cálculo autónomo. Requiere revisión contador |
| **DIM** (operaciones extranjero) | Anual | 15 de febrero | CFF Art. 76 | ⚠️ Requiere datos específicos |
| **Constancia retenciones** | Anual | 28 de febrero | CFF Art. 99 | ✅ Generación automática |

### 3.4 Autenticación SAT con FIEL/CSD

```python
from lxml import etree
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
import base64

class FirmaFIEL:
    """
    Firma digital con FIEL (e.firma) del SAT.
    Componentes: certificado X.509 (.cer), llave privada (.key), contraseña
    """

    def __init__(self, cer_path: str, key_path: str, password: str):
        # Cargar certificado
        with open(cer_path, 'rb') as f:
            self.certificate = f.read()

        # Cargar llave privada (formato DER, protegida con contraseña)
        with open(key_path, 'rb') as f:
            key_data = f.read()

        # Decodificar PKCS#8 encrypted private key
        self.private_key = pkcs12.load_key_and_certificates(
            key_data, password.encode()
        )

    def generar_cadena_original(self, xml_data: bytes) -> str:
        """
        Genera la cadena original del comprobante fiscal.
        Usa el XSLT del SAT (cadenaoriginal_4_0.xslt).
        """
        xslt_path = "sat_templates/cadenaoriginal_4_0.xslt"
        xslt = etree.parse(xslt_path)
        transform = etree.XSLT(xslt)
        result = transform(etree.fromstring(xml_data))
        return str(result)

    def firmar(self, xml_data: bytes) -> bytes:
        """
        Firma el XML con la FIEL.
        1. Genera cadena original
        2. Calcula SHA-256 de la cadena
        3. Firma con RSA-SHA256
        4. Agrega sello al XML
        """
        cadena = self.generar_cadena_original(xml_data)

        # SHA-256 hash
        digest = hashes.Hash(hashes.SHA256())
        digest.update(cadena.encode('utf-8'))
        hash_value = digest.finalize()

        # RSA-SHA256 signature
        sello = self.private_key.sign(
            hash_value,
            padding.PKCS1v15(),
            hashes.SHA256()
        )

        return base64.b64encode(sello)

    def sellar_declaracion(self, xml_declaracion: bytes) -> bytes:
        """Sella una declaración fiscal (DIOT, IVA, ISR) con FIEL."""
        sello = self.firmar(xml_declaracion)

        # Insertar sello en el XML
        tree = etree.fromstring(xml_declaracion)
        tree.set('Sello', sello.decode())
        tree.set('Certificado', base64.b64encode(self.certificate).decode())
        # NumCert es los últimos 20 dígitos del número de serie
        serial = self._get_certificate_serial()
        tree.set('NoCertificado', serial)

        return etree.tostring(tree, xml_declaration=True, encoding='UTF-8')
```

**Formato DIOT (TXT delimitado por pipes):**
```
|RFC|TipoOperacion|TipoTercero|TipoDoc|Moneda|TipoCambio|NumRegIdTrib|Fecha|RFCProv|NombreProv|IVA_Trasladado|IVA_Acreditable|BaseTasa16|BaseTasa0|BaseExento|
```

### 3.5 Errores que Causan Rechazo SAT y Prevención

| # | Error | Causa | Prevención en Agente |
|---|---|---|---|
| 1 | **UUID no válido** | CFDI cancelado o no registrado | Validar cada UUID contra el PAC antes de incluir en declaración |
| 2 | **RFC incorrecto** | Error de captura, homoclave mal | Validar RFC con dígito verificador (algoritmo Art. 23 CFF) + validar contra Facturapi |
| 3 | **Periodo incorrecto** | Mes/año fuera de rango | Validar que el periodo esté dentro del ejercicio fiscal actual |
| 4 | **Base cero en pago provisional** | No se determinó utilidad fiscal | Verificar que haya ingresos y deducciones > 0; si pérdida fiscal, generar con coeficiente |
| 5 | **DIOT con omisiones** | CFDIs no incluidos | Cruce automático: CFDIs en DB vs. DIOT generada — alertar diferencias |
| 6 | **Tipo de cambio incorrecto** | TC del día equivocado | Usar siempre TC oficial Banco de México (API pública) del último día del mes |
| 7 | **Doble declaración** | Presentar 2 veces | Verificar si ya existe declaración del periodo en tabla `declarations` |
| 8 | **Firma FIEL/CSD expirada** | Certificado vencido | Verificar vigencia del certificado al inicio de cada ciclo de declaración |
| 9 | **Estructura XML inválida** | XML mal formado | Validar contra XSD del SAT antes de firmar |
| 10 | **Conceptos no deducibles** | Gastos personales mezclados | Filtro automático por catálogo de conceptos deducibles (Art. 26 LISR) |
| 11 | **IVA acreditable incorrecto** | Proporcionalidad mal calculada | Recalcular proporción: ingresos_gravados / ingresos_totales |
| 12 | **ISR en ceros** | Utilidad fiscal no determinada | Si hay ingresos, calcular utilidad; alertar si resultado es negativo (pérdida) |
| 13 | **Plazo vencido** | Se pasó el día 17 | Scheduler envía alertas día 10, 14 y 16 del mes siguiente |
| 14 | **Certificado sin vigencia** | CSD vencido (> 4 años) | Monitorear fecha de vencimiento, alertar 60 días antes |

### 3.6 Integración con Facturapi/FiscalAPI para Timbrado y Descarga Masiva

```python
class FacturapiClient:
    """Wrapper sobre Facturapi para operaciones del agente fiscal."""

    BASE = "https://www.facturapi.io/v2"

    def __init__(self, api_key: str):
        self.headers = {"Authorization": f"Bearer {api_key}"}

    def validar_rfc(self, rfc: str) -> dict:
        """Valida RFC contra el SAT."""
        resp = httpx.get(
            f"{self.BASE}/tools/validate_tax_id",
            params={"tax_id": rfc},
            headers=self.headers
        )
        return resp.json()
        # → {"legal_name": "...", "tax_system": "612", "status": "active"}

    def descargar_cfdis_recibidos(self, rfc: str, fecha_inicio: str, fecha_fin: str) -> list:
        """Descarga masiva de CFDIs recibidos."""
        # Facturapi abstrae el proceso del SAT (24-72 horas)
        resp = httpx.post(f"{self.BASE}/invoices/mass-download", json={
            "rfc": rfc,
            "type": "received",
            "start_date": fecha_inicio,
            "end_date": fecha_fin
        }, headers=self.headers)
        return resp.json()  # → {"id": "download_123", "status": "processing"}

    def verificar_cancelados(self, uuids: list[str]) -> dict:
        """Verifica si CFDIs han sido cancelados."""
        resultados = {}
        for uuid in uuids:
            resp = httpx.get(
                f"{self.BASE}/invoices/{uuid}",
                headers=self.headers
            )
            resultados[uuid] = resp.json().get("status") != "canceled"
        return resultados

class FiscalAPIClient:
    """Wrapper sobre FiscalAPI — alternativa a Facturapi."""

    BASE = "https://www.fiscalapi.com/api/v1"

    def __init__(self, api_key: str):
        self.headers = {"x-api-key": api_key, "Content-Type": "application/json"}

    def descargar_masiva(self, rfc: str, periodo: str) -> str:
        """Solicita descarga masiva de CFDIs."""
        resp = httpx.post(f"{self.BASE}/mass-download", json={
            "rfc": rfc,
            "period": periodo
        }, headers=self.headers)
        return resp.json()["id"]

    def consultar_estado_descarga(self, download_id: str) -> dict:
        resp = httpx.get(
            f"{self.BASE}/mass-download/{download_id}",
            headers=self.headers
        )
        return resp.json()
```

### 3.7 Estimación de Esfuerzo

| Fase | Semanas | Entregable | Equipo |
|---|---|---|---|
| **Fase 1: Motor de cálculo** | 3 semanas | IVA, ISR (PM+PF), IEPS, DIOT — cálculo completo | 1 backend + 1 contador |
| **Fase 2: Generación XML + DIOT TXT** | 2 semanas | XMLs conforme Anexo 24, validación XSD, formato DIOT | 1 backend |
| **Fase 3: Firma FIEL** | 2 semanas | Módulo de firma RSA-SHA256, sellado XML, validación certificados | 1 backend |
| **Fase 4: Facturapi/FiscalAPI integration** | 2 semanas | Validación RFC, descarga masiva, verificación cancelados | 1 backend |
| **Fase 5: Envío SAT + HITL** | 2 semanas | Generar archivos listos para envío, workflow de aprobación, notificaciones | 1 backend |
| **Fase 6: Testing con datos reales** | 3 semanas | Pruebas con 3+ despachos, edge cases, validación contador | 2 devs + 1 contador |
| **TOTAL** | **14 semanas** | | **2-3 ingenieros** |

**Dependencias:** Agente 1 (Close) para datos del periodo. Agente 5 (Bookkeeping) para CFDIs ya procesados.

---

## 4. AGENTE 3: CONCILIACIÓN BANCARIA INTELIGENTE

### 4.1 Descripción

Importa estados de cuenta bancarios mexicanos en múltiples formatos, los parsea, y ejecuta matching progresivo contra registros contables (CFDIs, pólizas).

**Benchmark global:** Numeric logra 90%+ de conciliación automática. ReconArt maneja millones de transacciones.

### 4.2 Importar Estados de Cuenta: Formatos Soportados

| Formato | Extensión | Parser | Bancos que lo usan | Ejemplo |
|---|---|---|---|---|
| **CSV** | .csv | `csv.DictReader` con delimitador configurable | Todos (exportado) | BBVA exporta CSV con columnas: Fecha, Descripción, Monto, Saldo |
| **OFX** | .ofx | `ofxparse` librería Python | Citibanamex, Scotiabank, algunos Banorte | `<OFX><BANKTRANLIST>...` |
| **QIF** | .qif | Parser custom (formato texto) | Banregio, algunos HSBC | `D01/07/2026\nT-1500.00\nPMercado Pago\n^` |
| **MT940** | .mt940 | `mt-940` librería Python | HSBC, Santander (formato SWIFT) | `:61:260715D1500,00NTRF...` |
| **PDF** | .pdf | `pdfplumber` + patterns regex | BBVA, Banorte, Santander, Citibanamex, Banregio, Scotiabank | Tablas extraídas con layout parsing |
| **Excel** | .xlsx | `openpyxl` | Algunos bancos ofrecen export | Sheet con movimientos |

### 4.3 Parseo de PDFs Bancarios Mexicanos

```python
import pdfplumber
import re
from dataclasses import dataclass
from typing import Optional

@dataclass
class MovimientoBancario:
    fecha: str
    descripcion: str
    referencia: Optional[str]
    cargo: Optional[float]
    abono: Optional[float]
    saldo: Optional[float]

class BancoParser:
    """Parser base para PDFs bancarios mexicanos."""

    def parse(self, pdf_path: str) -> list[MovimientoBancario]:
        raise NotImplementedError


class BBVAParser(BancoParser):
    """
    BBVA México — layout de estado de cuenta empresarial.
    Columnas: Fecha | Concepto/Descripción | Referencia | Abono | Cargo | Saldo
    """
    PATRON_FECHA = re.compile(r'\d{2}/\d{2}/\d{4}')
    PATRON_MONTO = re.compile(r'[\d,]+\.\d{2}')

    def parse(self, pdf_path: str) -> list[MovimientoBancario]:
        movimientos = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        if self._es_movimiento(row):
                            movimientos.append(self._parse_row(row))
        return movimientos

    def _es_movimiento(self, row: list) -> bool:
        return bool(row and row[0] and self.PATRON_FECHA.match(str(row[0]).strip()))

    def _parse_row(self, row: list) -> MovimientoBancario:
        return MovimientoBancario(
            fecha=row[0].strip(),
            descripcion=row[1].strip() if len(row) > 1 else "",
            referencia=row[2].strip() if len(row) > 2 else None,
            abono=self._parse_monto(row[3]) if len(row) > 3 else None,
            cargo=self._parse_monto(row[4]) if len(row) > 4 else None,
            saldo=self._parse_monto(row[5]) if len(row) > 5 else None,
        )

    def _parse_monto(self, texto: str) -> Optional[float]:
        if not texto or texto.strip() in ('', '-'):
            return None
        limpio = texto.replace(',', '').replace('$', '').strip()
        return float(limpio)


class BanorteParser(BancoParser):
    """
    Banorte — layout diferente al BBVA.
    Columnas: Fecha | Descripción | Referencia | Depósitos | Retiros | Saldo
    """
    # Implementación específica para Banorte


class SantanderParser(BancoParser):
    """Santander — formato con separadores de miles con punto."""
    # Nota: Santander usa punto como separador de miles y coma como decimal


class HSBCParser(BancoParser):
    """HSBC — ofrece MT940 y PDF."""
    # MT940 es preferido (formato estándar SWIFT)


class CitibanamexParser(BancoParser):
    """Citibanamex — formato PDF con layout específico."""
    # Citibanamex también ofrece OFX


class BanregioParser(BancoParser):
    """Banregio — PDF con formato regional."""
    # Formato QIF también disponible


class ScotiabankParser(BancoParser):
    """Scotiabank — PDF y Excel."""
    # Excel es preferido cuando está disponible


# Factory para seleccionar parser según banco
PARSER_REGISTRY = {
    "bbva": BBVAParser,
    "banorte": BanorteParser,
    "santander": SantanderParser,
    "hsbc": HSBCParser,
    "citibanamex": CitibanamexParser,
    "banregio": BanregioParser,
    "scotiabank": ScotiabankParser,
}

def get_parser(banco: str, formato: str) -> BancoParser:
    if formato in ('ofx', 'qif', 'mt940'):
        return UniversalParser(formato)  # Parsers por formato estándar
    return PARSER_REGISTRY[banco]()
```

### 4.4 Matching: Exacto → Fuzzy → Multi-línea → LLM

```python
from rapidfuzz import fuzz
from typing import Optional

class MatchingEngine:
    """
    Motor de conciliación bancaria multi-nivel.
    Nivel 1: Exacto (monto + fecha + referencia)
    Nivel 2: Fuzzy (monto ± 1% + fecha ± 2 días + descripción similar)
    Nivel 3: Multi-línea (un pago bancario cubre varios CFDIs)
    Nivel 4: LLM (razonamiento para casos ambiguos)
    """

    def match(
        self,
        movimientos: list[MovimientoBancario],
        registros: list[dict],
        umbral_fuzzy: int = 80
    ) -> list[dict]:
        """
        Ejecuta matching progresivo.
        Retorna lista de matches con score y tipo.
        """
        unmatched_movs = list(movimientos)
        unmatched_regs = list(registros)
        matches = []

        # NIVEL 1: MATCH EXACTO
        for mov in list(unmatched_movs):
            exacto = self._match_exacto(mov, unmatched_regs)
            if exacto:
                matches.append({
                    "movimiento": mov,
                    "registro": exacto,
                    "score": 100,
                    "tipo": "exacto"
                })
                unmatched_movs.remove(mov)
                unmatched_regs.remove(exacto)

        # NIVEL 2: MATCH FUZZY
        for mov in list(unmatched_movs):
            fuzzy = self._match_fuzzy(mov, unmatched_regs, umbral_fuzzy)
            if fuzzy:
                matches.append({
                    "movimiento": mov,
                    "registro": fuzzy["registro"],
                    "score": fuzzy["score"],
                    "tipo": "fuzzy"
                })
                unmatched_movs.remove(mov)
                unmatched_regs.remove(fuzzy["registro"])

        # NIVEL 3: MATCH MULTI-LÍNEA
        for mov in list(unmatched_movs):
            multi = self._match_multilinea(mov, unmatched_regs)
            if multi:
                matches.append({
                    "movimiento": mov,
                    "registros": multi["registros"],
                    "score": multi["score"],
                    "tipo": "multi_linea"
                })
                unmatched_movs.remove(mov)
                for r in multi["registros"]:
                    unmatched_regs.remove(r)

        # NIVEL 4: MATCH CON LLM (solo para movimientos > $1,000 sin match)
        for mov in list(unmatched_movs):
            if abs(mov.abono or mov.cargo or 0) >= 1000:
                llm_result = self._match_llm(mov, unmatched_regs)
                if llm_result and llm_result["confidence"] >= 0.7:
                    matches.append({
                        "movimiento": mov,
                        "registro": llm_result["registro"],
                        "score": int(llm_result["confidence"] * 100),
                        "tipo": "llm",
                        "razonamiento": llm_result["razonamiento"]
                    })

        return matches, unmatched_movs, unmatched_regs

    def _match_exacto(self, mov, registros) -> Optional[dict]:
        """
        Match exacto: monto idéntico + fecha idéntica + referencia contenida.
        """
        for reg in registros:
            monto_mov = mov.abono or -(mov.cargo or 0)
            if (abs(monto_mov - reg["monto"]) < 0.01 and
                mov.fecha == reg["fecha"] and
                (not mov.referencia or mov.referencia in str(reg.get("referencia", "")))):
                return reg
        return None

    def _match_fuzzy(self, mov, registros, umbral) -> Optional[dict]:
        """
        Match fuzzy:
        - Monto ± 1% (por comisiones bancarias)
        - Fecha ± 2 días
        - Descripción: fuzzy ratio > umbral
        """
        mejor = None
        mejor_score = 0

        for reg in registros:
            monto_mov = mov.abono or -(mov.cargo or 0)
            diff_monto = abs(monto_mov - reg["monto"]) / max(abs(reg["monto"]), 1)

            if diff_monto > 0.01:  # Más de 1% de diferencia
                continue

            # Score de descripción
            score_desc = fuzz.partial_ratio(
                mov.descripcion.lower(),
                reg.get("concepto", "").lower()
            )

            if score_desc >= umbral and score_desc > mejor_score:
                mejor_score = score_desc
                mejor = {"registro": reg, "score": score_desc}

        return mejor

    def _match_multilinea(self, mov, registros) -> Optional[dict]:
        """
        Un movimiento bancario puede cubrir varios CFDIs.
        Ejemplo: transferencia SPEI de $5,000 cubre 3 facturas ($2,000 + $1,500 + $1,500).
        Algoritmo: subset sum sobre registros pendientes del mismo RFC.
        """
        monto_mov = mov.abono or -(mov.cargo or 0)

        # Agrupar registros por RFC/proveedor
        # Buscar combinación que sume el monto (± 1%)
        # Usar programación dinámica para subset sum
        candidatos = [r for r in registros
                      if r.get("fecha") >= (mov.fecha or "")]  # Filtrar por fecha

        combo = self._subset_sum(candidatos, monto_mov, tolerance=0.01)
        if combo:
            return {"registros": combo, "score": 95}
        return None

    def _match_llm(self, mov, registros) -> Optional[dict]:
        """
        Usa LLM para resolver casos ambiguos.
        Envía el movimiento + candidatos al LLM y pide que razone.
        """
        prompt = f"""Eres un contador experto mexicano. Concilia este movimiento bancario:

Movimiento bancario:
- Fecha: {mov.fecha}
- Descripción: {mov.descripcion}
- Monto: ${mov.abono or mov.cargo:,.2f}
- Referencia: {mov.referencia or 'N/A'}

Registros contables pendientes:
{self._format_registros(registros[:20])}  # Max 20 candidatos

¿Cuál registro corresponde a este movimiento? Responde en JSON:
{{"registro_id": "...", "confidence": 0.0-1.0, "razonamiento": "..."}}
Si no hay match claro, responde: {{"registro_id": null, "confidence": 0, "razonamiento": "..."}}"""

        # Llamar al LLM
        # Parsear respuesta JSON
        # Retornar resultado
```

### 4.5 Partidas No Conciliadas: Reglas y Alertas

| Situación | Acción del Agente | Alerta |
|---|---|---|
| **Depósito sin CFDI emitido** | Marcar como "pendiente de identificar" | ⚠️ "Depósito de $X el día Y sin factura asociada — posible ingreso no declarado" |
| **Retiro sin CFDI recibido** | Marcar como "pendiente de identificar" | ⚠️ "Retiro de $X sin factura — verificar deducibilidad" |
| **Transferencia entre cuentas propias** | Identificar automáticamente (misma CLABE titular) | ✅ "Transferencia entre cuentas propias — excluida de conciliación fiscal" |
| **Comisión bancaria** | Clasificar como gasto bancario (6030200) | ℹ️ "Comisión bancaria de $X — gasto deducible" |
| **Depósito de préstamo** | Preguntar al usuario | ℹ️ "Depósito grande sin factura — ¿es préstamo, cobro o anticipo?" |
| **Depósito > ingresos declarados × 1.15** | Alerta inmediata (Art. 91 LISR) | 🔴 "ALERTA: Depósitos superan ingresos declarados — riesgo de discrepancia fiscal" |
| **CFDI cancelado pero pago registrado** | No conciliar, alertar | 🔴 "CFDI UUID cancelado — verificar si hay sustituto" |
| **Pago duplicado** | Marcar como duplicado | ⚠️ "Posible pago duplicado: mismo monto y proveedor en 24 horas" |
| **Movimiento sin identificar > $50,000** | Escalar a humano inmediatamente | 🔴 "Movimiento no identificado por $X — requiere revisión urgente" |

### 4.6 Integración SPEI para Verificación de Pagos

```python
class SPEIVerifier:
    """
    Verifica pagos SPEI contra el sistema de Banxico.
    No hay API directa de Banxico para consulta de SPEIs individuales.
    Alternativas:
    1. API bancaria del cliente (BBVA, Banorte, etc.)
    2. CEP (Comprobante Electrónico de Pago) — descargable del SPEI
    3. STP API para pagos enviados vía STP
    """

    def verificar_cep(self, clave_rastreo: str, fecha: str) -> dict:
        """
        Descarga el CEP del SPEI.
        URL: https://www.banxico.org.mx/cep/
        """
        # El CEP se puede descargar como PDF desde el portal de Banxico
        # o desde la API bancaria del banco emisor
        resp = httpx.post(
            "https://www.banxico.org.mx/cep/descarga.do",
            data={
                "claveRastreo": clave_rastreo,
                "fecha": fecha,
                "tipoCuentaOrdenante": 40,  # CLABE
                "tipoCuentaBeneficiario": 40,
                "institucionOrdenante": "000",  # Genérico
                "institucionBeneficiario": "000",
                "monto": "0"  # El SAT valida internamente
            }
        )
        return self._parse_cep(resp.content)

    def verificar_pago_proveedor(
        self,
        proveedor_rfc: str,
        monto: float,
        fecha_aprox: str
    ) -> Optional[dict]:
        """
        Busca en los movimientos bancarios si existe un SPEI
        que coincida con el pago al proveedor.
        """
        # Matching contra movimientos bancarios ya importados
        pass
```

### 4.7 Estimación de Esfuerzo

| Fase | Semanas | Entregable | Equipo |
|---|---|---|---|
| **Fase 1: Parsers de formato** | 3 semanas | CSV, OFX, QIF, MT940, PDF (7 bancos MX) | 1 backend |
| **Fase 2: Matching engine** | 3 semanas | Exacto + fuzzy + multi-línea + LLM | 1 backend |
| **Fase 3: Alertas y reglas fiscales** | 2 semanas | Detección discrepancia fiscal, EFOS, duplicados | 1 backend + 1 contador |
| **Fase 4: SPEI verification** | 1 semana | Verificación CEP, matching contra movimientos | 1 backend |
| **Fase 5: Testing con PDFs reales** | 3 semanas | Parsers probados con estados de cuenta reales de 5+ bancos | 2 devs |
| **TOTAL** | **12 semanas** | | **2 ingenieros** |

**Dependencias:** Independiente en fase 1-2. Agente 4 (AP/AR) consume sus resultados.

---

## 5. AGENTE 4: AP/AR END-TO-END

### 5.1 Descripción

Gestiona cuentas por pagar (AP) y por cobrar (AR) de forma automatizada: desde la recepción de un CFDI hasta el pago/conciliación, pasando por OCR, validación, registro, aging y cobranza.

**Benchmark global:** Vic.ai logra 85% no-touch rate. Stampli automatiza 87%.

### 5.2 Flujo AP: Email → OCR → Validación CFDI → Registro → Aging → Pago SPEI

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    FLUJO ACCOUNTS PAYABLE (AP)                          │
│                                                                         │
│  PASO 1: RECEPCIÓN DE FACTURAS                                         │
│  ├── Opción A: Descarga masiva de CFDIs del SAT vía Facturapi          │
│  │   └── Facturapi.download_invoices(rfc, fecha_inicio, fecha_fin)     │
│  ├── Opción B: Recepción por email (proveedor envía XML adjunto)        │
│  │   └── IMAP polling + extracción de XML adjuntos                     │
│  └── Opción C: Upload manual del despacho                              │
│      └── API endpoint: POST /api/v1/ap/upload-cfdis                    │
│                                                                         │
│  PASO 2: VALIDACIÓN DEL CFDI                                           │
│  ├── Parsear XML (pipeline CFDI existente)                              │
│  ├── Validar estructura contra XSD SAT                                  │
│  ├── Verificar UUID contra SAT (no cancelado)                           │
│  ├── Validar RFC del emisor contra padrón SAT                           │
│  ├── Verificar que NO esté en lista 69-B (EFOS)                        │
│  ├── Validar que subtotal + IVA = total                                  │
│  └── Verificar que el RFC receptor coincida con el contribuyente        │
│                                                                         │
│  PASO 3: CLASIFICACIÓN                                                 │
│  ├── ML: Clasificar según catálogo de cuentas del contribuyente         │
│  │   └── Modelo entrenado (scikit-learn) con historial de clasificación │
│  ├── Reglas: Aplicar reglas contables (AccountingRulesEngine)           │
│  └── LLM: Para categorías ambiguas o nuevas                             │
│                                                                         │
│  PASO 4: REGISTRO EN ERP                                               │
│  ├── Generar póliza contable (cargo gasto + IVA acreditable, abono prov)│
│  ├── Validar cuadratura (debe == haber)                                 │
│  ├── Registrar en ERP vía IntegrationHub                                │
│  └── Registrar en tabla ap_invoices                                     │
│                                                                         │
│  PASO 5: AGING Y PROGRAMACIÓN DE PAGO                                  │
│  ├── Calcular fecha de vencimiento (NET 30, NET 60, según política)    │
│  ├── Asignar aging bucket: 0-30, 31-60, 61-90, 90+ días               │
│  ├── Programar pago según política del despacho                         │
│  └── Alertar cuando factura está próxima a vencer (7 días antes)       │
│                                                                         │
│  PASO 6: EJECUCIÓN DE PAGO                                             │
│  ├── Generar orden de pago SPEI                                         │
│  │   ├── Validar CLABE del proveedor                                    │
│  │   ├── Calcular monto (factura - retenciones si aplica)              │
│  │   └── Enviar vía STP o API bancaria                                  │
│  ├── Para pagos internacionales: validación Art. 178-179 LISR          │
│  │   └── Retención ISR a extranjeros (15%-40%)                         │
│  └── Registrar pago + generar complemento de pago (Art. 29-A fracc. VII)│
│                                                                         │
│  PASO 7: CONCILIACIÓN POST-PAGO                                        │
│  ├── Esperar movimiento bancario de salida                              │
│  ├── Match automático contra orden de pago                              │
│  ├── Actualizar estado AP: "pagada"                                     │
│  └── Generar CFDI complemento de pago si es necesario (PPD)            │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.3 Flujo AR: Factura → Cobro → Complemento Pago → Conciliación

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    FLUJO ACCOUNTS RECEIVABLE (AR)                       │
│                                                                         │
│  PASO 1: DETECCIÓN DE FACTURAS EMITIDAS                                │
│  ├── CFDIs de tipo "I" (Ingreso) emitidos por el contribuyente         │
│  ├── Método de pago = "PPD" (parcialidades/diferido) → requiere seguim.│
│  └── Método de pago = "PUE" (una sola exhibición) → esperar cobro      │
│                                                                         │
│  PASO 2: TRACKING DE COBROS                                            │
│  ├── Monitorear depósitos bancarios (Agente 3)                          │
│  ├── Match automático: depósito ↔ factura emitida                       │
│  ├── Para facturas PPD: generar complemento de pago por cada parcialidad│
│  │   └── Plazo: 5 días naturales siguientes al pago (Art. 29-A fracc.) │
│  └── Detectar sobrepagos/abonos a cuenta                                │
│                                                                         │
│  PASO 3: COMPLEMENTO DE PAGO                                           │
│  ├── Si la factura es PPD:                                              │
│  │   ├── Timbrar complemento de pago vía Facturapi                      │
│  │   │   └── POST /v2/invoices con tipo = "P" (Pago)                   │
│  │   ├── Relacionar con UUID de la factura original                     │
│  │   └── Enviar complemento al cliente por email                        │
│  └── Si la factura es PUE: solo registrar el cobro                      │
│                                                                         │
│  PASO 4: AGING DE CUENTAS POR COBRAR                                   │
│  ├── Clasificar por antigüedad: 0-30, 31-60, 61-90, 90+ días           │
│  ├── Generar reporte de aging semanal                                   │
│  └── Calcular provisión para cuentas incobrables (Art. 46 LISR)        │
│                                                                         │
│  PASO 5: COBRANZA AUTOMATIZADA                                         │
│  ├── Secuencia de recordatorios (services/collections.py existente):    │
│  │   ├── Día 1 post-vencimiento: email amistoso                        │
│  │   ├── Día 7: email formal + WhatsApp                                │
│  │   ├── Día 15: email de segundo aviso                                │
│  │   ├── Día 30: llamada programada + email final                      │
│  │   └── Día 60: escalar a cobranza humana / legal                     │
│  ├── Integrar con WhatsApp Business API para recordatorios              │
│  └── Generar reporte de efectividad de cobranza                         │
│                                                                         │
│  PASO 6: NOTAS DE CRÉDITO Y DEVOLUCIONES                               │
│  ├── Si cliente solicita devolución:                                    │
│  │   ├── Verificar que la factura original esté vigente                 │
│  │   ├── Timbrar nota de crédito (CFDI tipo "E" - Egreso)              │
│  │   ├── Referenciar UUID del CFDI original                             │
│  │   └── Registrar reverso en contabilidad                              │
│  ├── Si hay descuento por volumen:                                      │
│  │   └── Timbrar nota de crédito con concepto "Bonificación"           │
│  └── Actualizar DIOT: operaciones de crédito (tipo operación)          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.4 Notas de Crédito, Devoluciones, Retenciones

```python
class NotaCreditoProcessor:
    """Procesamiento de notas de crédito y devoluciones."""

    def crear_nota_credito(
        self,
        cfdi_original_uuid: str,
        monto: float,
        concepto: str,
        tipo: str  # "devolucion", "descuento", "bonificacion"
    ) -> dict:
        """
        Genera y timbra una nota de crédito (CFDI tipo E).
        Referencia: LISR Art. 25 fracc. I y II / CFF Art. 29
        Regla RMF 2.7.1.37
        """
        # 1. Verificar que el CFDI original no esté cancelado
        original = self.facturapi.get_invoice(cfdi_original_uuid)

        # 2. Crear CFDI tipo E (Egreso) con referencia al original
        nota = self.facturapi.create_invoice({
            "type": "E",  # Egreso
            "related_documents": [{
                "id": cfdi_original_uuid,
                "relationship": "01"  # Nota de crédito
            }],
            "items": [{
                "description": concepto,
                "product_key": "84111506",  # Servicios de facturación
                "quantity": 1,
                "price": monto
            }]
        })

        # 3. Registrar reverso contable
        self.accounting_rules_engine.generar_reverso(
            uuid_original=cfdi_original_uuid,
            uuid_nota=nota["id"],
            monto=monto
        )

        return nota


class RetencionesProcessor:
    """Procesamiento de retenciones de ISR a proveedores."""

    RETENCIONES = {
        "arrendamiento_pf": {
            "tasa": 0.10,  # 10%
            "fundamento": "LISR Art. 94 fracc. III",
            "aplica": "PF arrendadora"
        },
        "honorarios_pf": {
            "tasa": "tabla_art_96",  # Tabla progresiva
            "fundamento": "LISR Art. 94 fracc. II",
            "aplica": "PF prestadora de servicios"
        },
        "servicios_profesionales_pf": {
            "tasa": 0.10,  # 10% sobre ingresos brutos
            "fundamento": "LISR Art. 100",
            "aplica": "PF Actividades Empresariales"
        },
        "regalías_nacional": {
            "tasa": 0.25,  # 25%
            "fundamento": "LISR Art. 178 fracc. I",
            "aplica": "Regalías a residentes nacionales"
        },
        "regalías_extranjero": {
            "tasa": 0.40,  # 40%
            "fundamento": "LISR Art. 178 fracc. I",
            "aplica": "Regalías a residentes extranjeros"
        },
        "subcontratacion_laboral": {
            "tasa": 0.06,  # 6%
            "fundamento": "LISR Art. 12 fracc. I (reforma 2021)",
            "aplica": "Subcontratación laboral"
        }
    }

    def calcular_retencion(
        self,
        proveedor_rfc: str,
        tipo_servicio: str,
        monto_factura: float
    ) -> dict:
        """
        Calcula retención de ISR según tipo de servicio y régimen del proveedor.
        """
        # 1. Validar RFC del proveedor y obtener régimen
        proveedor = self.facturapi.validate_tax_id(proveedor_rfc)

        # 2. Determinar si es PF o PM
        es_pf = len(proveedor_rfc) == 13  # PF tiene 13 caracteres, PM tiene 12

        if not es_pf:
            return {"retencion": 0, "motivo": "PM — no aplica retención"}  # Simplificado

        # 3. Calcular según tipo de servicio
        config = self.RETENCIONES.get(tipo_servicio)
        if not config:
            return {"retencion": 0, "motivo": "Tipo de servicio no sujeto a retención"}

        if config["tasa"] == "tabla_art_96":
            retencion = self._calcular_tabla_art96(monto_factura)
        else:
            retencion = monto_factura * config["tasa"]

        return {
            "retencion": round(retencion, 2),
            "tasa": config["tasa"],
            "fundamento": config["fundamento"],
            "monto_neto": round(monto_factura - retencion, 2)
        }
```

### 5.5 Integración SPEI (Banxico) + Conekta + Stripe

```python
class SPEIPaymentProcessor:
    """Envío de pagos SPEI vía STP."""

    STP_BASE = "https://services.stpmex.com"

    def enviar_pago(self, orden: dict) -> dict:
        """
        Envía transferencia SPEI vía STP.
        Requiere: CLABE ordenante, CLABE beneficiario, monto, concepto.
        """
        payload = {
            "claveRastreo": orden["clave_rastreo"],
            "conceptoPago": orden["concepto"],
            "cuentaBeneficiario": orden["clabe_beneficiario"],
            "cuentaOrdenante": orden["clabe_ordenante"],
            "empresa": orden["empresa"],
            "institucionContraparte": orden["institucion_beneficiario"],  # Clave SPEI
            "institucionOperante": orden["institucion_ordenante"],
            "monto": orden["monto"],
            "nombreBeneficiario": orden["nombre_beneficiario"],
            "nombreOrdenante": orden["nombre_ordenante"],
            "rfcCurpBeneficiario": orden["rfc_beneficiario"],
            "rfcCurpOrdenante": orden["rfc_ordenante"],
            "tipoCuentaBeneficiario": 40,  # CLABE
            "tipoCuentaOrdenante": 40,
            "tipoPago": 1
        }

        resp = httpx.post(
            f"{self.STP_BASE}/ordenPago",
            json=payload,
            headers={"Authorization": f"Bearer {self.stp_token}"}
        )
        return resp.json()

    def consultar_estado(self, clave_rastreo: str) -> dict:
        """Consulta el estado de una transferencia SPEI."""
        resp = httpx.get(
            f"{self.STP_BASE}/ordenPago/{clave_rastreo}",
            headers={"Authorization": f"Bearer {self.stp_token}"}
        )
        return resp.json()


class ConektaCobros:
    """Cobros vía Conekta para AR."""

    BASE = "https://api.conekta.io"

    def crear_cobro_spei(self, cliente: dict, monto: float) -> dict:
        """Crea una orden de cobro con SPEI como método de pago."""
        resp = httpx.post(f"{self.BASE}/orders", json={
            "currency": "MXN",
            "customer_info": {
                "name": cliente["nombre"],
                "email": cliente["email"],
                "phone": cliente["telefono"]
            },
            "line_items": [{
                "name": "Factura",
                "unit_price": int(monto * 100),  # En centavos
                "quantity": 1
            }],
            "charges": [{
                "payment_method": {
                    "type": "spei"
                }
            }]
        }, headers={
            "Authorization": f"Bearer {self.conekta_key}",
            "Accept": "application/vnd.conekta-v2.1.0+json"
        })
        return resp.json()

    def crear_cobro_oxxo(self, cliente: dict, monto: float) -> dict:
        """Crea referencia OXXO para cobro en efectivo."""
        # Similar al SPEI pero con type: "oxxo"
        pass
```

### 5.6 Dashboard Aging de Cuentas

```python
# Endpoint API para dashboard de aging
@app.get("/api/v1/apar/aging/{tenant_id}")
async def get_aging_report(tenant_id: str, tipo: str = "ar"):
    """
    Genera reporte de antigüedad de saldos.
    Buckets: 0-30, 31-60, 61-90, 90+ días
    """
    if tipo == "ar":
        query = """
            SELECT
                CASE
                    WHEN CURRENT_DATE - fecha_vencimiento <= 30 THEN '0-30'
                    WHEN CURRENT_DATE - fecha_vencimiento <= 60 THEN '31-60'
                    WHEN CURRENT_DATE - fecha_vencimiento <= 90 THEN '61-90'
                    ELSE '90+'
                END as bucket,
                COUNT(*) as facturas,
                SUM(monto - monto_pagado) as saldo_pendiente,
                AVG(CURRENT_DATE - fecha_vencimiento) as dias_promedio
            FROM ar_invoices
            WHERE tenant_id = :tenant_id AND estado NOT IN ('pagada', 'cancelada')
            GROUP BY bucket
            ORDER BY bucket
        """
    else:
        # Similar para AP

    return await db.execute(query, {"tenant_id": tenant_id})
```

### 5.7 Estimación de Esfuerzo

| Fase | Semanas | Entregable | Equipo |
|---|---|---|---|
| **Fase 1: AP pipeline** | 4 semanas | Recepción CFDI → validación → clasificación → registro ERP | 1 backend |
| **Fase 2: AR pipeline** | 3 semanas | Facturas emitidas → tracking cobros → complemento pago | 1 backend |
| **Fase 3: Aging + Cobranza** | 2 semanas | Reporte aging, secuencia de recordatorios, WhatsApp | 1 backend |
| **Fase 4: SPEI + Conekta** | 3 semanas | Pagos SPEI vía STP, cobros vía Conekta/OXXO | 1 backend |
| **Fase 5: Notas crédito + Retenciones** | 2 semanas | Notas de crédito, devoluciones, retenciones ISR proveedores | 1 backend + 1 contador |
| **Fase 6: Testing** | 2 semanas | Flujo end-to-end con datos reales | 2 devs |
| **TOTAL** | **16 semanas** | | **2-3 ingenieros** |

**Dependencias:** Agente 3 (conciliación) para matching de pagos. Agente 1 (Close) para integración en checklist.

---

## 6. AGENTE 5: BOOKKEEPING COMPLETO AUTÓNOMO

### 6.1 Descripción

El agente "paraguas" que orquesta todo el ciclo contable: desde la recepción de un CFDI hasta las declaraciones fiscales, pasando por clasificación, generación de pólizas, registro en ERP, conciliación, cierre y declaraciones.

**Benchmark global:** Docyt "Million Dollar Accountant", Zeni AI Accountant Agent, Bench (35,000+ clientes).

### 6.2 Flujo Completo: CFDI → Clasificación → Póliza → ERP → Conciliación → Cierre → Declaraciones

```
┌─────────────────────────────────────────────────────────────────────────┐
│              FLUJO BOOKKEEPING COMPLETO AUTÓNOMO                        │
│                                                                         │
│  [CFDI XML] ──────────────────────────────────────────────────────┐     │
│       │                                                           │     │
│       ▼                                                           │     │
│  ┌──────────────────┐                                             │     │
│  │ 1. PARSER CFDI   │  (existente: cfdi/parser.py)               │     │
│  │  Parse XML 4.0   │  Extrae: UUID, RFCs, conceptos, montos     │     │
│  └────────┬─────────┘                                             │     │
│           │                                                       │     │
│           ▼                                                       │     │
│  ┌──────────────────┐                                             │     │
│  │ 2. VALIDADOR     │  (existente: cfdi/validator.py)            │     │
│  │  XSD + UUID + RFC│  Valida estructura + contra SAT            │     │
│  └────────┬─────────┘                                             │     │
│           │                                                       │     │
│           ▼                                                       │     │
│  ┌──────────────────┐    ┌──────────────────┐                     │     │
│  │ 3. CLASIFICADOR  │───►│ Training Data    │                     │     │
│  │  ML + LLM + Reglas│   │ (scikit-learn)   │                     │     │
│  └────────┬─────────┘    └──────────────────┘                     │     │
│           │  categoría gasto + cuenta contable                     │     │
│           ▼                                                       │     │
│  ┌──────────────────┐                                             │     │
│  │ 4. REGLAS        │  (NUEVO: accounting_rules_engine.py)        │     │
│  │  CONTABLES       │  Categoría → cuenta cargo + abono           │     │
│  └────────┬─────────┘                                             │     │
│           │  asiento contable (póliza)                             │     │
│           ▼                                                       │     │
│  ┌──────────────────┐                                             │     │
│  │ 5. REGISTRO ERP  │  (existente: integrations/hub.py)          │     │
│  │  CONTPAQi/Aspel/ │  Postea póliza al ERP del despacho         │     │
│  │  SAP/QBO/Odoo    │                                             │     │
│  └────────┬─────────┘                                             │     │
│           │  evento: journal.entry.created                         │     │
│           ▼                                                       │     │
│  ┌──────────────────┐                                             │     │
│  │ 6. CONCILIACIÓN  │  (Agente 3)                                 │     │
│  │  BANCARIA        │  Match contra estados de cuenta             │     │
│  └────────┬─────────┘                                             │     │
│           │                                                       │     │
│           ▼                                                       │     │
│  ┌──────────────────┐                                             │     │
│  │ 7. AP/AR         │  (Agente 4)                                 │     │
│  │  TRACKING        │  Aging, cobros, pagos                       │     │
│  └────────┬─────────┘                                             │     │
│           │                                                       │     │
│           ▼                                                       │     │
│  ┌──────────────────┐                                             │     │
│  │ 8. CIERRE        │  (Agente 1)                                 │     │
│  │  MENSUAL         │  Checklist + ajustes + reportes             │     │
│  └────────┬─────────┘                                             │     │
│           │                                                       │     │
│           ▼                                                       │     │
│  ┌──────────────────┐                                             │     │
│  │ 9. DECLARACIONES │  (Agente 2)                                 │     │
│  │  FISCALES        │  IVA + ISR + DIOT → SAT                    │     │
│  └────────┬─────────┘                                             │     │
│           │                                                       │     │
│           ▼                                                       │     │
│  [LIBROS CERRADOS + DECLARACIONES ENVIADAS]                        │     │
└─────────────────────────────────────────────────────────────────────────┘
```

### 6.3 ML para Clasificación de CFDIs

```python
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline
from sklearn.model_selection import cross_val_score
import joblib
import numpy as np

class CFDIClassifier:
    """
    Clasificador ML para CFDIs → cuenta contable.
    Basado en scikit-learn con features textuales y numéricas.

    Training data necesaria:
    - Mínimo: 500 CFDIs clasificados manualmente por el despacho
    - Ideal: 2,000+ CFDIs de múltiples clientes
    - Distribución balanceada por categoría (evitar clases desbalanceadas)
    """

    def __init__(self, model_path: str = None):
        if model_path:
            self.model = joblib.load(model_path)
        else:
            self.model = Pipeline([
                ('features', CFDIFeatureExtractor()),
                ('classifier', GradientBoostingClassifier(
                    n_estimators=200,
                    max_depth=6,
                    min_samples_split=10,
                    random_state=42
                ))
            ])

    def train(self, cfdis: list[dict], labels: list[str]):
        """
        Entrena el modelo con CFDIs ya clasificados.

        Input:
        - cfdis: lista de dicts con campos del CFDI parseado
        - labels: categoría asignada por el contador

        Features:
        - Texto: descripción del concepto (TF-IDF)
        - Numéricos: subtotal, IVA, total, tasa IVA
        - Categóricos: tipo CFDI (I/E/T), régimen emisor, uso CFDI
        - Contextuales: RFC emisor (si es recurrente)
        """
        X = self._extract_features(cfdis)
        scores = cross_val_score(self.model, X, labels, cv=5, scoring='f1_macro')
        print(f"Cross-val F1: {np.mean(scores):.3f} ± {np.std(scores):.3f}")

        self.model.fit(X, labels)
        self._save_training_data(cfdis, labels)

    def predict(self, cfdi: dict) -> tuple[str, float]:
        """
        Predice la categoría y cuenta contable para un CFDI.

        Returns:
        - categoría: string de la categoría (ej: "servicios_profesionales")
        - confidence: 0.0 a 1.0
        """
        X = self._extract_features([cfdi])
        proba = self.model.predict_proba(X)[0]
        idx_max = np.argmax(proba)
        categoria = self.model.classes_[idx_max]
        confidence = proba[idx_max]

        return categoria, confidence

    def _extract_features(self, cfdis: list[dict]) -> np.ndarray:
        """Extrae features para el modelo."""
        features = []
        for cfdi in cfdis:
            features.append({
                "concepto_texto": cfdi.get("concepto", ""),
                "subtotal": cfdi.get("subtotal", 0),
                "iva": cfdi.get("iva", 0),
                "total": cfdi.get("total", 0),
                "tasa_iva": self._calc_tasa_iva(cfdi),
                "tipo_cfdi": cfdi.get("tipo", "I"),
                "uso_cfdi": cfdi.get("uso_cfdi", ""),
                "regimen_emisor": cfdi.get("regimen_emisor", ""),
                "es_recurrente": self._is_recurrent(cfdi),  # RFC ya visto antes
            })
        return pd.DataFrame(features)


# Features del extractor
class CFDIFeatureExtractor:
    """
    Features necesarias para clasificación:

    TEXTUALES (TF-IDF):
    - Descripción del concepto del CFDI
    - Nombre del emisor
    - Clave producto/servicio SAT

    NUMÉRICOS:
    - Subtotal
    - IVA
    - Total
    - Tasa IVA (0%, 16%, exento)
    - Número de conceptos en el CFDI

    CATEGÓRICOS (one-hot):
    - Tipo CFDI: I (Ingreso), E (Egreso), T (Traslado), P (Pago)
    - Uso CFDI: G01, G02, G03, I01, I02, etc.
    - Régimen fiscal del emisor: 601, 603, 605, 606, 612, etc.
    - Método de pago: PUE, PPD
    - Forma de pago: 01, 02, 03, 04, etc.

    CONTEXTUALES:
    - ¿Es proveedor recurrente? (mismo RFC visto > 3 veces)
    - ¿Clasificación anterior del mismo RFC?
    - Día de la semana / mes (patrones estacionales)
    """
    pass
```

### 6.4 Training Data Necesaria

| Requisito | Cantidad Mínima | Cantidad Ideal | Fuente |
|---|---|---|---|
| **CFDIs clasificados manualmente** | 500 | 2,000+ | Exportar de CONTPAQi/Aspel con sus pólizas |
| **Categorías balanceadas** | ≥ 20 ejemplos/categoría | ≥ 100/categoría | Balancear con oversampling si necesario |
| **Múltiples contribuyentes** | 3+ RFCs | 10+ RFCs | Diversificar giro empresarial |
| **Temporalidad** | 6+ meses de datos | 12+ meses | Capturar estacionalidad |
| **Edge cases etiquetados** | 50+ | 200+ | Casos ambiguos resueltos por contador |
| **CFDIs de tasa 0%** | 20+ | 50+ | Para no confundir con exentos |
| **CFDIs cancelados** | 30+ | 100+ | Para reconocer y no clasificar |

**Proceso de recolección de training data:**

```python
def recolectar_training_data(despacho_id: str) -> dict:
    """
    Recolecta CFDIs ya clasificados por el despacho como training data.

    Fuentes:
    1. CONTPAQi/Aspel: Leer pólizas + CFDIs asociados (UUID en póliza)
    2. Historial de procesamiento: CFDIs ya clasificados en la DB
    3. Input manual: Contador clasifica CFDIs nuevos vía dashboard

    Output: CSV/JSON listo para entrenar el modelo
    """
    # 1. Leer de ERP
    cfdis_erp = erp_adapter.leer_polizas_con_cfdis(periodo="2025-01", "2025-12")

    # 2. Leer de DB
    cfdis_db = db.get_classified_invoices(despacho_id)

    # 3. Merge y deduplicar
    dataset = merge_and_deduplicate(cfdis_erp, cfdis_db)

    # 4. Validar con contador
    # → Exportar CSV para revisión manual

    return dataset
```

### 6.5 Decisiones Autónomas vs. Aprobación Humana

| Decisión | ¿Autónoma? | Condición | Si falla |
|---|---|---|---|
| **Clasificar CFDI con confianza > 0.85** | ✅ SÍ | ML predice con alta confianza | Registrar automáticamente |
| **Clasificar CFDI con confianza 0.6-0.85** | ⚠️ SEMI | ML sugiere, humano confirma | Enviar a cola de revisión |
| **Clasificar CFDI con confianza < 0.6** | ❌ NO | Categoría nueva o ambigua | Escalar a contador |
| **Generar póliza de depreciación** | ✅ SÍ | Fórmula fija, datos conocidos | Auto-generada |
| **Generar póliza de provisión aguinaldo** | ✅ SÍ | Cálculo estándar | Auto-generada |
| **Registrar en ERP** | ✅ SÍ | Póliza ya validada y cuadrada | Auto-registro |
| **Conciliación bancaria > 90%** | ✅ SÍ | Matches de alta confianza | Auto-conciliar, alertar excepciones |
| **Conciliación bancaria < 90%** | ⚠️ SEMI | Muchas excepciones | Enviar reporte al contador |
| **Cerrar periodo contable** | ❌ NO | Requiere aprobación explícita | Checklist completo, esperar approve |
| **Enviar declaración al SAT** | ❌ NO | Requiere FIEL + aprobación | Borrador listo, contador firma y envía |
| **Programar pago SPEI** | ⚠️ SEMI | Dentro de política de pagos | Auto-programar, humano autoriza monto > $50K |
| **Timbrar complemento de pago** | ✅ SÍ | Pago ya registrado y conciliado | Auto-timbrar |
| **Emitir nota de crédito** | ❌ NO | Requiere validación del cliente | Sugerir al contador, esperar confirmación |
| **Provisión incobrables** | ⚠️ SEMI | Según reglas de antigüedad Art. 46 | Auto-calcular, contador valida |

### 6.6 Catálogo de Cuentas SAT como Base

```python
CATALOGO_CUENTAS_SAT = {
    # ACTIVO (1)
    "1020000": "Bancos",
    "1020100": "Bancos nacionales",
    "1020200": "Bancos extranjeros",
    "1050000": "Clientes",
    "1050100": "Clientes nacionales",
    "1050200": "Clientes extranjeros",
    "1080000": "Deudores diversos",
    "1100000": "Anticipos de clientes",
    "1130000": "Mercancías",
    "1500000": "Terrenos",
    "1520000": "Edificios",
    "1540000": "Maquinaria y equipo",
    "1560000": "Mobiliario y equipo de oficina",
    "1580000": "Equipo de transporte",
    "1600000": "Equipo de cómputo",
    "1900000": "Activo diferido",

    # PASIVO (2)
    "2010000": "Proveedores nacionales",
    "2020000": "Proveedores extranjeros",
    "2050000": "Cuentas por pagar a partes relacionadas",
    "2080000": "Acreedores diversos",
    "2600000": "Impuestos y derechos por pagar",
    "2600100": "ISR por pagar",
    "2600200": "IVA por pagar",
    "2600300": "IVA acreditable",
    "2600400": "IVA trasladado",
    "2600500": "ISR por retener (nómina)",
    "2670000": "Acreedores por pago de nómina",

    # CAPITAL (3)
    "3010000": "Capital social",
    "3040000": "Resultado de ejercicios anteriores",
    "3050000": "Resultado del ejercicio",

    # INGRESOS (4)
    "4010000": "Ventas",
    "4020000": "Devoluciones sobre ventas",
    "4080000": "Ingresos por servicios",
    "4100000": "Ingresos por arrendamiento",

    # COSTOS (5)
    "5010000": "Costo de lo vendido",
    "5020000": "Compras",

    # GASTOS (6)
    "6010100": "Sueldos y salarios",
    "6010200": "Sueldos y salarios (asimilados)",
    "6010300": "Sueldos y salarios (IMSS)",
    "6010400": "Sueldos y salarios (INFONAVIT)",
    "6010500": "Sueldos y salarios (SAR)",
    "6010600": "Sueldos y salarios (vacaciones)",
    "6010700": "Sueldos y salarios (prima vacacional)",
    "6010800": "Sueldos y salarios (aguinaldo)",
    "6010900": "Sueldos y salarios (PTU)",
    "6020100": "Servicios profesionales",
    "6020200": "Servicios administrativos",
    "6020300": "Servicios de mantenimiento",
    "6020400": "Rentas de inmuebles",
    "6020500": "Publicidad y propaganda",
    "6020600": "Gastos legales y jurídicos",
    "6020700": "Gastos de viaje y representación",
    "6030100": "Intereses bancarios",
    "6030200": "Comisiones bancarias",
    "6040100": "Pérdida por crédito incobrable",
    "6050100": "Pérdida cambiaria",
    "6070100": "Gastos por inflación",
}

# Mapeo de categorías CFDI → cuentas contables (reglas por defecto)
MAPEO_DEFAULT = {
    # (tipo_cfdi, categoria) → {cargo, abono, iva_cargo, iva_abono}
    ("I", "servicios_profesionales"): {
        "cargo": "6020100",   # Servicios profesionales
        "abono": "2010000",   # Proveedores nacionales
        "iva_cargo": "2600300"  # IVA acreditable
    },
    ("I", "renta_oficina"): {
        "cargo": "6020400",   # Rentas de inmuebles
        "abono": "2010000",
        "iva_cargo": "2600300"
    },
    ("I", "materia_prima"): {
        "cargo": "5010000",   # Costo de lo vendido
        "abono": "2010000",
        "iva_cargo": "2600300"
    },
    ("I", "papeleria"): {
        "cargo": "6020300",   # Servicios de mantenimiento (o gastos generales)
        "abono": "2010000",
        "iva_cargo": "2600300"
    },
    ("I", "publicidad"): {
        "cargo": "6020500",   # Publicidad y propaganda
        "abono": "2010000",
        "iva_cargo": "2600300"
    },
    ("I", "honorarios_legales"): {
        "cargo": "6020600",   # Gastos legales y jurídicos
        "abono": "2010000",
        "iva_cargo": "2600300"
    },
    ("I", "comision_bancaria"): {
        "cargo": "6030200",   # Comisiones bancarias
        "abono": "1020000",   # Bancos
        "iva_cargo": "2600300"
    },
    ("I", "intereses_bancarios"): {
        "cargo": "6030100",   # Intereses bancarios
        "abono": "1020000",
        "iva_cargo": None     # Intereses pueden no tener IVA
    },
    ("E", "venta_servicios"): {
        "cargo": "1050000",   # Clientes
        "abono": "4080000",   # Ingresos por servicios
        "iva_abono": "2600400"  # IVA trasladado
    },
    ("E", "venta_mercancia"): {
        "cargo": "1050000",
        "abono": "4010000",   # Ventas
        "iva_abono": "2600400"
    },
}
```

### 6.7 Estimación de Esfuerzo

| Fase | Semanas | Entregable | Equipo |
|---|---|---|---|
| **Fase 1: Motor de reglas contables** | 3 semanas | AccountingRulesEngine, mapeo categoría→cuenta, generación pólizas | 1 backend + 1 contador |
| **Fase 2: ML classifier** | 4 semanas | Entrenamiento modelo, feature extraction, pipeline de retraining | 1 ML engineer |
| **Fase 3: Orquestación end-to-end** | 3 semanas | Pipeline completo CFDI→póliza→ERP→conciliación→cierre→declaración | 1 backend |
| **Fase 4: Decisiones HITL** | 2 semanas | Framework de autonomía vs aprobación, umbrales configurables | 1 backend |
| **Fase 5: Dashboard + Training UI** | 3 semanas | UI para clasificar CFDIs, revisar pólizas, aprobar cierres | 1 fullstack |
| **Fase 6: Testing + Validación** | 3 semanas | Prueba con 3+ despachos piloto, calibración de umbrales | 2 devs + 1 contador |
| **TOTAL** | **18 semanas** | | **3-4 ingenieros** |

**Dependencias:** Integra TODOS los demás agentes. Es el orquestador final.

---

## 7. TIMELINE GLOBAL Y DEPENDENCIAS

### 7.1 Diagrama de Dependencias

```
SEMANA  1   2   3   4   5   6   7   8   9  10  11  12  13  14  15  16  17  18  19  20
        │   │   │   │   │   │   │   │   │   │   │   │   │   │   │   │   │   │   │   │

AGENTE 3 (Conciliación Bancaria) — 12 semanas
        ├───────────────────────────────────────────────┤
        │  F1: Parsers   │ F2: Matching │ F3: Alertas  │ F4: SPEI │ F5: Test│
        │    (3 sem)     │   (3 sem)    │   (2 sem)    │ (1 sem)  │(3 sem) │

AGENTE 2 (Declaraciones Fiscales) — 14 semanas
            ├───────────────────────────────────────────────────────────┤
            │ F1: Calc │ F2: XML │ F3: FIEL │ F4: PAC │ F5: Envío │ F6: Test│
            │ (3 sem)  │(2 sem)  │ (2 sem)  │(2 sem)  │ (2 sem)   │(3 sem) │

AGENTE 1 (Close Management) — 14 semanas
                ├───────────────────────────────────────────────────────┤
                │ F1: Core │ F2: ERPs │ F3: Ajustes │ F4: HITL │ F5: Test│
                │ (3 sem)  │ (4 sem)  │  (3 sem)    │ (2 sem)  │(2 sem) │
                                     ↑ DEP: Ag3 (conciliación)

AGENTE 4 (AP/AR) — 16 semanas
                            ├───────────────────────────────────────────────────────┤
                            │ F1: AP │ F2: AR │ F3: Aging │ F4: SPEI │ F5: NC │ F6: Test│
                            │(4 sem) │(3 sem) │ (2 sem)   │ (3 sem)  │(2 sem) │(2 sem)│
                            ↑ DEP: Ag3 (conciliación para matching)

AGENTE 5 (Bookkeeping) — 18 semanas
                                                    ├───────────────────────────────────────────────────────────┤
                                                    │ F1: Reglas │ F2: ML  │ F3: E2E │ F4: HITL │ F5: UI │ F6: Test│
                                                    │ (3 sem)    │(4 sem)  │ (3 sem) │ (2 sem)  │(3 sem) │(3 sem) │
                                                    ↑ DEP: Ag1 + Ag2 + Ag3 + Ag4
```

### 7.2 Timeline Consolidado (Equipo de 3-4 Ingenieros)

| Mes | Semanas | Entregable | Agentes |
|---|---|---|---|
| **Mes 1-2** | 1-8 | Infraestructura compartida (Event Bus, Celery, DB migrations) + Conciliación Bancaria (parsers + matching) + Inicio Declaraciones (motor cálculo) | Ag3, Ag2, Infra |
| **Mes 3** | 9-12 | Conciliación Bancaria MVP completa + Declaraciones (XML + FIEL) + Inicio Close Management | Ag3 ✅, Ag2, Ag1 |
| **Mes 4** | 13-16 | Close Management MVP + Declaraciones (PAC + envío) + Inicio AP/AR | Ag1, Ag2, Ag4 |
| **Mes 5** | 17-20 | AP/AR MVP + Close Management (ERPs) + Declaraciones MVP completa | Ag4, Ag1, Ag2 ✅ |
| **Mes 6** | 21-24 | AP/AR (SPEI + Conekta) + Inicio Bookkeeping (reglas + ML) | Ag4, Ag5 |
| **Mes 7-8** | 25-32 | Bookkeeping (ML + orquestación) + Close Management completa + AP/AR completa | Ag5, Ag1 ✅, Ag4 ✅ |
| **Mes 9** | 33-36 | Bookkeeping (HITL + UI) + Integración end-to-end | Ag5 |
| **Mes 10** | 37-40 | Bookkeeping completa + Testing global + Piloto con despachos | Ag5 ✅, Todos |

### 7.3 Secuencia Recomendada de Desarrollo

```
PRIORIDAD 1 (Meses 1-3):
  ├── Infraestructura: Event Bus, Celery workers, DB migrations
  ├── Agente 3 (Conciliación Bancaria): Independiente, alto impacto
  └── Agente 2 (Declaraciones): Motor de cálculo (base para otros)

PRIORIDAD 2 (Meses 3-5):
  ├── Agente 1 (Close Management): Integra conciliación + declaraciones
  └── Agente 4 (AP/AR): Integra conciliación, alto valor para despachos

PRIORIDAD 3 (Meses 5-10):
  └── Agente 5 (Bookkeeping): Orquestador final, integra todos los demás
```

---

## 8. MVP DE CADA AGENTE

### 8.1 Definición de MVP

**MVP = Lo mínimo que genera valor real para un despacho contable y permite validar el producto con clientes piloto.**

### 8.2 MVPs Específicos

| Agente | MVP | Qué incluye | Qué NO incluye | Valor para despacho |
|---|---|---|---|---|
| **1. Close Management** | Checklist automático + 5 ajustes básicos | Verificación CFDIs, conciliación check, depreciaciones, provisiones aguinaldo/vacaciones, balanza generada | Integración ERPs (todas), todos los ajustes, dictamen fiscal | Reduce cierre de 5 días a 2 días |
| **2. Declaraciones** | Cálculo IVA + ISR + DIOT automáticos | Motor de cálculo completo, generación XML, formato DIOT TXT | Firma FIEL automática, envío directo al SAT | Elimina 20 horas/mes de cálculo manual |
| **3. Conciliación Bancaria** | Parsing BBVA + Banorte + matching exacto + fuzzy | 2 parsers PDF, matching exacto y fuzzy, reporte de conciliación | 5 bancos restantes, multi-línea, LLM, SPEI | Elimina 10 horas/mes de conciliación manual |
| **4. AP/AR** | Recepción CFDI → clasificación → registro + aging report | Pipeline AP básico (desde Facturapi), aging AR/AP | SPEI payments, Cobranza automática, complementos pago | Reduce data entry de AP en 70% |
| **5. Bookkeeping** | Pipeline CFDI → reglas contables → póliza (sin ML) | Motor de reglas (sin ML), pólizas automáticas, registro DB | ML classifier, integración ERPs, orquestación completa | Reduce data entry contable en 60% |

### 8.3 MVP del Agente 5 como MVP Global

Si se debe elegir UN solo MVP que demuestre todo el valor:

**"Un CFDI entra → sale la póliza lista para el ERP + el borrador de declaración"**

```
INPUT:  XML CFDI 4.0 (recibido del SAT)
        │
        ▼
[Parser] → [Validador] → [Clasificador (reglas)] → [Motor contable] → [Póliza]
        │
OUTPUT: Póliza de diario con:
        - Cuenta cargo (gasto)
        - IVA acreditable
        - Cuenta abono (proveedor)
        - Cuadratura validada
        - Lista para registrar en CONTPAQi/Aspel
```

**Tiempo de desarrollo del MVP global: 6-8 semanas con 2 ingenieros.**

---

## 9. RIESGOS Y MITIGACIONES

### 9.1 Riesgos Técnicos

| # | Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|---|
| 1 | **CONTPAQi SDK COM no funciona en servidor Linux** | ALTA | ALTO | Usar SQL Server directo (pyodbc) como primario. COM como fallback solo para Windows. Docker con Wine como último recurso. |
| 2 | **PDFs bancarios con layout inconsistente entre sucursales** | MEDIA | MEDIO | Implementar parser con múltiples estrategias: tablas → regex → OCR fallback. Testing con PDFs de 3+ sucursales por banco. |
| 3 | **SAT cambia formato XML/XSD sin aviso** | BAJA | ALTO | Validar contra XSD al inicio de cada operación. Mantener XSD actualizados vía RSS del SAT. Fallback a versión anterior si falla. |
| 4 | **Facturapi/FiscalAPI rate limits** | MEDIA | BAJO | Implementar backoff exponencial. Batch de operaciones. Cache de consultas RFC. |
| 5 | **ML classifier con accuracy insuficiente (< 70%)** | MEDIA | ALTO | Iniciar con reglas hardcodeadas (sin ML). ML como capa adicional. Siempre tener "escalar a humano" como fallback. Re-entrenar mensualmente. |
| 6 | **FIEL/CSD expirados sin aviso** | MEDIA | ALTO | Monitorear vigencia de certificados. Alertas 60, 30 y 7 días antes. Nunca operar con certificado vencido. |
| 7 | **Race conditions en Celery workers** | BAJA | MEDIO | Usar locks distribuidos (Redis) para operaciones que modifican el mismo tenant. Idempotencia en todas las tareas. |
| 8 | **Multi-tenant data leakage** | BAJA | CRÍTICO | Row-level security en PostgreSQL. Middleware que inyecta tenant_id en todas las queries. Tests de aislamiento. |

### 9.2 Riesgos de Negocio

| # | Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|---|
| 1 | **Despachos no quieren compartir FIEL/CSD** | ALTA | ALTO | Ofrecer modo "solo borrador" (sin firma/envío). El agente calcula y genera XML, el contador firma manualmente. |
| 2 | **Reglas fiscales cambian con reforma** | MEDIA | ALTO | Motor de reglas externalizado en JSON/YAML (no hardcodeado). Proceso de actualización semanal con contador. |
| 3 | **Contadores desconfían de la automatización** | ALTA | ALTO | Modelo hybrid: AI propone, humano aprueba. Log de cada decisión. Empezar con tareas de bajo riesgo (conciliación) antes de declaraciones. |
| 4 | **Competencia de Alegra (ya en México)** | MEDIA | MEDIO | Diferenciación: agentes genuinamente autónomos vs. superficiales. Integración con ERPs existentes (Alegra reemplaza, Likida complementa). |
| 5 | **Costo de APIs (Facturapi, LLMs) come márgenes** | MEDIA | MEDIO | Facturapi: $0.60/timbre es bajo. LLMs: usar GPT-4o-mini para clasificación rutinaria, GPT-4o solo para casos ambiguos. Cache de respuestas LLM. |
| 6 | **Regulación SAT sobre IA en contabilidad** | BAJA | ALTO | El agente siempre deja audit trail. El contador humano firma y es responsable. El agente es herramienta, no autónomo legalmente. |

### 9.3 Riesgos Operativos

| # | Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|---|
| 1 | **Despacho piloto no proporciona datos limpios** | ALTA | MEDIO | Proceso de onboarding documentado. Checklist de datos requeridos. Período de gracia para limpieza de datos. |
| 2 | **SQL Server CONTPAQi offline / no accesible remotamente** | MEDIA | ALTO | Ofrecer agente local (Docker container en la máquina del despacho) que sincroniza con nube. |
| 3 | **Timeouts en web services SOAP del SAT** | ALTA | BAJO | Retry con backoff exponencial. Operaciones asíncronas (no bloquear UI). Cache de resultados. |

---

## 10. INFRAESTRUCTURA COMPARTIDA

### 10.1 Event Bus (Redis Streams)

```python
# b2b_ai/infra/event_bus.py

EVENTS = {
    # CFDI processing
    "cfdi.processed": {"tenant_id", "invoice_id", "categoria", "monto", "tipo"},
    "cfdi.batch.completed": {"tenant_id", "batch_id", "total", "procesados", "errores"},

    # Accounting
    "journal.entry.created": {"tenant_id", "poliza_id", "periodo", "total_debe", "total_haber"},
    "journal.entry.posted_erp": {"tenant_id", "poliza_id", "erp_poliza_id"},

    # Banking
    "bank.statement.uploaded": {"tenant_id", "bank", "movements_count"},
    "bank.match.completed": {"tenant_id", "matched", "unmatched", "confidence_avg"},

    # AP/AR
    "ap.invoice.received": {"tenant_id", "proveedor_rfc", "uuid", "monto"},
    "ap.payment.due": {"tenant_id", "proveedor_id", "factura_id", "fecha_vencimiento"},
    "ar.invoice.overdue": {"tenant_id", "cliente_id", "factura_id", "dias_vencido"},
    "ar.payment.received": {"tenant_id", "cliente_rfc", "monto", "factura_id"},

    # Close
    "close.checklist.step": {"tenant_id", "mes", "step", "status", "details"},
    "close.month.approved": {"tenant_id", "mes", "approved_by"},
    "close.month.rejected": {"tenant_id", "mes", "reason"},

    # Declarations
    "declaration.generated": {"tenant_id", "tipo", "periodo", "monto"},
    "declaration.submitted": {"tenant_id", "tipo", "periodo", "acuse"},
    "declaration.error": {"tenant_id", "tipo", "periodo", "error_code"},

    # Alerts
    "anomaly.detected": {"tenant_id", "tipo", "severidad", "descripcion"},
    "human.review.required": {"tenant_id", "entity_type", "entity_id", "reason"},
    "certificate.expiring": {"tenant_id", "rfc", "days_remaining"},
}
```

### 10.2 Celery Tasks

```python
# b2b_ai/infra/tasks.py

@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def task_process_cfdi_batch(self, tenant_id: str, xml_paths: list[str]):
    """Procesa un lote de CFDIs de forma asíncrona."""

@celery_app.task(bind=True, max_retries=2)
def task_generate_declaration(self, tenant_id: str, tipo: str, periodo: str):
    """Genera una declaración fiscal (IVA/ISR/DIOT)."""

@celery_app.task(bind=True)
def task_reconcile_bank(self, tenant_id: str, statement_path: str, bank: str):
    """Concilia un estado de cuenta bancario contra facturas."""

@celery_app.task(bind=True)
def task_run_close_checklist(self, tenant_id: str, mes: str):
    """Ejecuta el checklist de cierre mensual paso a paso."""

@celery_app.task(bind=True)
def task_generate_aging_report(self, tenant_id: str, tipo: str):
    """Genera reporte de antigüedad de saldos (AR o AP)."""

@celery_app.task(bind=True, max_retries=3)
def task_process_ap_invoice(self, tenant_id: str, cfdi_uuid: str):
    """Procesa una factura de AP: validar, clasificar, registrar."""

@celery_app.task(bind=True)
def task_send_payment_spei(self, tenant_id: str, payment_order: dict):
    """Envía un pago SPEI vía STP."""

@celery_app.task(bind=True)
def task_timbrar_complemento_pago(self, tenant_id: str, payment_data: dict):
    """Timbra un complemento de pago CFDI."""
```

### 10.3 Database Schema (Tablas Nuevas)

```sql
-- Ver archivo completo en ARQUITECTURA-5-AGENTES.md sección 5.2
-- Tablas principales:
-- accounting_rules    → Reglas CFDI → cuenta contable
-- journal_entries     → Asientos contables generados
-- declarations        → Declaraciones fiscales
-- close_periods       → Periodos de cierre
-- ar_invoices         → Facturas por cobrar
-- ap_invoices         → Facturas por pagar
-- event_log           → Log de eventos del bus
-- agent_state         → Estado de los agentes
-- ml_models           → Modelos ML versionados
-- ml_training_data    → Datos de entrenamiento
-- conciliation_sessions → Sesiones de conciliación
-- conciliation_matches → Matches de conciliación
```

---

## APÉNDICE A: ESTRUCTURA DE DIRECTORIOS

```
b2b_ai/
├── agents/
│   ├── __init__.py
│   ├── base.py                   # AgentBase (abstract)
│   ├── close_manager.py          # Agente 1: Close Management
│   ├── fiscal.py                 # Agente 2: Declaraciones Fiscales
│   ├── conciliation.py           # Agente 3: Conciliación Bancaria
│   ├── apar.py                   # Agente 4: AP/AR
│   └── bookkeeping.py            # Agente 5: Bookkeeping (orquestador)
├── services/
│   ├── accounting_rules_engine.py  # Motor de reglas contables
│   ├── declaration_engine.py       # Motor de declaraciones
│   ├── close_manager.py            # Close management scheduler
│   ├── apar_manager.py             # AP/AR pipeline
│   ├── ml_classifier.py            # Clasificador ML de CFDIs
│   ├── bank_parsers/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── bbva.py
│   │   ├── banorte.py
│   │   ├── santander.py
│   │   ├── hsbc.py
│   │   ├── citibanamex.py
│   │   ├── banregio.py
│   │   ├── scotiabank.py
│   │   └── universal.py           # OFX, QIF, MT940
│   ├── matching_engine.py          # Matching multi-nivel
│   ├── firma_fiel.py               # Firma FIEL/CSD
│   └── sat_submitter.py            # Envío al SAT
├── integrations/
│   ├── erp/
│   │   ├── contpaqi.py
│   │   ├── aspel.py
│   │   ├── sap_b1.py
│   │   ├── quickbooks.py
│   │   └── odoo.py
│   ├── pac/
│   │   ├── facturapi.py
│   │   └── fiscalapi.py
│   ├── payments/
│   │   ├── stp_spei.py
│   │   ├── conekta.py
│   │   └── stripe_mx.py
│   └── hub.py                      # IntegrationHub (existente)
├── infra/
│   ├── event_bus.py                # Redis Streams
│   ├── celery_app.py               # Celery config
│   ├── tasks.py                    # Celery tasks
│   ├── scheduler.py                # APScheduler
│   └── health.py                   # Health monitoring
├── db/
│   ├── models.py                   # SQLAlchemy models (extend)
│   ├── migrations/                 # Alembic migrations
│   └── multi_tenant.py             # Tenant isolation
├── api/
│   ├── routes/
│   │   ├── close.py
│   │   ├── declarations.py
│   │   ├── conciliation.py
│   │   ├── apar.py
│   │   └── bookkeeping.py
│   └── main.py                     # FastAPI app
├── notifications/                  # Existente
├── templates/
│   ├── sat/
│   │   ├── cadenaoriginal_4_0.xslt
│   │   ├── diot_formato.txt
│   │   ├── balanza_xsd/
│   │   └── polizas_xsd/
│   └── reports/
│       ├── checklist_cierre.html
│       ├── aging_report.html
│       └── declaracion_resumen.html
└── tests/
    ├── test_close_manager.py
    ├── test_declarations.py
    ├── test_conciliation.py
    ├── test_apar.py
    ├── test_bookkeeping.py
    ├── test_ml_classifier.py
    ├── test_bank_parsers.py
    └── fixtures/
        ├── cfdis_ejemplo/
        ├── estados_cuenta/
        └── training_data/
```

---

## APÉNDICE B: KPIs DE ÉXITO

| KPI | Target MVP | Target Producción | Benchmark Global |
|---|---|---|---|
| **CFDIs clasificados automáticamente** | 60% | 85% | Vic.ai: 85% |
| **Conciliación bancaria automática** | 70% | 90%+ | Numeric: 90%+ |
| **Cierre mensual automatizado** | 50% | 80%+ | Numeric: 90%+ |
| **Declaraciones calculadas correctamente** | 95% | 99% | — |
| **Pólizas cuadradas al primer intento** | 90% | 99% | — |
| **Tiempo de cierre mensual (por cliente)** | 3 días | 1 día | — |
| **Reducción de tiempo del contador** | 40% | 70% | Bench: 70 horas/mes |
| **Precisión matching bancario** | 85% | 95% | — |
| **Errores de declaración rechazados por SAT** | < 5% | < 1% | — |
| **No-touch rate AP** | 50% | 85% | Vic.ai: 85% |

---

## APÉNDICE C: GLOSARIO

| Término | Definición |
|---|---|
| **CFDI** | Comprobante Fiscal Digital por Internet — factura electrónica mexicana |
| **FIEL** | Firma Electrónica Avanzada (e.firma) — certificado X.509 del SAT |
| **CSD** | Certificado de Sello Digital — para timbrar CFDIs |
| **PAC** | Proveedor Autorizado de Certificación — timbra CFDIs ante el SAT |
| **DIOT** | Declaración Informativa de Operaciones con Terceros |
| **RFC** | Registro Federal de Contribuyentes |
| **CLABE** | Clave Bancaria Estandarizada (18 dígitos) |
| **SPEI** | Sistema de Pagos Electrónicos Interbancarios (Banxico) |
| **STP** | Sistema de Transferencias y Pagos — proveedor tecnológico SPEI |
| **EFOS** | Empresas Facturadoras de Operaciones Simuladas (lista 69-B) |
| **NIF** | Normas de Información Financiera (equivalente mexicano a IFRS) |
| **LISR** | Ley del Impuesto Sobre la Renta |
| **LIVA** | Ley del Impuesto al Valor Agregado |
| **CFF** | Código Fiscal de la Federación |
| **RMF** | Reglas de Miscelánea Fiscal |
| **HITL** | Human-In-The-Loop — intervención humana en decisiones del agente |
| **PPD** | Pago en Parcialidades o Diferido — método de pago CFDI |
| **PUE** | Pago en Una sola Exhibición — método de pago CFDI |
| **INPC** | Índice Nacional de Precios al Consumidor |

---

> **Documento generado como blueprint ejecutable.**
> **Última actualización:** Agosto 2026
> **Para actualizaciones de legislación fiscal:** Consultar siempre la Miscelánea Fiscal vigente y el portal del SAT.
