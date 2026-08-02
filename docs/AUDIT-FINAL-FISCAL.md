# AUDITORÍA FISCAL Y CUMPLIMIENTO — B2B-AI Enterprise
**Fecha:** 2026-08-01
**Alcance:** b2b_ai/cfdi/, b2b_ai/sat/, b2b_ai/services/payroll.py, b2b_ai/services/pipeline.py, b2b_ai/features/declaraciones/, b2b_ai/features/nomina/, b2b_ai/features/compliance.py, b2b_ai/features/conciliacion/, b2b_ai/features/reconciliation_agent/, b2b_ai/fiscal_tables.py

**Método:** Lectura exhaustiva línea-por-línea de cada archivo, cruce con legislación fiscal mexicana vigente.

---

## Resumen Ejecutivo

| Categoría | Hallazgos Críticos | Hallazgos Altos | Hallazgos Medios | Hallazgos Bajos |
|---|---|---|---|---|
| CFDI Parsing | 1 | 2 | 2 | 1 |
| ISR | 1 | 1 | 0 | 0 |
| IMSS | 0 | 1 | 1 | 0 |
| INFONAVIT | 0 | 0 | 0 | 0 |
| DIOT | 1 | 1 | 0 | 0 |
| IVA | 0 | 0 | 1 | 0 |
| IEPS | 0 | 0 | 1 | 0 |
| Nómina | 0 | 1 | 2 | 1 |
| Declaraciones | 0 | 1 | 2 | 0 |
| Conciliación | 0 | 0 | 1 | 0 |
| **TOTAL** | **3** | **7** | **10** | **3** |

---

## 1. CFDI Parsing

### FIS-01 [CRÍTICO] — Carta Porte no soportada
- **Archivo:** b2b_ai/cfdi/parser.py (completo)
- **Descripción:** El parser CFDI no extrae el complemento Carta Porte (namespace `cartaporte31`/`cartaporte30`). Las operaciones de transporte terrestre, aéreo, marítimo o ferroviario requieren Carta Porte 3.1 como complemento obligatorio (CFF Art. 29, Anexo 20). Sin este complemento, los CFDIs de transporte no producen efecto fiscal completo.
- **Artículo:** CFF Art. 29, Anexo 20, Regla 2.7.1.9 RMF
- **Severidad:** CRÍTICO
- **Fix:** Agregar namespace `cartaporte31: http://www.sat.gob.mx/CartaPorte31` y extraer: Origen, Destino, Mercancias, Autotransporte (permisos SCT, póliza seguro, vehículo). Agregar al dict de salida como `carta_porte`.

### FIS-02 [ALTO] — CFDI Globales (público en general) no detectados
- **Archivo:** b2b_ai/cfdi/parser.py:103
- **Descripción:** El parser extrae `TipoDeComprobante` pero no detecta CFDIs globales (RFC genérico XAXX010101000 con múltiples receptores). Los CFDIs globales tienen reglas distintas para IVA acreditable y DIOT. No hay flag `es_global` en la salida.
- **Artículo:** CFF Art. 29, Anexo 20 (CFDI Global con RFC genérico)
- **Severidad:** ALTO
- **Fix:** Detectar RFC receptor `XAXX010101000` o `XEXX010101000` y marcar `es_cfdi_global=True`. Ajustar lógica de DIOT para excluir estos.

### FIS-03 [ALTO] — Notas de crédito (tipo E) sin lógica de relación completa
- **Archivo:** b2b_ai/cfdi/validator.py:159-175
- **Descripción:** El validator tiene un BUG-F3 comment para notas de crédito (tipo E con total=0), pero solo valida la aritmética del total. No verifica que los `CfdiRelacionados` tengan `TipoRelacion=01` (Nota de crédito de los documentos relacionados) ni que los UUIDs referenciados existan. Una nota de crédito sin relación válida no produce efecto fiscal.
- **Artículo:** Anexo 20 (TipoRelacion obligatorio para tipo E)
- **Severidad:** ALTO
- **Fix:** Para tipo E, validar: (1) `cfdi_relacionados` no vacío, (2) `tipo_relacion == "01"`, (3) al menos un UUID referenciado.

