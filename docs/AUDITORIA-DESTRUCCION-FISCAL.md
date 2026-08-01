# 🔥 AUDITORÍA DE DESTRUCCIÓN — Fiscal + Edge Cases

> **Objetivo:** Encontrar bugs que causarían datos incorrectos, rechazo del SAT, o pérdida de dinero real.
> **Método:** Lectura línea-por-línea de `b2b_ai/` (parser, validadores, servicios, API, compliance).
> **Fecha:** 2026-08-01

---

## 1. CFDI Parsing

### BUG #1 — XML enorme causa OOM (sin límite de tamaño)

**Archivo:** `cfdi/parser.py:80-86`, `features/nomina/parser.py:176,231`

**Escenario:** Un adversario sube un XML de 500 MB (o un XML "bomba" con entidades expansibles — XML bomb / billion laughs attack). `etree.parse()` y `etree.fromstring()` cargan todo en memoria de golpe.

**Resultado incorrecto:** El proceso del worker se queda sin RAM (OOM), se cae el endpoint, y si es un batch async, todo el job muere silenciosamente.

**Fix:**
```python
MAX_XML_BYTES = 10 * 1024 * 1024  # 10 MB

def parse_cfdi_bytes(xml_bytes: bytes):
    if len(xml_bytes) > MAX_XML_BYTES:
        raise CFDIError(f"XML excede {MAX_XML_BYTES} bytes")
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    root = etree.fromstring(xml_bytes, parser=parser)
    ...
```

**Severidad:** 🔴 CRÍTICA — Denegación de servicio, pérdida de datos en batch.

---

### BUG #2 — Sin detección de encoding: ISO-8859-1 y Windows-1252 rompen acentos

**Archivo:** `cfdi/parser.py:86`, `features/nomina/parser.py:231`

**Escenario:** Un proveedor genera CFDIs con `encoding="ISO-8859-1"` (válido según Anexo 20 del SAT). lxml intenta decodificar como UTF-8 por defecto y falla o corrompe caracteres: `PEÑA` → `PEï¿½A`.

**Resultado incorrecto:** RFCs válidos con Ñ (ej. `ÑAC123456789`) se rechazan por el validador de RFC. Nombres de emisores quedan ilegibles en reportes. Conciliación falla porque el RFC no coincide.

**Fix:** Usar el encoding declarado en el XML:
```python
def parse_cfdi_bytes(xml_bytes: bytes):
    # Detectar encoding del XML declaration
    head = xml_bytes[:200].decode('ascii', errors='ignore')
    import re
    m = re.search(r'encoding=["\']([^"\']+)', head)
    enc = m.group(1) if m else 'utf-8'
    text = xml_bytes.decode(enc, errors='replace')
    root = etree.fromstring(text.encode('utf-8'))
```

**Severidad:** 🟡 ALTA — Silenciosamente corrompe datos fiscales válidos.

---

### BUG #3 — Notas de crédito (TipoDeComprobante="E") ignoradas en validación de total

**Archivo:** `cfdi/validator.py:158-169`

**Escenario:** Una nota de crédito tiene `TipoDeComprobante="E"`, subtotal negativo (o positivo con descuento igual al subtotal), y total = 0. El validador calcula:
```python
esperado = subtotal + iva - descuento - ret_tot
```
Si subtotal=100, iva=16, descuento=116, total=0 → `esperado = 100+16-116-0 = 0`. Esto pasa.

Pero si la nota de crédito tiene subtotal=0 y total negativo (CFDI 4.0 lo permite para notas de crédito), el validador rechaza porque `total < 0` no se valida explícitamente — solo se compara aritméticamente.

**Resultado incorrecto:** Notas de crédito válidas se rechazan con `total_incoherente`. El contador no puede procesar devoluciones.

**Fix:** Validar que para TipoDeComprobante="E", el total puede ser 0 (nunca negativo según SAT, pero el subtotal puede ser 0 con impuestos negativos por retención).

**Severidad:** 🟡 ALTA — Bloquea el flujo de notas de crédito.

---

### BUG #4 — CFDI globales (RFC genérico XAXX010101000) no se detectan como no deducibles

**Archivo:** `cfdi/parser.py`, `services/classify.py`

**Escenario:** Un CFDI emitido "al público en general" usa `Rfc="XAXX010101000"` (RFC genérico del SAT). El parser lo extrae normalmente. El clasificador lo marca como `gasto_operativo`. Pero fiscalmente, un CFDI con RFC genérico NO es deducible de ISR (CFF Art. 27) ni genera IVA acreditable (LIVA Art. 5).

