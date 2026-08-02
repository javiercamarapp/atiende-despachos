# Likida AI Enterprise — Guía de Demo

Demo lista para presentar a un prospecto con **un solo comando**:

```bash
cd B2B-AI-MVP/enterprise
.venv/bin/python scripts/demo_pilot.py
```

> Requiere Python 3.11 (usa el `.venv` del repo). El script es autocontenido
> (solo stdlib + `uvicorn` ya instalado) y no necesita configuración previa.

El script hace todo: puebla una base demo, levanta la API en
`http://localhost:8000`, recorre el pipeline completo y ejecuta 3 escenarios
comerciales con salida visual en terminal.

---

## Qué hace `scripts/demo_pilot.py`

### 1. Puebla la base demo (`scripts/demo_data/demo_pilot.db`)
Ejecuta `scripts/seed_demo.py` (determinista, `seed=42`): 3 despachos contables
(tenants), 15 clientes, 300 CFDIs, 150 transacciones bancarias (BBVA, Banorte,
Santander, HSBC), 30 nóminas y 15 documentos. La base se **regenera desde cero**
en cada corrida para una demo siempre consistente.

### 2. Levanta la API
FastAPI en `http://localhost:<puerto>` (por defecto 8000) con la base demo.
Credenciales demo automáticas:
- API key: `demo-key-likida-2026` (header `X-API-Key`)
- Tenant activo: `1` (Contadores Asociados del Bajío)
- OpenAPI docs: `http://localhost:8000/docs`

### 3. Escenarios

| Escenario | Endpoint | Qué demuestra |
|---|---|---|
| **S0 · Pipeline completo** | `POST /api/v1/pipeline/run` | Sube 5 CFDIs (emitidos + recibidos) y 6 movimientos bancarios y ejecuta CFDI → parse → bookkeeping (clasificación + pólizas + ERP) → conciliación bancaria real con el motor de conciliación. Muestra matches, tasa de conciliación y discrepancias. |
| **A · Procesamiento de CFDI** | `POST /api/v1/invoices/process` | Subida real multipart de un XML: validación fiscal (CFF), clasificación automática con confianza, póliza ERP y marcado de revisión humana cuando aplica. |
| **B · Nómina** | `POST /api/v1/payroll/calculate` | Cálculo de nómina completa: ISR (LISR), IMSS y neto a pagar para un empleado. |
| **C · Conciliación bancaria** | `POST /api/v1/reconcile/run` | Cruza los CFDIs del periodo contra el estado de cuenta (monto+fecha y referencia), reporta conciliados/pendientes y la tasa de conciliación. |

### 4. Apaga el servidor
Termina con un resumen y cierra el servidor automáticamente.

### Opciones

```bash
.venv/bin/python scripts/demo_pilot.py --port 8080     # puerto custom
.venv/bin/python scripts/demo_pilot.py --db /tmp/demo.db  # base custom
.venv/bin/python scripts/demo_pilot.py --host 0.0.0.0  # exponer en la red
```

---

## Datos de ejemplo (`scripts/demo_data/`)

Personalizables por prospecto sin tocar código:

| Carpeta | Contenido |
|---|---|
| `cfdi/emitido_*.xml` | 5 CFDIs emitidos (el despacho es el emisor, RFC `LIK920101X01`), CFDI 4.0 timbrados según CFF. |
| `cfdi/recibido_*.xml` | 5 CFDIs recibidos (proveedores → despacho). |
| `bancos/transacciones.json` | 10 movimientos bancarios (BBVA, Banorte, Santander) con referencia = UUID del CFDI para que la conciliación encuentre cruces. |
| `nominas/nominas.json` | 3 empleados para el escenario de nómina. |

Cada CFDI lleva `NoCertificado` + `Sello` en el nodo raíz (el validador CFF los
exige) y un `UUID` de timbre único. Para personalizar la demo de un prospecto:
edita los RFC/nombres/montos en los XML y ajusta las referencias de
`transacciones.json` para que sigan cruzando con los CFDIs.

---

## Datos del seed (`scripts/seed_demo.py`)

El seed también puede ejecutarse por separado:

```bash
.venv/bin/python scripts/seed_demo.py                    # SQLite por defecto
.venv/bin/python scripts/seed_demo.py --db /tmp/demo.db  # SQLite custom
.venv/bin/python scripts/seed_demo.py --json-only        # solo genera JSONs
B2B_DB_URL=postgresql://u:p@host/db .venv/bin/python scripts/seed_demo.py
```

Genera el dataset completo en `scripts/seed_data/*.json` y lo inserta en la BD.
Emails admin por tenant: `admin@bajio.contadores.mx`,
`admin@norte.grupofiscal.mx`, `admin@pacifico.despacho.mx`.

### Conteos esperados tras el seed

```
tenants=3  client_users=15  invoices=300  bank_transactions=150  nominas=30  documents=15  roles=12
```

---

## Grabar la demo (`scripts/demo_recording.sh`)

Para capturar la demo como terminal output + transcripción Markdown:

```bash
bash scripts/demo_recording.sh            # graba a scripts/demo_output/
bash scripts/demo_recording.sh /tmp/demo  # carpeta de salida custom
```

Genera:
- `TRANSCRIPCION.md` — la salida de la demo formateada como Markdown.
- `salida_raw.txt` — salida cruda del terminal.
- Capturas de pantalla de la terminal (macOS `screencapture`).

> En macOS la grabación por screenshot requiere acceso a "Grabación de
> pantalla" para el proceso. Si no se captura la imagen, el script sigue
> generando la transcripción Markdown sin problemas.
