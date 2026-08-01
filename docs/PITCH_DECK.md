# Likida AI Enterprise — Pitch Deck (Seed A)

---

## Slide 1: Cover

**Likida AI**
*Agentes IA para despachos contables en México*

Seed A — Agosto 2026

---

## Slide 2: El Problema

### México tiene un cuello de botella contable masivo

- **689 vacantes** de contadores públicos sin cubrir (IMCP, 2025)
- **Costo promedio de un contador**: $18,200 MXN/mes ($218,400/año)
- **Captura manual de facturas**: los despachos dedican 3-5 horas/día por contador a tareas repetitivas (abrir XML, leer datos, teclear montos, clasificar gastos)
- **Errores humanos costosos**: Un RFC mal capturado o un monto invertido = horas de conciliación fallida
- **Riesgo fiscal**: CFDI mal validado puede generar multas del SAT superiores a los $100,000 MXN

> El problema no es la contabilidad — es la captura de datos.

---

## Slide 3: La Solución

### Likida AI — Agentes IA que preparan y validan; tú determinas y firmas

Un agente de IA que:
1. **Navega tu ERP** (CONTPAQi, Aspel, QuickBooks) vía Computer Use
2. **Captura y valida** cada CFDI 4.0 (aritmética, catálogos SAT, IVA, retenciones, DIOT)
3. **Clasifica contablemente** el gasto y genera la póliza
4. **Tú revisas** un resumen flagged y firmas — la máquina preparó todo

**El profesional conserva siempre la decisión final y la firma.**

---

## Slide 4: Producto

### Plataforma completa, no un chatbot

| Capa | Qué hace |
|------|----------|
| **11 agentes IA** | Captura, validación, clasificación, conciliación, nómina, declaraciones, alertas, reportes, email, pagos, pre-auditoría |
| **50+ integraciones** | ERPs (CONTPAQi, Aspel, QuickBooks, Xero), bancos (BBVA, Banorte, Santander), SAT (CFDI 4.0, DIOT, Contabilidad Electrónica), almacenamiento, pagos |
| **Multi-tenant** | Aislamiento de datos por despacho. Cada operación trazable |
| **Compliance fiscal** | Validación CFDI 4.0, catálogos SAT, DIOT, retenciones, contabilidad electrónica |
| **Dashboard & alertas** | Reportes en tiempo real, anomalías, vencimientos, estados de cuenta |

---

## Slide 5: Cómo Funciona (en la práctica)

```
[ERP del cliente] → [Agente IA navega y captura] → [Valida fiscalmente] → [Clasifica contable] → [Dashboard + alertas]
                                                                                                      ↓
                                                                                            [Profesional revisa y firma]
```

- **Sin integraciones API frágiles**: Computer Use navega el ERP como lo haría un humano
- **Validación fiscal real**: No es un parser simple — verifica aritmética, catálogos, fechas, retenciones
- **Auditoría completa**: Cada tool call registrado, cada decisión trazable

---

## Slide 6: Mercado

### TAM / SAM / SOM — México

| Métrica | Valor | Fuente / Metodología |
|---------|-------|---------------------|
| **TAM** (Total Addressable Market) | ~$8,200 MM MXN/año | 50,000 despachos contables × $13,700/mes promedio × 12 meses |
| **SAM** (Serviceable Available Market) | ~$1,200 MM MXN/año | Despachos con 200+ CFDI/mes que adoptarían automatización |
| **SOM** (Serviceable Obtainable Market) | ~$48 MM MXN/año | Meta 3 años: 500 clientes × $8,000 MXN/mes promedio |

**Drivers de crecimiento:**
- 689 vacantes sin cubrir se duplicaron en 3 años
- CFDI 4.0 y contabilidad electrónica obligatoria desde 2022
- Expansión del régimen de confianza (RESICO) incrementa volumen de declaraciones
- Digitalización acelerada post-COVID en despachos contables

---

## Slide 7: Modelo de Negocio

### SaaS B2B — Suscripción mensual por volumen de CFDI

| Plan | Precio (MXN/mes) | CFDI/mes | Target |
|------|-------------------|----------|--------|
| Starter | $8,000 | 300 | Despachos pequeños (1-3 contadores) |
| **Pro** ⭐ | $20,000 | 900 | Despachos medianos (5-15 contadores) |
| Business | $40,000 | 2,500 | Despachos grandes (15-40 contadores) |
| Enterprise | $80,000 | 6,000+ | Redes de despachos / Big 4 |