### FIS-04 [MEDIO] — Complemento de Pago v1.0 y v2.0 mezclados
- **Archivo:** b2b_ai/cfdi/parser.py:22-30
- **Descripción:** El parser registra ambos namespaces `pago10` y `pago20` pero busca solo nodos `Pago` (localname), lo que funciona para ambos. Sin embargo, no distingue la versión del complemento. Los CFDIs de pago con complemento v1.0 tienen campos adicionales (RfcEmisorCtaOrd, CtaOrdenante, RfcEmisorCtaBen, CtaBeneficiario) que no se extraen pero sí se requieren para CFDI 4.0 (Anexo 20).
- **Artículo:** Anexo 20, complemento de Pagos v2.0
- **Severidad:** MEDIO
- **Fix:** Detectar versión del complemento de pagos y extraer campos bancarios obligatorios para v2.0.

### FIS-05 [MEDIO] — Sin validación de ObjetoImp por concepto
- **Archivo:** b2b_ai/cfdi/validator.py (completo)
- **Descripción:** El parser extrae `objeto_imp` por concepto (línea 155) pero el validator no lo valida. El catálogo c_ObjetoImp (01=No objeto, 02=Sí objeto, 03=Sí y obligación de desglose, 04=Sí y tasa 0%) es obligatorio en CFDI 4.0. Un concepto con `objeto_imp=01` no debería tener impuestos trasladados.
- **Artículo:** Anexo 20, c_ObjetoImp, regla 2.7.1.32 RMF
- **Severidad:** MEDIO
- **Fix:** Validar coherencia: si `objeto_imp=01`, no debe haber traslados. Si `objeto_imp=02/03`, debe haber al menos un traslado.

### FIS-06 [BAJO] — Doble return en parse_nomina_bytes
- **Archivo:** b2b_ai/features/nomina/parser.py:292-293
- **Descripción:** `return data` duplicado al final de la función (líneas 291 y 292). No causa error pero es código muerto.
- **Artículo:** N/A (calidad de código)
- **Severidad:** BAJO
- **Fix:** Eliminar la línea 292 `return data` duplicada.

---

## 2. ISR

### FIS-07 [CRÍTICO] — engine.py usa tablas ISR 2024 hardcodeadas, no las centralizadas de fiscal_tables.py
- **Archivo:** b2b_ai/features/declaraciones/engine.py:27-53
- **Descripción:** `engine.py` define sus propias `ISR_TABLE_MONTHLY` y `ISR_TABLE_ANNUAL` con valores de 2024 (limite_inferior 312.41, 2636.28...). Mientras tanto, `fiscal_tables.py` tiene las tablas correctas de 2025 (limite_inferior 416.34, 3508.42...). `compliance.py` y `declaraciones/service.py` importan de `fiscal_tables.py` (2025), pero `engine.py` tiene su propia copia 2024. Esto genera **dos cálculos ISR distintos** para el mismo contribuyente.
- **Artículo:** LISR Art. 96, RMF 2025 Anexo 3
- **Severidad:** CRÍTICO
- **Fix:** Eliminar `ISR_TABLE_MONTHLY` e `ISR_TABLE_ANNUAL` de `engine.py`. Importar de `fiscal_tables.py`: `from b2b_ai.fiscal_tables import ISR_MENSUAL_2025 as ISR_TABLE_MONTHLY, ISR_ANUAL_2025 as ISR_TABLE_ANNUAL`.

