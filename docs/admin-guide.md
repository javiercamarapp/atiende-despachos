# Guía de Administración — Configuración de Tenants

Esta guía es para el **administrador del sistema** que gestiona los despachos
(clientes) en Likida AI Enterprise. Cubre el modelo multi-tenant, cómo crear y aislar
tenants, cómo provisionar API keys y cómo operar el sistema de forma segura.

---

## 1. El modelo multi-tenant

Cada **tenant** es un despacho contable independiente. Todos los datos de
trabajo (facturas, clasificaciones, notificaciones) llevan un `tenant_id` y
las consultas del servicio **filtran siempre** por ese id, aislando la
información entre despachos.

Tablas principales y su aislamiento:

| Tabla | ¿Tiene `tenant_id`? | Contenido |
|---|---|---|
| `tenants` | — | Los despachos (el catálogo de tenants). |
| `users` | ✅ | Usuarios dentro de un tenant. |
| `invoices` | ✅ | CFDI procesados (registro central). |
| `classifications` | ✅ | Historial de clasificaciones por factura. |
| `audit_log` | ✅ | Bitácora de TODAS las llamadas a tools. |
| `notifications` | ✅ | Notificaciones enviadas/en cola. |
| `api_keys` | ✅ | API keys (hashadas) por tenant. |
| `leads` | — | Leads de la landing (sin tenant). |

---

## 2. Crear un tenant

### 2.1 Vía Python (programático / script de aprovisionamiento)

```python
from b2b_ai.db.db import Database

db = Database("b2b_ai.db")
tenant_id = db.create_tenant("Despacho López y Asociados", rfc="LXA990101XXX")
print("Tenant creado con id:", tenant_id)

# Opcional: crear un usuario dentro del tenant
user_id = db.create_user(tenant_id, "María López", "maria@despacho-lopez.com", role="contador")
```

### 2.2 Vía CLI

El CLI usa por defecto el primer tenant. Para operar sobre un tenant
específico usa `--tenant-id`:

```bash
bb-ai status --tenant-id 2
bb-ai process fixtures/cfdis/01_gasto_operativo_papeleria.xml --tenant-id 2
```

> Nota: no existe comando CLI dedicado para crear tenants; usa el script
> Python de arriba (o crea un endpoint de aprovisionamiento — ver sección 6).

---

## 3. Aislar datos entre despachos

El aislamiento es **por código**: cada método de lectura de `Database`
acepta `tenant_id` y filtra por él. Ejemplos:

```python
db.list_invoices(tenant_id=2)          # solo facturas del despacho 2
db.invoice_stats(tenant_id=2)          # métricas del despacho 2
db.list_audit(tenant_id=2)             # auditoría del despacho 2
db.get_invoice(5, tenant_id=2)         # factura 5 SOLO si es del tenant 2
db.count_invoices(tenant_id=2)
```

En la API, el tenant se impone de dos maneras:

1. **Por API key:** si la key está asociada a un `tenant_id` (tabla
   `api_keys`), las peticiones quedan acotadas a ese tenant. Aunque envíes
   `tenant_id` en la query, la respuesta usa el tenant efectivo de la key
   cuando no se pasa uno explícito.
2. **Por query param:** `GET /api/v1/invoices?tenant_id=2`.

> ⚠️ **Seguridad:** en multi-tenant real, asegúrate de que cada despacho use
> **su propia API key** ligada a su `tenant_id`, para que el aislamiento
> funcione de extremo a extremo. No uses la key de servicio (`B2B_API_KEY`)
> en producción multi-tenant.

---

## 4. Provisionar API keys

Las API keys se guardan **hashadas** (SHA-256) en `api_keys`, nunca en claro.

### 4.1 Crear una key para un tenant

```python
import secrets
from b2b_ai.db.db import Database

db = Database("b2b_ai.db")
tenant_id = 2

# Genera una key aleatoria larga
raw_key = secrets.token_urlsafe(32)   # p. ej. "7xK...mQ"
key_id, key_hash = db.create_api_key(tenant_id, "key-produccion-despacho-2", raw_key)

print("Entrega ESTA key al despacho (es la única vez que se ve):", raw_key)
# Almacena key_id para referencia; la key en claro no se puede recuperar.
```

