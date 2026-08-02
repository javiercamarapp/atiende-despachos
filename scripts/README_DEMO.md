# Demo — Datos contables mexicanos realistas (seed_demo)

`scripts/seed_demo.py` puebla la base de datos con un dataset determinista y
realista de despacho contable mexicano, listo para mostrar a prospectos.

## Qué crea

| Entidad | Cantidad | Detalle |
|---|---|---|
| Tenants | 3 | Despachos contables de ejemplo con RFC válido |
| Clientes | 5 por tenant (15) | Empresas mexicanas con RFC de persona moral |
| CFDIs | 20 por cliente (300) | Emitidos (I) y recibidos (E), montos realistas MXN, folio fiscal UUID |
| Transacciones | 50 por tenant (150) | BBVA, Banorte, Santander y HSBC |
| Nóminas | 10 por tenant (30) | CFDI de nómina con percepciones/deducciones y RFC físico |
| Documentos | 5 por tenant (15) | Índice de gestión documental (categorías CFDI/contrato/nómina/…) |
| Roles y permisos | admin, contador, auditor, readonly | Matriz de permisos por rol, por tenant |
| Usuarios | 1 admin + contador + auditor por tenant | email admin por tenant |

Los datos son deterministas (`random.seed=42` por defecto): se regeneran
idénticos en cada ejecución para una demo consistente.

## Ejecución

Requisito: Python 3.11+ (solo stdlib). Sin dependencias de la app.

```bash
cd B2B-AI-MVP/enterprise

# 1) SQLite por defecto (crea/puebla b2b_ai.db junto al script)
python scripts/seed_demo.py

# 2) Ruta SQLite custom
python scripts/seed_demo.py --db /tmp/demo.db

# 3) Postgres (necesita psycopg2-binary)
B2B_DB_URL=postgresql://usuario:pass@host:5432/nombre python scripts/seed_demo.py

# 4) Solo generar los JSON (sin tocar la BD)
python scripts/seed_demo.py --json-only
```

El script crea el esquema (portable SQLite/Postgres) y hace los INSERTs.
Es idempotente por tabla: al re-ejecutar se puede limpiar la BD primero.

## Acceso al demo

- **Emails admin por tenant** (role=`admin`):
  - `admin@bajio.contadores.mx`   (Contadores Asociados del Bajío)
  - `admin@norte.grupofiscal.mx`  (Grupo Fiscal del Norte)
  - `admin@pacifico.despacho.mx`  (Despacho Contable del Pacífico)
- **Clientes del portal** (`client_users`, role=`cliente`): el campo
  `password_hash` es `sha256("demo-pass-<email>")` — en demo, la contraseña
  de cada cliente del portal es `demo-pass-` + su email.
- **Roles RBAC**: los roles por defecto (admin/contador/auditor/readonly)
  se registran en la tabla `roles` (builtin=1) y los `users` de cada tenant
  quedan vinculados vía `user_roles`. La app también los siembra en su store
  en memoria al arrancar (`b2b_ai.features.roles.seed.seed_default_roles`).

## Datos generados (scripts/seed_data/)

| Archivo | Contenido |
|---|---|
| `tenants.json` | 3 despachos (nombre, RFC, ERP, plantilla contable) |
| `clientes.json` | 15 clientes con RFC válido y sector |
| `cfdis.json` | 300 CFDIs emitidos/recibidos |
| `transacciones.json` | 150 movimientos bancarios (4 bancos) |
| `nominas.json` | 30 nóminas con percepciones y deducciones |
| `documents.json` | 15 documentos (índice plano) |
| `documents_state.json` | Mismo contenido en formato `DOCS_STATE_FILE` (para `b2b_ai.features.document_management`) |
| `roles.json` | Matriz de permisos por rol |

> `documents_state.json` sigue el formato que `DocumentService._load_state`
> espera (`{documents, versions, shares}`). Para cargarlo en la gestión
> documental: `DOCS_STATE_FILE=<abs path a documents_state.json>` al arrancar
> la app, o subir los 5 documentos por tenant desde la UI.

## Verificación

```sql
-- Tras poblar, los conteos deben ser:
SELECT 'tenants',           COUNT(*) FROM tenants;
SELECT 'client_users',      COUNT(*) FROM client_users;
SELECT 'invoices',          COUNT(*) FROM invoices;           -- 300
SELECT 'bank_transactions', COUNT(*) FROM bank_transactions;  -- 150
SELECT 'nominas',           COUNT(*) FROM nominas;            -- 30
SELECT 'documents',         COUNT(*) FROM documents;          -- 15
SELECT 'roles',             COUNT(*) FROM roles;              -- 12
```