### FIS-08 [ALTO] — payroll.py defaults a tabla ISR 2024 cuando la activa es 2025
- **Archivo:** b2b_ai/services/payroll.py:37-40, 95, 129-133
- **Descripción:** `AÑO_FISCAL = 2024` (línea 95). `TARIFA_ISR_2024_MENSUAL` se construye desde `ISR_MENSUAL_2024` (línea 37). En `calc_isr()`, el default para mensual es `TARIFA_ISR_2024_MENSUAL` (tabla 2024). Esto significa que si no se pasa una tarifa explícita, se calcula ISR con tabla 2024 incorrecta para 2025. Sin embargo, `TARIFA_ISR_2024_QUINCENAL` usa `ISR_QUINCENAL_2025` (correcto). **Inconsistencia: mensual→2024, quincenal→2025.**
- **Artículo:** LISR Art. 96, RMF 2025 Anexo 3
- **Severidad:** ALTO
- **Fix:** Cambiar `AÑO_FISCAL = 2025`. Construir `TARIFA_ISR_MENSUAL` desde `ISR_MENSUAL_2025`. Renombrar variables para reflejar año correcto. O mejor: importar directamente de `fiscal_tables.get_isr_table()`.

---

## 3. IMSS

### FIS-09 [ALTO] — Sin cálculo de cuotas patronales IMSS
- **Archivo:** b2b_ai/services/payroll.py:58-93
- **Descripción:** El diccionario `RATES` solo contiene las tasas del **trabajador** (EYM, RCVA, IV, GMP). No hay tasas **patronales** (las que el patrón paga aparte). Las cuotas patronales IMSS incluyen: EYM patronal (art. 106), RCVA patronal (art. 108), RCV 1.125% (art. 168 LSS), GMP patronal (art. 109), riesgo de trabajo (art. 73). Estas son **exigibles** para la provisión mensual del patrón y para el cálculo del costo total de nómina.
- **Artículo:** LSS Arts. 105-109, 147, 168
- **Severidad:** ALTO
- **Fix:** Agregar al diccionario `RATES` las tasas patronales (aprox 20.40×UMA/día cuota fija + ~1.75% SBC EYM + 1.125% RCV + 3.90% RCV subcuenta + riesgo trabajo). Crear `calc_imss_patronal()` separada de la del trabajador.

### FIS-10 [MEDIO] — UMA 2025 incorrecta en RATES
- **Archivo:** b2b_ai/services/payroll.py:81
- **Descripción:** `"imss_uma_diario": Decimal("108.57")`. El UMA diario 2025 correcto (publicado DOF febrero 2025) es **$113.15** (ver fiscal_tables.py:121). Esto afecta el cálculo del excedente 3 UMA y la cuota fija patronal.
- **Artículo:** LSS Art. 107, Ley del INEGI
- **Severidad:** MEDIO
- **Fix:** Cambiar a `Decimal("113.15")` o importar de `fiscal_tables.UMA_DIARIO_2025`.

---

## 4. INFONAVIT

### ✅ CORRECTO — Separación patronal/trabajador
- **Archivo:** b2b_ai/services/payroll.py:236-258, 453-479
- **Descripción:** La aportación del 5% SBC está correctamente marcada como `provision_patronal` (art. 29-II Ley INFONAVIT). Las deducciones del trabajador muestran `"infonavit": "0.00"` (línea 479). El XML de nómina incluye comentario explicativo (líneas 624-627). **Implementación correcta.**

---

## 5. DIOT

### FIS-011 [CRÍTICO] — Conflicto TipoOperacion: catalogs.py vs diot_generator.py vs engine.py
- **Archivos:**
  - b2b_ai/cfdi/catalogs.py:138-142 → Catálogo SAT oficial: `{"03", "06", "85"}`
  - b2b_ai/features/declaraciones/diot_generator.py:61-66 → Acepta: `{"01", "02", "03", "04", "05", "06", "07", "08"}`
  - b2b_ai/features/declaraciones/engine.py:324-332 → Mapea IVA→TipoOperacion: 16%→"03", 8%→"03", 0%→"06"
- **Descripción:** **Tres definiciones incompatibles de TipoOperacion DIOT:**
  1. `catalogs.py` (correcto): solo 03, 06, 85 — conforme Regla 3.10.7 RMF.
  2. `diot_generator.py` (INCORRECTO): acepta 01-08 — esto NO es el catálogo SAT, es inventado.
  3. `engine.py` (parcialmente correcto): solo genera "03" y "06", pero nunca genera "85" (otros).
  
  El `diot_generator.py` acepta TipoOperacion que NO existen en el SAT (01, 02, 04, 05, 07, 08). Si se usa el generador con estos valores, el SAT rechazará la DIOT.
