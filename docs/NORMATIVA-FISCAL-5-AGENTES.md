# NORMATIVA FISCAL MEXICANA — 5 SOLUCIONES AGENTICAS

> **Documento de referencia técnica** para el desarrollo de agentes IA en `likida-ai-enterprise`.
> Todas las referencias son artículos reales y verificables del CFF, LISR, LIVA, LFT, RMF y NIF.
>
> Última actualización: Agosto 2026 | Basado en legislación vigente (incluye reformas 2024-2025)

---

## TABLA DE CONTENIDOS

1. [Close Management Agent](#1-close-management-agent)
2. [Declaraciones Fiscales](#2-declaraciones-fiscales)
3. [Conciliación Bancaria](#3-conciliación-bancaria)
4. [AP/AR — Cuentas por Pagar y Cobrar](#4-apar--cuentas-por-pagar-y-cobrar)
5. [Bookkeeping — Contabilidad Completa](#5-bookkeeping--contabilidad-completa)
6. [Referencias cruzadas y tabla de artículos](#6-referencias-cruzadas)
7. [Apéndice: Catálogo de Cuentas SAT](#7-apéndice-catálogo-de-cuentas-sat)

---

## 1. CLOSE MANAGEMENT AGENT

### 1.1 NIF (Normas de Información Financiera) Aplicables

Las NIF son emitidas por el **CINIF (Consejo Mexicano de Normas de Información Financiera)** y son de observancia obligatoria para todos los reporting entities en México (CFF Art. 28, fracc. I).

| NIF | Nombre | Aplicación al cierre |
|-----|--------|---------------------|
| **NIF A-1** | Estructura de las Normas de Información Financiera | Marco conceptual: devengación contable, partida doble, negocio en marcha |
| **NIF A-3** | Necesidades de los usuarios y objetivos de los estados financieros | Define qué información debe generar el agente de cierre |
| **NIF A-5** | Elementos básicos de los estados financieros | Definición de activos, pasivos, capital contable, ingresos, gastos |
| **NIF A-7** | Supuestos fundamentales | Devengación contable, negocio en marcha |
| **NIF B-1** | Estado de situación financiera | Cómo presentar activos/pasivos al cierre |
| **NIF B-2** | Estado de resultados integral | Clasificación de gastos por función o naturaleza |
| **NIF B-3** | Estado de cambios en el patrimonio | Variaciones de capital contable |
| **NIF B-4** | Estado de flujos de efectivo | Método directo o indirecto |
| **NIF B-5** | Notas a los estados financieros | Revelaciones obligatorias en cierre anual |
| **NIF C-1** | Efectivo y equivalentes de efectivo | Conciliación bancaria como base de cierre |
| **NIF C-3** | Inventarios | Ajuste por valuación al cierre (costo o NRV) |
| **NIF C-4** | Activos intangibles | Amortización periódica |
| **NIF C-6** | Inversiones en asociadas y negocios conjuntos | Participación en resultados |
| **NIF C-9** | Instrumentos financieros | Valuación al valor razonable |
| **NIF C-15** | Combos de arrendamiento | Reconocimiento de ROU assets (reforma 2019) |
| **NIF C-20** | Instrumentos financieros con características de pasivo, capital o ambas | Clasificación correcta |
| **NIF D-1** | Ingresos por contratos con clientes | Reconocimiento de ingresos (criterio de 5 pasos) |
| **NIF D-2** | Beneficios a los empleados | Provisión de aguinaldo, vacaciones, prima vacacional, PTU |
| **NIF D-3** | Impuestos a la utilidad | ISR causado vs. ISR pagado, impuestos diferidos (DITL/DITR) |
| **NIF D-4** | Subvenciones del gobierno y transferencias | Si aplica (estímulos fiscales) |
| **NIF D-6** | Provisiones, contingencias y compromisos | Provisión para juicios laborales, fiscales |
| **NIF D-7** | Hechos posteriores al cierre | Ajustes y revelaciones entre fecha de cierre y emisión |
| **NIF E-1** | Consolidación de estados financieros | Si el agente maneja grupos corporativos |
| **NIF E-2** | Combinación de negocios | Adquisiciones durante el periodo |
| **NIF NIIF 1** | Adopción por primera vez de las NIIF | Para contribuyentes que usan NIIF (opción en CFF Art. 28) |

### 1.2 CFF Art. 28 — Contabilidad Electrónica

**Artículo 28 del Código Fiscal de la Federación** establece las obligaciones fundamentales:

**Fracción I** — Llevar contabilidad con base en NIF y cumplir con:
- Sistemas y registros contables que integren una **contabilidad electrónica**
- **Catálogo de cuentas** del contribuyente conforme al **agrupador del SAT** (Anexo 24 RMF)
- Enviar al SAT el **catálogo de cuentas** en formato XML
- Enviar mensualmente la **balanza de comprobación** (dentro de los 3 días siguientes a que venza el plazo de la declaración del periodo)
- Enviar la **información del auxiliar de folios de CFDI** (polizas_xml)

**Fracción II** — Las **pólizas contables electrónicas** se deben:
- Generar en formato XML conforme al anexo 24 de la RMF
- Entregar al SAT cuando sea requerido mediante requerimiento fiscal
- Contener: UUID del CFDI relacionado, cuenta contable, descripción, importes

**Fracción III** — Excepciones (Art. 28, fracc. III):
- Personas físicas con actividad empresarial cuyos ingresos no excedan del límite del Régimen de Incorporación Fiscal (actualmente $3.5M anuales)
- Quienes tributen en el régimen de Sueldos y Salarios
- Personas físicas en el régimen de Actividades Empresariales y Profesionales con ingresos ≤ $2M (opción simplificada)

### 1.3 Plazos Legales de Cierre Mensual/Anual

| Obligación | Plazo | Fundamento |
|-----------|-------|------------|
| **Pagos provisionales ISR mensuales** | Día 17 del mes siguiente | LISR Art. 14 (PM) / Art. 116-117 (PF) |
| **Declaración mensual IVA** | Día 17 del mes siguiente | LIVA Art. 5, fracc. II |
| **DIOT (mensual)** | Día 17 del mes siguiente | RMF 2.7.1.1 |
| **Balanza de comprobación mensual** | 3 días hábiles después del vencimiento de la declaración | RMF 2.8.1.5 |
| **Catálogo de cuentas** | Una vez al año (o al registrarse) + cuando cambie | RMF 2.8.1.2 |
| **Declaración anual ISR PM** | 31 de marzo del año siguiente | LISR Art. 9, fracc. IV |
| **Declaración anual ISR PF** | 30 de abril del año siguiente | LISR Art. 150 |
| **PTU (reparto)** | Dentro de 60 días siguientes al cierre (PM con trabajadores) | LFT Art. 122 |
| **Dictamen fiscal** (si aplica) | 15 de mayo / 15 de junio / 30 de junio del año siguiente | LISR Art. 32-A |

### 1.4 Pólizas de Ajuste Más Comunes en Cierre Mensual

| Póliza de ajuste | Cuenta Cargo | Cuenta Crédito | Fundamento |
|------------------|-------------|----------------|------------|
| **Depreciación mensual** | Gasto depreciación (601-xxxx) | Activo fijo neto (15x-xxxx) | NIF C-6, LISR Art. 34-36 |
| **Amortización intangibles** | Gasto amortización (602-xxxx) | Intangible neto (2xx-xxxx) | NIF C-4, LISR Art. 41 |
| **Provisión aguinaldo** | Gasto aguinaldo (601-xxxx) | Provisión aguinaldo (2xx-xxxx) | NIF D-2, LFT Art. 87 |
| **Provisión vacaciones y prima vacacional** | Gasto prestaciones (601-xxxx) | Provisión vacaciones (2xx-xxxx) | NIF D-2 |
| **Provisión PTU** | Gasto PTU (601-xxxx) | Provisión PTU (2xx-xxxx) | LFT Art. 120 |
| **ISR causado (ajuste anual)** | ISR (501-xxxx) | Provisión ISR (2xx-xxxx) | NIF D-3 |
| **Diferencias de cambio** | Gasto/Pérdida FX (605-xxxx) o Cuenta por cobrar (1xx) | Cuenta por cobrar/pagar FX | NIF C-1, LISR Art. 8 |
| **Ajuste de inventarios** | Costo de ventas (501-xxxx) | Inventario (1xx-xxxx) | NIF C-3 |
| **Valuación de inversiones** | Pérdida valuación (606-xxxx) / Utilidad valuación (4xx) | Inversión (1xx-xxxx) | NIF C-9, C-20 |
| **Provisión cuentas incobrables** | Gasto incobrables (604-xxxx) | Valuación CxC (1xx-xxxx) | NIF C-1, LISR Art. 46-47 |
| **Ajuste por inflación acumulable/deducible** | Ingreso por inflación (4xx) / Gasto por inflación (607) | Diversos activos/pasivos monetarios | LISR Art. 44-45 |
| **Amortización de cartera de crédito** | Ajuste cartera (502-xxxx) | Valuación cartera (1xx) | NIF C-1, para SIFIDE/sofomes |

### 1.5 Qué Revisa un Auditor Fiscal (Checklist)

El auditor fiscal revisa que la **base fiscal** sea congruente con la **base contable**, identificando diferencias permanentes y temporarias:

1. **Ingresos acumulables** (LISR Art. 16-18): Que todos los CFDI emitidos estén reflejados, que no haya ingresos omitidos
2. **Deducciones autorizadas** (LISR Art. 25-32 para PM, Art. 105-112 para PF): Que cada gasto cumpla con los requisitos de CFF Art. 27
3. **CFDI como requisito de deducción** (CFF Art. 27, fracc. V y V bis): Que todo gasto deducible tenga CFDI válido
4. **Depreciación fiscal vs. contable** (LISR Art. 34-41): Diferencias en porcentajes, vida útil
5. **Inventarios** (LISR Art. 32, fracc. I-III): Método de valuación (costo identificado, UEPS, PEPS, promedio)
6. **Nómina y retenciones** (LISR Art. 110, 174): Que las retenciones de ISR se hayan enterado correctamente
7. **IVA acreditado** (LIVA Art. 5): Que el IVA acreditable sea estrictamente proporcional al gasto relacionado con la actividad gravada
8. **IVA trasladado** (LIVA Art. 1): Que todo ingreso cobrado tenga IVA trasladado correspondiente
9. **Operaciones con partes relacionadas** (LISR Art. 179-181): Precios de transferencia, valor razonable
10. **Precios de transferencia** (LISR Art. 179-181, Art. 76-A, 76-B CFF): Estudios documentales para operaciones con residentes en el extranjero
11. **Contabilidad electrónica** (CFF Art. 28): Que la balanza, catálogo y pólizas se hayan enviado al SAT en tiempo y forma
12. **Multas y recargos** (CFF Art. 73-81): Cálculo de actualizaciones, recargos, multas por incumplimiento
13. **Consolidación fiscal** (si aplica, LISR Art. 61-71): Operaciones entre integradas e integradora

---

## 2. DECLARACIONES FISCALES

### 2.1 Artículos del CFF que Aplican

| Artículo | Tema | Relevancia para el agente |
|----------|------|--------------------------|
| **CFF Art. 27** | Requisitos de las deducciones | Toda factura capturada debe cumplir estos requisitos para ser deducible |
| **CFF Art. 29** | Expedición de CFDI | El agente debe validar CFDI 4.0 recibidos y emitidos |
| **CFF Art. 31** | Obligaciones de los contribuyentes | Registro de ingresos/egresos, expedir CFDI, declaraciones |
| **CFF Art. 32** | Declaraciones informativas | Presentar la DIOT y otras informativas |
| **CFF Art. 32-A** | Dictamen fiscal | Opción para contribuyentes con ingresos > $100M o autorización previa |
| **CFF Art. 33** | Obligaciones específicas | Llevar contabilidad, presentar declaraciones |
| **CFF Art. 76** | Declaración anual de personas morales | Información detallada sobre la operación |
| **CFF Art. 86** | Declaración anual de personas físicas | Oportunidad y forma |
| **CFF Art. 87** | Facultades de la autoridad para requerir información | El SAT puede requerir datos específicos |
| **CFF Art. 110** | Personas físicas obligadas a declarar | Régimen de Sueldos y Salarios, Actividades Empresariales, Arrendamiento |
| **CFF Art. 116** | Pagos provisionales de personas físicas | Cálculo y forma de pago |
| **CFF Art. 39** | Aviso de actualización de actividades económicas | Actualización en el RFC |

### 2.2 LISR — Impuesto Sobre la Renta

#### 2.2.1 Pagos Provisionales (LISR Art. 14 — Personas Morales)

```
Pago provisional = Utilidad fiscal del periodo × Tasa ISR (30%) 
                   − Pagos provisionales de periodos anteriores
                   − Participación de trabajadores pagada en el periodo (proporcional)
```

**Obligaciones:**
- **Personas Morales**: Pago provisional mensual a más tardar el día 17 del mes siguiente (Art. 14, párrafo 2)
- **Opción de coeficiente de utilidad** (Art. 14, párrafo 8): El SAT puede autorizar el cálculo con coeficiente de utilidad del ejercicio anterior
- **Personas Físicas**: Pagos provisionales mensuales con cálculo según actividad (Art. 116)

**Opción de pagos bimestrales** (Art. 14, penúltimo párrafo): Personas morales con ingresos totales ≤ $4M pueden optar por pagos provisionales bimestrales.

#### 2.2.2 Pagos Definitivos

No existe "pago definitivo" como tal para PM. Las PM realizan pagos provisionales mensuales y una **declaración anual** (Art. 9, fracc. IV).

Para PF: Existe pago definitivo anual (Art. 150-170).

#### 2.2.3 Declaración Anual

**Personas Morales (Art. 9, fracc. IV):**
- Plazo: 3 meses posteriores al cierre del ejercicio (31 de marzo para PM con cierre 31 de diciembre)
- Se determina la **utilidad fiscal** y se restan pagos provisionales
- Se determina ISR a cargo o saldo a favor
- Se incluye la PTU como deducción autorizada (proporcional, no el total)

**Personas Físicas (Art. 150):**
- Plazo: 30 de abril del año siguiente
- Régimen de Sueldos y Salarios: Opción de no declarar si no exceden $400K anuales de un solo patrón
- Actividades Empresariales y Profesionales: Declaración anual obligatoria

#### 2.2.4 ISR Diferido (NIF D-3)

La determinación de **impuestos diferidos** es obligatoria para estados financieros (no fiscal):
- **DITL** (Diferencia Impuesto a la Utilidad de ejercicios anteriores): Activos/pasivos por impuestos diferidos
- **DITR** (Diferencia Impuesto a la Utilidad del ejercicio): Efecto del ISR diferido del periodo

### 2.3 LIVA — Ley del Impuesto al Valor Agregado

#### 2.3.1 Acreditamiento (LIVA Art. 5)

**Art. 5, fracc. I** — El IVA acreditable se determina así:
- IVA **pagado** en la adquisición de bienes, uso o goce temporal, y servicios
- IVA **pagado** por importación de bienes o servicios
- **Requisito**: Que el bien o servicio se utilice para realizar actividades gravadas (Art. 5, fracc. I)
- **Proporcionalidad** (Art. 5, fracc. II): Si el contribuyente realiza actividades gravadas y exentas, solo acredita proporcionalmente

**IVA acreditable = IVA pagado × (Ingresos gravados / Ingresos totales)**

#### 2.3.2 Tasa 0% (LIVA Art. 2, fracc. I — 2-A)

Aplica a:
- Exportaciones de bienes y servicios
- Enajenación de bienes intangibles a residentes en el extranjero
- Ventas al mayoreo de productos agropecuarios
- Medicinas de patente (hasta cierto límite)
- Alimentos procesados para consumo humano (salvo ciertos)
- Hielo y agua no gaseosa ni compuesta
- Animales y vegetales no industrializados
- Equipo médico

**Agente debe**: Identificar facturas con tasa 0% y tratarlas como IVA acreditable al 100% (no proporcional).

#### 2.3.3 IVA a Favor (Saldo a Favor)

- Cuando el IVA acreditable > IVA trasladado, hay **saldo a favor**
- Art. 6 LIVA: El saldo a favor se puede solicitar en devolución (Art. 22 CFF) o compensar contra ISR (Art. 6 LIVA)
- **Plazo de devolución**: 40 días hábiles (Art. 22 CFF, plazo estándar)
- **Compensación universal** (CFF Art. 23): Se puede compensar contra cualquier otra contribución federal
- **Requisito para devolución**: Solicitud a través del portal SAT + CFDI correspondientes

### 2.4 DIOT — Declaración Informativa de Operaciones con Terceros

**Fundamento**: CFF Art. 32, fracc. III y RMF 2.7.1.1

#### Obligaciones:
- **Quiénes**: Todos los contribuyentes del IVA (personas físicas y morales)
- **Contenido**: Operaciones con proveedores y clientes (RFC, monto de operación, IVA trasladado, IVA acreditable, tipo de operación)
- **Formato**: Electrónico a través del portal SAT (Anexo 19 RMF — formato XML)
- **Plazo**: Día 17 del mes siguiente a la operación

#### Estructura de la DIOT:
```xml
<!-- Tipos de operación en la DIOT -->
03 - Actos o actividades gravados a tasa general (16%)
05 - Actos o actividades por los que se debe pagar el IVA en forma definitiva
06 - Actos o actividades gravados a tasa 0%
07 - Actos o actividades a que se refiere la fracción III del Art. 2-A LIVA
85 - Actos o actividades del Art. 2, último párrafo (enajenación de bienes muebles usados)
```

### 2.5 IEPS — Impuesto Especial sobre Producción y Servicios

**Fundamento**: LIVA Art. 2, fracc. II y Ley del IEPS Art. 1-10

**Cuándo aplica:**
| Producto/Servicio | Tasa IEPS |
|------------------|-----------|
| Bebidas alcohólicas | 26.5% a 53% (según grado alcohólico) |
| Cerveza | $3.00/litro (o $0.57/litro según graduación) |
| Tabacos labrados | 160% ad valorem + cuota específica |
| Gasolinas y diésel | Cuota por litro (varía por región) |
| Bebidas energizantes | $13.48/litro |
| Bebidas saborizadas (refrescos) | $1.58/litro |
| Plaguicidas | 6% (ciertos tipos) |
| Juegos con apuestas y sorteos | 30% |
| Alimentos de alto contenido calórico | 8% |

**Para el agente fiscal**: El IEPS debe:
- Incluirse en la determinación de IVA (la base del IVA incluye el IEPS)
- Reportarse en declaraciones informativas (LISR Art. 32, fracc. II)
- Validar en DIOT: IEPS trasladado se incluye en el campo correspondiente

### 2.6 LISR Nómina — Retenciones y Subsidio

#### 2.6.1 Retenciones de ISR a Empleados (LISR Art. 96-113)

**Art. 96** — Retención mensual según tablas:
- Se aplica la tarifa mensual del Art. 96 (tabla de ISR vigente)
- Se resta el **subsidio para el empleo** (Art. 110, fracc. V)

**Art. 97** — Retención anual:
- Determinar el ISR anual y restar retenciones mensuales
- El empleador determina ISR anual en la última nómina del año

#### 2.6.2 Subsidio para el Empleo (Art. 110, fracc. V)

| Ingreso mensual | Subsidio mensual |
|-----------------|------------------|
| Hasta $2,038.52 | $407.02 |
| $2,038.53 - $3,426.66 | Tabla decreciente |
| Más de $3,426.66 | $0.00 |

**Requisito**: El subsidio se aplica solo si el ingreso mensual no excede el equivalente de la 2ª línea de la tabla del Art. 96. El subsidio se determina según tabla del Art. 110 (incluida en la Ley).

**Art. 174** — Personas físicas que paguen asimilados a salarios: Retención del 35% (sin deducciones personales). Si los ingresos anuales no exceden de $75M, existe la opción de retención con tarifa progresiva.

#### 2.6.3 Otras Retenciones de Nómina

| Concepto | Fundamento | Retención |
|----------|-----------|-----------|
| ISR asimilados | LISR Art. 94-96 | 35% (o tarifa Art. 96) |
| ISR a extranjeros | LISR Art. 178-179 | 15% a 40% según concepto |
| ISR por primas de antigüedad | LISR Art. 110, fracc. II | Tarifa Art. 96 |
| INFONAVIT (patrón) | LINFRAVIT Art. 29 | 5% sobre SALARIO INTEGRADO (SBC) |
| IMSS (patrón) | LSS Art. 15-16 | Variable según riesgo |
| SAR (patrón) | LSS Art. 168 | 2% sobre SBC |

### 2.7 Declaraciones Informativas

#### 2.7.1 IETU (Impuesto Empresarial a Tasa Única) — ELIMINADO
- **Estado**: El IETU fue eliminado en 2014. No es aplicable actualmente.
- **Referencia histórica**: Art. 1-LISR (derivado de la Ley del IETU de 2007-2013)
- **Para el agente**: Solo considerar si hay saldos a favor pendientes de amortizar de ejercicios anteriores (transición de IETU a ISR)

#### 2.7.2 IDE (Impuesto a Depósitos en Efectivo) — ELIMINADO
- **Estado**: El IDE fue derogado en 2014.
- **Referencia histórica**: Art. 1-5 de la LIDE (2008-2013)
- **Para el agente**: No aplica. Los depósitos en efectivo se controlan por el Art. 55 CFF (facultades de revisión) y el Art. 59 (presunción de ingresos).

#### 2.7.3 Informativas Vigentes Relevantes

| Declaración | Plazo | Fundamento |
|-------------|-------|------------|
| **DIOT** (IVA) | Día 17 del mes siguiente | RMF 2.7.1.1 |
| **DIM** (Operaciones con residentes en el extranjero) | 15 de febrero del año siguiente | CFF Art. 76 fracc. VII |
| **Dictamen fiscal** (si aplica) | 15 de mayo / 15 de junio / 30 de junio | LISR Art. 32-A |
| **Estados Financieros** (para PM obligadas) | Con declaración anual | CFF Art. 34 |
| **Constancia de retenciones** a asalariados | 28 de febrero del año siguiente | CFF Art. 99 fracc. I |
| **Constancia de pagos a extranjeros** | 28 de febrero | CFF Art. 76 fracc. XI |
| **Informativa global** (FACTA/CRS) | Según convenio | RMF 2.15.6 |

### 2.8 Plazos por Régimen Fiscal

#### Personas Morales:
| Régimen | Pago Provisional | Declaración Anual |
|---------|------------------|-------------------|
| **General (título II)** | Día 17 del mes siguiente | 31 de marzo |
| **Régimen coordinado (cooperativas)** | Día 17 del mes siguiente | 31 de marzo |
| **Personas morales con fines no lucrativos** | Sin pago provisional (ciertos casos) | 31 de marzo |
| **Régimen de Incorporación Fiscal (ex PM)** | Día 17 bimestral | 30 de abril |

#### Personas Físicas:
| Régimen | Pago Provisional | Declaración Anual |
|---------|------------------|-------------------|
| **Sueldos y Salarios** | Sin pago provisional (retiene patrón) | 30 de abril (opcional si ≤ $400K de un patrón) |
| **Actividades Empresariales y Profesionales** | Día 17 del mes siguiente | 30 de abril |
| **Régimen de Incorporación Fiscal** | Día 17 bimestral | 30 de abril |
| **Arrendamiento** | Día 17 del mes siguiente | 30 de abril |
| **Enajenación de bienes** | Mes siguiente a la enajenación | 30 de abril (complementaria) |
| **Intereses** | Sin pago provisional (retiene pagador) | 30 de abril |
| **Dividendos** | Sin pago provisional (retiene pagador) | 30 de abril |
| **Premios** | Sin pago provisional (retiene pagador) | 30 de abril |

### 2.9 Excepciones y Errores Comunes que Causan Rechazo SAT

| Error | Causa | Solución para el agente |
|-------|-------|------------------------|
| **UUID no válido** | CFDI cancelado o no registrado en SAT | Validar CFDI contra el PAC antes de registrar |
| **RFC incorrecto** | Error de captura | Validar RFC contra lista del SAT (Art. 23 CFF) |
| **Periodo incorrecto** | Declaración mensual en periodo equivocado | Mapping correcto de periodos fiscales |
| **Base cero en pago provisional** | No se determinó utilidad fiscal | Alerta automática de utilidad/pérdida fiscal |
| **DIOT con omisiones** | Facturas sin captura | Cruce automático CFDI vs. DIOT |
| **Tipo de cambio incorrecto** | Uso de TC del día equivocado | TC oficial del Banco de México del día (Art. 8 CFF) |
| **Conceptos no deducibles** | Gastos personales mezclados | Filtrado por catálogo de conceptos deducibles |
| **Doble declaración** | Presentar la misma declaración dos veces | Validación de folios existentes |
| **Firma FIEL/CIEC expirada** | Certificado vencido | Alerta de vencimiento de e.firma (Art. 17-D CFF) |
| **Pagos provisionales en ceros** | Contribuyente con actividad no reportada | Generar con coeficiente de utilidad histórica |

---

## 3. CONCILIACIÓN BANCARIA

### 3.1 CFF Art. 28 — Obligación de Conciliar

**Art. 28, fracc. I, incisos:**

La contabilidad electrónica debe integrar:
- **Estado de cuenta bancario** como parte de la contabilidad
- Los **movimientos bancarios** deben estar reflejados en la contabilidad
- **La conciliación bancaria** no es explícitamente nombrada como "obligación" en Art. 28, pero se deriva de:
  - Art. 28: Los registros contables deben reflejar fielmente las operaciones
  - Art. 31, fracc. I: Llevar contabilidad que integre una auxiliar de registro de operaciones

**RMF 2.8.1.5** — Requisitos de la balanza de comprobación:
- Debe incluir información de CFDI
- El SAT puede verificar que los ingresos declarados sean congruentes con depósitos bancarios

### 3.2 Reglas Miscelánea Fiscal para Conciliación

| Regla | Contenido | Impacto |
|-------|-----------|---------|
| **RMF 2.8.1.2** | Catálogo de cuentas con agrupadores SAT | Las cuentas bancarias deben estar correctamente clasificadas (1020000) |
| **RMF 2.8.1.5** | Balanza de comprobación mensual | El SAT cruza la balanza con los estados de cuenta |
| **RMF 2.8.1.6** | Pólizas contables electrónicas | Contienen UUIDs que permiten rastrear cada movimiento |
| **RMF 2.8.2.1** | Conciliación de saldos | Los saldos de la balanza deben coincidir con los estados de cuenta |
| **RMF 2.8.3.6** | Validación de CFDI en pólizas | Cada gasto debe tener CFDI que lo respalde |

### 3.3 Discrepancias Fiscales (LISR Art. 91)

**Art. 91 de la LISR** — Discrepancia fiscal para personas físicas:

> Cuando las erogaciones en un año de calendario sean **mayores** a los ingresos declarados, el SAT determinará presuntivamente los ingresos omitidos.

**Aplicación:**
- Se comparan **erogaciones** (depósitos bancarios, adquisición de bienes, gastos con tarjeta) contra **ingresos declarados**
- Si hay diferencia, se presume como ingreso gravable la diferencia

**Art. 91, párrafo 3**: No se consideran erogaciones:
- Los depósitos que el contribuyente demuestre provienen de:
  - Ingresos declarados anteriormente
  - Otros ingresos exentos
  - Enajenación de bienes (demostrable con CFDI)
  - Herencias o donativos (Art. 93 LISR)

**Para el agente de conciliación**: 
- La conciliación bancaria debe detectar automáticamente discrepancias entre ingresos declarados y depósitos
- Generar alertas cuando depósitos > ingresos × 1.15 (umbral configurable)

### 3.4 Presunción de Ingresos (LISR Art. 59)

**Art. 59 de la LISR** — Presunción de ingresos (Personas Físicas):

> Se presume que son ingresos los depósitos en cuentas a nombre del contribuyente, **salvo** que se demuestre que:
> - Provienen de un ingreso que ya fue declarado
> - Son transferencias entre cuentas propias
> - Son préstamos o créditos (con documentación comprobatoria)
> - Son ingresos exentos (herencias, donativos)

**Art. 59, párrafo 2**: La autoridad fiscal puede:
- Presumir ingresos por depósitos en cuentas del contribuyente
- Presumir ingresos por tarjetas de crédito
- Presumir ingresos por adquisición de bienes registrados (autos, inmuebles)

**Para el agente:**
```
INGRESOS_PRESUMIDOS = depósitos_bancarios 
                      + compras_tarjeta 
                      - transferencias_entre_cuentas_propias 
                      - ingresos_ya_declarados 
                      - préstamos_documentados
```

---

## 4. AP/AR — CUENTAS POR PAGAR Y COBRAR

### 4.1 Deducción de Pagos a Proveedores (CFF Art. 27, LISR Art. 25-32)

#### 4.1.1 CFF Art. 27 — Requisitos Generales de Deducción

Toda deducción debe cumplir con **todos** los requisitos del Art. 27:

| Fracción | Requisito | Implementación en agente |
|----------|-----------|--------------------------|
| **I** | Ser estrictamente indispensable para los ingresos | Validar que el concepto sea del giro del negocio |
| **III** | Estar amparada con CFDI | Validar UUID, RFC emisor, concepto, total |
| **IV** | Pago con cheque nominativo, transferencia bancaria, tarjeta | Validar forma de pago en CFDI (método de pago ≠ PPD sin pago parcial) |
| **V** | CFDI vigente y timbrado | Validar contra el SAT que no esté cancelado |
| **V bis** | Retención de ISR e IVA cuando aplique | Verificar que el CFDI incluya retenciones |
| **VI** | Llevar contabilidad conforme NIF | Registro contable automático |
| **IX** | Tratándose de pagos al extranjero | Constancia de retención (Art. 76 fracc. XI) |
| **X** | Deducción de inversiones | LISR Art. 34-43 |

#### 4.1.2 LISR Art. 25 — Conceptos Deducibles (Personas Morales)

| Artículo | Concepto | Requisito clave |
|----------|----------|-----------------|
| **Art. 25, fracc. I** | Devoluciones recibidas | CFDI de nota de crédito |
| **Art. 25, fracc. II** | Descuentos y bonificaciones | CFDI de nota de crédito |
| **Art. 25, fracc. III** | Costo de lo vendido | Método de inventarios (Art. 32) |
| **Art. 25, fracc. IV** | Gastos netos de descuentos | CFDI + pago bancario |
| **Art. 25, fracc. V** | Inversiones (amortización/depreciación) | Art. 34-43 |
| **Art. 25, fracc. VI** | Cuotas al IMSS pagadas por el patrón | CFDI del IMSS |
| **Art. 25, fracc. VII** | Aportaciones de seguridad social (INFONAVIT, SAR) | Recibos de pago |
| **Art. 25, fracc. VIII** | Fondos de ahorro | LFT Art. 154 |
| **Art. 25, fracc. IX** | Primas de seguros | Póliza + CFDI |
| **Art. 25, fracc. X** | Arrendamiento financiero (leasing) | LISR Art. 38 (IFRS 16/NIF D-5) |
| **Art. 25, fracc. XI** | Regalías y asistencia técnica | Retenciones correspondientes |
| **Art. 25, fracc. XII** | Regalías pagadas a residentes en el extranjero | CFF Art. 174 LISR |
| **Art. 25, fracc. XIII** | PTU pagada a trabajadores | Art. 120 LFT |
| **Art. 25, fracc. XIV** | Inversiones en investigación y desarrollo | Deducción en el ejercicio (o amortización) |

#### 4.1.3 LISR Art. 26 — Gastos No Deducibles

| Fracción | Concepto | Alerta para el agente |
|----------|----------|----------------------|
| **I** | Gastos personales del contribuyente | Filtrar RFC propietario/accionista |
| **II** | Donativos no onerosos ni remunerativos | No deducible salvo Art. 79 LISR |
| **III** | Multas y recargos fiscales | No deducible (Art. 26, fracc. I CFF) |
| **IV** | Pérdidas por caso fortuito o fuerza mayor | Solo si no hay seguro |
| **V** | Inversiones en bienes raíces destinadas a casa habitación | Excepciones si son arrendamiento |
| **VI** | Pagos por concepto de interés, premio o cualquier rendimiento de títulos valor | Requisitos adicionales |
| **VII** | Gastos que generen ingresos exentos | Proporcionalidad |

### 4.2 Acreditamiento de IVA (LIVA Art. 5)

#### 4.2.1 Flujo de IVA en AP/AR

```
AR (Cuentas por Cobrar):
  Venta → IVA Trasladado (16%) → CFDI emitido → IVA por cobrar
  Cuando se cobra → IVA Trasladado se enterado en declaración mensual

AP (Cuentas por Pagar):
  Compra → IVA Acreditable (16%) → CFDI recibido → IVA por acreditar
  Cuando se paga → Se acredita contra IVA trasladado
```

#### 4.2.2 Art. 5, fracc. I LIVA — Requisitos del Acreditamiento

1. **Que el IVA haya sido trasladado** al contribuyente (en el CFDI)
2. **Que esté efectivamente pagado** (Art. 5, fracc. I) — El IVA solo es acreditable cuando se paga el bien o servicio
3. **Que se destine a la actividad gravada** (Art. 5, fracc. I) — Proporcionalidad
4. **Que se cuente con CFDI** (Art. 5, fracc. I)
5. **Que esté desglosado** en el CFDI (Art. 29 CFF)

#### 4.2.3 Proporcionalidad del Acreditamiento (Art. 5, fracc. II)

```
Porcentaje de operaciones gravadas = Ingresos gravados / Ingresos totales
IVA acreditable = IVA pagado × Porcentaje gravado
```

**Ingresos gravados** incluyen: Tasa general (16%) + Tasa 0%
**No se incluyen**: Ingresos exentos de IVA (intereses, dividendos, arrendamiento exento, etc.)

### 4.3 Retenciones de ISR a Proveedores

| Concepto | Fundamento | Tasa de retención | Aplica cuando |
|----------|-----------|-------------------|---------------|
| **Arrendamiento (inmuebles)** | LISR Art. 94, fracc. III / Art. 96 | 10% del pago | PF arrendadora |
| **Honorarios profesionales** | LISR Art. 94, fracc. II / Art. 96 | Tarifa Art. 96 (sobre monto) | PF prestadora de servicios |
| **Servicios profesionales** | LISR Art. 100 | 10% sobre ingresos brutos | PF en Actividades Empresariales y Profesionales |
| **Regalías** | LISR Art. 178, fracc. I | 25% (res. MX) / 40% (res. extranjero) | Regalías a residentes |
| **Premios** | LISR Art. 178, fracc. II | 1% a 21% (según monto) | Sorteos, concursos |
| **Intereses** | LISR Art. 135-143 | 0.08% a 4.9% mensual (según monto) | PF inversionistas |
| **Subcontratación laboral** | LISR Art. 12, fracc. I (reforma 2021) | 6% del pago | Empresa que subcontrata (no deducible salvo PTU especializado) |

**Art. 100 LISR** — Retención por pagos a personas físicas por honorarios:
- Pagador retiene ISR según tabla del Art. 96
- Se emite CFDI de nómina (asimilados) o de retención de pagos a PF

### 4.4 Notas de Crédito y Devoluciones

**Fundamento**: LISR Art. 25, fracc. I y II / CFF Art. 29

| Tipo | Efecto fiscal | CFDI requerido |
|------|--------------|----------------|
| **Nota de crédito por devolución** | Reduce ingresos acumulables del vendedor; reduce IVA trasladado | CFDI tipo "E" (Egreso) |
| **Nota de crédito por descuento** | Reduce ingresos del vendedor; reduce base de IVA | CFDI tipo "E" |
| **Devolución de mercancía por proveedor** | Reduce costo de ventas del comprador; reduce IVA acreditable | CFDI tipo "E" del proveedor |
| **Bonificación por volumen** | Reduce gastos del comprador; reduce IVA acreditable | CFDI tipo "E" |
| **Cancelación de factura** | Anula ingreso/gasto; anula IVA trasladado/acreditable | CFDI cancelado (UUID cancelado) |

**Regla RMF 2.7.1.37** — Notas de crédito:
- Las notas de crédito deben emitirse como CFDI tipo "E" (Egreso)
- Deben referenciar el UUID del CFDI original
- Se presentan en la DIOT como operaciones de crédito

### 4.5 Anticipos y Pagos Parciales

**CFF Art. 29-A, fracc. IV** — Anticipos:

| Concepto | Tratamiento |
|----------|-------------|
| **Anticipo a proveedor** | CFDI de nómina NO se requiere; se emite CFDI al entregar el anticipo, y CFDI de "Pago en una sola exhibición" al recibir el bien/servicio |
| **Anticipo de cliente** | Se emite CFDI por el anticipo (Art. 29-A fracc. IV); al facturar definitivamente se emite CFDI que desglosa el anticipo |
| **Pago parcial** | CFDI de pago con complemento de pago (Art. 29-A fracc. VII) |
| **PPD (Pago en Parcialidades o Diferido)** | Método de pago = "PPD"; requiere complemento de pago por cada parcialidad |

**Regla RMF 2.7.1.32** — Complemento de pagos:
- Cuando el pago se reciba en parcialidades o diferido, se debe emitir CFDI con complemento de pago
- **Plazo**: 5 días naturales siguientes al pago (reforma 2023-2025)
- Cada pago independiente requiere su propio complemento
- El complemento sustituye al CFDI por el monto del pago

---

## 5. BOOKKEEPING — CONTABILIDAD COMPLETA

### 5.1 Catálogo de Cuentas SAT (Agrupador 6 Dígitos)

El **Anexo 24 de la RMF** establece el agrupador SAT de cuentas contables. Cada contribuyente mapea sus cuentas contables (catálogo propio) a este agrupador.

#### Estructura del Agrupador SAT:

```
Primer dígito  → Naturaleza de la cuenta (1=Activo, 2=Pasivo, 3=Capital, 4=Ingresos, 5=Costos, 6=Gastos)
Segundo dígito → Tipo general
Tercer dígito  → Tipo intermedio
Cuarto dígito  → Cuenta mayor
Quinto dígito  → Subcuenta
Sexto dígito   → Sub-subcuenta
```

#### Agrupadores Principales (Primer Nivel):

| Código | Agrupador | Ejemplo |
|--------|-----------|---------|
| **100000** | **Activo** | |
| 1020000 | Bancos | Cuenta bancaria |
| 1050000 | Clientes | Cuentas por cobrar |
| 1080000 | Deudores diversos | Préstamos a terceros |
| 1100000 | Anticipos de clientes | |
| 1130000 | Mercancías | Inventario |
| 1180000 | Papel de trabajo | |
| 1200000 | Otros activos | |
| 1500000 | Terrenos | |
| 1520000 | Edificios | |
| 1540000 | Maquinaria y equipo | |
| 1560000 | Mobiliario y equipo de oficina | |
| 1580000 | Equipo de transporte | |
| 1600000 | Equipo de computo | |
| 1700000 | Construcciones en proceso | |
| 1800000 | Crédito mercantil (goodwill) | |
| 1900000 | Activo diferido | Pagos anticipados (seguros, rentas) |
| **2000000** | **Pasivo** | |
| 2010000 | Proveedores nacionales | Cuentas por pagar |
| 2020000 | Proveedores extranjeros | |
| 2050000 | Cuentas por pagar a partes relacionadas | |
| 2080000 | Acreedores diversos | |
| 2100000 | Anticipos de proveedores | |
| 2160000 | Acreedores hipotecarios | Créditos hipotecarios |
| 2200000 | Documentos por pagar | |
| 2500000 | Otros pasivos | |
| 2600000 | Impuestos y derechos por pagar | |
| 2610000 | ISR por pagar | |
| 2620000 | IVA por pagar | |
| 2640000 | PTU por pagar | |
| 2650000 | IMSS por pagar | |
| 2660000 | INFONAVIT por pagar | |
| 2670000 | Acreedores por pago de nómina | |
| **3000000** | **Capital Contable** | |
| 3010000 | Capital social | |
| 3020000 | Aportaciones para futuros aumentos de capital | |
| 3040000 | Resultado de ejercicios anteriores | |
| 3050000 | Resultado del ejercicio | |
| 3060000 | Otros resultados integrales (ORI) | |
| **4000000** | **Ingresos** | |
| 4010000 | Ventas | |
| 4020000 | Devoluciones sobre ventas | |
| 4040000 | Otros ingresos de la actividad ordinaria | |
| 4060000 | Otros ingresos | |
| 4080000 | Ingresos por servicios | |
| 4100000 | Ingresos por arrendamiento | |
| **5000000** | **Costos** | |
| 5010000 | Costo de lo vendido | |
| 5020000 | Compras | |
| 5030000 | Gastos de fabricación (costo indirecto) | |
| **6000000** | **Gastos** | |
| 6010000 | Gastos de administración | |
| 6020000 | Gastos de venta | |
| 6030000 | Gastos financieros | Intereses, comisiones bancarias |
| 6040000 | Pérdida en cuentas incobrables | |
| 6050000 | Pérdida cambiaria | |
| 6060000 | Pérdida por valuación de activos | |
| 6070000 | Gastos por inflación | Art. 45 LISR |

### 5.2 Agrupadores para Balanza de Comprobación

La **balanza de comprobación** es un reporte mensual obligatorio que se envía al SAT conforme a la **RMF 2.8.1.5**.

**Estructura XML del Anexo 24:**
```xml
<Balanza xmlns="http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/BalanzaComprobacion"
         Version="1.3"
         RFC="XAXX010101000"
         Mes="01"
         Anio="2026"
         TipoEnvio="Normal"> <!-- Normal / Complementaria -->
  <Cuentas NumCta="1020000" 
           Descripción="Bancos" 
           SaldoIni="100000.00" 
           Debe="500000.00" 
           Haber="400000.00" 
           SaldoFin="200000.00" />
</Balanza>
```

**Campos obligatorios por cuenta:**
- `NumCta`: Código del agrupador SAT (6 dígitos)
- `Descripción`: Nombre de la cuenta
- `SaldoIni`: Saldo inicial del periodo
- `Debe`: Total de cargos del periodo
- `Haber`: Total de abonos del periodo
- `SaldoFin`: Saldo final (= SaldoIni + Debe - Haber)

**Reglas de validación del SAT:**
1. SaldoIni de periodo = SaldoFin del periodo anterior
2. Σ Debe = Σ Haber (partida doble)
3. SaldoFin = SaldoIni + Debe - Haber
4. Las cuentas deben mapear al agrupador SAT

### 5.3 Pólizas Contables Electrónicas

**Fundamento**: CFF Art. 28, fracc. II y RMF 2.8.1.6

#### Estructura de Pólizas XML (Anexo 24):
```xml
<Polizas xmlns="http://www.sat.gob.mx/esquemas/ContabilidadE/1_3/Polizas"
         Version="1.3"
         RFC="XAXX010101000"
         Mes="01"
         Anio="2026"
         TipoSolicitud="AF"> <!-- AF=Acto de fiscalización, FC=Devolución, CO=Compensación -->
  <Poliza NumUnIdenPol="001" 
          Fecha="2026-01-15" 
          Concepto="Gasto de nómina enero 2026">
    <Transaccion NumCta="6010000" 
                 Descripción="Sueldos y salarios" 
                 Concepto="Nómina enero" 
                 Debe="100000.00" 
                 Haber="0.00">
      <CFDI UUID="12345678-1234-1234-1234-123456789abc" />
    </Transaccion>
    <Transaccion NumCta="2670000" 
                 Descripción="Acreedores por pago de nómina" 
                 Concepto="Nómina enero" 
                 Debe="0.00" 
                 Haber="100000.00">
    </Transaccion>
  </Poliza>
</Polizas>
```

**Tipos de póliza:**
| Tipo | Código | Uso |
|------|--------|-----|
| **Diario** | D | Operaciones generales |
| **Ingreso** | I | Cobros a clientes, depósitos bancarios |
| **Egreso** | E | Pagos a proveedores, retiros bancarios |

**Cuándo se solicitan pólizas (Art. 28, fracc. II):**
- En requerimiento del SAT durante una auditoría
- En solicitud de devolución de IVA
- En dictamen fiscal (si aplica)
- El SAT puede solicitarlas en cualquier momento hasta 5 años después de la presentación de la declaración

### 5.4 Dictamen Fiscal (LISR Art. 32-A)

**Art. 32-A de la LISR** — Quiénes están obligados a dictaminarse:

**Obligados (Art. 32-A, fracc. I):**
1. Contribuyentes que en el ejercicio anterior hayan declarado ingresos acumables ≥ **$1,650,490,600** (valor actualizable anualmente)
2. Contribuyentes que al cierre del ejercicio anterior tengan acciones colocadas entre el gran público inversionista en la Bolsa de Valores

**Opción voluntaria (Art. 32-A, fracc. II):**
- Cualquier contribuyente puede optar por dictaminarse
- Plazo para notificar al SAT: **6 meses** posteriores al cierre del ejercicio (Art. 32-A, párrafo 3)
- El aviso se presenta en el portal SAT

**Contenido del dictamen (Art. 32-A):**
1. Estados financieros dictaminados
2. Notas a los estados financieros
3. Cálculo del ISR
4. Determinación de la PTU
5. Conciliación fiscal (ingresos financieros vs. fiscales)
6. Observaciones relevantes
7. Opinión del contador público autorizado

**Plazos del dictamen:**

| Situación | Plazo de presentación |
|-----------|----------------------|
| Dictaminar por obligación | 15 de mayo del año siguiente al cierre |
| Dictaminar por opción (ingresos > $100M) | 15 de junio del año siguiente |
| Dictaminar por opción (ingresos ≤ $100M) | 30 de junio del año siguiente |
| Corrección del dictamen | 12 meses siguientes a la presentación |

**Sanciones por no dictaminarse (Art. 81 fracc. VI y Art. 82 fracc. V CFF):**
- Multa de $15,310 a $91,870 pesos (actualizable)
- No haber dictaminado cuando se está obligado (Art. 81, fracc. VI CFF)

### 5.5 Reglas de Contabilidad Electrónica Resumidas (RMF 2.8.1.x)

| Regla | Obligación | Formato |
|-------|-----------|---------|
| **2.8.1.1** | Catálogo de cuentas | XML (Anexo 24) |
| **2.8.1.2** | Envío del catálogo | Al registrarse o cuando cambie |
| **2.8.1.5** | Balanza de comprobación | XML mensual |
| **2.8.1.6** | Pólizas contables | XML (a requerimiento del SAT) |
| **2.8.1.8** | Auxiliar de folios de CFDI | XML (a requerimiento) |
| **2.8.1.9** | Información de auxiliares de CFDI | UUID relacionado en cada póliza |

---

## 6. REFERENCIAS CRUZADAS

### Tabla Consolidada de Artículos

| Artículo | Ley | TEMA | Agente(s) que aplica |
|----------|-----|------|---------------------|
| **Art. 23 CFF** | CFF | RFC y constancia de situación fiscal | Todos |
| **Art. 27 CFF** | CFF | Requisitos de deducción | AP, Bookkeeping |
| **Art. 28 CFF** | CFF | Contabilidad electrónica | Close, Bookkeeping |
| **Art. 29 CFF** | CFF | CFDI | AP/AR, Bookkeeping |
| **Art. 29-A CFF** | CFF | Requisitos del CFDI | AP/AR |
| **Art. 31 CFF** | CFF | Obligaciones de contribuyentes | Declaraciones |
| **Art. 32 CFF** | CFF | Informativas (DIOT) | Declaraciones |
| **Art. 32-A CFF** | CFF | Dictamen fiscal | Bookkeeping |
| **Art. 33 CFF** | CFF | Obligaciones específicas | Declaraciones |
| **Art. 34 CFF** | CFF | Estados financieros | Close, Bookkeeping |
| **Art. 44-45 CFF** | CFF | Pagos en parcialidades | AP/AR |
| **Art. 55 CFF** | CFF | Facultades de comprobación | Conciliación |
| **Art. 59 CFF** | CFF | Presunción de ingresos (PF) | Conciliación |
| **Art. 69 CFF** | CFF | Presunción de ingresos (PM) | Conciliación |
| **Art. 73-81 CFF** | CFF | Multas | Todos |
| **Art. 76 CFF** | CFF | Declaración anual PM | Declaraciones |
| **Art. 86 CFF** | CFF | Declaración anual PF | Declaraciones |
| **Art. 99 CFF** | CFF | Retenciones de ISR | Nómina |
| **Art. 110 CFF** | CFF | Medios electrónicos | Declaraciones |
| **Art. 116 CFF** | CFF | Pagos provisionales PF | Declaraciones |
| **Art. 117 CFF** | CFF | Pagos definitivos | Declaraciones |
| **Art. 17-D CFF** | CFF | Firma electrónica | Todos |
| **Art. 8 LISR** | LISR | Tipo de cambio | Close, AP/AR |
| **Art. 9 LISR** | LISR | Declaración anual PM | Declaraciones |
| **Art. 14 LISR** | LISR | Pagos provisionales PM | Declaraciones |
| **Art. 16-18 LISR** | LISR | Ingresos acumulables | Close, Bookkeeping |
| **Art. 25-32 LISR** | LISR | Deducciones autorizadas PM | AP, Bookkeeping |
| **Art. 26 LISR** | LISR | Gastos no deducibles | AP |
| **Art. 32 LISR** | LISR | Costo de lo vendido (inventarios) | Close, Bookkeeping |
| **Art. 34-43 LISR** | LISR | Inversiones (depreciación/amortización) | Close, AP |
| **Art. 44-45 LISR** | LISR | Ajuste por inflación fiscal | Close, Bookkeeping |
| **Art. 46-47 LISR** | LISR | Deducción de créditos incobrables | Close, AR |
| **Art. 59 LISR** | LISR | Presunción de ingresos (PF) | Conciliación |
| **Art. 91 LISR** | LISR | Discrepancia fiscal | Conciliación |
| **Art. 94-96 LISR** | LISR | Sueldos y salarios (retención) | Nómina |
| **Art. 100 LISR** | LISR | Honorarios (retención) | AP |
| **Art. 110 LISR** | LISR | Subsidio para el empleo | Nómina |
| **Art. 150 LISR** | LISR | Declaración anual PF | Declaraciones |
| **Art. 174 LISR** | LISR | Asimilados a salarios | Nómina |
| **Art. 178-179 LISR** | LISR | Retenciones a residentes en extranjero | AP |
| **Art. 179-181 LISR** | LISR | Precios de transferencia | Close, Bookkeeping |
| **Art. 32-A LISR** | LISR | Dictamen fiscal | Bookkeeping |
| **Art. 1 LIVA** | LIVA | Objeto del IVA | Declaraciones |
| **Art. 2 LIVA** | LIVA | Tasa del IVA (16%, 0%, exentas) | Declaraciones |
| **Art. 2-A LIVA** | LIVA | Definición de tasa 0% | Declaraciones |
| **Art. 5 LIVA** | LIVA | Acreditamiento del IVA | AP/AR, Declaraciones |
| **Art. 6 LIVA** | LIVA | Saldo a favor del IVA | Declaraciones |
| **Art. 18 LIVA** | LIVA | Obligaciones de contribuyentes | Declaraciones |
| **Art. 120 LFT** | LFT | Participación de trabajadores en utilidades (PTU) | Close |
| **Art. 87 LFT** | LFT | Aguinaldo | Close, Nómina |
| **Art. 76-78 LFT** | LFT | Vacaciones y prima vacacional | Close, Nómina |
| **Art. 154 LFT** | LFT | Fondos de ahorro | Close |
| **RMF 2.7.1.1** | RMF | DIOT | Declaraciones |
| **RMF 2.8.1.1** | RMF | Catálogo de cuentas | Bookkeeping |
| **RMF 2.8.1.5** | RMF | Balanza de comprobación | Close, Bookkeeping |
| **RMF 2.8.1.6** | RMF | Pólizas contables | Bookkeeping |

---

## 7. APÉNDICE: CATÁLOGO DE CUENTAS SAT

### 7.1 Mapeo de Cuentas Bancarias (1020000)

| Código SAT | Nombre | Tipo |
|-----------|--------|------|
| 1020000 | Bancos | Activo (general) |
| 1020100 | Bancos nacionales | Activo |
| 1020200 | Bancos extranjeros | Activo |
| 1020300 | Bancos en moneda extranjera | Activo |

### 7.2 Mapeo de Clientes/Proveedores

| Código SAT | Nombre | Tipo |
|-----------|--------|------|
| 1050000 | Clientes | Activo |
| 1050100 | Clientes nacionales | Activo |
| 1050200 | Clientes extranjeros | Activo |
| 1050300 | Clientes nacionales (partes relacionadas) | Activo |
| 2010000 | Proveedores nacionales | Pasivo |
| 2020000 | Proveedores extranjeros | Pasivo |
| 2050000 | Cuentas por pagar a partes relacionadas | Pasivo |

### 7.3 Mapeo de Gastos Más Comunes

| Código SAT | Nombre | Uso |
|-----------|--------|-----|
| 6010100 | Sueldos y salarios | Nómina directa |
| 6010200 | Sueldos y salarios (asimilados) | Asimilados a salarios |
| 6010300 | Sueldos y salarios (IMSS) | Cuotas IMSS patronales |
| 6010400 | Sueldos y salarios (INFONAVIT) | Cuotas INFONAVIT |
| 6010500 | Sueldos y salarios (SAR) | Aportaciones SAR |
| 6010600 | Sueldos y salarios (vacaciones) | Provisión vacaciones |
| 6010700 | Sueldos y salarios (prima vacacional) | Provisión prima vacacional |
| 6010800 | Sueldos y salarios (aguinaldo) | Provisión aguinaldo |
| 6010900 | Sueldos y salarios (PTU) | Provisión PTU |
| 6020100 | Servicios profesionales | Honorarios a PF |
| 6020200 | Servicios administrativos | Outsourcing |
| 6020300 | Servicios de mantenimiento | Mantenimiento oficinas |
| 6020400 | Rentas de inmuebles | Arrendamiento operativo |
| 6020500 | Publicidad y propaganda | Marketing |
| 6020600 | Gastos legales y jurídicos | Abogados |
| 6020700 | Gastos de viaje y representación | Viajes |
| 6030100 | Intereses bancarios | Gastos financieros |
| 6030200 | Comisiones bancarias | Comisiones |
| 6040100 | Pérdida por crédito incobrable | Provisión incobrables |
| 6050100 | Pérdida cambiaria | FX loss |
| 6070100 | Gastos por inflación | Ajuste inflacionario (Art. 45 LISR) |

### 7.4 Mapeo de Impuestos

| Código SAT | Nombre | Tipo |
|-----------|--------|------|
| 2600000 | Impuestos y derechos por pagar | Pasivo |
| 2600100 | Impuesto sobre la renta por pagar | Pasivo |
| 2600200 | IVA por pagar | Pasivo |
| 2600300 | IVA acreditable | Activo |
| 2600400 | IVA trasladado | Pasivo (IVA cobrado) |
| 2600500 | ISR por retener (nómina) | Pasivo |
| 2600600 | IEPS por pagar | Pasivo |
| 2600700 | Impuestos diferidos por pagar | Pasivo |
| 1800100 | IVA acreditable (corto plazo) | Activo |

---

## NOTAS TÉCNICAS PARA DESARROLLO

### Para el agente Close Management:
- **NIF D-3**: El cálculo de impuestos diferidos es obligatorio para estados financieros. Implementar DTL (Deferred Tax Liability) y DTA (Deferred Tax Asset)
- **NIF D-2**: La provisión de prestaciones laborales se calcula con el método de beneficios acumulados (Project Unit Credit)
- **NIF D-1**: El reconocimiento de ingresos sigue el modelo de 5 pasos: (1) identificar contrato, (2) identificar obligaciones de desempeño, (3) determinar precio de la transacción, (4) asignar precio a obligaciones, (5) reconocer ingreso cuando se cumple la obligación

### Para el agente Declaraciones:
- **LISR Art. 14** permite dos métodos de pago provisional: (1) contable (utilidad fiscal del mes) y (2) coeficiente de utilidad (ingresos cobrados × coeficiente del ejercicio anterior)
- **LIVA Art. 5**: El acreditamiento requiere que el IVA esté pagado, no solo facturado. Implementar control de "IVA pendiente de acreditar" vs. "IVA acreditado"
- **CFF Art. 23**: El RFC se determina mediante homoclave. Implementar validación de RFC con dígito verificador

### Para el agente Conciliación Bancaria:
- **LISR Art. 91**: La discrepancia fiscal es un procedimiento del SAT, no una obligación del contribuyente. El agente debe prevenir, no reaccionar
- Implementar matching automático: depósitos ↔ CFDI emitidos, retiros ↔ CFDI recibidos
- Los traspasos entre cuentas propias deben identificarse para no contabilizarlos como ingreso

### Para el agente AP/AR:
- **CFF Art. 29-A, fracc. VII**: El complemento de pagos es obligatorio para pagos en parcialidades. Implementar generación automática de complementos
- **LIVA Art. 5**: El IVA acreditable del periodo = IVA pagado en el periodo (no facturado). Implementar flujo de caja de IVA
- **LISR Art. 100**: La retención a PF se hace sobre el monto del pago, no sobre la utilidad

### Para el agente Bookkeeping:
- **RMF 2.8.1.5**: La balanza de comprobación mensual debe enviarse en XML conforme al Anexo 24
- **RMF 2.8.1.6**: Las pólizas contables se solicitan en auditoría; deben estar listas para exportar en XML en cualquier momento
- **Art. 32-A LISR**: El dictamen fiscal solo es obligatorio para contribuyentes con ingresos ≥ $1,650,490,600 (2024, actualizable)

---

> **Disclaimer**: Este documento es una compilación de referencia técnica para desarrollo de software. Los montos, tasas y plazos pueden cambiar con reformas fiscales. Consultar siempre la legislación vigente y al SAT para la versión actualizada. Las cifras de montos están basadas en legislación de 2024-2025 y deben verificarse contra la Miscelánea Fiscal vigente.