**Resultado incorrecto:** El sistema clasifica la factura como deducible y la incluye en la DIOT como IVA acreditable. Esto infla artificialmente el IVA acreditable, y si se presenta así, el SAT rechaza la DIOT o genera un requerimiento.

**Fix:** Agregar detección de RFC genéricos en el parser/validator:
```python
RFCS_GENERICOS = {"XAXX010101000", "XEXX010101000", "XAXX010101001"}
if datos.get("emisor_rfc") in RFCS_GENERICOS:
    warnings.append("CFDI al público en general: no deducible, IVA no acreditable")
```

**Severidad:** 🔴 CRÍTICA — Incluye IVA no acreditable en DIOT = rechazo del SAT.

---

### BUG #5 — CfdiRelacionados solo extrae UUID, pierde TipoRelacion

**Archivo:** `cfdi/parser.py:222-225`

**Escenario:** Un CFDI de nota de crédito referencia la factura original con:
```xml
<CfdiRelacionados TipoRelacion="03">
  <CfdiRelacionado UUID="original-uuid"/>
</CfdiRelacionados>
```
El parser solo extrae el UUID pero ignora `TipoRelacion` (01=Nota de crédito, 03=Sustitución, etc.).

**Resultado incorrecto:** Sin `TipoRelacion`, el sistema no puede distinguir entre una nota de crédito (ajuste) y una sustitución (reemplazo). Las facturas sustituidas no se marcan como canceladas en el ERP.

**Fix:** Extraer también `TipoRelacion` del nodo padre.

**Severidad:** 🟡 ALTA — Pierde metadatos fiscales obligatorios.

---

## 2. Nómina

### BUG #6 — Salarios en cero pasan validación silenciosamente

**Archivo:** `features/nomina/parser.py:81-88`, `features/nomina/validators.py`

**Escenario:** Un CFDI de nómina con `SalarioDiarioIntegrado="0"` o `TotalPercepciones="0"`. El parser convierte `"0"` a `Decimal("0")`. Los validadores no tienen ninguna regla contra salario=0. Los validadores solo verifican RFC, fechas, NumDiasPagados, PeriodicidadPago y TipoNomina — NUNCA montos.

**Resultado incorrecto:** Una nómina con salario $0 se acepta como válida y pasa al ERP. Esto es fiscalmente imposible — un empleado sin salario no existe ante el IMSS. Si el SAT recibe esto, genera un requerimiento inmediato.

**Fix:** Agregar validación:
```python
def validate_montos(data: NominaData) -> List[str]:
    errors = []
    if data.total_percepciones is not None and data.total_percepciones <= 0:
        errors.append(f"TotalPercepciones ({data.total_percepciones}) debe ser > 0.")
    if data.salario_diario_integrado is not None and data.salario_diario_integrado <= 0:
        errors.append(f"SalarioDiarioIntegrado ({data.salario_diario_integrado}) debe ser > 0.")
    return errors
```

**Severidad:** 🔴 CRÍTICA — Nóminas inválidas pasan al SAT.

---

### BUG #7 — Empleados sin RFC no se rechazan (solo CURP requerida)

**Archivo:** `features/nomina/parser.py:212-218`

**Escenario:** El complemento de nómina requiere CURP pero no tiene campo de RFC del empleado. El RFC del empleado viene del CFDI `Receptor` principal. El parser de nómina no extrae ni valida el RFC del receptor del CFDI — solo extrae CURP, NumEmpleado, etc. del complemento.

**Resultado incorrecto:** Si el CFDI tiene RFC del receptor vacío o inválido, el parser de nómina no lo detecta. La nómina se procesa sin RFC del empleado, lo cual es inválido ante el SAT (toda nómina debe tener receptor identificado).

**Fix:** El parser de nómina ya extrae `cfdi_emisor_rfc` del comprobante. Debe extraer también `cfdi_receptor_rfc` y validarlo.

**Severidad:** 🟡 ALTA — Nóminas sin receptor identificado pasan validación.

---

### BUG #8 — Años bisiestos: aguinaldo proporcional usa 365 días siempre

**Archivo:** `services/payroll.py:367`

**Escenario:** Un empleado que trabajó todo 2024 (366 días, año bisiesto) solicita aguinaldo proporcional. El cálculo:
```python
monto = sd * dias_ley * (dt / Decimal("365"))
```
Con `dt=366`: `monto = sd * 15 * (366/365) = sd * 15 * 1.00274`. Esto da un aguinaldo MAYOR al de ley (15 días completos).

**Resultado incorrecto:** Se paga ~0.27% extra de aguinaldo. Para un salario de $500/día, son ~$20 extra por empleado. Con 1000 empleados: $20,000 pagados de más. No es enorme, pero es un error aritmético real.

