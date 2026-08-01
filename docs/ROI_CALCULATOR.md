# Likida AI Enterprise — ROI Calculator

*Herramienta para evaluar el retorno de inversión de Likida AI en un despacho contable.*

---

## Datos de Entrada (ajustables por cliente)

| Parámetro | Valor típico | Nota |
|-----------|-------------|------|
| Facturas procesadas al mes | 500 | Rango típico despacho mediano |
| Tiempo manual por factura | 12 minutos | Apertura XML, lectura, captura, clasificación |
| Costo hora contador | $150 MXN | Promedio IMCP 2025 (incluye prestaciones) |
| Tasa de error manual | 3-5% | RFC, montos, clasificación |
| Costo promedio por error | $500 MXN | Tiempo de corrección + posible multa |
| Plan Likida AI | Pro ($20,000/mes) | Para 500 CFDI/mes |

---

## Ahorro de Tiempo

### Antes de Likida AI (manual)

| Actividad | Tiempo por factura |
|-----------|-------------------|
| Abrir y descargar XML/PDF | 1 min |
| Leer y extraer datos (RFC, montos, fechas) | 3 min |
| Validar aritmética y montos | 2 min |
| Verificar catálogos SAT | 1 min |
| Clasificar gasto contablemente | 3 min |
| Capturar en ERP / sistema | 2 min |
| **Total por factura** | **12 min** |

### Después de Likida AI (automatizado)

| Actividad | Tiempo por factura |
|-----------|-------------------|
| Revisar resumen y flagged items | 2 min |
| Ajustar y firmar | 1 min |
| **Total por factura** | **3 min** |

### Resultado

| Métrica | Valor |
|---------|-------|
| **Tiempo ahorrado por factura** | 9 minutos (75% reducción) |
| **Tiempo total ahorrado al mes** | 75 horas (500 facturas × 9 min) |
| **Equivalentes en medio tiempo** | ~0.47 FTE (tiempo completo: 160 hrs/mes) |

---

## Ahorro de Costos

### Costo manual (sin Likida)

| Concepto | Cálculo | Costo mensual |
|----------|---------|---------------|
| Captura y validación | 500 × 12 min × $150/hr ÷ 60 | $15,000 MXN |
| Corrección de errores | 500 × 4% × $500 | $10,000 MXN |
| **Costo total manual** | | **$25,000 MXN/mes** |

### Costo con Likida AI (Plan Pro)

| Concepto | Costo mensual |
|----------|---------------|
| Suscripción Likida AI | $20,000 MXN |
| Tiempo de revisión humano | 500 × 3 min × $150/hr ÷ 60 = $3,750 MXN |
| **Costo total con Likida** | **$23,750 MXN/mes** |

### Ahorro neto mensual

| Métrica | Valor |
|---------|-------|
| **Ahorro neto mensual** | $1,250 MXN/mes (starter) |
| **Ahorro neto mensual (con errores eliminados)** | $11,250 MXN/mes |
| **Reducción de riesgo fiscal** | Incalculable (multas SAT pueden superar $100K MXN) |

> **Nota honesta**: El ahorro directo en el plan Pro es moderado. El verdadero ROI viene de:
> 1. **Escalar sin contratar**: procesar 2x o 3x más facturas sin contratar personal adicional
> 2. **Eliminar errores**: un solo error de RFC puede costar más que una mensualidad de Likida
> 3. **Cumplimiento fiscal**: evitar multas del SAT por CFDI mal validados
> 4. **Retención de talento**: liberar contadores de tareas repetitivas para trabajo de mayor valor

---

## Escenarios de ROI por Plan

### Scenario A: Despacho pequeño (Starter — 300 CFDI/mes)

| Métrica | Manual | Con Likida | Ahorro |
|---------|--------|------------|--------|
| Tiempo/mes | 60 hrs | 15 hrs | 45 hrs (75%) |
| Costo captura | $9,000 | $2,250 | $6,750 |
| Errores/mes (3%) | 9 facturas | ~1 factura | 8 errores menos |
| Costo errores | $4,500 | $500 | $4,000 |
| Costo Likida | — | $8,000 | — |
| **Costo total** | **$13,500** | **$10,750** | **$2,750/mes (20%)** |
| **ROI anual** | | | **$33,000 MXN** |

### Scenario B: Despacho mediano (Pro — 900 CFDI/mes)