- **Artículo:** Regla 3.10.7 RMF, catálogo c_TipoOperacion DIOT
- **Severidad:** CRÍTICO
- **Fix:** Corregir `diot_generator.py:61` para usar `DIOT_TIPO_OPERACION` de `catalogs.py`. En `engine.py:324-332`, considerar mapear operaciones exentas a "85" (otros) en lugar de solo "03"/"06".

### FIS-012 [ALTO] — DIOT no filtra operaciones con tasa 8% frontera
- **Archivo:** b2b_ai/features/declaraciones/engine.py:327-329
- **Descripción:** `_map_iva_tipo()` mapea tanto 16% como 8% al mismo TipoOperacion "03". Esto es correcto para la categoría, pero el registro DIOT debe **desglosar** IVA trasladado a 16% vs IVA trasladado a 8% frontera en campos separados. La frontera usa tasa 8% (LIVA Art. 2-A) y debe reportarse en la columna de IVA trasladado 16% como actos a tasa general, o bien separarse.
- **Artículo:** LIVA Art. 1-C, Art. 2-A, Regla 3.10.7 RMF
- **Severidad:** ALTO
- **Fix:** Agregar campo `iva_trasladado_8` en `DiotRecord` para desglosar operaciones de zona fronteriza. En la generación del pipe-delimited, usar columna adicional.

---

## 6. IVA

### FIS-013 [MEDIO] — IVA validator asume siempre tasa 16% para acreditamiento
- **Archivo:** b2b_ai/cfdi/validator.py:149-156
- **Descripción:** La validación global de IVA compara contra `IVA_TASA` (16%) hardcodeado. Si el CFDI tiene tasa mixta (conceptos a 0%, 8%, y 16%), la comparación global será siempre warning. No valida IVA acreditable proporcional (LIVA Art. 5) cuando hay operaciones exentas.
- **Artículo:** LIVA Art. 5, Art. 5-B (proporción de acreditamiento)
- **Severidad:** MEDIO
- **Fix:** Validar IVA por concepto individual (ya lo hace por concepto pero no para tasa 0%/8%). Agregar proporción de acreditamiento cuando hay mezcla de tasa 0% y 16%.

### ✅ Tasas IVA correctas (0%, 8%, 16%)
- validator.py:30-34 define las tres tasas. compliance.py:106 `VALID_IVA_RATES = {0, 0.0, 8, 0.08, 16, 0.16}`. engine.py:59-61. **Correcto.**

---

## 7. IEPS

### FIS-014 [MEDIE] — IEPS: lista de productos incompleta y sin validación de Ley IEPS Art. 2-A
- **Archivo:** b2b_ai/features/declaraciones/engine.py:64-75
- **Descripción:** `IEPS_RATES` cubre 10 categorías de producto, pero Ley IEPS Art. 2 incluye más: producción de energía eléctrica (varios %), enajenación de bienes raíces con tasa preferente, plataformas digitales. Además, `plaguicidas` a 0.08 es incorrecto: la Ley IEPS Art. 2-A señala tasa 8% para ciertos plaguicidas pero la tasa exacta depende del tipo (algunos están exentos). Falta la tasa IEPS para renta de bienes inmuebles (no hay IEPS para esto).
- **Artículo:** Ley IEPS Art. 2, 2-A
- **Severidad:** MEDIO
- **Fix:** Expandir `IEPS_RATES` con categorías faltantes. Agregar nota de que la tasa de combustibles fósiles varía por mes (Art. 2-A, cuadro de cuotas IEPS mensual publicado por SAT). Agregar validación de que cada producto tenga su tasa correcta al momento de la operación.

---

## 8. Nómina