**Fix:**
```python
from calendar import isleap
year = date.today().year
dias_año = 366 if isleap(year) else 365
monto = sd * dias_ley * (dt / Decimal(str(dias_año)))
```

**Severidad:** 🟡 BAJA — Pérdida de dinero real pero pequeña por empleado.

---

### BUG #9 — Nóminas extraordinarias: NumDiasPagados=0 rechazado

**Archivo:** `features/nomina/validators.py:149-150`

**Escenario:** Una nómina extraordinaria (`TipoNomina="E"`) de aguinaldo puro puede tener `NumDiasPagados="0"` (no se pagaron días laborados, solo el aguinaldo). El validador rechaza:
```python
if data.num_dias_pagados <= 0:
    errors.append("NumDiasPagados (...) debe ser mayor a 0.")
```

**Resultado incorrecto:** Toda nómina extraordinaria de aguinaldo se rechaza. El patrón no puede timbrar aguinaldos sin días laborados.

**Fix:** Permitir NumDiasPagados=0 para TipoNomina="E":
```python
if data.tipo_nomina == "E" and data.num_dias_pagados == 0:
    pass  # Válido para nóminas extraordinarias
elif data.num_dias_pagados <= 0:
    errors.append(...)
```

**Severidad:** 🔴 CRÍTICA — Bloquea el timbrado de aguinaldos.

---

### BUG #10 — Cambio de año fiscal: tabla ISR hardcodeada a 2024, sin mecanismo de actualización

**Archivo:** `features/declaraciones/service.py:47-72`, `services/payroll.py:29-56`, `features/compliance.py:99-124`

**Escenario:** Hay TRES copias independientes de la tabla ISR:
1. `declaraciones/service.py` — ISR_TABLE_MONTHLY (2024)
2. `payroll.py` — TARIFA_ISR_2024_MENSUAL (2024)
3. `compliance.py` — ISR_TABLE_2024_MONTHLY (2024)

Cuando el SAT publica la nueva tabla para 2025 (o cualquier año), hay que actualizar 3 archivos diferentes. Si se actualiza uno sin los otros, los cálculos son inconsistentes.

**Resultado incorrecto:** ISR calculado con tabla de 2024 para el ejercicio fiscal 2025. El SAT rechaza declaraciones que usan tabla incorrecta. Diferencias entre nómina (payroll.py) y declaraciones (service.py) generan inconsistencias en conciliación.

**Fix:** Centralizar tablas en un módulo único `fiscal_tables.py` con versionado por año.

**Severidad:** 🔴 CRÍTICA — Afecta TODOS los cálculos fiscales al cambiar de año.

---

## 3. ISR / IMSS

### BUG #11 — ISR: tabla mensual vs anual — gap entre rangos

**Archivo:** `features/declaraciones/service.py:565-582`

**Escenario:** El método `_apply_isr_table` usa:
```python
if lower <= taxable_income < next_lower:
```
Pero los rangos de la tabla tienen gaps de $0.01:
```python
(0.00, 312.41, ...), (312.42, 2636.28, ...), ...
```
Un ingreso de exactamente $312.415 cae entre rangos (>= 312.41 y < 312.42) → ninguna rama matchea → retorna `0.0` (el fallback al final).

**Resultado incorrecto:** ISR de $312.415 se calcula como $0.00 en vez de ~$6.00. Para ingresos en estos gaps de $0.01, el ISR es $0.

**Fix:** Usar `<=` para el límite superior de cada rango (como hace `compliance.py`):
```python
if lower <= taxable_income <= upper:
```

**Severidad:** 🟡 MEDIA — Solo afecta ingresos en gaps de $0.01, pero es un error aritmético.

---

### BUG #12 — ISR anual vs mensual: tabla mensual × 12 ≠ tabla anual

**Archivo:** `features/declaraciones/service.py:47-72`

**Escenario:** La tabla mensual y la tabla anual NO son proporcionales. Ejemplo: el primer rango mensual es $0-$312.41 con tasa 1.92%, pero el anual es $0-$3,748.57 (que es 312.41 × 12 = $3,748.92, no $3,748.57). Hay diferencias de centavos.

**Resultado incorrecto:** Un empleado que gana exactamente $312.41/mes × 12 = $3,748.92/año cae en el rango 2 de la tabla anual ($3,748.58-$31,635.36) pero en el rango 1 de la tabla mensual. La declaración anual calcula ISR diferente a la suma de provisionales mensuales, generando diferencias artificiales.

**Fix:** Usar las tablas oficiales publicadas por el SAT sin derivar una de la otra.

**Severidad:** 🟡 BAJA — Diferencias de centavos, pero genera inconsistencias en conciliación.

---

### BUG #13 — IMSS: salario base cotización negativo o cero no se valida

