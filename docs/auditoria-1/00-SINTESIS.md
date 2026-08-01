# Auditoría 1 — síntesis

**Fecha:** 1-ago-2026. **Repo:** `likida-ai-enterprise` (B&B AI / Likida AI
Enterprise), local en `~/Desktop/B2B-AI-MVP/enterprise`. **Sha base:** `f4944ab`.
**Modo:** local, con el operador presente. **Tipo:** primera auditoría —
sin ronda anterior, doce rubros de cero.

**El repo se construyó en ~14 horas** (106 commits, 31-jul/1-ago-2026) vía un
agente disparado por WhatsApp (Hermes) usando MiniMax 2.5, costo total ~$6
USD. Siguió cambiando bajo esta misma auditoría — el sha base es de hace
menos de una hora al momento de escribir esto.

---

## Nota global: 2.8/10

| Rubro | Nota | Críticos |
|---|:--:|:--:|
| Tool calling | 4 | 1 |
| Backend y API | 3 | 4 |
| Sistema agéntico | 3 | 4 |
| Seguridad | 3 | 4 |
| Pruebas | 3 | 3 |
| Operabilidad y DX | 3 | 3 |
| Rendimiento y costo | 3 | 2 |
| Modelo de datos | 3 | 3 |
| Frontend | 3 | 2 |
| Cumplimiento legal | 2 | 2 |
| Arquitectura | 2 | 3 |
| **Cumplimiento fiscal** | **2** | **10** |

**42 críticos en total**, ninguno resultó falso. La enorme mayoría se
verificó ejecutando el código de verdad (`TestClient`, Postgres real en
Docker, mutación de funciones de producción) — no por lectura. Comparado con
`likida.ai` (7 rondas, 6.5/10 hoy): este repo tiene en su **primera** auditoría
más del doble de críticos que Likida acumuló en sus primeras siete rondas
combinadas.

---

## Los cuatro hallazgos que importan más, en orden

### 1 · Hay huecos de seguridad explotables ahora mismo, no teóricos

- Un desconocido se vuelve **admin de cualquier despacho** con una petición
  sin token (`auth/api.py:110-117`).
- `/api/v2/batch` **lee cualquier archivo del disco del servidor** y lo
  importa al tenant del atacante (`api/v2.py:286-314`).
- Nómina y pre-auditoría corren **sin ninguna credencial**, con el
  `tenant_id` puesto por quien llama (`features/nomina_completa/routes.py`).
- La firma del webhook de pago **no protege nada** — el atacante elige qué
  secreto se verifica (`billing/api.py:59-78`).
- Un IDOR confirmado por separado en backend: la API key de un tenant
  escribe facturas en el libro de OTRO tenant (`webhooks.py`).

Los cinco se reprodujeron con peticiones reales, no se infirieron leyendo.

### 2 · La nómina y el IVA calculan cifras equivocadas, no bordes raros

Del rubro fiscal (10 críticos, todos ejecutados contra el código real):
INFONAVIT patronal descontado del sueldo del trabajador (al revés); cuotas
IMSS calculadas sobre el SBC **diario** y restadas de una nómina **mensual**
(~34× de error); ISR quincenal con tarifa **mensual**; catálogos del SAT
inventados (se aceptan claves que no existen, se rechazan las que sí); un
validador de CFDI que da "12/12 checks" a un XML sin los requisitos del CFF
29-A; ningún camino que verifique la lista 69-B antes de asentar la póliza.
Y por separado, arquitectura encontró **dos calculadoras de ISR** en la misma
app que dan resultados distintos para el mismo salario ($2,604 contra $0).

Esto no es "bug de software" en el sentido normal: es una declaración mal
hecha o un trabajador mal pagado, con el nombre del despacho encima.

### 3 · El camino a producción (Railway + Postgres) no conecta con nada

Confirmado de forma independiente por **cinco** auditores distintos
(backend, arquitectura, datos, rendimiento, operabilidad): Alembic tiene dos
heads desde la migración 0004 y no puede migrar contra Postgres; el pool de
conexiones es SQLite-only aunque se le pase un DSN de Postgres; `DEPLOY-GUIDE.md`
documenta una variable de entorno (`DATABASE_URL`) que el código nunca lee
(lee `B2B_DB_URL`); y `/health` **miente** sobre qué base de datos está
usando. Seguir la guía de deploy tal cual hoy no falla con un error — corre
en silencio sobre SQLite efímero, perdiendo datos en cada redeploy.

### 4 · Puede que nada de esto importe: el camino auditado podría no ser el real

El auditor fiscal encontró, hacia el final de su ronda, que
`b2b_ai/features/` contiene una **segunda implementación completa** de DIOT,
contabilidad electrónica y nómina — y que el commit `e643695` (de esta misma
tarde) **acaba de registrar esos routers en FastAPI**. Es posible que la
mayoría de los hallazgos de arriba describan un camino de código que ya no
es el que corre en producción. Esto no invalida los hallazgos —cada uno se
reprodujo contra código real que existe y se puede alcanzar— pero significa
que **la ronda 2 tiene que auditar la segunda implementación antes que nada**,
porque hoy nadie sabe si hereda los mismos errores o los repite distinto.

---

## Lo que sí está bien, para no perder la proporción

- La suite tiene 4,900+ pruebas y corre limpia (0 failed) contra SQLite.
- El P1 de seguridad ya reportado (JWT hardcodeado) **se verificó cerrado**
  de verdad, no de palabra.
- El diseño de "el LLM propone, la decisión fiscal es humana" con fallback a
  reglas está bien intencionado — el problema no es la arquitectura de la
  idea, es que la ejecución bajo 14 horas dejó huecos en casi cada capa.

---

## Comparación con likida.ai, para la decisión que ya está tomada

Javier ya dijo que `likida.ai` es la apuesta segura y que este repo se
construyó para un amigo contador. Esta auditoría no cambia esa decisión —la
confirma con números—: 2.8 contra 6.5, en la primera ronda contra la
séptima. Antes de que alguien real use esto para pagar nóminas o presentar
DIOT, como mínimo necesita: cerrar los 4-5 huecos de seguridad explotables,
decidir CUÁL implementación fiscal es la real y arreglar esa, y conectar de
verdad el camino a Postgres antes de desplegar.

---

## No se arregló nada esta ronda, a propósito

El árbol siguió cambiando bajo esta auditoría (ver "Fecha" arriba) y es la
primera ronda sin precedente — las dos condiciones que la disciplina de esta
skill usa para desactivar el autofix. Esta ronda es diagnóstico puro.

Reportes completos por rubro en `docs/auditoria-1/<rubro>.md`. Tablero en
`docs/auditoria-1/tablero.html` / `.png`.