### FIS-015 [ALTO] — Nómina extraordinaria: generate_payroll_cfdi siempre usa TipoNomina="O"
- **Archivo:** b2b_ai/services/payroll.py:596
- **Descripción:** `generate_payroll_cfdi()` hardcodea `TipoNomina="O"` (ordinaria). Para aguinaldo, PTU, prima vacacional y pagos extraordinarios, debe ser `TipoNomina="E"` (extraordinaria). El parser (`nomina/parser.py`) lee `tipo_nomina` correctamente (O/E), pero el generador siempre produce "O".
- **Artículo:** Anexo 20, c_TipoNomina
- **Severidad:** ALTO
- **Fix:** Agregar parámetro `tipo_nomina="O"` a `generate_payroll_cfdi()` y pasarlo al XML. Para pagos extraordinarios (aguinaldo, PTU), pasar `tipo_nomina="E"`.

### FIS-016 [MEDIO] — Aguinaldo proporcional usa year actual hardcodeado
- **Archivo:** b2b_ai/services/payroll.py:338-341
- **Descripción:** `calc_aguinaldo()` usa `_date.today().year` para determinar si es bisiesto. Esto es correcto para el año actual, pero si se calcula aguinaldo proporcional de un año anterior (ej: liquidación 2024, bisiesto=False), usa el año actual (2025, bisiesto=False también). Sin embargo, si el cálculo se hace en 2026 (bisiesto=True) para un periodo de 2025, usaría 366 días incorrectamente. **BUG-F8 ya documentado en el código.**
- **Artículo:** LFT Art. 87
- **Severidad:** MEDIO
- **Fix:** Agregar parámetro `año=None` a `calc_aguinaldo()`. Si None, usar `year = _date.today().year`. Si se pasa, usar el año del periodo.

### FIS-017 [MEDIO] — Sin cálculo de PTU individual en payroll
- **Archivo:** b2b_ai/services/payroll.py:261-271
- **Descripción:** `calc_ptu()` calcula la PTU total de la empresa (10% utilidad fiscal), pero no calcula la PTU individual del trabajador. La PTU individual se distribuye conforme LFT Art. 123: (1) 50% proporcional a días trabajados, (2) 50% proporcional al salario. El payroll solo tiene la PTU empresa total, no la distribución individual.
- **Artículo:** LFT Art. 123 fracc. IX, Art. 120, 122, 123 LFT
- **Severidad:** MEDIO
- **Fix:** Crear `calc_ptu_individual(dias_trabajados, salario_diario, ptu_total_empresa, num_trabajadores)` que implemente la fórmula de distribución del Art. 123 LFT.

### FIS-018 [BAJO] — Días de vacaciones: tabla parcialmente incompleta
- **Archivo:** b2b_ai/services/payroll.py:352-379
- **Descripción:** La tabla de vacaciones muestra hasta año 20. El código implementa `extra = ((a - 1) // 5) * 2` que es correcta para años > 5. Sin embargo, la tabla mostrada en el docstring tiene un error para año 7: dice 22 pero la fórmula da 22. Verificación OK. **No hay bug real**, pero el docstring podría confundir.
- **Artículo:** LFT Art. 76 (reformado DOF 27-dic-2022)
- **Severidad:** BAJO
- **Fix:** Mejorar el docstring con nota de que la tabla es representativa y la fórmula aplica para todos los años ≥ 6.

---

## 9. Declaraciones

### FIS-019 [ALTO] — Envío SAT: _send_soap() es stub, no implementación real
- **Archivo:** b2b_ai/features/declaraciones/sat_submitter.py:215-267
- **Descripción:** `_send_soap()` (línea 233-255) intenta importar `zeep` pero no construye el SOAP real. Devuelve `SubmissionStatus.PENDING` con mensaje "Envío SOAP a SAT configurado". Esto significa que **las declaraciones no se envían al SAT automáticamente** — solo se generan los XMLs. El usuario debe subirlos manualmente al portal SAT.
- **Artículo:** CFF Art. 31 (declaraciones provisionales), Art. 150 (declaración anual)
- **Severidad:** ALTO (funcional — no bloqueante para MVP pero imprescindible para producción)
- **Fix:** Implementar WSSecurity con FIEL/X.509, construir SOAP envelope para DeclaraSAT, manejar acuse/rechazo. Alternativa: integrar con PAC o software de despacho (CONTPAQi).