**Archivo:** `services/payroll.py:206-263`

**Escenario:** `calc_imss` recibe `salario_base_cotizacion` como parámetro. Si es 0 o negativo, todos los componentes calculan a 0: `eym=0, rcva=0, iv=0, gmp=0, total=0`. No hay error.

**Resultado incorrecto:** Una nómina con SBC=0 se procesa sin retención de IMSS. El patrón evade sus obligaciones de seguridad social. El IMSS detecta esto en su cruce de datos y genera un crédito fiscal.

**Fix:** Validar SBC > 0 y SBC >= UMA diaria (Art. 107 LSS):
```python
if sbc < r["imss_uma_diario"]:
    raise ValueError(f"SBC ({sbc}) no puede ser menor a UMA diaria ({r['imss_uma_diario']})")
```

**Severidad:** 🔴 CRÍTICA — Evade retenciones de seguridad social.

---

### BUG #14 — Subsidio al empleo: tabla 2025 pero tabla ISR 2024

**Archivo:** `services/payroll.py:71-83` (subsidio 2025) vs `services/payroll.py:29-56` (ISR 2024)

**Escenario:** Las tablas están desincronizadas:
- ISR mensual: tabla 2024
- Subsidio al empleo: tabla 2025

El subsidio se calcula sobre el ingreso gravado usando la tabla 2025, pero el ISR se calcula con la tabla 2024. Si las tablas cambian de un año a otro, la resta `ISR - subsidio` usa valores de años diferentes.

**Resultado incorrecto:** Empleados con ingresos en el límite entre tablas pueden recibir subsidio incorrecto. Ejemplo: si el límite de subsidio sube de $13,340 (2024) a $14,000 (2025), pero el ISR se calcula con tabla 2024, un empleado con ingreso de $13,500 recibe subsidio 2025 pero paga ISR 2024.

**Fix:** Sincronizar ambas tablas al mismo año fiscal.

**Severidad:** 🔴 CRÍTICA — Cálculo fiscal incorrecto para TODOS los empleados.

---

### BUG #15 — Ingresos muy altos (>$1M/mes): Decimal OK en payroll, float en declaraciones

**Archivo:** `features/declaraciones/service.py:229-233`

**Escenario:** El servicio de declaraciones usa `float()`:
```python
ingresos = float(data.get("ingresos", 0))
utilidad = round(ingresos - deducciones, 2)
```
Para ingresos de $10,000,000.00, `float` tiene precisión limitada: `10000000.1 - 10000000.0 = 0.0999999999978172` (no 0.1). Con `round(..., 2)` esto da `0.1`, pero para cálculos encadenados el error se propaga.

**Resultado incorrecto:** Para empresas con ingresos >$1M, el ISR calculado puede diferir en centavos o pesos del valor correcto. El SAT usa Decimal con 6 decimales de precisión — cualquier diferencia genera inconsistencia.

**Fix:** Usar `Decimal` en todo el módulo de declaraciones (como ya hace `payroll.py`).

**Severidad:** 🟡 MEDIA — Diferencias de centavos que escalan con ingresos altos.

---

## 4. IVA

### BUG #16 — IVA acreditable > IVA trasladado no genera ninguna alerta

**Archivo:** `features/declaraciones/service.py:130-138`

**Escenario:** Un mes con muchas compras y pocas ventas: `iva_pagado = $500,000`, `iva_cobrado = $10,000`. El sistema calcula `saldo_favor = max(0, 500000 - 10000) = $490,000` y lo acepta sin cuestionar.

**Resultado incorrecto:** Un saldo a favor de $490,000 es inusual y puede indicar: (a) empresa en inversión real, (b) error de captura, o (c) esquema de facturación fantasma. El SAT automáticamente audita devoluciones >$100,000. El sistema no advierte al contador.

**Fix:** Agregar umbrales de alerta:
```python
if iva_pagado > iva_cobrado * 3:
    iva_data.requires_human_review = True
    iva_data.human_review_reason = "IVA acreditable > 3× IVA trasladado"
```

**Severidad:** 🟡 ALTA — El contador se entera cuando el SAT rechaza, no antes.

---

### BUG #17 — Tasa 0% (exportaciones): validador rechaza como inválido

**Archivo:** `features/diot/validators.py:374-384`

**Escenario:** Una factura de exportación tiene `tasa=0.0` pero `monto_neto > 0`. El cálculo:
```python
effective_rate = round(iva_trasladado / monto_neto, 4)  # = 0.0
if effective_rate not in {0.0, 0.08, 0.16}:
    # error
```
En este caso `0.0` SÍ está en el set, así que pasa. PERO: si `iva_trasladado` es `None` (no viene en el XML porque es tasa 0), entonces `iva_trasladado = 0` por default y `effective_rate = 0/monto_neto = 0.0`. Esto funciona.

