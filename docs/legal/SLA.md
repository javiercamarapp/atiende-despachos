# Acuerdo de Nivel de Servicio (SLA) — B&B AI (Likida AI)

**Versión:** 1.0  
**Fecha de última actualización:** 1 de agosto de 2026  
**Empresa:** B&B AI, S.A. de C.V. («el Proveedor»)  
**Cliente:** [Nombre del Cliente / Razón Social]

---

## 1. Alcance

El presente Acuerdo de Nivel de Servicio («SLA») establece las métricas de desempeño, niveles de disponibilidad y compromisos de soporte técnico que el Proveedor garantiza al Cliente en relación con la Plataforma B&B AI (Likida AI).

Este SLA forma parte integral del contrato o cotización suscrito entre las partes y de los Términos de Servicio vigentes.

---

## 2. Definiciones

| Término | Definición |
|---|---|
| **Plataforma** | El conjunto de servicios SaaS de automatización contable y fiscal proporcionados por el Proveedor bajo la marca B&B AI / Likida AI. |
| **Tiempo de actividad (Uptime)** | Porcentaje del tiempo total en que la Plataforma está disponible y operativa para el Cliente, excluyendo las ventanas de mantenimiento programado. |
| **Tiempo de inactividad (Downtime)** | Periodo en que la Plataforma no está disponible o presenta degradación severa que impide su uso normal, excluyendo causas atribuibles al Cliente. |
| **Mantenimiento programado** | Ventanas de mantenimiento planificado notificadas al Cliente con al menos 48 horas de anticipación. |
| **Mantenimiento correctivo** | Intervenciones urgentes para corregir fallas críticas que afecten la disponibilidad del servicio. |
| **Tiempo de respuesta de la API** | Tiempo transcurrido desde que la Plataforma recibe una petición API hasta que retorna una respuesta completa. |
| **Soporte técnico** | Atención brindada por el equipo de soporte del Proveedor para resolver incidencias, dudas técnicas y solicitudes de ayuda del Cliente. |
| **Incidencia** | Cualquier evento, error o anomalía que afecte el funcionamiento normal de la Plataforma. |
| **Tiempo de primera respuesta** | Tiempo máximo entre la notificación de una incidencia por parte del Cliente y la primera respuesta efectiva del equipo de soporte. |
| **Periodo de medición** | Mes calendario completo. |

---

## 3. Compromisos de disponibilidad

### 3.1 Disponibilidad del servicio

| Métrica | Compromiso |
|---|---|
| **Uptime mensual** | **99.9%** o superior |
| **Tiempo máximo de inactividad no programada** | 43 minutos por mes calendario |
| **Mantenimiento programado** | Máximo 2 horas por mes, en ventanas fuera del horario laboral del Cliente (preferentemente sábado 02:00–06:00 hrs, horario de la Ciudad de México) |

### 3.2 Tiempo de respuesta de la API

| Métrica | Compromiso |
|---|---|
| **Latencia promedio de la API** | **< 200 milisegundos** (percentil 95) |
| **Tiempo máximo aceptable** | < 500 milisegundos en percentil 99 |
| **Tiempo de procesamiento de CFDI individuales** | < 3 segundos por CFDI en condiciones normales |
| **Tiempo de procesamiento de lotes** | < 30 segundos por lote de hasta 100 CFDI |

### 3.3 Exclusiones del cómputo de uptime

El tiempo de inactividad **no se computará** cuando se deba a:

- Mantenimiento programado notificado conforme a la sección 3.1.
- Mantenimiento correctivo urgente para corregir vulnerabilidades de seguridad críticas (máximo 2 incidentes al año).
- Causas atribuibles al Cliente (configuración incorrecta, integrações defectuosas de su parte, etc.).
- Fuerza mayor conforme al artículo 2148 del Código Civil Federal.
- Indisponibilidad de servicios de terceros fuera del control del Proveedor (API del SAT, servicios de intermediación bancaria, etc.).

---

## 4. Clasificación de incidencias

### 4.1 Niveles de severidad

| Severidad | Descripción | Ejemplo |
|---|---|---|
| **S1 — Crítica** | La Plataforma está completamente inoperativa o una funcionalidad crítica para múltiples usuarios no funciona. | API caída, inability de emitir CFDI, pérdida de conexión con el SAT |
| **S2 — Alta** | Funcionalidad importante degradada, pero la Plataforma sigue operativa con limitaciones parciales. | Conciliación bancaria lenta, errores intermitentes en procesamiento de CFDI |
| **S3 — Media** | Funcionalidad no crítica afectada, workaround disponible. | Errores en reportes secundarios, UI con rendimiento reducido |
| **S4 — Baja** | Solicitud de información, mejora menor o incidencia cosmética. | Duda de uso, solicitud de documentación, ajuste de configuración |

---

## 5. Compromisos de soporte técnico

### 5.1 Tiempos de primera respuesta por severidad

| Severidad | Tiempo de primera respuesta | Tiempo de resolución estimado |
|---|---|---|
| **S1 — Crítica** | **< 30 minutos** | < 4 horas |
| **S2 — Alta** | **< 2 horas** | < 8 horas |
| **S3 — Media** | **< 4 horas** | < 24 horas (1 día hábil) |
| **S4 — Baja** | **< 8 horas** | < 72 horas (3 días hábiles) |