| Métrica | Manual | Con Likida | Ahorro |
|---------|--------|------------|--------|
| Tiempo/mes | 180 hrs | 45 hrs | 135 hrs (75%) |
| Costo captura | $27,000 | $6,750 | $20,250 |
| Errores/mes (3%) | 27 facturas | ~3 facturas | 24 errores menos |
| Costo errores | $13,500 | $1,500 | $12,000 |
| Costo Likida | — | $20,000 | — |
| **Costo total** | **$40,500** | **$28,250** | **$12,250/mes (30%)** |
| **ROI anual** | | | **$147,000 MXN** |

### Scenario C: Despacho grande (Business — 2,500 CFDI/mes)

| Métrica | Manual | Con Likida | Ahorro |
|---------|--------|------------|--------|
| Tiempo/mes | 500 hrs | 125 hrs | 375 hrs (75%) |
| Costo captura | $75,000 | $18,750 | $56,250 |
| Errores/mes (3%) | 75 facturas | ~8 facturas | 67 errores menos |
| Costo errores | $37,500 | $4,000 | $33,500 |
| Costo Likida | — | $40,000 | — |
| **Costo total** | **$112,500** | **$62,750** | **$49,750/mes (44%)** |
| **ROI anual** | | | **$597,000 MXN** |

---

## Break-Even Analysis

### Cuándo se paga solo Likida AI?

| Plan | Pago mensual | Ahorro neto/mes | Break-even |
|------|-------------|-----------------|------------|
| Starter ($8K) | $8,000 | $2,750 | **3 meses** |
| Pro ($20K) | $20,000 | $12,250 | **2 meses** |
| Business ($40K) | $40,000 | $49,750 | **< 1 mes** |
| Enterprise ($80K) | $80,000 | $100,000+ | **< 1 mes** |

### Payback con factor de escalamiento

El verdadero ROI se multiplica cuando el despacho **escala sin contratar**:

| Escenario | Facturas/mes | Personal manual necesario | Con Likida | Empleados evitados | Ahorro anual |
|-----------|-------------|--------------------------|------------|-------------------|-------------|
| Duplicar volumen | 1,000 → 2,000 | +1 contador ($218K/yr) | Mismo equipo | 1 FTE | $218,400 |
| Triangular volumen | 1,000 → 3,000 | +2 contadores ($437K/yr) | +1 medio FTE | 1.5 FTE | $327,600 |

---

## ROI Intangibles (no cuantificables directamente)

| Beneficio | Impacto |
|-----------|---------|
| **Cumplimiento fiscal** | Multas SAT por CFDI mal validados: $100K-$500K+ MXN |
| **Retención de talento** | Contadores prefieren asesorar vs. capturar datos |
| **Velocidad de cierre** | Cierre mensual de 5 días → 1 día |
| **Escalabilidad** | Crece sin contratar proporcionalmente |
| **Trazabilidad** | Auditorías internas y externas más rápidas |
| **Satisfacción del cliente** | Reportes más rápidos, menos errores, más valor |

---

## Methodology Notes

- **Tiempo por factura**: Estimado basado en observaciones de despachos contables tipo. Incluye: descarga de XML, apertura, lectura de campos, validación, clasificación y captura manual. Rango real observado: 8-18 minutos.
- **Costo hora contador**: $150 MXN/hora incluye salario base + prestaciones (IMSS, aguinaldo, PTU, vacaciones) para contador público junior-intermedio en CDMX (fuente: IMCP, OCC Mundial, Glassdoor México).
- **Tasa de error**: 3-5% en proceso manual (fuente: estudios de precisión en procesamiento de datos contables). Errores más comunes: RFC incorrecto, monto invertido, clasificación errónea, fecha mal capturada.
- **Costo por error**: Estimado conservador. Un RFC incorrecto puede rechazar todo elXML, requiriendo re-procesamiento. Una clasificación errónea puede generar auditoría.
- **Todos los precios en MXN**. Para conversión USD, usar tipo de cambio vigente.

---

## Uso de esta herramienta

1. **Para el despacho**: Ajusta los parámetros de entrada (facturas/mes, tiempo manual, costo/hora) a tu realidad.
2. **Para el vendedor**: Usa los escenarios A/B/C como punto de partida y personaliza con datos del cliente.
3. **Para el pitch**: El ROI anual del escenario B ($147K MXN) equivale a ~7 meses de sueldo de un medio contador.