Sin embargo, el `validate_iva_amount` en `diot/validators.py:117-138`:
```python
expected_iva = monto_neto * expected_rate  # monto_neto * 0.16 = positivo
if abs(iva_trasladado - expected_iva) / abs(expected_iva) > tolerance:
    return False, "IVA trasladado no coincide con esperado..."
```
Para tasa 0%, `expected_rate=0.16` (hardcodeado como default) genera un IVA esperado de 16% del neto, pero el real es 0%. Esto falla.

**Resultado incorrecto:** Exportaciones (tasa 0%) se rechazan por "IVA trasladado no coincide con 16% esperado".

**Fix:** Hacer `expected_rate` un parámetro obligatorio, no default a 0.16.

**Severidad:** 🟡 ALTA — Bloquea exportaciones legítimas.

---

### BUG #18 — IEPS (Impuesto Especial) se parsea pero nunca se incluye en DIOT

**Archivo:** `cfdi/parser.py:207-208`, `features/diot/service.py:47-86`

**Escenario:** Un CFDI de gasolina tiene IVA (002) + IEPS (003). El parser extrae `ieps` correctamente. Pero la DIOT solo incluye `iva_trasladado` y `iva_acreditable` — no hay campo para IEPS. El monto_neto de la DIOT no incluye IEPS.

**Resultado incorrecto:** La DIOT no reporta el IEPS correctamente. Para operaciones con IEPS, el monto_neto de la DIOT debe ser la base sin IVA ni IEPS, pero el parser mezcla todo en subtotal.

**Fix:** La DIOT es solo para IVA, así que esto es parcialmente correcto. Pero el sistema debe advertir que el CFDI tiene IEPS para que se reporte en la declaración de IEPS aparte.

**Severidad:** 🟡 MEDIA — IEPS requiere declaración separada que el sistema no maneja.

---

### BUG #19 — IVA rate check: valida contra 0.16% no contra 16% — error de magnitud

**Archivo:** `features/declaraciones/validators.py:170-176`

**Escenario:** El validador de IVA intenta verificar que `iva_cobrado` sea múltiplo de 16%:
```python
remainder = round(iva_cobrado % 0.16, 4)
```
Esto calcula `iva_cobrado % 0.16` — el residuo de dividir entre 0.16. Para `iva_cobrado = $160.00`: `160 % 0.16 = 0.0`. Correcto.

Pero para `iva_cobrado = $16.00`: `16 % 0.16 = 0.0`. También correcto.
Para `iva_cobrado = $16.01`: `16.01 % 0.16 ≈ 0.01`. Esto pasa el check (`remainder != 0` pero `remainder <= 0.01`).

**Problema real:** El check es un "soft check" que nunca bloquea. Pero el comment dice "check if cobrado looks like a 16% multiple" — esto no tiene sentido porque IVA cobrado no necesita ser múltiplo de 16% del subtotal. Es el SUBTOTAL × 16% lo que da el IVA, no el IVA mismo.

**Resultado incorrecto:** El check no hace nada útil. Si el usuario pone `iva_cobrado = $999` para un subtotal de $100, el check pasa porque `999 % 0.16 = algo < 0.01`. No detecta IVA incorrecto.

**Fix:** Eliminar este check engañoso o reemplazarlo con: `abs(iva_cobrado - subtotal * 0.16) < tolerance`.

**Severidad:** 🟡 MEDIA — Validación inútil que da falsa confianza.

---

## 5. Conciliación

### BUG #20 — Comparación exacta de float: $1,000.10 ≠ $1,000.1 en Python

**Archivo:** `features/conciliacion/service.py:196`, `features/conciliacion/service.py:338`

**Escenario:** El matching exacto usa:
```python
if txn.amount == pol.monto and txn.date == pol.fecha:
```
`txn.amount` viene del CSV del banco como string → float. `pol.monto` viene de la DB como float. Si el banco reporta `1000.1` y la póliza tiene `1000.10`, Python los considera iguales (ambos son `1000.1` como float). Pero si hay redondeo intermedio (banco reporta `1000.095` que se redondea a `1000.10` vs póliza `1000.10`), la comparación puede fallar por precisión de punto flotante.

**Resultado incorrecto:** Transacciones que SÍ coinciden se marcan como no conciliadas. El contador pierde tiempo investigando "discrepancias" que no existen.

**Fix:** Usar tolerancia absoluta:
```python
if abs(txn.amount - pol.monto) < 0.01 and txn.date == pol.fecha:
```

**Severidad:** 🟡 ALTA — Genera falsos positivos en conciliación.

