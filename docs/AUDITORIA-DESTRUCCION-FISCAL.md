# 🧨 AUDITORÍA DE DESTRUCCIÓN — FISCAL + EDGE CASES

> **Fecha:** 2026-08-01
> **Objetivo:** Encontrar bugs que causarían datos incorrectos, rechazo del SAT, o pérdida de dinero real en producción.
> **Métodología:** Lectura de código fuente completo de `b2b_ai/` — parser, validadores, servicios, API.

---

## Índice

1. [CFDI Parsing](#1-cfdi-parsing)
2. [Nómina](#2-nómina)
3. [ISR / IMSS / Subsidio](#3-isr--imss--subsidio)
4. [IVA / IEPS / DIOT](#4-iva--ieps--diot)
5. [Conciliación Bancaria](#5-conciliación-bancaria)
6. [Clasificación Contable](#6-clasificación-contable)
7. [Multi-tenant](#7-multi-tenant)
8. [Límites y Escalabilidad](#8-límites-y-escalabilidad)
9. [Fechas y Periodos Fiscales](#9-fechas-y-periodos-fiscales)
10. [Resumen de Severidad](#10-resumen-de-severidad)

---

## 1. CFDI Parsing

### BUG-CFDI-001: XML enorme causa OOM (Memory Exhaustion)

**Archivo:** `cfdi/parser.py:86` / `features/nomina/parser.py:176`

**Escenario:** Un CFDI malicioso o corrupto de 500MB+ se sube al endpoint `/nomina/parse` o `/api/v2/batch`. `etree.parse(xml_path)` y `etree.fromstring(xml_bytes)` cargan el XML completo en memoria.

**Resultado incorrecto:** El proceso del worker se queda sin memoria (OOM), el contenedor se reinicia, y todos los CFDIs en procesamiento paralelo se pierden sin reportar error al usuario. Si esto se hace en batch de 1000 archivos, un solo XML malicioso tumbaría todo el lote.

**Fix:**
```python
MAX_XML_SIZE = 10 * 1024 * 1024  # 10 MB

def parse_cfdi(xml_path):
    size = os.path.getsize(xml_path)
    if size > MAX_XML_SIZE:
        raise CFDIError(f"XML excede {MAX_XML_SIZE // (1024*1024)}MB: {size}")
    # ... resto del parseo
```

Para bytes: validar `len(xml_bytes) > MAX_XML_SIZE` antes de `etree.fromstring()`.

**Severidad:** 🔴 CRÍTICA — Un adversario puede tumbar el servicio con un solo archivo.

---

### BUG-CFDI-002: Sin manejo de encoding — XMLs en ISO-8859-1 o Windows-1252 fallan

**Archivo:** `cfdi/parser.py:86`, `features/nomina/parser.py:231`

**Escenario:** Muchos PACs y ERPs mexicanos generan XMLs con `encoding="ISO-8859-1"` o `encoding="Windows-1252"` (acentos en nombres, descripciones con ñ). `etree.fromstring()` falla silenciosamente o decodifica mal caracteres como Ñ, á, é.

**Resultado incorrecto:** RFCs y nombres con caracteres especiales se corrompen. El validador de RFC rechaza un RFC válido "PEÑA1234567" porque se parsea como "PEï¿½A1234567". Las descripciones de conceptos se pierden, causando clasificación incorrecta.

**Fix:**
```python
def parse_cfdi_bytes(xml_bytes: bytes):
    # Detect encoding from XML declaration
    head = xml_bytes[:200].decode('ascii', errors='ignore')
    encoding_match = re.search(r'encoding=["\']([^"\']+)', head)
    encoding = encoding_match.group(1) if encoding_match else 'utf-8'
    try:
        text = xml_bytes.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        text = xml_bytes.decode('utf-8', errors='replace')
    root = etree.fromstring(text.encode('utf-8'))
```

**Severidad:** 🔴 CRÍTICA — Silently corrupt data on valid CFDIs.

---

### BUG-CFDI-003: Sin soporte para CFDI Globales (TipoDeComprobante con múltiples receptores)

**Archivo:** `cfdi/parser.py:91-93`

**Escenario:** El parser valida que el root sea `Comprobante`, pero no maneja CFDIs globales donde TipoDeComprobante es "I" pero el Receptor es el público en general (RFC genérico "XAXX010101000"). Tampoco detecta si es un CFDI de exportación (Exportacion="02") que tiene reglas de IVA diferentes.

**Resultado incorrecto:** CFDIs de público en general se procesan normalmente, el IVA del 16% se reporta como acreditable cuando NO lo es (Art. 5-B LIVA). CFDIs de exportación (tasa 0%) se rechazan por el validador de IVA que espera 16%.

**Fix:** Detectar RFC genéricos y exportaciones en el validador y marcar IVA como no acreditable.

**Severidad:** 🟡 ALTA — Error fiscal silencioso, puede causar rechazo del SAT en devolución de IVA.

---

### BUG-CFDI-004: Notas de Crédito (TipoDeComprobante=E) no se manejan en conciliación

**Archivo:** `cfdi/parser.py:100`, `features/conciliacion/service.py`

**Escenario:** Una nota de crédito (TipoDeComprobante="E") reduce el monto de una factura original. El parser la extrae correctamente, pero la conciliación bancaria no la relaciona con la factura original. El matching algorítmico (EXACT, AMOUNT_DATE) no tiene lógica para emparejar notas de crédito con facturas.

**Resultado incorrecto:** Notas de crédito quedan como "unmatched_bank" o "unmatched_polizas". El contador ve discrepancias fantasma. Si la nota de crédito es grande, el reporte de conciliación sugiere crear pólizas de ajuste innecesarias.

**Fix:** Agregar lógica para vincular CfdiRelacionados.UUID con la factura original, y tratar notas de crédito como ajustes negativos en la conciliación.

**Severidad:** 🟡 ALTA — Conciliación incorrecta genera trabajo manual innecesario.

---

### BUG-CFDI-005: CfdiRelacionados pierde TipoRelacion

**Archivo:** `cfdi/parser.py:222-225`

**Escenario:** El parser solo extrae UUID de CfdiRelacionado pero ignora el atributo `TipoRelacion` del nodo padre `CfdiRelacionados`. Este campo es obligatorio para saber si es una sustitución, nota de crédito, factura generada por pagos, etc.

**Resultado incorrecto:** Sin TipoRelacion, no se puede saber si un CFDI sustituye a otro (debe cancelar el anterior). Si el SAT recibe ambos como activos, genera multas por doble deducción.

**Fix:**
```python
for node in root.iter():
    if _localname(node) == "CfdiRelacionados":
        tipo_rel = node.get("TipoRelacion", "")
        for child in node:
            if _localname(child) == "CfdiRelacionado":
                relacionados.append({
                    "uuid": child.get("UUID", ""),
                    "tipo_relacion": tipo_rel,
                })
```

**Severidad:** 🟡 ALTA — Pérdida de metadatos fiscales obligatorios.

---

## 2. Nómina

### BUG-NOM-001: Salario diario = 0 no se rechaza

**Archivo:** `features/nomina/validators.py`, `services/payroll.py:465`

**Escenario:** Un CFDI de nómina llega con `SalarioDiarioIntegrado="0"` o `SalarioDiarioIntegrado=""`. El parser retorna `None` (vía `_dec`), y el validador no tiene ninguna regla que rechace salarios en cero o nulos. `calculate_payroll` con `salario_diario=0` produce todos los cálculos en 0.

**Resultado incorrecto:** Una nómina de $0 se acepta como válida. Si el patrón está declarando nóminas en cero para evadir IMSS/INFONAVIT, el sistema no alerta. El SAT rechaza el CFDI porque `NumDiasPagados > 0` con `TotalPercepciones = 0` viola el Anexo 20.

**Fix:** Agregar validación:
```python
def validate_salario(data: NominaData) -> List[str]:
    errors = []
    if data.salario_diario_integrado is not None and data.salario_diario_integrado <= 0:
        errors.append("SalarioDiarioIntegrado debe ser mayor a 0.")
    return errors
```

**Severidad:** 🔴 CRÍTICA — Acepta nóminas inválidas que el SAT rechazará.

---

### BUG-NOM-002: NumDiasPagados > 31 aceptado sin error

**Archivo:** `features/nomina/validators.py:141-162`

**Escenario:** El validador compara NumDiasPagados contra los días naturales del periodo `(fecha_fin - fecha_inicio).days + 1`. Para un periodo de quincena (15 días), NumDiasPagados=15 es correcto. Pero si alguien pone NumDiasPagados=999 con un periodo de un mes, el validador solo rechaza si > días naturales (max 31). Un periodo de 31 días acepta 31 días pagados.

**Problema real:** Para nóminas extraordinarias (TipoNomina="E"), NumDiasPagados puede ser 0 o un valor especial que indica "periodo irregular". El validador actual rechaza `NumDiasPagados <= 0` con `"debe ser mayor a 0"`, lo cual es incorrecto para nóminas extraordinarias de aguinaldo o liquidación que pueden tener 0 días de periodo laborado.

**Resultado incorrecto:** Nóminas extraordinarias de aguinaldo (15 días de aguinaldo sin días laborados en el periodo) se rechazan falsamente.

**Fix:** Permitir NumDiasPagados=0 cuando TipoNomina="E".

**Severidad:** 🟡 ALTA — Rechaza nóminas válidas de aguinaldo y liquidación.

---

### BUG-NOM-003: Aguinaldo proporcional usa 365 días — ignora años bisiestos

**Archivo:** `services/payroll.py:367`

**Escenario:** Un empleado que trabajó todo 2024 (año bisiesto: 366 días) pide su aguinaldo proporcional. `calc_aguinaldo` calcula: `salario_diario × 15 × (dias_trabajados / 365)`. Si trabajó 366 días, la fracción es `366/365 = 1.0027`, lo que da un aguinaldo MAYOR al de ley (15 días completos).

**Resultado incorrecto:** En un año bisiesto, el aguinaldo proporcional supera el aguinaldo completo. Para un salario de $1,000/día: aguinaldo completo = $15,000, pero proporcional con 366 días = $15,041.10. Diferencia de $41 que se paga de más. Multiplied por miles de empleados, es dinero real.

**Fix:**
```python
from calendar import isleap
year = datetime.now().year  # o el año del periodo
dias_año = 366 if isleap(year) else 365
monto = sd * dias_ley * (dt / Decimal(str(dias_año)))
```

**Severidad:** 🟡 MEDIA — Pérdida de dinero real pero pequeña por empleado.

---

### BUG-NOM-004: Tabla de subsidio 2025 mezclada con tabla ISR 2024

**Archivo:** `services/payroll.py:71` (SUBSIDIO 2025) vs `features/declaraciones/service.py:47` (ISR 2024) vs `services/payroll.py:29` (ISR 2024)

**Escenario:** Las tablas están hardcodeadas y versionadas manualmente. `payroll.py` tiene ISR 2024 + Subsidio 2025. `declaraciones/service.py` tiene ISR 2024. `compliance.py` tiene ISR 2024. Cuando cambie el año fiscal, hay que actualizar 3+ archivos diferentes.

**Resultado incorrecto:** Si se actualiza la tabla ISR a 2025 pero se olvida el subsidio (o vice versa), el cálculo de nómina produce ISR incorrecto + subsidio incorrecto = neto doblemente incorrecto. Para un empleado con salario de $8,000/mes, la diferencia puede ser de $200-500/mes.

**Fix:** Centralizar las tablas fiscales en un solo archivo con versionado por año:
```python
# fiscal_tables.py
TABLES = {
    2024: {"isr_monthly": [...], "isr_annual": [...], "subsidio": [...]},
    2025: {"isr_monthly": [...], "isr_annual": [...], "subsidio": [...]},
}
def get_tables(year: int) -> dict:
    return TABLES.get(year) or TABLES[max(TABLES.keys())]
```

**Severidad:** 🔴 CRÍTICA — Error silencioso en cada nómina procesada.

---

## 3. ISR / IMSS / Subsidio

### BUG-ISR-001: Inconsistencia en bordes de tabla ISR entre módulos

**Archivo:** `features/declaraciones/service.py:544-582` vs `features/compliance.py:134-155`

**Escenario:** El módulo de declaraciones (`_apply_isr_table`) usa `< next_lower` para determinar el rango:
```python
if lower <= taxable_income < next_lower:  # declaraciones
```
Pero `compliance.py` usa `<= upper`:
```python
if lower <= taxable_income <= upper:  # compliance
```

**Resultado incorrecto:** Para un ingreso de exactamente $312.41 (borde del primer rango):
- `declaraciones` calcula: `0 + (312.41 - 0) × 0.0192 = $6.00`
- `compliance` calcula: `0 + (312.41 - 0) × 0.0192 = $6.00` ← mismo resultado porque el límite superior es `312.41`

Pero para $312.42:
- `declaraciones`: entra al rango `[312.42, 2636.29)` → `5.99 + (312.42 - 312.42) × 0.0640 = $5.99`
- `compliance`: entra al rango `[312.42, 2636.28]` → `5.99 + 0 = $5.99`

El problema es el gap: un ingreso de $2636.285 (entre 2636.28 y 2636.29) cae en rangos diferentes dependiendo del módulo. `declaraciones` lo pone en el rango 2 (correcto), `compliance` podría no matchear ningún rango (el upper del rango 2 es 2636.28 y el lower del rango 3 es 2636.29).

**Fix:** Estandarizar TODOS los módulos para usar la misma función de tabla ISR (extraer a un módulo común).

**Severidad:** 🟡 ALTA — Diferencias de centavos que se acumulan en miles de cálculos.

---

### BUG-ISR-002: Subsidio al empleo no se aplica en declaraciones anuales

**Archivo:** `features/declaraciones/service.py:498-542`

**Escenario:** `calculate_dual_isr` calcula ISR anual definitivo como `isr_anual - pagos_provisionales_acumulados`. Pero no tiene en cuenta el subsidio al empleo. Si un empleado tuvo subsidio durante el año (porque su ingreso mensual era < $13,340), los pagos provisionales retenidos ya incluyen la reducción por subsidio. Sin embargo, el cálculo anual no desglosa el subsidio.

**Resultado incorrecto:** El ISR definitivo anual puede resultar en un "saldo a favor" mayor al real, o en un "saldo en contra" si el subsidio acumulado no se contabiliza. Para un empleado con ingreso de $10,000/mes: subsidio mensual ≈ $209 × 12 = $2,508 de diferencia.

**Fix:** Agregar parámetro `subsidio_acumulado` al cálculo dual.

**Severidad:** 🟡 ALTA — Error en declaración anual de miles de empleados.

---

### BUG-ISR-003: ISR negativo no posible pero sí real en casos de subsidio excedente

**Archivo:** `services/payroll.py:487`

**Escenario:** El código calcula `isr_neto = max(0, isr_antes - subsidio)`. Esto es correcto para nómina, pero el `max(0)` oculta información importante: cuando `subsidio > isr_antes`, el trabajador recibe dinero EXTRA (subsidio en efectivo). El código actual calcula `subsidio_efectivo` pero NO lo resta de las deducciones ni lo suma a las percepciones.

**Resultado incorrecto:** El "neto a pagar" en el recibo de nómina es menor al real, porque el subsidio en efectivo no se contabiliza como ingreso adicional. Para un empleado con ISR de $150 y subsidio de $407: debería recibir sueldo - deducciones + $257 extra, pero el sistema solo muestra sueldo - deducciones + $0.

**Fix:** Agregar el subsidio en efectivo como OtroPago en las percepciones:
```python
if subsidio > isr_antes:
    subsidio_efectivo = subsidio - isr_antes
    otros_pagos["subsidio_empleo"] = _fmt(subsidio_efectivo)
```

**Severidad:** 🔴 CRÍTICA — El empleado recibe menos dinero del que le corresponde legalmente.

---

### BUG-ISR-004: IMSS calcula con 30 días fijos cuando no se especifica dias_pagados

**Archivo:** `services/payroll.py:226,470`

**Escenario:** `calc_imss` y `calculate_payroll` usan `dias_pagados = 30` por defecto. Para nóminas quincenales, debería ser 15. Para nóminas de 28 días (febrero), debería ser 28.

**Resultado incorrecto:** En nómina quincenal, el IMSS se calcula sobre 30 días en vez de 15, duplicando la retención al trabajador. Para un SBC de $500/día: IMSS quincenal correcto ≈ $187.50, pero el sistema cobra $375.00. Diferencia de $187.50 por nómina.

**Fix:** Hacer `dias_pagados` obligatorio (no default) y validar contra la periodicidad.

**Severidad:** 🔴 CRÍTICA — Retención doble en cada nómina quincenal.

---

### BUG-ISR-005: Ingresos muy altos (>$1M/mes) — Decimal precision OK pero float no

**Archivo:** `features/declaraciones/service.py:229-233`

**Escenario:** `generate_provisional_isr` usa `float()` para ingresos:
```python
ingresos = float(data.get("ingresos", 0))
utilidad = round(ingresos - deducciones, 2)
```
Para ingresos de $10,000,000.00, `float` tiene precisión de ~15 dígitos, así que $10,000,000.00 es exacto. Pero la resta `10000000.00 - 9999999.99 = 0.01000000000095` introduce error de punto flotante.

**Resultado incorrecto:** `round(0.01000000000095, 2) = 0.01` — correcto en este caso. Pero para operaciones encadenadas (ISR mensual acumulado × 12 meses), el error de float se propaga. Para una empresa con ingresos de $50M/mes, la diferencia acumulada puede ser de $50-100 al año.

**Fix:** Usar `Decimal` consistentemente en todo el módulo de declaraciones (igual que `payroll.py` ya hace).

**Severidad:** 🟢 BAJA — Diferencias centavos, pero incorrecto para auditoría.

---

## 4. IVA / IEPS / DIOT

### BUG-IVA-001: DIOT usa float para acumulación — pérdida de centavos

**Archivo:** `features/diot/service.py:49-86`

**Escenario:** `_aggregate_invoices` usa `float` para acumular montos:
```python
g["monto_neto"] += neto  # float + float = float impreciso
```
Para 10,000 facturas de $999.99 cada una, la suma exacta es $9,999,900.00. Con float, la suma puede dar $9,999,899.999999998 o $9,999,900.000000002. El `round(..., 2)` al final puede dar $9,999,900.00 o $9,999,899.99.

**Resultado incorrecto:** La DIOT reporta un monto que no coincide exactamente con la suma de facturas. El SAT cruza la DIOT contra los CFDIs timbrados y rechaza si hay diferencia, incluso de $0.01.

**Fix:** Usar `Decimal` para toda la acumulación en DIOT.

**Severidad:** 🔴 CRÍTICA — Rechazo del SAT en declaraciones DIOT.

---

### BUG-IVA-002: IVA acreditable > IVA trasladado no genera error

**Archivo:** `features/declaraciones/service.py:130-138`

**Escenario:** El servicio de declaraciones IVA calcula `saldo_favor = max(0, iva_pagado - iva_cobrado)`. Si `iva_pagado` (acreditable) = $500,000 e `iva_cobrado` (trasladado) = $100,000, se genera un saldo a favor de $400,000. Esto es legalmente posible (empresa en inversión), pero el sistema no genera ninguna alerta.

**Resultado incorrecto:** Un saldo a favor de $400,000 en un mes es una señal de alerta (posible esquema de facturación fantasma). El sistema lo acepta sin ninguna validación adicional. El SAT lo marca para auditoría, pero el sistema no lo anticipa.

**Fix:** Agregar umbral de alerta:
```python
if iva_pagado > iva_cobrado * 3:  # IVA pagado > 3× cobrado
    iva_data.requires_extra_validation = True
    iva_data.alert_reason = "IVA acreditable excede 3x IVA trasladado"
```

**Severidad:** 🟡 MEDIA — No es un bug per se, pero falta detección de anomalías.

---

### BUG-IVA-003: IEPS se parsea pero nunca se valida ni se reporta en DIOT

**Archivo:** `cfdi/parser.py:207-208`, `features/diot/`

**Escenario:** El parser extrae IEPS (impuesto="003") de los traslados globales. Pero el DIOT y las declaraciones de IVA no tienen ningún campo para IEPS. Un CFDI con IEPS (bebidas alcohólicas, combustibles, bebidas azucaradas) tiene IVA + IEPS que se suman al total, pero solo el IVA se reporta.

**Resultado incorrecto:** Si una gasolinera factura $100,000 con IVA $16,000 + IEPS $30,000, el DIOT solo reporta $16,000 de IVA trasladado. El IEPS de $30,000 es invisible. Esto es correcto para DIOT (que solo reporta IVA), pero el sistema NO valida que el IEPS esté siendo manejado por otro proceso.

**Fix:** Marcar CFDIs con IEPS para atención especial en el pipeline de clasificación.

**Severidad:** 🟢 BAJA — IEPS tiene su propio régimen, pero el sistema debería ser consciente.

---

### BUG-IVA-004: Tasa 0% se maneja como "no tiene IVA"

**Archivo:** `cfdi/validator.py:149-156`

**Escenario:** El validador compara IVA contra 16% del subtotal. Para una exportación (tasa 0%), IVA = $0 y subtotal = $100,000. El cálculo: `esperado = 100000 × 0.16 = $16,000`. `abs(0 - 16000) > 0.02` → WARNING.

**Resultado incorrecto:** Toda exportación genera un warning de "IVA global difiere de 16%". El warning es informativo, pero si el validador se usa como gate para determinar si un CFDI es válido para DIOT/devolución, una exportación podría ser rechazada incorrectamente.

**Fix:** No comparar contra 16% si TipoDeComprobante indica exportación o si alguna línea tiene TasaOCuota=0.

**Severidad:** 🟡 MEDIA — Genera falsos positivos que ruidan la validación.

---

## 5. Conciliación Bancaria

### BUG-CONC-001: Comparación exacta de float falla para montos bancarios

**Archivo:** `features/conciliacion/service.py:196,213,338,354`

**Escenario:** El matching EXACT usa `txn.amount == pol.monto`. Si el banco reporta `1000.10` y la póliza tiene `1000.10`, la comparación `1000.10 == 1000.10` funciona. Pero si el banco reporta `1000.1` (un decimal) y la póliza tiene `1000.10` (dos decimales), Python los considera iguales. Sin embargo, si hay redondeo intermedio (banco: `1000.095` redondeado a `1000.10`, póliza: `1000.10`), la comparación float puede fallar.

**Resultado incorrecto:** Facturas que SÍ coinciden se marcan como UNMATCHED, generando "discrepancias" fantasma que el contador debe investigar manualmente.

**Fix:** Usar tolerancia absoluta en vez de igualdad exacta:
```python
if abs(txn.amount - pol.monto) <= 0.01:  # tolerancia de 1 centavo
```

**Severidad:** 🟡 ALTA — Genera trabajo manual innecesario y pérdida de confianza en el sistema.

---

### BUG-CONC-002: CSV con comas en montos ($1,000.00) no se parsea

**Archivo:** `features/conciliacion/service.py` — NO hay parser de CSV de banco

**Escenario:** Los bancos mexicanos (BBVA, Banorte, Santander) exportan estados de cuenta en CSV con montos como `"1,000.00"` o `"$1,000.00"`. El servicio de conciliación espera objetos `BankTransaction` ya parseados, pero no hay código que convierta CSV del banco a estos objetos.

**Resultado incorrecto:** El usuario debe convertir manualmente el CSV del banco al formato JSON que espera el sistema. Si el CSV tiene comas como separador de miles Y como delimitador de columnas, la confusión es total: `"1,000.00"` se parsea como dos campos: `"1"` y `"000.00"`.

**Fix:** Implementar parser de CSV bancario con auto-detección de formato y manejo de separadores de miles.

**Severidad:** 🔴 CRÍTICA — El sistema es inútil sin importación automática de estados de cuenta.

---

### BUG-CONC-003: Detección de duplicados falsos positivos

**Archivo:** `features/conciliacion/service.py:453-470`

**Escenario:** La detección de duplicados usa `(amount, date)` como key. Dos pagos legítimos del mismo monto el mismo día (ej: dos proveedores diferentes cobran $5,000.00 el 15 de enero) se marcan como "transacciones duplicadas".

**Resultado incorrecto:** El sistema propone revertir una de las dos transacciones legítimas. Si el contador acepta la propuesta sin revisar, se pierde un pago real.

**Fix:** Agregar referencia/descripción al key de duplicados:
```python
key = (txn.amount, txn.date, txn.reference[:10] if txn.reference else "")
```
Y solo marcar como duplicado si TODOS los campos coinciden.

**Severidad:** 🟡 ALTA — Puede causar reversión de pagos legítimos.

---

### BUG-CONC-004: PDF corrupto no se maneja

**Archivo:** Todo el módulo de conciliación — NO hay parser de PDF

**Escenario:** Algunos bancos solo ofrecen estados de cuenta en PDF (Banorte, HSBC). El sistema no tiene ningún parser de PDF bancario.

**Resultado incorrecto:** El usuario no puede usar el sistema para conciliación con estos bancos. No hay error message, simplemente no hay funcionalidad.

**Fix:** Implementar extracción de PDF bancario (con `pdfplumber` o similar) o al menos un endpoint que acepte PDF y lo rechaze con un mensaje claro.

**Severidad:** 🟡 MEDIA — Limita la utilidad del sistema para ciertos bancos.

---

## 6. Clasificación Contable

### BUG-CLAS-001: Clasificación incorrecta se envía al ERP sin rollback

**Archivo:** `services/classify.py`, `services/pipeline.py`

**Escenario:** El pipeline procesa un CFDI así: parse → validate → classify → send to ERP. Si la clasificación es incorrecta (ej: un gasto de $500,000 clasificado como "gasto_operativo" cuando debería ser "activo_fijo"), la póliza ya se envió al ERP (CONTPAQi, Aspel, etc.).

**Resultado incorrecto:** No hay rollback. Una vez enviada al ERP, la póliza incorrecta queda registrada. El contador debe hacer una póliza de corrección manual. Si el sistema procesa 1000 CFDIs en batch y la clasificación tiene 5% de error, son 50 pólizas incorrectas.

**Fix:** Implementar "borrador" mode donde las pólizas se crean como DRAFT en el ERP y requieren aprobación antes de ser definitivas. O al menos, no enviar al ERP cuando `requires_human_review=True`.

**Severidad:** 🔴 CRÍTICA — Envía datos incorrectos a sistema contable externo sin posibilidad de revertir.

---

### BUG-CLAS-002: Keyword "investigacion" matchea "inversion" (substring collision)

**Archivo:** `services/classify.py:68`

**Escenario:** El clasificador usa `if w in texto` (substring match). La palabra "investigación" contiene "inversi" → NO matchea "inversion" (porque "inversi" ≠ "inversion"). Pero "desarrollo de software" matchea "desarrollo" y "software" por separado, lo cual es correcto.

El problema real es: "licencia de software" → matchea "activo_fijo" (por "licencia perpetua" vía substring "licencia") Y "inversion" (por "licencia anual" vía substring "licencia"). Esto crea un empate.

**Resultado incorrecto:** El clasificador retorna `requires_human_review=True` con confianza 0.30 para CFDIs que son claramente gastos operativos de software. El flujo se detiene esperando revisión humana para algo obvio.

**Fix:** Usar word boundaries en vez de substring: `if re.search(r'\b' + re.escape(w) + r'\b', texto)`.

**Severidad:** 🟡 MEDIA — Ruido en clasificación, pero el flag de revisión humana lo mitiga.

---

### BUG-CLAS-003: Categoría "desconocido" no escala a revisor humano automáticamente

**Archivo:** `services/classify.py:91-93`

**Escenario:** Cuando la categoría es "desconocido" (score=0), el sistema retorna `requires_human_review=True`. Pero no hay mecanismo para escalar al revisor: no se envía email, no se crea ticket, no se pone en cola de revisión.

**Resultado incorrecto:** Los CFDIs "desconocidos" se acumulan sin que nadie los revise. Si un tenant procesa 100 CFDIs/día y 10% son "desconocidos", en un mes hay 300 CFDIs pendientes de clasificación manual. El contador no tiene visibilidad de esta deuda.

**Fix:** Implementar cola de revisión con notificación al contador cuando hay > N CFDIs pendientes.

**Severidad:** 🟡 MEDIA — Acumulación silenciosa de trabajo pendiente.

---

## 7. Multi-tenant

### BUG-MT-001: Contexto de tenant no es thread-safe

**Archivo:** `features/multi_tenant/service.py:92,438`

**Escenario:** `self._current_context` es un atributo de instancia de `MultiTenantService`. En FastAPI con async, múltiples requests comparten la misma instancia del servicio (singleton via `_default_service`). Dos requests simultáneos de tenants diferentes:

1. Request A: `switch_tenant_context("tenant_A")` → `_current_context = TenantA`
2. Request B: `switch_tenant_context("tenant_B")` → `_current_context = TenantB`
3. Request A: `get_current_context()` → ¡retorna TenantB!

**Resultado incorrecto:** Tenant A ve los datos de Tenant B. Cross-tenant data leak. En un contexto fiscal, esto significa que un contribuyente ve facturas, RFCs y nóminas de otro contribuyente — violación de LFPDPPP (Ley Federal de Protección de Datos Personales).

**Fix:** Usar `contextvars.ContextVar` en vez de atributo de instancia:
```python
import contextvars
_current_context_var = contextvars.ContextVar('tenant_context', default=None)
```

**Severidad:** 🔴 CRÍTICA — Violación de aislamiento de datos fiscales entre contribuyentes.

---

### BUG-MT-002: Stores en memoria se pierden en restart

**Archivo:** `features/multi_tenant/service.py:88-91`, `features/diot/service.py:40`, `features/devolucion_iva/service.py:50-52`, `features/declaraciones/service.py:81-82`

**Escenario:** Todos los servicios usan dicts en memoria como store: `_tenants`, `_declaraciones`, `_deadlines`, `_reports`, `_solicitudes`, `_status`, `_papeles_trabajo`, `_JOBS`.

**Resultado incorrecto:** Si el servidor se reinicia (deploy, crash, OOM), TODOS los datos se pierden: tenants, declaraciones fiscales, solicitudes de devolución, reportes DIOT, jobs de batch. En un contexto fiscal, esto significa que declaraciones presentadas se pierden, deadlines se olvidan, y el historial de conciliación desaparece.

**Fix:** Persistir en base de datos (PostgreSQL) — el proyecto ya tiene `db/` con soporte PG.

**Severidad:** 🔴 CRÍTICA — Pérdida total de estado en cada reinicio.

---

### BUG-MT-003: Dos tenants procesan el mismo CFDI UUID simultáneamente

**Archivo:** `features/multi_tenant/service.py`, `api/v2.py`

**Escenario:** Dos tenants comparten el mismo proveedor (RFC del emisor). El proveedor emite un CFDI con UUID X. Tenant A lo procesa primero y lo guarda en su esquema. Tenant B lo procesa después.

**Resultado incorrecto:** No hay conflicto porque cada tenant tiene su propio store/DB. Pero si ambos tenants reportan el mismo UUID X en su DIOT, el SAT detecta el UUID duplicado y rechaza ambas DIOTs. El sistema no detecta este escenario.

**Fix:** Implementar validación cross-tenant de UUIDs para detectar duplicados antes de presentar DIOT.

**Severidad:** 🟡 MEDIA — Edge case raro pero posible con proveedores compartidos.

---

## 8. Límites y Escalabilidad

### BUG-LIM-001: Batch de 1000 CFDIs — sin streaming, carga todo en memoria

**Archivo:** `api/v2.py:300-338`

**Escenario:** `_process_batch_items` itera sobre todos los paths y acumula resultados en una lista `raw`. Para 1000 CFDIs de ~1MB cada uno, se cargan ~1GB de XML en memoria simultáneamente (antes de que `process_file` termine y libere).

**Resultado incorrecto:** OOM en el worker. El batch falla a la mitad sin reportar qué archivos se procesaron y cuáles no.

**Fix:** Procesar en chunks de 50-100 archivos, con streaming de resultados:
```python
for chunk in chunks(validated_paths, 50):
    for p in chunk:
        result = _process_one(tenant_id, p, dbx)
        yield result  # stream results
```

**Severidad:** 🔴 CRÍTICA — Batch de producción causa OOM.

---

### BUG-LIM-002: Jobs async se acumunan en memoria — memory leak

**Archivo:** `api/v2.py:94-118`

**Escenario:** `_JOBS` es un dict global que nunca se limpia. Cada batch async agrega un job con todos sus resultados. Para 100 batches/día × 1000 resultados × ~1KB cada uno = ~100MB/día de jobs acumulados. En un mes: ~3GB.

**Resultado incorrecto:** Memory leak gradual. El servidor se queda sin memoria después de semanas de operación.

**Fix:** Agregar TTL para jobs completados:
```python
def _cleanup_old_jobs(max_age_hours=24):
    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    with _JOBS_LOCK:
        for jid, job in list(_JOBS.items()):
            if job["status"] in ("completed", "error") and job["created_at"] < cutoff.isoformat():
                del _JOBS[jid]
```

**Severidad:** 🟡 ALTA — Memory leak gradual pero inevitable.

---

### BUG-LIM-003: Thread-per-batch no escala — sin pool de workers

**Archivo:** `api/v2.py:378-382`

**Escenario:** Cada batch async crea un `threading.Thread` nuevo. Para 10 batches concurrentes, hay 10 threads procesando 10,000 CFDIs simultáneamente.

**Resultado incorrecto:** Sin pool de workers, no hay backpressure. El servidor puede crear 100+ threads, cada uno consumiendo ~200MB de memoria para sus XMLs. Total: 20GB de RAM para batch processing.

**Fix:** Usar `concurrent.futures.ThreadPoolExecutor(max_workers=4)` con queue.

**Severidad:** 🟡 ALTA — Escalabilidad limitada en producción.

---

## 9. Fechas y Periodos Fiscales

### BUG-FECH-001: Nómina que cruza año fiscal — periodo incorrecto

**Archivo:** `features/nomina/validators.py:113-138`

**Escenario:** Una nómina quincenal con FechaInicialPago="2024-12-16" y FechaFinalPago="2024-12-31", pero FechaPago="2025-01-01" (se pagó el 1 de enero). El validador rechaza porque `FechaPago > FechaFinalPago`. Esto es correcto para nóminas ordinarias, pero ¿qué pasa con la declaración fiscal?

**Problema real:** La nómina se emitió en 2024 pero se pagó en 2025. ¿Se reporta en la DIOT de diciembre 2024 o enero 2025? El CFDI se timbra con fecha de emisión 2024, pero el pago es 2025. El sistema no tiene lógica para asignar el periodo fiscal correcto.

**Resultado incorrecto:** Si la DIOT se genera por mes de emisión, la nómina va a diciembre 2024. Si se genera por mes de pago, va a enero 2025. El sistema no define cuál es correcto, lo que puede causar inconsistencias DIOT vs declaraciones.

**Fix:** Documentar y aplicar la regla fiscal: la nómina se reporta en el periodo de la FechaPago (LISR art. 96).

**Severidad:** 🟡 MEDIA — Ambigüedad que puede causar inconsistencias.

---

### BUG-FECH-002: 31 de diciembre a medianoche — deadline calculation off-by-one

**Archivo:** `features/declaraciones/service.py:141-144`

**Escenario:** El 31 de diciembre de 2024 a las 23:59:59, alguien genera una declaración de IVA de diciembre 2024. El deadline se calcula como:
```python
if month == 12:
    deadline_date = date(year + 1, 1, 17)  # 2025-01-17
```
Esto es correcto. Pero `days_remaining = (deadline_date - date.today()).days` usa `date.today()` que depende de la timezone del servidor.

**Resultado incorrecto:** Si el servidor está en UTC y el usuario en CST (UTC-6), a las 23:59 CST el servidor ve 05:59 del 1 de enero. `date.today()` retorna 2025-01-01. `days_remaining = (2025-01-17 - 2025-01-01).days = 16`. Pero debería ser 17 (el usuario aún está en diciembre).

**Fix:** Usar la timezone del contribuyente (México CST/CDT):
```python
from zoneinfo import ZoneInfo
today = datetime.now(ZoneInfo("America/Mexico_City")).date()
```

**Severidad:** 🟢 BAJA — Off-by-one en días restantes, no afecta el deadline real.

---

### BUG-FECH-003: Periodo fiscal anual no maneja ISR provisional acumulado de 13 pagos

**Archivo:** `features/declaraciones/service.py:498-542`

**Escenario:** Algunas empresas pagan nómina 13 veces al año (12 mensuales + un extraordinario). El ISR provisional acumulado debería sumar 13 pagos, pero el sistema solo espera 12 (meses del año). Si se suman 13 provisionales, el ISR definitivo anual puede dar negativo (saldo a favor) inesperadamente.

**Resultado incorrecto:** El sistema genera un "saldo a favor" de ISR que no es real — simplemente se retuvo más de lo necesario por el pago extra.

**Fix:** Validar que `pagos_provisionales_acumulados` no exceda el ISR anual por más de un pago provisional (tolerancia para el 13er pago).

**Severidad:** 🟢 BAJA — Edge case para empresas con nómina extraordinaria.

---

## 10. Resumen de Severidad

| Severidad | Count | Bugs |
|-----------|-------|------|
| 🔴 CRÍTICA | 10 | CFDI-001, CFDI-002, NOM-001, NOM-004, ISR-003, ISR-004, IVA-001, CLAS-001, MT-001, MT-002, LIM-001, CONC-002 |
| 🟡 ALTA | 11 | CFDI-003, CFDI-004, CFDI-005, NOM-002, ISR-001, ISR-002, CONC-001, CONC-003, CLAS-002, LIM-002, LIM-003 |
| 🟡 MEDIA | 5 | NOM-003, IVA-002, IVA-004, CLAS-003, FECH-001, MT-003 |
| 🟢 BAJA | 4 | ISR-005, IVA-003, FECH-002, FECH-003 |

### Top 5 bugs más peligrosos (por impacto financiero):

1. **ISR-003/ISR-004:** Empleados reciben menos dinero del legal → demandas laborales
2. **IVA-001/DIOT float:** SAT rechaza DIOT → multas Art. 81 CFF ($400-$1,100 por no presentar)
3. **CLAS-001:** Pólizas incorrectas al ERP → errores contables que requieren auditoría completa
4. **MT-001:** Cross-tenant data leak → violación LFPDPPP → multas de $100M-$320M MXN
5. **NOM-004:** Tablas fiscales mezcladas → nóminas incorrectas × miles de empleados

---

*Auditoría generada por análisis estático de código. Se recomienda complementar con pruebas de penetración, fuzzing de XML, y pruebas de carga.*