### FIS-020 [MEDIO] — FIELSigner: no genera cadena original con XSLT
- **Archivo:** b2b_ai/features/declaraciones/fiel_signer.py:269-284
- **Descripción:** `sign_declaration()` (línea 274) firma directamente los `xml_bytes` si no se provee `cadena_original`. En producción, la cadena original debe generarse con la transformación XSLT del SAT (no firmar el XML directo). Firmar el XML sin cadena original genera un sello inválido ante el SAT.
- **Artículo:** CFF Art. 29, Anexo 20 (cadena original con XSLT)
- **Severidad:** MEDIO
- **Fix:** Implementar generación de cadena original con XSLT templates del SAT. El código tiene el comentario "simplified mode — in production you'd use XSLT" pero falta la implementación real.

### FIS-021 [MEDIO] — Plazos de declaración ISR anual correcto pero sin validación de régimen
- **Archivo:** b2b_ai/features/declaraciones/service.py:322-323
- **Descripción:** ISR anual deadline = `date(year + 1, 4, 30)` que es correcto para PM. Sin embargo, para PF asalariados que presentan declaración anual voluntaria el plazo es abril 30, pero para PM en régimen general es abril 30, para RESICO es abril 30, etc. No hay distinción de régimen para los plazos.
- **Artículo:** CFF Art. 31, 150 LISR
- **Severidad:** MEDIO
- **Fix:** Agregar lógica de plazos por régimen fiscal (no todos usan abril 30 para ISR anual). Para PM en régimen general, el plazo es abril 30 del año siguiente. Para coordinados es marzo 31.

---

## 10. Conciliación

### FIS-022 [MEDIO] — Parsing: 7 bancos cubiertos pero sin validación de integridad del archivo
- **Archivo:** b2b_ai/features/reconciliation_agent/parsers.py:87-117
- **Descripción:** `BANK_PROFILES` cubre 7 bancos (BBVA, Banorte, Santander, HSBC, Citibanamex, Banregio, Scotiabank). Los parsers CSV/OFX/QIF/MT940/PDF están implementados. **Sin embargo**, no hay validación de checksums (OFX signon, MT940 checksum) ni detección de archivos corruptos parciales. Un CSV truncado no genera error — produce resultados parciales silenciosamente.
- **Artículo:** N/A (integridad de datos)
- **Severidad:** MEDIO
- **Fix:** Agregar validación post-parsing: (1) warning si el número de movimientos < 2 (posible parse fallido), (2) validar que montos son numéricos, (3) warning si fechas están fuera del mes esperado.

### ✅ Matching Engine: 4 niveles implementados
- **Archivo:** b2b_ai/features/reconciliation_agent/matching_engine.py
- **Descripción:** Nivel 1 (Exacto), Nivel 2 (Fuzzy con rapidfuzz), Nivel 3 (Multi-línea/subset sum), Nivel 4 (LLM). Implementación robusta con tolerancias configurables. **Buena cobertura.**

---

## 11. Hallazgos Transversales

### FIS-023 [ALTO] — Duplicación de tablas ISR: 3 copias con divergencia
- **Archivos:**
  - `b2b_ai/features/declaraciones/engine.py:27-53` — copia 2024 hardcodeada
  - `b2b_ai/fiscal_tables.py:34-62` — copia centralizada 2025
  - `b2b_ai/features/compliance.py:100-101` — importa de fiscal_tables (2025)
- **Descripción:** `fiscal_tables.py` fue creado como "single source of truth" pero `engine.py` no lo adoptó. Hay dos versiones de la tabla ISR en el código — una 2024 y otra 2025 — y el sistema usa ambas según qué módulo se invoque.
- **Artículo:** LISR Art. 96
- **Severidad:** ALTO (ya cubierto en FIS-07, pero el alcance del impacto es transversal)
- **Fix:** Migrar `engine.py` a importar de `fiscal_tables.py`. Eliminar copias hardcodeadas.