---

### BUG #21 — CSV con comas en montos ($1,000.50) rompe parsing

**Archivo:** `features/conciliacion/` — NO hay parser de CSV implementado

**Escenario:** Los bancos mexicanos (BBVA, Banorte, HSBC) exportan estados de cuenta en CSV con montos formateados: `"$1,000.50"` o `"1,000.50"`. El sistema espera objetos `BankTransaction` pre-parseados, pero no hay código que convierta CSV crudo del banco.

**Resultado incorrecto:** El usuario debe convertir manualmente el CSV a JSON. Si intenta usar CSV directamente, `"$1,000.50"` se parsea como string inválido, no como float 1000.50. Los montos con comas se rompen.

**Fix:** Implementar parser de CSV bancario con auto-detección de formato:
```python
def parse_amount(raw: str) -> float:
    cleaned = raw.replace("$", "").replace(",", "").strip()
    return float(cleaned)
```

**Severidad:** 🟡 ALTA — Conciliación inutilizable sin parser de CSV.

---

### BUG #22 — Detección de duplicados: misma cantidad + mismo día = falso positivo

**Archivo:** `features/conciliacion/service.py:453-470`

**Escenario:** Dos transacciones legítimas del mismo monto el mismo día:
- Pago proveedor A: $5,000 el 15-ene
- Pago proveedor B: $5,000 el 15-ene

El detector de duplicados usa `(amount, date)` como key y las marca como duplicadas.

**Resultado incorrecto:** El sistema propone revertir una de las dos transacciones. Si el contador acepta la recomendación sin revisar, pierde un pago legítimo.

**Fix:** Incluir referencia/descripción en el key de duplicados, y solo marcar como duplicado si TODOS los campos coinciden (no solo monto+fecha).

**Severidad:** 🟡 ALTA — Puede causar reversión de pagos legítimos.

---

### BUG #23 — PDF de banco: no hay parser implementado

**Archivo:** Todo el módulo `features/conciliacion/`

**Escenario:** Algunos bancos (Banorte, HSBC) solo ofrecen estados de cuenta en PDF. El sistema solo acepta objetos `BankTransaction` ya estructurados.

**Resultado incorrecto:** Conciliación inutilizable para clientes de estos bancos. No hay endpoint para subir PDF.

**Fix:** Implementar extracción de PDF (pdfplumber/tabula) o al menos rechazar con mensaje claro.

**Severidad:** 🟡 MEDIA — Limita la base de clientes potenciales.

---

## 6. Clasificación

### BUG #24 — Clasificación incorrecta se envía al ERP sin rollback posible

**Archivo:** `services/classify.py`, `services/pipeline.py`

**Escenario:** El pipeline es: parse → validate → classify → send to ERP. Una vez que la póliza se envía a CONTPAQi/Aspel, no hay mecanismo de rollback. Si la clasificación es incorrecta (ej: $500K de maquinaria clasificado como "gasto_operativo" en vez de "activo_fijo"), la póliza queda registrada.

**Resultado incorrecto:** Activo fijo no se depreció. Gasto operativo inflado. Si el SAT audita, el contribuyente no puede justificar la clasificación. Con 5% de error en clasificación y 1000 CFDIs/mes: 50 pólizas incorrectas/mes.

**Fix:** No enviar al ERP cuando `requires_human_review=True`. Crear borrador primero.

**Severidad:** 🔴 CRÍTICA — Envía datos incorrectos al sistema contable.

---

### BUG #25 — Categoría "desconocido" no escala a revisor humano

**Archivo:** `services/classify.py:91-93`

**Escenario:** El clasificador retorna `"desconocido"` con `requires_human_review=True`. Pero no hay sistema de notificación: no email, no ticket, no cola de revisión. Los CFDIs desconocidos se acumulan silenciosamente.

**Resultado incorrecto:** Un tenant que procesa 100 CFDIs/día con 10% desconocidos acumula 300 CFDIs pendientes/mes. Nadie los revisa hasta que el SAT pregunta.

**Fix:** Implementar cola de revisión con notificación al contador.

**Severidad:** 🟡 ALTA — Acumulación silenciosa de trabajo pendiente.

---

### BUG #26 — Keywords substring: "desarrollo de software" matchea "inversión" Y "activo fijo"

**Archivo:** `services/classify.py:68`

**Escenario:** El clasificador usa `if w in texto` (substring match). Para un CFDI de "Licencia de software anual":
- "activo_fijo": matchea "licencia perpetua" (por "licencia")
- "inversion": matchea "licencia anual" (por "licencia")

Ambas categorías suman score → empate → `requires_human_review=True` con confianza 0.30.

