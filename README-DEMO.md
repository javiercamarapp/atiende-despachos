# 🚀 Likida AI Enterprise — Guía de Demo para Prospectos

## Inicio rápido

```bash
cd enterprise/
./demo_run.sh
```

El servidor arranca en **http://localhost:8080** con un dashboard interactivo.

---

## Estructura de la demo

| Archivo | Descripción |
|---------|-------------|
| `demo_server.py` | Servidor FastAPI con dashboard y API |
| `demo_run.sh` | Script de inicio (chmod +x ya hecho) |
| `README-DEMO.md` | Esta guía |
| `b2b_ai/demo-data/` | 10 CFDI XML de ejemplo |
| `b2b_ai/demo-output/` | Reporte HTML generado por `b2b-ai demo` |

---

## Flujo de la demo (paso a paso)

### 1. Abrir el Dashboard

1. Ejecuta `./demo_run.sh`
2. Abre **http://localhost:8080** en el navegador
3. Verás el dashboard de Likida AI Enterprise con las estadísticas en 0

### 2. Procesar los 10 CFDI de ejemplo

1. Haz clic en **"🔄 Procesar los 10 CFDI de Demo"**
2. Observa la barra de progreso mientras se procesan
3. El dashboard se actualiza con:
   - Total de facturas procesadas (10)
   - Facturas válidas vs con observaciones
   - Anomalías detectadas
   - Monto total

### 3. Explorar los resultados

1. Ve a la pestaña **"📋 Resultados"**
2. La tabla muestra cada factura con:
   - Archivo, emisor, fecha, monto
   - **Categoría contable** (Gasto Operativo, Activo Fijo, Nómina, etc.)
   - **Confianza** de la clasificación (%)
   - **Estado** (OK o anomalía con severidad)
3. Haz clic en **"Ver"** para ver el detalle completo de cada CFDI

### 4. Mostrar las anomalías detectadas

En la pestaña de resultados, verás tarjetas de anomalías:

| Tipo | Severidad | Ejemplo |
|------|-----------|---------|
| **Duplicado** | HIGH | Misma factura dos veces (CFF Art. 29-A) |
| **Monto inusual** | MEDIUM | Monto fuera del rango histórico |
| **IVA inconsistente** | MEDIUM | IVA no coincide con subtotal × tasa |
| **Proveedor nuevo** | LOW | RFC sin historial previo |

Cada anomalía incluye la **referencia legal** (CFF, Ley del IVA, etc.)

### 5. Subir un CFDI personalizado

1. Ve a la pestaña **"📤 Subir CFDI"**
2. Arrastra o selecciona un archivo `.xml` de CFDI 4.0
3. El sistema lo procesa en tiempo real y muestra la clasificación

---

## Los 10 CFDI de ejemplo

| # | Archivo | Tipo | Categoría | Monto | Nota |
|---|---------|------|-----------|-------|------|
| 1 | gasto_papeleria.xml | I (Ingreso) | Gasto Operativo | $1,740 | Artículos de oficina |
| 2 | gasto_hosting.xml | I | Gasto Operativo | $2,552 | Hosting cloud |
| 3 | gasto_servicios_profesionales.xml | I | Gasto Operativo | $9,860 | Consultoría fiscal |
| 4 | nomina_empleado1.xml | N (Nómina) | Nómina | $25,500 | María López |
| 5 | nomina_empleado2.xml | N | Nómina | $18,500 | Juan Carlos Ramírez |
| 6 | nota_credito1.xml | E (Egreso) | Gasto Operativo | $0.00 | Devolución papelería |
| 7 | nota_credito2.xml | E | Gasto Operativo | $0.00 | Ajuste hosting |
| 8 | activo_fijo_computo.xml | I | Activo Fijo | $40,600 | Laptop Dell |
| 9 | factura_cancelada.xml | I | Gasto Operativo | $3,480 | ⚠️ Factura cancelada |
| 10 | monto_inusual.xml | I | Activo Fijo | $1,136,800 | ⚠️ Monto inusual |

---

## Puntos clave para la presentación

### Para el despacho contable:
- **Clasificación automática**: El agente categoriza cada factura en las 4 categorías contables (Gasto, Nómina, Activo Fijo, Inversión) con un score de confianza
- **Detección de anomalías**: Identifica facturas duplicadas, montos inusuales, IVA inconsistente, y proveedores nuevos
- **Referencia legal**: Cada anomalía cita los artículos del CFF y Ley del IVA aplicables
- **Revisión humana**: Cuando la confianza es baja, marca para revisión del contador

### Para el dueño del despacho:
- **Velocidad**: 10 facturas procesadas en segundos
- **Sin errores manuales**: Elimina la digitación manual
- **Auditoría**: Todo queda registrado (audit trail)
- **Integración**: Se conecta con CONTPAQi (ERP contable mexicano)

---

## API Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/` | Dashboard HTML interactivo |
| GET | `/docs` | Documentación Swagger de la API |
| GET | `/api/demo/status` | Estadísticas de procesamiento |
| GET | `/api/demo/results` | Todos los resultados como JSON |
| POST | `/api/demo/upload` | Subir y procesar un CFDI XML |
| GET | `/api/demo/process-all` | Procesar los 10 CFDI de demo |

---

## Personalización

### Cambiar el puerto

```bash
./demo_run.sh 9090
```

### Agregar más CFDI de ejemplo

Coloca archivos `.xml` de CFDI 4.0 en `b2b_ai/demo-data/` y se procesarán automáticamente.

### Usar con LLM real (DeepSeek)

El demo server usa clasificación por reglas (rápida, sin costo). Para usar el LLM real:

```bash
b2b-ai demo --live
```

Esto genera un reporte HTML estático en `b2b_ai/demo-output/demo-report.html`.

---

## Troubleshooting

| Problema | Solución |
|----------|----------|
| `ModuleNotFoundError: b2b_ai` | Ejecuta desde `enterprise/` o instala con `pip install -e .` |
| `lxml not found` | `pip install lxml` |
| Puerto 8080 en uso | `./demo_run.sh 9090` |
| Server no arranca | Verifica que Python 3.10+ esté instalado |

---

*Likida AI Enterprise — Agente contable inteligente para despachos mexicanos*