### FIS-024 [ALTO] — SAT validator es mock completo — sin conexión real
- **Archivo:** b2b_ai/sat/validator.py:35-148
- **Descripción:** `SATValidator.check_status()` usa mock determinista (folio termina en "0" → cancelado). No consulta el SAT real. En producción, cualquier CFDI con folio fiscal válido será reportado como "vigente" salvo que casualmente termine en "0". Esto es aceptable para MVP/desarrollo pero **no para producción**.
- **Artículo:** Regla 2.7.1.39 RMF
- **Severidad:** ALTO (documentado como mock-first, pero debe implementarse)
- **Fix:** Implementar consulta real al Web Service SAT de estatus de CFDI (SOAP o REST). Alternativa: integrar con PAC.

### FIS-025 [BAJO] — EFOS 69-B: lista estática de ejemplo
- **Archivo:** b2b_ai/sat/efos_69b.py:39-43
- **Descripción:** La lista 69-B contiene solo RFCs ficticios de prueba. El código tiene comentario "EN PRODUCCIÓN: reemplazar con la carga del archivo CSV del SAT". La lista debe actualizarse al menos mensualmente.
- **Artículo:** CFF Art. 69-B, RMF 2.7.1.39
- **Severidad:** BAJO (documentado, pero requiere implementación para producción)
- **Fix:** Implementar descarga automática periódica del CSV del SAT y actualización de la lista.

---

## Matriz de Corrección Priorizada

| # | Prioridad | Hallazgo | Esfuerzo | Impacto Fiscal |
|---|---|---|---|---|
| 1 | P0 | FIS-07/FIS-23: Duplicación ISR tablas (2024 vs 2025) | 1h | ISR incorrecto |
| 2 | P0 | FIS-011: DIOT TipoOperacion conflict (01-08 vs 03/06/85) | 30min | DIOT rechazada por SAT |
| 3 | P0 | FIS-08: payroll.py default tabla 2024 | 30min | ISR nómina incorrecto |
| 4 | P1 | FIS-015: generate_payroll_cfdi siempre TipoNomina="O" | 1h | Nómina extraordinaria inválida |
| 5 | P1 | FIS-10: UMA 2025 incorrecta (108.57 vs 113.15) | 5min | IMSS incorrecto |
| 6 | P1 | FIS-09: Sin cuotas patronales IMSS | 2-3h | Costo nómina incompleto |
| 7 | P1 | FIS-01: Carta Porte no soportada | 4-8h | CFDIs transporte inválidos |
| 8 | P2 | FIS-02: CFDI globales no detectados | 2h | DIOT incorrecta |
| 9 | P2 | FIS-03: Notas crédito sin validación relación | 1h | Notas crédito inválidas |
| 10 | P2 | FIS-019: SAT submitter es stub | 8-16h | Envío manual requerido |
| 11 | P2 | FIS-020: FIEL sin XSLT | 4-8h | Sello inválido |
| 12 | P2 | FIS-012: DIOT sin desglose frontera 8% | 2h | DIOT incompleta |
| 13 | P3 | FIS-04/05/13/14/17/18/21/22 | 2-4h cada uno | Mejoras menores |

---

## Notas Legales

- Todas las referencias legales son al marco jurídico vigente a agosto 2025.
- Las tablas ISR 2025 en `fiscal_tables.py` se publicaron en DOF diciembre 2024 (RMF 2025, Anexo 3).
- El UMA 2025 ($113.15/día) se publicó en DOF febrero 2025 por INEGI.
- Los plazos de declaración se basan en CFF Art. 31 y LISR Art. 96, 150.
- La DIOT se rige por Regla 3.10.7 RMF vigente.

---

*Auditoría generada por agente especializado. Requiere validación de contador público certificado antes de implementar correcciones.*