**Resultado incorrecto:** CFDIs claros de software se marcan como ambiguos y requieren revisión manual. El 40%+ de CFDIs de tecnología pueden caer en este caso.

**Fix:** Usar word boundaries: `re.search(r'\b' + re.escape(w) + r'\b', texto)`.

**Severidad:** 🟡 MEDIA — Genera ruido pero el flag de revisión mitiga.

---

## 7. Multi-tenant

### BUG #27 — Contexto de tenant compartido entre requests (no thread-safe)

**Archivo:** `features/multi_tenant/service.py:92,438`

**Escenario:** FastAPI usa async y comparte la instancia de `MultiTenantService` entre requests:
```python
# En module level:
_default_service: Optional[MultiTenantService] = None
def _get_service() -> MultiTenantService:
    global _default_service
    if _default_service is None:
        _default_service = MultiTenantService()
    return _default_service
```
`self._current_context` es un atributo de instancia. Dos requests simultáneos:
1. Request A (tenant_A): `switch_tenant_context("tenant_A")`
2. Request B (tenant_B): `switch_tenant_context("tenant_B")`
3. Request A: `get_current_context()` → retorna **tenant_B** ❌

**Resultado incorrecto:** Tenant A accede a datos de Tenant B. Violación de aislamiento de datos. En contexto fiscal: un contribuyente ve facturas, RFCs y nóminas de otro. Violación de LFPDPPP.

**Fix:** Usar `contextvars.ContextVar`:
```python
import contextvars
_tenant_ctx = contextvars.ContextVar('tenant_ctx', default=None)
```

**Severidad:** 🔴 CRÍTICA — Violación de aislamiento de datos fiscales.

---

### BUG #28 — Stores en memoria: restart del servidor pierde TODO

**Archivo:** `features/multi_tenant/service.py:88-91`, `features/diot/service.py:40`, `features/declaraciones/service.py:81-82`, `features/devolucion_iva/service.py:50-52`

**Escenario:** TODOS los servicios usan dicts en memoria:
```python
self._declaraciones: Dict[str, Declaracion] = {}
self._deadlines: Dict[str, Deadline] = {}
_tenants: Dict[str, Tenant] = {}
_reports: Dict[str, DiotReport] = {}
_solicitudes: Dict[str, SolicitudDevolucion] = {}
```

**Resultado incorrecto:** Cada deploy, restart, o crash pierde: declaraciones fiscales, deadlines, solicitudes de devolución, reportes DIOT, configuración de tenants, y jobs de batch. Un deploy durante la temporada de declaraciones puede perder deadlines críticos.

**Fix:** Persistir en la DB que ya existe en `db/`.

**Severidad:** 🔴 CRÍTICA — Pérdida total de estado fiscal en cada restart.

---

## 8. Límites / Escalabilidad

### BUG #29 — Batch de 1000 CFDIs: carga todo en memoria antes de procesar

**Archivo:** `api/v2.py:300-338`

**Escenario:** `_process_batch_items` itera secuencialmente y acumula resultados:
```python
raw = []
for p in paths:
    raw.append(_process_one(tenant_id, p, dbx))
```
Cada `process_file` carga el XML completo en memoria. Para 1000 XMLs de 1MB = 1GB de RAM mínimo.

**Resultado incorrecto:** OOM en producción con batches grandes. El job async falla silenciosamente (el except en `_run_job` solo guarda el error, no notifica).

**Fix:** Procesar en chunks de 50 con limpieza de memoria entre chunks.

**Severidad:** 🔴 CRÍTICA — Batch grande causa OOM.

---

### BUG #30 — Jobs async se acumulan en memoria (memory leak)

**Archivo:** `api/v2.py:94-118`

**Escenario:** `_JOBS` es un dict global que nunca se limpia. Cada batch agrega resultados completos. Con 100 batches/día × 1000 resultados × ~1KB = ~100MB/día.

**Resultado incorrecto:** Memory leak gradual. En 30 días: ~3GB de jobs acumulados. El servidor se queda sin RAM.

**Fix:** TTL para jobs completados (24h), purgar periódicamente.

**Severidad:** 🟡 ALTA — Memory leak gradual pero inevitable.

---

### BUG #31 — Thread por batch: sin pool de workers, sin backpressure

**Archivo:** `api/v2.py:378-382`

**Escenario:** Cada batch crea un `threading.Thread` nuevo. 10 batches concurrentes = 10 threads × ~200MB RAM cada uno = 2GB.

**Resultado incorrecto:** Sin límite de concurrencia, el servidor puede crear 100+ threads, cada uno consumiendo RAM para sus XMLs.

**Fix:** `ThreadPoolExecutor(max_workers=4)` con queue.

**Severidad:** 🟡 ALTA — Escalabilidad rota.