### 5.2 Canales de soporte

| Canal | Disponibilidad | Horario |
|---|---|---|
| **Soporte crítico (S1)** | Correo electrónico + chat en vivo + teléfono | 24/7 (para incidencias S1) |
| **Soporte general (S2-S4)** | Correo electrónico + chat en vivo | Lunes a viernes, 9:00–18:00 hrs (horario CDMX) |
| **Documentación y conocimiento** | Centro de ayuda en línea | 24/7 |

### 5.3 Información requerida para reportar una incidencia

Para agilizar la atención, el Cliente deberá proporcionar al reportar una incidencia:

- Descripción detallada del problema
- Severidad estimada (S1–S4)
- Pasos para reproducir el incidente
- Capturas de pantalla o logs de error (si aplica)
- Versión de la Plataforma y navegador utilizado
- Horario en que se presentó la incidencia

---

## 6. Créditos por incumplimiento

### 6.1 Créditos de servicio

En caso de que el Proveedor no cumpla con el compromiso de uptime del 99.9%, el Cliente tendrá derecho a un crédito de servicio calculado como sigue:

| Uptime mensual | Crédito (% del costo mensual) |
|---|---|
| 99.0% – 99.9% | 10% |
| 95.0% – 99.0% | 25% |
| 90.0% – 95.0% | 50% |
| < 90.0% | 100% (reembolso del mes completo) |

### 6.2 Condiciones para la solicitud de créditos

- El Cliente debe reportar la indisponibilidad al equipo de soporte dentro de los **siete (7) días naturales** siguientes al evento.
- Los créditos son **exclusivamente aplicables** a futuras facturaciones y **no son reembolsables** en efectivo.
- El crédito máximo acumulable no excederá el costo mensual del servicio.
- No se otorgarán créditos por indisponibilidad causada por el Cliente, mantenimiento programado o fuerza mayor.

### 6.3 Resolución de incidencias S1 no resueltas

Si una incidencia S1 no es resuelta dentro del tiempo estimado de resolución (4 horas):

- El Proveedor asignará recursos adicionales de ingeniería.
- El Cliente recibirá actualizaciones cada **30 minutos** hasta la resolución.
- Se aplicará un **crédito adicional del 15%** sobre el costo mensual por cada 4 horas adicionales de indisponibilidad, hasta un máximo del 100%.

---

## 7. Monitoreo y reportes

**7.1** El Proveedor monitorea la disponibilidad y el rendimiento de la Plataforma de manera continua mediante sistemas de monitoreo automatizados.

**7.2** El Cliente tendrá acceso a un **panel de estado del servicio** (status page) en línea con información en tiempo real sobre la disponibilidad de la Plataforma.

**7.3** El Proveedor proporcionará al Cliente un **reporte mensual de SLA** que incluya:

- Uptime alcanzado vs. comprometido
- Número de incidencias por severidad
- Tiempo promedio de primera respuesta por severidad
- Tiempo promedio de resolución por severidad
- Estado del rendimiento de la API (latencia promedio)

**7.4** Los reportes mensuales estarán disponibles a partir del **día 5 de cada mes** por el período inmediato anterior.

---

## 8. Escalamiento

**8.1** Si una incidencia S1 no es diagnosticada dentro de los primeros **60 minutos**, el Cliente podrá solicitar el escalamiento a un ingeniero senior o al responsable de la Plataforma.

**8.2** Si una incidencia S1 persiste por más de **2 horas**, se activará el protocolo de crisis del Proveedor, incluyendo:

- Participación del equipo de ingeniería de mayor nivel
- Comunicación directa con el representante del Cliente
- Evaluación de la implementación de un plan de contingencia

---

## 9. Exclusión de garantías

**9.1** El SLA no constituye una garantía absoluta de disponibilidad ininterrumpida. Los compromisos de uptime y tiempo de respuesta representan objetivos de servicio y métricas de desempeño.

**9.2** El SLA no aplica a entornos de prueba, desarrollo o pruebas de concepto (POC) que el Proveedor pueda poner a disposición del Cliente de manera gratuita o temporal.

---

## 10. Vigencia

El presente SLA entrará en vigor en la fecha de firma o aceptación del contrato/cotización correspondiente y permanecerá vigente durante toda la duración de la relación contractual entre las partes.

---

## 11. Modificaciones

El Proveedor se reserva el derecho de modificar los compromisos de este SLA con un preaviso de **treinta (30) días naturales** al Cliente. Las mejoras en los niveles de servicio podrán implementarse sin necesidad de preaviso.

---

**Aceptación del Cliente**

Al aceptar la cotización o firmar el contrato con el Proveedor, el Cliente declara haber leído, comprendido y aceptado los términos del presente Acuerdo de Nivel de Servicio.

---

**B&B AI, S.A. de C.V.**  
Ciudad de México, México  
Sitio web: [www.likida.ai](https://www.likida.ai)  
Contacto técnico: soporte@likida.ai