### 4.2 Verificar que la key funciona

```bash
curl -H "X-API-Key: <la-key-que-entregaste>" http://localhost:8000/api/v1/invoices?tenant_id=2
```

### 4.3 Listar keys de un tenant

```python
for k in db.list_api_keys(tenant_id=2):
    print(k["id"], k["name"], "active" if k["active"] else "inactive", k["created_at"])
```

> **Nota:** el listado **no** devuelve la key en claro (solo su hash); por
> diseño es irrecuperable. Si un cliente la pierde, revócala y emite una
> nueva.

### 4.4 Revocar / desactivar una key

Actualmente la desactivación se hace actualizando el campo `active` a `0`:

```python
db.conn.execute("UPDATE api_keys SET active=0 WHERE id=?", (key_id,))
db.conn.commit()
```

Las keys desactivadas dejan de autenticarse (la resolución filtra por
`active=1`).

### 4.5 Key de servicio (dev / standalone)

La variable de entorno `B2B_API_KEY` actúa como **key maestra de servicio**
para pruebas single-tenant. En `docker-compose` se define así:

```yaml
environment:
  - B2B_API_KEY=${B2B_API_KEY:-change-me}
```

> En producción multi-tenant **no** uses la key de servicio; provisiona keys
> por tenant en la tabla `api_keys`.

---

## 5. Configuración de entorno

Copia `.env.example` a `.env` y edita:

```bash
cd enterprise
cp .env.example .env
vi .env
```

| Variable | Descripción | Default |
|---|---|---|
| `B2B_API_KEY` | Key maestra de servicio (dev). En prod, usa algo largo/aleatorio: `openssl rand -hex 32`. | `change-me` |
| `B2B_DB_PATH` | Ruta de la base SQLite. | `<repo>/b2b_ai.db` (o `/data/b2b_ai.db` en Docker) |

---

## 6. Operación con Docker

### 6.1 Levantar el stack

```bash
cd enterprise
cp .env.example .env && vi .env   # define B2B_API_KEY
docker compose up --build -d
```

- API en `http://localhost:8000`
- Docs en `/docs`
- **DB persistente** en el volumen nombrado `db` (sobrevive a
  `docker compose down`, no a `down -v`).

### 6.2 Verificar health

```bash
curl http://localhost:8000/health
# {"status":"ok","service":"b2b-ai","version":"1.0.0","schema_version":2,...}
```

### 6.3 Monitoreo de auditoría

El `audit_log` registra **toda** llamada a tool (y los intentos de auth
fallidos). Para auditoría:

```python
db.list_audit(tenant_id=2, tool_name="api_auth", limit=50)   # intentos de auth
db.list_audit(tenant_id=2, tool_name="parse_cfdi", limit=50) # parses del despacho
```

---

## 7. Migraciones del esquema

El esquema se versiona con migraciones automáticas (tabla `schema_version`).
Al arrancar, `Database.migrate()` aplica las pendientes en orden.

```bash
# Versión actual del esquema
bb-ai status | grep Esquema
# o
python -c "from b2b_ai.db.db import Database; print(Database().schema_version())"
```

| Migración | Versión | Contenido |
|---|---|---|
| `initial_schema` | 1 | tenants, users, invoices, classifications, audit_log, notifications. |
| `api_keys_and_leads` | 2 | api_keys (hashadas) y leads. |

> Para añadir una migración nueva, agrega un dict a `MIGRATIONS` en
> `b2b_ai/db/models.py` con `version` incremental. Las migraciones se aplican
> automáticamente en la siguiente conexión.

---

## 8. Mejores prácticas de administración

1. **Una key por tenant**, entregada por canal seguro, y rotación periódica.
2. **Nunca** loguees ni expongas keys en claro (solo se guarda el hash).
3. **Audita** regularmente el `audit_log` por tenant.
4. **Respaldos** de la base SQLite (volumen `db`); considera el upgrade a
   PostgreSQL para producción (el esquema es PG-ready).
5. **Revisa los flags** `requires_human_review` antes de emitir cualquier
   declaración o presentación.
6. **Elimina el `--reset`** del modo producción; es solo para dev.
7. Define la `B2B_API_KEY` con `openssl rand -hex 32` y nunca la versiones.