---

## 9. Fechas

### BUG #32 — Nómina quincenal que cruza año: FechaPago fuera de rango

**Archivo:** `features/nomina/validators.py:113-138`

**Escenario:** Nómina quincenal de diciembre:
- FechaInicialPago: 2024-12-16
- FechaFinalPago: 2024-12-31
- FechaPago: 2025-01-01 (se pagó el 1 de enero)

El validador rechaza: `FechaPago (2025-01-01) está fuera del rango [2024-12-16, 2024-12-31]`.

**Resultado incorrecto:** Nóminas legítimas pagadas el primer día hábil de enero se rechazan. Esto es MUY común en la práctica.

**Fix:** Permitir FechaPago hasta 3 días después de FechaFinalPago (tolerancia bancaria).

**Severidad:** 🔴 CRÍTICA — Bloquea nóminas reales de fin de año.

---

### BUG #33 — Diciembre 31 a medianoche: timezone del servidor vs contribuyente

**Archivo:** `features/declaraciones/service.py:159`

**Escenario:** `days_remaining = (deadline_date - date.today()).days` usa `date.today()` que depende de la timezone del servidor. Si el servidor está en UTC:
- 31-dic 23:59 CST = 01-ene 05:59 UTC
- `date.today()` en UTC retorna 2025-01-01
- `days_remaining = (2025-01-17) - (2025-01-01) = 16 días`
- Pero el contribuyente en México todavía está en 2024 → debería ser 17 días

**Resultado incorrecto:** El deadline muestra un día menos de lo real. Si el sistema envía recordatorios basado en esto, el contador recibe el aviso un día tarde.

**Fix:** Usar timezone de México: `datetime.now(ZoneInfo("America/Mexico_City")).date()`.

**Severidad:** 🟡 BAJA — Off-by-one en días restantes.

---

### BUG #34 — Periodos fiscales cruzados: ISR provisional de diciembre vs anual

**Archivo:** `features/declaraciones/service.py:498-542`

**Escenario:** `calculate_dual_isr` calcula ISR anual definitivo:
```python
isr_definitivo = max(0, isr_anual - pagos_provisionales_acumulados)
```
Pero no valida que `pagos_provisionales_acumulados` corresponda al mismo año. Si el usuario pasa provisionales de 2024 + 2025 mezclados, el definitivo se calcula mal.

**Resultado incorrecto:** ISR definitivo incorrecto → declaración anual errónea → el SAT rechaza o genera diferencias.

**Fix:** Validar que los provisionales correspondan al año de la declaración.

**Severidad:** 🟡 MEDIA — Error de usuario pero el sistema debería prevenirlo.

---

### BUG #35 — Fecha de timbrado vs fecha de emisión: sin validación de plazo SAT

**Archivo:** `cfdi/validator.py:263-267`

**Escenario:** El validador verifica que `FechaTimbrado >= Fecha` (correcto). Pero no verifica el plazo del SAT: un CFDI debe timbrarse dentro de las 72 horas siguientes a su emisión (Regla 2.7.1.35 RMF). Un CFDI emitido el 1 de enero y timbrado el 1 de marzo es inválido.

**Resultado incorrecto:** CFDIs tardíamente timbrados pasan validación. Si el SAT los rechaza por plazo vencido, el contribuyente pierde la deducción.

**Fix:** Agregar: `if (f_timb - f_emi).days > 3: warning("CFDI timbrado fuera de plazo (72h)")`.

**Severidad:** 🟡 BAJA — Es un warning, no un rechazo automático del SAT.

---

## Resumen de Severidad

| Severidad | Cantidad | Bugs |
|-----------|----------|------|
| 🔴 CRÍTICA | 13 | #1, #4, #6, #9, #10, #13, #14, #24, #27, #28, #29, #32 |
| 🟡 ALTA | 13 | #2, #3, #5, #7, #11, #16, #17, #20, #21, #22, #25, #30, #31 |
| 🟡 MEDIA | 7 | #8, #15, #18, #19, #23, #26, #34 |
| 🟡 BAJA | 4 | #12, #33, #35, #8 |

### Top 5 más peligrosos:

1. **#27 — Cross-tenant data leak** — Violación LFPDPPP, multas de $100M-$320M MXN
2. **#10 — Tablas ISR hardcodeadas × 3** — Afecta TODOS los cálculos al cambiar de año
3. **#13/#14 — IMSS en cero + subsidio desincronizado** — Nóminas incorrectas para TODOS los empleados
4. **#32 — Nómina fin de año rechazada** — Bloquea pagos reales de diciembre
5. **#24 — Clasificación sin rollback al ERP** — Pólizas incorrectas permanentes en contabilidad