**Unit Economics esperados:**
- ACV promedio: $240,000 MXN ($20K × 12)
- Gross margin: ~80% (costo principal: inference de LLMs)
- LTV/CAC target: > 5x
- Payback period: < 3 meses

---

## Slide 8: Traction

### Lo que tenemos hoy (honesto)

| Métrica | Estado |
|---------|--------|
| **Producto funcional** | ✅ API completa, 11 módulos, 50+ integraciones, tests unitarios y de integración |
| **Landing page** | ✅ En producción en likida.ai |
| **Docker desplegable** | ✅ Stack completo: API + PostgreSQL + Redis + Nginx |
| **Onboarding wizard** | ✅ Checklist interactivo para nuevos clientes |
| **Beta testing** | 🔄 En proceso con 2 despachos piloto |
| **Revenue** | 🔜 Pre-revenue (pilotos gratuitos) |
| **Equipo fundador** | 1 persona full-stack + IA |

> Transparencia: Estamos en etapa de piloto. El producto está construido y funcional, pero aún no tenemos revenue recurrente. Los pilotos nos darán las métricas de conversión para el Series A.

---

## Slide 9: Ventajas Competitivas (Moats)

1. **Computer Use sobre ERPs**: No necesitamos APIs del ERP — el agente navega como un humano. Esto funciona con CUALQUIER ERP web, sin integración por cliente.

2. **Validación fiscal profunda**: No es un parser de XML — es un sistema que verifica aritmética, catálogos SAT, retenciones, DIOT, y flaggea para revisión humana.

3. **Multi-tenant enterprise**: Aislamiento de datos, auditoría completa, RBAC. Listo para Big 4 y redes de despachos.

4. **Knowledge moat**: Cada validación fiscal nos da más datos para mejorar. Los catálogos SAT se actualizan, y nuestro sistema se adapta.

5. **Costo operativo bajo**: Inference de LLMs a costo marginal ~$0.5-2 MXN por CFDI procesado vs $15-30 MXN costo humano.

---

## Slide 10: Roadmap

### 12 meses

| Trimestre | Hito |
|-----------|------|
| **Q3 2026** | Cierre pilotos → primeros 10 clientes paying. Validar PMF. |
| **Q4 2026** | Escalar a 50 clientes. Agente de conciliación bancaria automatizada. |
| **Q1 2027** | Integración con bancos vía open banking. Módulo de dictamen fiscal. |
| **Q2 2027** | 100+ clientes. Preparar Series A. Expansión LATAM (Colombia, Perú). |

---

## Slide 11: Equipo

**Founder & CEO**
- Full-stack engineer con experiencia en IA y fintech
- Construyó Likida AI de 0: arquitectura, integraciones SAT, computer use, billing

**Próximas contrataciones (con funding):**
- 1 × Sales/Partnerships (despachos contables en México)
- 1 × Backend engineer (escalabilidad, open banking)
- 1 × Customer Success (onboarding y soporte)

---

## Slide 12: El Ask

### Seed A — $3M MXN (~$150K USD)

| Uso de fondos | % | Detalle |
|---------------|---|---------|
| **Ingeniería** | 45% | 2 engineers, infra cloud, inference costs |
| **Ventas** | 30% | 1 AE, marketing digital, eventos contables |
| **Operaciones** | 15% | Customer success, onboarding, soporte |
| **Reserva** | 10% | 6 meses runway buffer |

**Hitos con el funding:**
- 50 clientes paying en 12 meses
- $400K MXN MRR
- Unit economics validados (LTV/CAC > 5x)
- Preparar Series A

---

## Slide 13: Visión

### México tiene 50,000 despachos contables procesando millones de facturas al mes manualmente.

Likida AI convierte ese trabajo repetitivo en un pipeline automatizado donde el contador se enfoca en lo que importa: asesorar, decidir y firmar.

**La máquina prepara. El profesional determina.**

---

## Appendix: Datos Verificables

| Dato | Fuente |
|------|--------|
| 689 vacantes de contadores | IMCP / IMSS / ENOE |
| $18,200 MXN/mes costo promedio contador | IMCP survey 2025 |
| 50,000 despachos contables en México | SAT / IMCP registros |
| CFDI 4.0 obligatorio desde 2022 | SAT Resolución Miscelánea Fiscal |
| Contabilidad electrónica obligatoria | CFF Art. 28, reglas SAT |
| ~$0.5-2 MXN costo inferencia por CFDI | estimado interno (GPT-4o-mini / Claude Haiku) |
| $15-30 MXN costo humano por CFDI | estimado: tiempo promedio × costo/hora |
