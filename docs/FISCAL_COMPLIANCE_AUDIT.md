# Auditoría Integral de Cumplimiento Fiscal/Legal

**Fecha:** 1 de agosto de 2026  
**Auditor:** Gates (Inteligencia)  
**Alcance:** Código fuente completo — b2b_ai/features/*, b2b_ai/services/*, b2b_ai/sat/*, b2b_ai/cfdi/*, b2b_ai/auth/*, docs/legal/*  
**Escala:** 1–10 (donde 10 = cumplimiento total sin gaps)

---

## Resumen Ejecutivo

| Ley | Norma | Estado | Nota |
|-----|-------|--------|------|
| CFF | Art. 82, 85, 86, 88, 89 | ✅ Cumple | Base sólida, gaps menores |
| LISR | Art. 96, 105, 106, 107 | ⚠️ Cumple parcial | Tablas desactualizadas + inconsistencia |
| LIVA | Art. 5, 8, 9 | ✅ Cumple | Tasas correctas, cálculo correcto |
| LFT | Art. 76, 89, 168-187 | ✅ Cumple | Reforma 2023 implementada correctamente |
| LFPDPPP | Aviso, Consentimiento, ARCO, Sensibles | ❌ No cumple | Gaps críticos múltiples |

**Nota global estimada: 4/10**

---

## 1. CFF (Código Fiscal de la Federación)

### Art. 82 — Protección de datos fiscales en logs
**Estado: ✅ CUMPLE**

| Requisito | Implementación | Archivo |
|-----------|---------------|---------|
| Enmascaramiento de RFC en logs | `mask_rfc()` — muestra primeros 3 chars, enmascara medio | `compliance.py:39-44` |
| Enmascaramiento de montos grandes | `mask_amount()` — redacta >$100k | `compliance.py:47-50` |
| Logging seguro automático | `safe_log()` — regex automático para RFC y montos | `compliance.py:53-68` |

**Hallazgo:** La función `safe_log()` aplica regex para enmascarar RFCs y montos en tiempo real. Los montos >$100,000 se redactan. Buena práctica.

**Riesgo residual:** Ninguno significativo.

---

### Art. 85 — Registros contables completos (DIOT/CFDI cross-reference)
**Estado: ✅ CUMPLE**

| Requisito | Implementación | Archivo |
|-----------|---------------|---------|
| DIOT cross-reference con CFDI | Validación cruzada invoices↔entries | `diot/service.py:57-101` |
| Validación de integridad DIOT | `validate_diot_entries()` | `diot/validators.py:145-171` |
| Referencia legal explícita | `"CFF Art. 89"` en metadata | `diot/service.py` |

**Hallazgo:** El pipeline DIOT valida consistencia entre facturas CFDI y entradas DIOT. Se detectan inconsistencias de IVA y se reportan como `Inconsistencia` con severidad.

**Nota:** El `diot_validator.py` (servicio de validación XML) usa un catálogo de TipoOperación `{03, 06, 85}` que NO coincide con el catálogo del otro módulo DIOT (`{01=IVA, 02=IEPS, 03=Exento}`). Ver hallazgo DIOT-01.

#### 🔴 HALLAZGO DIOT-01: Catálogo TipoOperación inconsistente entre módulos
- **Severidad:** ALTO
- **Archivos:** `b2b_ai/features/diot/validators.py` vs `b2b_ai/services/diot_validator.py`
- **Descripción:** `diot/validators.py` usa TipoIva (GENERAL_16, FRONTERA_8, EXENTO_0), mientras `services/diot_validator.py` define `VALID_TIPO_OPERACION = {"03", "06", "85"}`. El segundo archivo tiene un comment que dice "El catálogo anterior (01=IVA, 02=IEPS, 03=Exento) NO es el catálogo SAT real" — pero el catálogo real del SAT para DIOT es efectivamente {01=IVA, 02=IEPS, 03=Exento, 12=IEPS}. Los códigos 03/06/85 corresponden a un catálogo diferente.
- **Impacto:** Si se usa `diot_validator.py` para validar XML DIOT real, rechazaría operaciones válidas o aceptara inválidas.
- **Recomendación:** Unificar en un solo catálogo SAT correcto. Verificar cuál módulo se usa en producción.

---

### Art. 86 — Contabilidad electrónica XML válido
**Estado: ✅ CUMPLE**

| Requisito | Implementación | Archivo |
|-----------|---------------|---------|
| Validación de balanza XML | `validate_balanza()` + `validate_balanza_totals()` | `contabilidad_electronica/validators.py` |
| Generación de XML SAT | `generate_balanza_xml()`, `generate_catalogo_xml()` | `contabilidad_electronica/generator.py` |
| Validación de catálogo | `validate_catalogo()` | `contabilidad_electronica/validators.py` |
| Obligaciones por régimen fiscal | Tabla completa 601/612/606/626 | `contabilidad_electronica/routes.py:29-65` |

**Hallazgo:** El módulo genera XML conforme al XSD del SAT y valida antes de generar. Las obligaciones fiscales están mapeadas por régimen.

**Riesgo residual:** El sistema mock NO verifica realmente contra el Web Service del SAT en producción.

---

### Art. 88 — Sistemas de contabilidad
**Estado: ✅ CUMPLE**

| Requisito | Implementación | Archivo |
|-----------|---------------|---------|
| Pre-auditoría contable | `check_consistency()` — partida doble, fechas, cuentas | `pre_auditoria/service.py:35-90` |
| Deducibilidad de gastos | `check_deductibility()` — Art. 28 LISR | `pre_auditoria/service.py:24-33` |
| Catálogo de gastos no deducibles | Lista explícita de conceptos | `pre_auditoria/service.py:21-33` |

**Hallazgo:** La pre-auditoría verifica consistencia de asientos contables (partida doble, fechas no futuras, cuentas completas, descripción obligatoria).

---

### Art. 89 — Salidas fiscales con referencia legal
**Estado: ✅ CUMPLE**

| Requisito | Implementación | Archivo |
|-----------|---------------|---------|
| `referencia_legal` en cada salida | `FiscalOutput` dataclass | `compliance.py:81-103` |
| `supuesto` documentado | Campo en FiscalOutput | `compliance.py:83` |
| `requires_human_review` | Flag por defecto True | `compliance.py:84` |
| `escalation_path` | Default: review_by_contador | `compliance.py:87` |
| `idempotency_key` | UUID por operación | `compliance.py:88` |
| Audit trail | `AuditTrail` con logging completo | `compliance.py` |

**Hallazgo:** Cada salida fiscal lleva metadata completa de conformidad con Art. 89. Los servicios usan `ManualProcessMixin` para forzar revisión humana.

---

## 2. LISR (Ley del Impuesto Sobre la Renta)

### Art. 96 — Tablas de ISR
**Estado: ⚠️ CUMPLE PARCIAL**

| Ubicación | Tabla | Año fiscal | Fuente |
|-----------|-------|-----------|--------|
| `compliance.py` | ISR_TABLE_2024_MONTHLY/ANNUAL | **2024** | LISR Art. 96 |
| `declaraciones/service.py` | ISR_TABLE_MONTHLY/ANNUAL | **2024** | Duplicada de compliance.py |
| `services/payroll.py` | TARIFA_ISR_2025_MENSUAL/QUINCENAL | **2025** | LISR Art. 96 |
| `nomina_completa/service.py` | Usa `calculate_isr()` de compliance | **2024** | Importa de compliance.py |

#### 🔴 HALLAZGO LISR-01: Tablas ISR desactualizadas e inconsistentes
- **Severidad:** CRÍTICO
- **Archivos:** `compliance.py`, `declaraciones/service.py`, `services/payroll.py`, `nomina_completa/service.py`
- **Descripción:** Existen MÚLTIPLES tablas ISR con diferentes años fiscales:
  1. `compliance.py` tiene tabla **2024** (usada por `nomina_completa` y declaraciones)
  2. `services/payroll.py` tiene tabla **2025** (más actualizada, con tarifa quincenal)
  3. Las tablas de 2024 en compliance.py y declaraciones son idénticas (duplicación)
  
  Los valores difieren significativamente. Ejemplo primer escalón:
  - 2024: 0.00–312.41 → cuota 0.00, tasa 1.92%
  - 2025: 0.01–746.04 → cuota 0.00, tasa 1.92% (límites muy diferentes)
  
  **Rango 2024 primer tramo:** $0–$312.41  
  **Rango 2025 primer tramo:** $0.01–$746.04
  
- **Impacto:** Si un cálculo de nómina usa la tabla de 2024 (via compliance.py) y otro usa la de 2025 (via payroll.py), los montos de ISR serán completamente diferentes para el mismo salario. Esto genera declaraciones incorrectas y posibles sanciones del SAT.
- **Recomendación:** 
  1. Eliminar las tablas duplicadas en `compliance.py` y `declaraciones/service.py`
  2. Usar UNA sola tabla, actualizada al año fiscal vigente (2025)
  3. Versionar la tabla con `AÑO_FISCAL` como hace `payroll.py`

---

### Art. 105 — Gastos deducibles
**Estado: ✅ CUMPLE**

| Requisito | Implementación | Archivo |
|-----------|---------------|---------|
| Clasificación de gastos | `NON_DEDUCTIBLE_CONCEPTS` lista explícita | `pre_auditoria/service.py:21-33` |
| Verificación de deducibilidad | `check_deductibility()` por factura | `pre_auditoria/service.py:35-70` |
| Referencia a Art. 28 LISR | Documentado en cada hallazgo | `pre_auditoria/service.py` |

---

### Art. 106 — Gastos no deducibles
**Estado: ✅ CUMPLE**

| Concepto | Excluido | Ref |
|----------|----------|-----|
| Multas | ✅ Sí | `NON_DEDUCTIBLE_CONCEPTS` |
| Recargos | ✅ Sí | `NON_DEDUCTIBLE_CONCEPTS` |
| Penalizaciones | ✅ Sí | `NON_DEDUCTIBLE_CONCEPTS` |
| Propinas | ✅ Sí | `NON_DEDUCTIBLE_CONCEPTS` |
| Gastos personales | ✅ Sí | `NON_DEDUCTIBLE_CONCEPTS` |
| Donativos | ✅ Sí | `NON_DEDUCTIBLE_CONCEPTS` |
| Gastos representación excesivos | ✅ Sí | `NON_DEDUCTIBLE_CONCEPTS` |

---

### Art. 107 — Limitaciones de gastos
**Estado: ✅ CUMPLE**

- Verificación de monto excesivo sin soporte (> $50,000) en `pre_auditoria/service.py:59-64`
- Se marca como "requiere documentación de soporte adicional"

---

## 3. LIVA (Ley del Impuesto al Valor Agregado)

### Art. 5 — Tasas de IVA correctas
**Estado: ✅ CUMPLE**

| Tasa | Implementada | Validada |
|------|-------------|----------|
| 0% (exportaciones, alimentos, medicinas) | ✅ | `VALID_IVA_RATES = {0.0, 0.08, 0.16}` |
| 8% (zona fronteriza) | ✅ | Mismo set |
| 16% (general) | ✅ | Mismo set |

**Archivos de validación:**
- `compliance.py:70` — `VALID_IVA_RATES`
- `diot/validators.py:22` — `VALID_IVA_RATES`
- `diot/models.py` — `TipoIva` enum

**Hallazgo:** Las tasas están restringidas a los tres valores legales. Cualquier otro valor es rechazado.

---

### Art. 8 — IVA acreditable
**Estado: ✅ CUMPLE**

| Requisito | Implementación | Archivo |
|-----------|---------------|---------|
| Validación de monto IVA vs tasa | `validate_iva_amount()` con tolerancia 1% | `diot/validators.py:117-138` |
| Validación por entrada DIOT | `validate_iva_calculation()` | `diot/validators.py:145-171` |
| Cross-reference IVA trasladado vs acreditable | Agregación en DIOT service | `diot/service.py:57-101` |

---

### Art. 9 — IVA no acreditable
**Estado: ✅ CUMPLE**

- El sistema detecta y reporta inconsistencias cuando `iva_acreditable` no coincide con lo esperado
- EFOS/69-B check: si el emisor está en la lista 69-B, el IVA NO es acreditable (`sat/efos_69b.py:51-55`)
- Se reporta: "Las operaciones amparadas por comprobantes de este contribuyente NO producen efecto fiscal alguno"

---

## 4. LFT (Ley Federal del Trabajo)

### Art. 76 — Vacaciones
**Estado: ✅ CUMPLE**

| Año | Días esperados | Implementados | Fórmula |
|-----|---------------|--------------|---------|
| 1 | 12 | 12 | `12 + 2*(a-1)` para a≤5 |
| 2 | 14 | 14 | ✓ |
| 3 | 16 | 16 | ✓ |
| 4 | 18 | 18 | ✓ |
| 5 | 20 | 20 | ✓ |
| 6 | 22 | 22 | `20 + ((a-1)//5)*2` |
| 10 | 22 | 22 | ✓ |
| 11 | 24 | 24 | ✓ |
| 15 | 24 | 24 | ✓ |
| 16 | 26 | 26 | ✓ |
| 20 | 26 | 26 | ✓ |

**Archivo:** `b2b_ai/services/payroll.py:380-407`  
**Reformado:** LFT art. 76 reformado 1-ene-2023 (DOF 27-dic-2022)

**Verificación:** La fórmula `extra = ((a - 1) // 5) * 2` para años ≥ 6 es correcta según la reforma. El primer escalón abre en el SEXTO año, no en el décimo.

**Tests que validan:**
- `tests/test_payroll.py:56-60`
- `tests/services/test_payroll.py:130-142`

---

### Art. 89 — Prima vacacional
**Estado: ✅ CUMPLE**

| Requisito | Implementación | Archivo |
|-----------|---------------|---------|
| Tasa mínima 25% | Default `prima_vacacional_tasa = Decimal("0.2500")` | `payroll.py:137` |
| Cálculo: 25% del pago de vacaciones | `calc_prima_vacacional()` | `payroll.py:422-434` |
| Referencia legal | `"LFT art. 80 (prima vacacional ≥ 25%)"` | `payroll.py:433` |

---

### Art. 168-187 — Cuotas IMSS
**Estado: ✅ CUMPLE**

| Componente | Tasa | Base | Archivo |
|-----------|------|------|---------|
| **Obrero** | | | |
| EYM base | 0.25% | SBC diario | `payroll.py:116` |
| EYM prest. dineradas | 0.75% | SBC diario | `payroll.py:117` |
| EYM prest. especie | 0.375% | SBC diario | `payroll.py:118` |
| Invalidez y vida | 0.625% | SBC diario | `payroll.py:119` |
| RCVA | 1.125% | SBC diario | `payroll.py:122` |
| GMP | 0.375% | SBC diario | `payroll.py:122` |
| **Patronal** | | | |
| EYM cuota fija | 20.40% | SBC diario | `payroll.py` (RATES) |
| Excedente 3 UMA | 0.40% | SBC - 3×UMA | `payroll.py:128` |
| Retiro | 2.00% | SBC diario | `payroll.py` |
| Cesantía vejez | 3.15% | SBC diario | `payroll.py` |
| Guardarantía | 1.25% | SBC diario | `payroll.py` |
| **INFONAVIT** | 5.00% | SBC | `payroll.py:134` |

**UMA diaria 2025:** $108.57 (`payroll.py:127`)

**Hallazgo:** Las cuotas del trabajador y patronal están implementadas con todas las fracciones de la LSS. El cálculo incluye excedente de 3 UMA para EYM.

**Nota:** La implementación en `nomina_completa/service.py` usa tasas simplificadas (1.20% obrero, 20.40% patronal) que son aproximaciones. `services/payroll.py` tiene el cálculo detallado por componente.

#### 🟡 HALLAZGO LFT-01: Cálculo IMSS simplificado en nomina_completa
- **Severidad:** MEDIO
- **Archivo:** `b2b_ai/features/nomina_completa/service.py:30-47`
- **Descripción:** `_calcular_imss_obrero()` usa una tasa plana de 1.20% en vez del cálculo detallado por componente que existe en `services/payroll.py:calc_imss()`. La diferencia es pequeña pero puede generar inconsistencias entre los dos módulos de nómina.
- **Recomendación:** Unificar para usar `calc_imss()` de `services/payroll.py` en todos los módulos.

---

## 5. LFPDPPP (Ley Federal de Protección de Datos Personales)

### Aviso de Privacidad
**Estado: ❌ NO CUMPLE**

| Requisito | Estado | Detalle |
|-----------|--------|---------|
| Aviso de privacidad existe | ✅ | `docs/legal/PRIVACY-POLICY.md` (215 líneas) |
| Aviso accesible al titular | ❌ | No enlazado desde landing, no servido como página web |
| RFC del responsable | ❌ | `[PENDIENTE — completar con RFC legal de la empresa]` |
| Autoridad correcta | ❌ | Cita PROFEPA (ambiental) en vez de SABG |
| Landing dice "incluido" | ❌ | Falso — el archivo no está vinculado a ningún endpoint visible |

#### 🔴 HALLAZGO LFPDPPP-01: Aviso de privacidad no accesible al titular
- **Severidad:** CRÍTICO
- **Archivos:** `landing/index.html:894`, `docs/legal/PRIVACY-POLICY.md`
- **Descripción:** La landing afirma "Aviso de privacidad incluido" pero no hay `<a href>` hacia el documento. La ruta `/legal/privacy` existe en `app.py:1307-1314` pero no está referenciada en ninguna landing ni en el portal.
- **Impacto:** Cualquier dato recabado (formulario contacto, registro portal, carga documentos) se obtiene sin que el titular haya visto el aviso. Incumplimiento del Art. 16 LFPDPPP.
- **Recomendación:** Agregar enlace visible en ambas landings y en el portal de usuario.

#### 🔴 HALLAZGO LFPDPPP-02: Autoridad competente incorrecta en aviso de privacidad
- **Severidad:** CRÍTICO
- **Archivo:** `docs/legal/PRIVACY-POLICY.md:201-208`
- **Descripción:** El §13 cita "Procuraduría Federal del Consumidor (PROFEPA)" — mezclando PROFECO (consumidor) con PROFEPA (ambiente). La LFPDPPP vigente desde 21-mar-2025 transfirió funciones a la **Secretaría Anticorrupción y Buen Gobierno (SABG)**.
- **Impacto:** Un titular que siga el documento llegará a una agencia sin competencia.
- **Recomendación:** Corregir para citar SABG como autoridad.

#### 🔴 HALLAZGO LFPDPPP-03: RFC del responsable no completado
- **Severidad:** ALTO
- **Archivo:** `docs/legal/PRIVACY-POLICY.md:6`
- **Descripción:** El campo `RFC: [PENDIENTE — completar con RFC legal de la empresa]` no está rellenado.
- **Recomendación:** Completar con el RFC legal antes de producción.

---

### Consentimiento
**Estado: ❌ NO CUMPLE**

| Requisito | Estado | Detalle |
|-----------|--------|---------|
| Captura de consentimiento | ❌ | `client_users` no tiene `accepted_terms_at` |
| Checkbox en landing | ❌ | Formulario de contacto sin checkbox |
| Endpoint de revocación | ❌ | No existe `unsubscribe/opt-out` |
| Evidencia de consentimiento | ❌ | Sin registro de aceptación |

#### 🔴 HALLAZGO LFPDPPP-04: Sin evidencia de consentimiento
- **Severidad:** CRÍTICO
- **Archivos:** `b2b_ai/db/models.py:348-357`, `b2b_ai/auth/users.py:115-131`
- **Descripción:** `client_users` no tiene columna de consentimiento. `create_user()` crea usuario sin registrar aceptación. El formulario de contacto de la landing no tiene checkbox.
- **Impacto:** Imposible demostrar consentimiento ante la SABG. Violación de Art. 8 LFPDPPP.
- **Recomendación:** 
  1. Agregar columna `accepted_privacy_at` a `client_users`
  2. Agregar checkbox de consentimiento al formulario de registro
  3. Registrar timestamp de aceptación

---

### Derechos ARCO
**Estado: ❌ NO CUMPLE**

| Derecho | Documento | Implementación código |
|---------|-----------|----------------------|
| Acceso | ✅ Prometido §5 | ❌ Sin endpoint |
| Rectificación | ✅ Prometido §5 | ❌ Sin endpoint |
| Cancelación | ✅ Prometido §5 | ❌ `invoices` excluido de borrado |
| Oposición | ✅ Prometido §5 | ❌ Sin endpoint |

#### 🔴 HALLAZGO LFPDPPP-05: Derechos ARCO sin implementación real
- **Severidad:** CRÍTICO
- **Archivos:** `b2b_ai/db/db.py:520-554`, `b2b_ai/api/v2.py:552-567`
- **Descripción:** `enforce_retention()` solo borra `audit_log`, `webhook_deliveries`, `notifications` y `portal_sessions`. **`invoices` (donde viven RFC, CURP, banking) NUNCA se purga.** El borrado automático a 12 meses prometido en §7.2 no ocurre porque nadie llama al endpoint manual.
- **Impacto:** Si un titular ejerce cancelación, no hay ruta de código que borre sus datos fiscales de `invoices`.
- **Recomendación:** 
  1. Crear endpoints REST para Acceso/Rectificación/Cancelación/Oposición
  2. Implementar borrado parcial de datos de titular en `invoices` manteniendo obligaciones fiscales de retención
  3. Programar cron para `enforce_retention()`

---

### Datos Sensibles
**Estado: ✅ CUMPLE (con salvedad)**

| Requisito | Estado | Detalle |
|-----------|--------|---------|
| No recaba datos sensibles | ✅ | §2.4 del aviso dice que no recaba |
| Datos de nómina de trabajadores | ⚠️ | Vía CFDI: CURP, salario, percepciones viajan a LLM externo |

#### 🔴 HALLAZGO LFPDPPP-06: Datos laborales de trabajadores viajan sin filtrar a LLM externo
- **Severidad:** CRÍTICO
- **Archivos:** `b2b_ai/agent/loop.py:156`, `b2b_ai/cfdi/parser.py:250-267`, `b2b_ai/services/llm.py`
- **Descripción:** El pipeline procesa CFDI tipo nómina, extrae CURP, salario diario, percepciones/deducciones del trabajador, y pasa esos datos completos al LLM para clasificación. Si el tenant tiene un proveedor LLM real (OpenAI, Anthropic, etc.), esos datos salen por HTTP a un tercero fuera de México.
- **Impacto:** El titular de esos datos (el trabajador) nunca dio consentimiento. Transferencia de datos personales sin base legal.
- **Recomendación:** Filtrar el sub-dict `nomina` antes de enviar al LLM. Usar solo datos anonimizados para clasificación.

---

## Hallazgos Adicionales

### 🟡 HALLAZGO ADD-01: ISR tabla subsidio empleo 2025 en payroll.py pero subsidio en compliance.py no existe
- **Severidad:** MEDIO
- **Archivo:** `b2b_ai/services/payroll.py` (SUBSIDIO_EMPLEO_MENSUAL) vs `b2b_ai/features/nomina_completa/service.py` (_calcular_subsidio)
- **Descripción:** `nomina_completa/service.py` tiene una tabla de subsidio propia con montos diferentes a los de `payroll.py`. Ambas referencian LISR Art. 174 pero con valores distintos.
- **Recomendación:** Unificar tabla de subsidio en un solo lugar.

### 🟡 HALLAZGO ADD-02: SAT validator en modo mock
- **Severidad:** MEDIO
- **Archivo:** `b2b_ai/sat/validator.py`
- **Descripción:** La verificación de CFDI y RFC es mock determinista (folios que terminan en '0' → cancelados). En producción, se debe conectar al Web Service real del SAT.
- **Recomendación:** Documentar como pendiente de integración. Agregar flag de modo real vs mock.

### 🟡 HALLAZGO ADD-03: EFOS 69-B con lista estática de ejemplo
- **Severidad:** MEDIO
- **Archivo:** `b2b_ai/sat/efos_69b.py:31-35`
- **Descripción:** La lista 69-B usa RFCs de ejemplo (`AAA010101AAA`, `EFOS000101ABC`). En producción, se debe descargar periódicamente del SAT.
- **Recomendación:** Agregar mecanismo de actualización periódica desde el archivo descargable del SAT.

### 🟢 HALLAZGO ADD-04: Contabilidad electrónica — obligaciones por régimen
- **Estado:** Bien implementado
- **Archivo:** `contabilidad_electronica/routes.py:29-65`
- **Detalle:** Tabla completa de obligaciones mensuales/anuales por régimen fiscal (601, 612, 606, 626).

### 🟢 HALLAZGO ADD-05: DIOT — detección de EFOS en emisores
- **Estado:** Bien implementado
- **Archivo:** `sat/efos_69b.py`
- **Detalle:** Check contra lista 69-B antes de aceptar deducibilidad de IVA.

---

## Resumen de Hallazgos por Severidad

### CRÍTICOS (6)
1. **LISR-01:** Tablas ISR desactualizadas e inconsistentes (2024 vs 2025)
2. **LFPDPPP-01:** Aviso de privacidad no accesible al titular
3. **LFPDPPP-02:** Autoridad competente incorrecta (PROFEPA → SABG)
4. **LFPDPPP-04:** Sin evidencia de consentimiento
5. **LFPDPPP-05:** Derechos ARCO sin implementación real
6. **LFPDPPP-06:** Datos laborales viajan sin filtrar a LLM externo

### ALTOS (2)
7. **DIOT-01:** Catálogo TipoOperación inconsistente entre módulos
8. **LFPDPPP-03:** RFC del responsable no completado

### MEDIOS (4)
9. **LFT-01:** Cálculo IMSS simplificado en nomina_completa
10. **ADD-01:** Tabla subsidio empleo duplicada con valores diferentes
11. **ADD-02:** SAT validator en modo mock
12. **ADD-03:** EFOS 69-B con lista estática

---

## Plan de Remediación Prioritizado

### Fase 1 — Inmediato (antes de producción)
1. **Unificar tablas ISR** → eliminar duplicados, usar tabla 2025 vigente
2. **Publicar aviso de privacidad** → agregar enlace en landings y ruta `/legal/privacy`
3. **Corregir autoridad** → cambiar PROFEPA por SABG en PRIVACY-POLICY.md
4. **Completar RFC** → llenar campo RFC del responsable
5. **Filtrar datos de nómina** → excluir sub-dict `nomina` antes del LLM

### Fase 2 — Corto plazo (1-2 semanas)
6. **Implementar endpoints ARCO** → Acceso/Rectificación/Cancelación/Oposición
7. **Capturar consentimiento** → agregar `accepted_privacy_at` y checkbox
8. **Unificar cálculo IMSS** → usar `calc_imss()` de payroll.py en todos los módulos
9. **Unificar tabla subsidio** → consolidar en un solo archivo

### Fase 3 — Medio plazo (1 mes)
10. **Conectar SAT real** → reemplazar mock de `sat/validator.py`
11. **Actualizar lista 69-B** → mecanismo de descarga periódica del SAT
12. **Cron para retention** → programar ejecución automática de `enforce_retention()`

---

## Archivos Revisados

| Categoría | Archivos | Líneas revisadas |
|-----------|----------|-----------------|
| Compliance central | `compliance.py`, `flags.py` | ~800 |
| Nómina/LISR | `nomina/validators.py`, `nomina/parser.py`, `nomina_completa/service.py`, `services/payroll.py` | ~2,500 |
| DIOT/LIVA | `diot/validators.py`, `diot/service.py`, `services/diot_validator.py` | ~1,500 |
| Declaraciones | `declaraciones/validators.py`, `declaraciones/service.py` | ~1,200 |
| Conciliación fiscal | `conciliacion_fiscal/validators.py`, `conciliacion_fiscal/service.py` | ~800 |
| Pre-auditoría | `pre_auditoria/service.py` | ~400 |
| CFDI/SAT | `cfdi/parser.py`, `cfdi/validator.py`, `cfdi/catalogs.py`, `sat/validator.py`, `sat/efos_69b.py` | ~1,200 |
| Contabilidad electrónica | `contabilidad_electronica/routes.py` | ~300 |
| Reportes | `reportes_gerenciales/validators.py`, `reportes_gerenciales/service.py` | ~800 |
| Auth/Seguridad | `auth/middleware.py` | ~300 |
| Legal | `docs/legal/PRIVACY-POLICY.md`, `docs/legal/TERMS-OF-SERVICE.md` | ~370 |
| Auditorías previas | `docs/auditoria-1/legal.md` | ~55 |
| **Total** | **28 archivos** | **~10,200 líneas** |

---

*Auditoría generada por Gates (Inteligencia) — Likida AI Enterprise*
