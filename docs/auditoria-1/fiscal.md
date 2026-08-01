# Cumplimiento fiscal — auditoría 1

**Nota: 2/10** (ronda 1, sin nota previa). Razón: **mirada más profunda** — no hay
nota anterior que mover. El ancla del rubro dice «3 o menos si el producto imprime
una cifra fiscal equivocada». Este producto imprime **nueve** cifras fiscales
equivocadas que verifiqué corriendo el código, en los cuatro módulos que un
despacho usaría para presentar ante el SAT (nómina, CFDI, DIOT, contabilidad
electrónica). No es un 1 porque la estructura existe y hay trabajo correcto real
(ver «Lo que revisé y está bien»); es un 2 porque el contenido normativo de esa
estructura está inventado o desfasado, y —punto 6 del MAPA, confirmado— **no
existe ni el mecanismo para rastrear de dónde salió cada regla**: `command grep -rn
"69-B\|EFOS"` sobre `*.py` devuelve **cero** coincidencias en código; las únicas
menciones viven en `docs/comparativa-repos-2026-08.md:165`, describiendo la carpeta
`normas/` que tiene el *otro* repo.

Riesgo mayor hoy: un despacho que corra este producto le retiene a un trabajador
$11.76 de IMSS donde la ley pide ~$370, le descuenta una aportación patronal que
no le corresponde, y le paga 20 días de vacaciones donde la LFT reformada pide 22
— todo con la etiqueta «referencia: LSS», «referencia: LFT arts. 76-77» impresa al
lado del número.

Método: sin fichas normativas contra las cuales comparar, comparé contra la norma
citada por el propio código, y **ejecuté** cada cálculo. Todo hallazgo con cifras
abajo salió de una corrida real, no de leer. Donde no pude verificar la vigencia
de una tarifa sin fuente primaria, lo marco explícitamente como **no verificable
en esta ronda** en vez de asumir.

---

## Hallazgos

### [CRÍTICO] La aportación patronal de INFONAVIT se descuenta del sueldo del trabajador
`b2b_ai/services/payroll.py:128-138`, `:260`, `:269-276`, `:398-399`

Escenario: `calculate_payroll({"salario_diario":"500"}, 15000)` →
`deducciones.infonavit = "26.13"`, restado en `neto_a_pagar`, y emitido en el CFDI
como `<nomina:Deduccion TipoDeduccion="003" Concepto="INFONAVIT">`.

El 5% del SBC del art. 29 fr. II de la Ley del INFONAVIT es una **aportación a
cargo del patrón**, no una deducción al trabajador. Lo único descontable al
trabajador es la amortización de un crédito INFONAVIT vigente (art. 29 fr. III),
cuyo monto lo fija el aviso de retención del instituto, no un 5% del SBC. La LFT
art. 110 enumera las deducciones permitidas y esta no está.

Consecuencia: el trabajador cobra de menos cada periodo por un concepto que no se
le puede descontar; el patrón sigue debiendo la aportación completa. Es una
deducción ilegal impresa en un recibo de nómina.

Causa raíz probable: se modeló una carga patronal como si fuera obrera.

---

### [CRÍTICO] Las cuotas de seguridad social se calculan sobre el SBC **diario** y se restan de una nómina **mensual**
`b2b_ai/services/payroll.py:110-125`, `:230-233`, `:252`, `:259-260`

Escenario (ejecutado): `salario_diario=500`, `sueldo_bruto=15000` →
`_sbc_desde` devuelve `522.60`, que es un SBC **diario** (500 × 1.0452). Luego
`calc_imss(522.60)` aplica las tasas sobre ese diario:
`eym=5.88`, `rcva=5.88`, **`imss total = 11.76`**, y ese es el importe restado del
neto mensual. La cuota obrera real sobre un SBC de 522.60/día por 30 días ronda
los **$370**. El código descuenta ~3% de lo debido — un factor ≈30 de error, que
es exactamente el número de días del periodo que nunca se multiplicó.

Consecuencia: el recibo de nómina que el despacho entrega a su cliente y al
trabajador trae un neto inflado ~$360/mes por trabajador; el patrón paga al IMSS
la cuota real y descubre el descuadre en la conciliación, o no lo descubre y la
provisión contable queda corta todo el ejercicio.

Nota adicional en la misma tabla: `RATES["imss_total_trabajador"] = 0.0175`
(`payroll.py:43`) se documenta como «≈ EYM + RCVA» pero EYM+RCVA como está
codificado suman `0.0225`. La constante no se usa en ningún lado y contradice a
las que sí. Las tasas no salen de una fuente: falta Invalidez y Vida, faltan
Gastos Médicos de Pensionados, y falta la regla del excedente de 3 UMA del art.
106 LSS.

Causa raíz probable: `dias_pagados` nunca entra al cálculo (ver siguiente
hallazgo); el SBC diario se trata como si fuera el del periodo.

---

### [CRÍTICO] El subsidio para el empleo no existe en el módulo de nómina
`b2b_ai/services/payroll.py` (módulo completo — 405 líneas, cero ocurrencias)

Escenario: verificado por búsqueda sobre el archivo — la palabra «subsidio» no
aparece. Para un trabajador con ingreso gravado de $8,000 mensuales,
`calc_isr(8000)` devuelve **`impuesto = "553.30"`** y `calculate_payroll` retiene
esos 553.30 completos. El subsidio para el empleo es de aplicación **obligatoria**
para el patrón en ese rango de ingreso, se acredita contra el ISR del periodo, y
cuando lo excede se **entrega en efectivo** al trabajador.

Consecuencia doble: (1) al trabajador se le retiene ISR que no debía retenérsele;
(2) el CFDI de nómina que emite `generate_payroll_cfdi` sale sin el nodo
`<nomina:OtroPago TipoOtroPago="002">` con `SubsidioAlEmpleo`, que el PAC exige
cuando el subsidio es aplicable — el timbrado se rechaza, o peor, se timbra sin él
y la declaración anual del trabajador queda mal.

Marco como **no verificable en esta ronda** el monto exacto del subsidio (depende
del decreto vigente y de la UMA del ejercicio), pero su **ausencia total** es
verificable y es el hallazgo.

Causa raíz probable: se implementó la tarifa del art. 96 LISR y se paró ahí; el
subsidio vive en un decreto aparte que nadie transcribió.

---

### [CRÍTICO] El ISR de una nómina quincenal se calcula con la tarifa mensual
`b2b_ai/services/payroll.py:75` (parámetro `periodicidad`), `:80`, `:258`

Escenario (ejecutado): `calc_isr(7500, periodicidad="quincenal")` →
**`impuesto = "498.90"`**. El parámetro `periodicidad` está en la firma y **nunca
se lee en el cuerpo de la función**; siempre se aplica `TARIFA_ISR_2025_MENSUAL`.
El cálculo correcto para una quincena de $7,500 pasa por la tarifa del periodo (o
por el equivalente mensual de $15,000 → ISR 1,552.78 → mitad = **776.39**). El
código retiene **277.49 menos por quincena**, ~$6,660 al año por trabajador.

No es un camino hipotético: `generate_payroll_cfdi` documenta
`periodicidad ('Mensual'|'Quincenal')` en su docstring (`payroll.py:315`) y estampa
`PeriodicidadPago="Quincenal"` en el CFDI (`payroll.py:380`). El producto ofrece
explícitamente el camino donde el número sale mal.

Consecuencia: retención insuficiente en cada quincena del ejercicio. El patrón es
responsable solidario del ISR no retenido (CFF art. 26 fr. I): la diferencia se la
cobran a él, con actualización y recargos.

Causa raíz probable: el parámetro se agregó a la firma como intención y nunca se
implementó el despacho de tarifa.

---

### [CRÍTICO] `dias_vacaciones` se equivoca de escalón a partir del sexto año (LFT art. 76 reformado)
`b2b_ai/services/payroll.py:184-196` (la línea es `extra = ((a - 5) // 5) * 2`)

Escenario (ejecutado, código vs. LFT art. 76 vigente desde 1-ene-2023):

| Antigüedad | Código | Ley |
|---|---|---|
| 1-5 años | 12/14/16/18/20 | 12/14/16/18/20 ✓ |
| **6 años** | **20** | **22** ✗ |
| 7, 8, 9 años | 20 | 22 ✗ |
| 10 años | 22 | 22 ✓ |
| **11-14 años** | **22** | **24** ✗ |
| 15 años | 24 | 24 ✓ |
| **16-19 años** | **24** | **26** ✗ |

El texto reformado dice «A partir del **sexto** año, el período de vacaciones
aumentará en dos días por cada cinco de servicios» — el escalón abre en el año 6,
no en el 10. El código lo abre cinco años tarde y sólo coincide con la ley por
casualidad en los años 5, 10 y 15.

Y arrastra la prima vacacional: `calc_prima_vacacional(500, 6)` devuelve
`{'dias': 20, 'pago_vacaciones': '10000.00', 'prima': '2500.00'}` donde la ley da
22 días, $11,000 y $2,750.

Consecuencia: a un trabajador con 6 años de antigüedad y salario diario de $500 se
le pagan **$1,250 de menos** cada año (2 días de vacaciones + su prima), con la
leyenda «referencia: LFT arts. 76-77» impresa junto a la cifra. Es exactamente el
patrón que el rubro nombra: una cifra equivocada citando un artículo que dice otra
cosa.

Causa raíz probable: se tradujo «cada cinco años» al operador `//5` sin fijar bien
el origen del escalón.

---

### [CRÍTICO] El IVA acreditable toma sólo el **primer** traslado 002: en una factura de tasa mixta reporta 0.00
`b2b_ai/cfdi/parser.py:204`, consumido en `b2b_ai/cfdi/validator.py:96` y `:236-245`

Escenario (ejecutado con un CFDI real de tasa mixta — SubTotal 10,000 = 5,000 al
16% + 5,000 al 0%, TotalImpuestosTrasladados 800.00, Total 10,800):

```
iva parseado = 0.00        ← debería ser 800.00
ISSUE: total_incoherente | SubTotal + IVA − Descuento − Retenciones = 10000.00 pero Total=10800.00
DIOT: iva_acreditable = '0'
```

`next((t["importe"] for t in traslados if t["impuesto"] == "002"), None)` se queda
con el primer nodo `Traslado` de impuesto 002 y descarta el resto. El SAT agrupa
los traslados globales por (Impuesto, TipoFactor, TasaOCuota), así que **toda**
factura con más de una tasa de IVA —una despensa, un restaurante, una farmacia—
tiene dos o tres nodos 002 y este parser lee uno. `TotalImpuestosTrasladados`, que
es el dato autoritativo, se extrae en `parser.py:314` y **nunca se lee**.

Consecuencia: el despacho acredita $0 de IVA donde tenía derecho a $800 por
factura, y además la factura sale marcada `ok=False`. En el sentido contrario (si
el nodo de 16% viene primero y hay otro mayor después) acredita de más y la
diferencia se la reclama el SAT.

Causa raíz probable: se modeló «un CFDI tiene un IVA» cuando el Anexo 20 modela
una lista.

---

### [CRÍTICO] El validador de DIOT no contrasta el IVA acreditable contra nada: un 10× pasa como válido
`b2b_ai/services/diot_validator.py:253-262` y `:264-281`

Escenario (ejecutado): una operación con `Monto=10000.00`,
`IVATrasladado=1600.00`, **`IVAAcreditable=16000.00`** (un cero de más) →

```
valid = True   errores = 0   warnings = 0
total_iva_acreditable = 16000.0
```

La única validación sobre `IVAAcreditable` es `validate_non_negative_float`. La
comprobación de tasa efectiva de las líneas 264-281 mira sólo `IVATrasladado` /
`Monto`. No hay ninguna regla que diga que el acreditable no puede exceder al
trasladado, ni que deba guardar relación con el monto.

Consecuencia: el despacho presenta una DIOT declarando $16,000 de IVA acreditable
sobre una operación de $10,000, el producto le dijo «válido, 0 errores», y el
cruce del SAT contra la DIOT del proveedor lo detecta. Diferencia acreditada
indebidamente: $14,400 en una sola línea. Es el error que este módulo existe para
atrapar.

Causa raíz probable: se validaron tipos y signos, no relaciones aritméticas entre
campos.

---

### [CRÍTICO] Los catálogos SAT están inventados: se aceptan claves que no existen y se rechazan las que sí
`b2b_ai/cfdi/catalogs.py:53-91` (c_UsoCFDI) y `b2b_ai/services/diot_validator.py:38-43` (TipoOperacion)

Escenario A (ejecutado) — c_UsoCFDI. El catálogo oficial del Anexo 20 para CFDI
4.0 tiene G01, G02, G03, I01–I08, D01–D10, S01, CP01, CN01. El archivo agrega
**doce claves que no existen** y `is_valid_uso_cfdi` las aprueba:

```
G04=True  G07=True  G11=True  G13=True  G24=True  G25=True  P01=True
```

`P01` además es de CFDI **3.3** y quedó fuera en 4.0. Y las descripciones de las
que sí existen están cambiadas: el archivo pone I05 = «Dientes, piezas, accesorios
y aparatos de ajuste» (es «Dados, troqueles, moldes, matrices y herramental»), I06
= «Otros bienes o servicios» (es «Comunicaciones telefónicas»), I07 = «Bienes no
identificados» (es «Comunicaciones satelitales»), S01 = «Sin obligaciones
fiscales» (es «Sin efectos fiscales» — el nombre que copió es el del régimen 616).

Escenario B (ejecutado) — DIOT. El catálogo de Tipo de Operación de la DIOT es
**03** (prestación de servicios profesionales), **06** (arrendamiento de
inmuebles) y **85** (otros). El módulo declara `VALID_TIPO_OPERACION = {"01",
"02", "03"}` con etiquetas IVA/IEPS/Exento, que no es ese catálogo:

```
TipoOperacion='06' -> valid=False    ← clave real del SAT, rechazada
TipoOperacion='85' -> valid=False    ← la más común de las tres, rechazada
TipoOperacion='01' -> valid=True     ← clave inventada, aceptada
```

Y el docstring del módulo (`diot_validator.py:10-22`) declara una estructura
`<DIOT><Operacion>` como «SAT XML structure expected». La DIOT no se presenta en
ese XML.

Consecuencia: el módulo que dice «validates DIOT XML files against SAT
requirements» valida contra requisitos que no son los del SAT. Un despacho que
confíe en el «válido» presenta un archivo que la autoridad no acepta, o corrige
claves correctas por incorrectas porque la herramienta se las marcó mal.

Causa raíz probable: los catálogos se escribieron de memoria en vez de
descargarse; el propio archivo lo admite en `catalogs.py:8-11` («Marcado como ?
INFERIDO») pero las funciones `is_valid_*` se usan igual para **reprobar** un
CFDI.

---

### [CRÍTICO] `validate_cfdi` devuelve `ok=True` y «12/12 checks» sobre un XML al que le faltan todos los requisitos del CFF 29-A
`b2b_ai/cfdi/validator.py:165-194` (las cinco ramas `else: _ok(...)`)

Escenario (ejecutado): un `<cfdi:Comprobante>` **sin** `TipoDeComprobante`, sin
`MetodoPago`, sin `FormaPago`, sin `UsoCFDI`, sin `RegimenFiscal` del emisor, sin
`Sello`, sin `NoCertificado` y sin `TimbreFiscalDigital` →

```
ok=True   checks={'pass': 12, 'fail': 0}
```

El patrón `if campo and not es_valido(campo): _fail(...) else: _ok(...)` trata el
campo **ausente** como aprobado, y encima le suma uno al contador de aciertos. Las
cinco validaciones de catálogo fallan abiertas. Los cinco atributos son
obligatorios en el Anexo 20 y sus equivalentes son requisitos del CFF art. 29-A.

Consecuencia: el despacho ve «válido, 12 de 12» sobre un documento que ni siquiera
está timbrado, lo clasifica y lo asienta como gasto deducible. El comprobante no
ampara la deducción ni el acreditamiento (CFF 29-A último párrafo), y eso se
descubre en la revisión, no antes.

Causa raíz probable: se confundió «no aplica» con «cumple»; no hay una lista de
campos obligatorios separada de la validación de contenido.

---

### [CRÍTICO] Ningún camino verifica el 69-B ni el estatus de cancelación antes de asentar la póliza
`b2b_ai/services/pipeline.py:63-101`; `b2b_ai/sat/validator.py:47-72`; cero referencias a 69-B en todo el código

Esto responde las dos preguntas del encargo, y las dos respuestas son «sí, existe
ese camino».

**EFOS (69-B).** `command grep -rn -E "69-B|69B|EFOS|EDOS" --include="*.py" .`
devuelve **cero** coincidencias en código. No hay lista, ni descarga, ni bandera,
ni consulta. Un CFDI emitido por un contribuyente en la lista **definitiva** del
art. 69-B del CFF entra por `parse_cfdi`, sale `ok=True` de `validate_cfdi`, se
clasifica, se registra en la póliza del ERP (`pipeline.py:89`) y se anota como
`iva_acreditable` en la línea de DIOT (`validator.py:236-245`). Las operaciones
amparadas por esos comprobantes **no producen efecto fiscal alguno** salvo que se
acredite la materialidad: la deducción y el acreditamiento son inexistentes.

**Cancelado.** `SATValidator` sólo lo usan `sat/api.py:108` y `sat/scheduler.py:121`.
**`pipeline.py` nunca lo llama**: el flujo es
`parse_cfdi → validate_cfdi → detect_pii → classify → detect_anomalies →
evaluate_approval → register_erp → insert_invoice`, sin una sola consulta de
estatus. Y cuando sí se llama, `check_status` es un mock que decide por el último
carácter del UUID (`sat/validator.py:63`): «folios que terminan en '0' →
cancelado». Sobre UUIDs hexadecimales eso declara **vigente ~15 de cada 16
comprobantes cancelados** y grita «Factura cancelada detectada (SAT)» por correo
(`sat/scheduler.py:144`) sobre facturas vigentes cuyo UUID acabe en 0. En el mismo
archivo, `verify_rfc` (`:105`) reporta `registrado=True` para cualquier RFC que no
empiece con XAXX — un RFC inventado con formato correcto sale «registrado».

Consecuencia: un CFDI cancelado por el emisor sigue soportando una deducción y un
IVA acreditable en la contabilidad que el despacho presenta. Con EFOS, además de
la corrección, el riesgo es el del art. 69-B tercer párrafo para el receptor.

Causa raíz probable: la verificación ante el SAT se diseñó como un módulo aparte,
mock-first, y nunca se conectó al pipeline que produce el efecto fiscal.

---

### [ALTO] El IEPS trasladado se parsea y se descarta: toda factura de gasolina, alcohol o refresco sale inválida
`b2b_ai/cfdi/parser.py:205` (se extrae) · `b2b_ai/cfdi/validator.py:152-163` (nunca se usa)

Escenario (ejecutado, factura de diésel real: SubTotal 1,000, IEPS 300, IVA 208,
Total 1,508):

```
ok=False
ISSUE: total_incoherente | SubTotal + IVA − Descuento − Retenciones = 1208.00 pero Total=1508.00
```

La fórmula de la línea 155 es `subtotal + iva - descuento - ret_tot`. Le falta el
IEPS y cualquier otro traslado que no sea 002. El parser sí lo extrajo
(`ieps = 300.00`); el validador no lo mira.

Consecuencia: para un despacho con clientes de autotransporte, restaurantes o
abarrotes, la mayoría de sus comprobantes de mayor monto salen marcados
inválidos. O el despacho aprende a ignorar el `ok` del producto —y entonces el
validador no sirve para nada— o descarta facturas deducibles.

---

### [ALTO] El IVA se declara acreditable sin mirar `MetodoPago` ni `FormaPago`, y el monto reportado a la DIOT incluye impuestos
`b2b_ai/cfdi/validator.py:236-245`

Escenario A (ejecutado): un CFDI **PPD** (pago en parcialidades o diferido) de
enero produce `diot: {reportable: True, iva_acreditable: ...}` con periodo
`2026-01`. El IVA de un PPD sólo es acreditable en el mes en que se **paga
efectivamente** (LIVA art. 5 fr. III), lo cual se acredita con el complemento de
pago, no con la factura. El campo `metodo_pago` está disponible en `datos` y no se
consulta en ninguna de las diez líneas del bloque.

Escenario B (ejecutado, factura de diésel de arriba): la línea de DIOT sale con
`total_operacion: '1508.00'` — que es el `Total`, IVA e IEPS **incluidos**. La
DIOT reporta el valor de los actos o actividades (la base), no el total facturado.
Ese renglón viene inflado un 50.8% sobre la base.

Escenario C: no se mira `forma_pago`. Un pago en efectivo (clave 01) superior a
$2,000 hace no acreditable el IVA y no deducible el gasto (LIVA art. 5 fr. I,
LISR art. 27 fr. III). No hay ninguna comprobación.

Consecuencia: la DIOT y la declaración mensual de IVA salen con la base y el
periodo equivocados en tres direcciones distintas. Es el entregable que el
despacho presenta ante la autoridad.

---

### [ALTO] La cancelación no mira la fecha: un CFDI de 2019 se declara «cancelación directa»
`b2b_ai/cfdi/cancellation.py:32-38` y `:60-72`

Escenario (ejecutado):
`evaluate_cancellation({"tipo":"I","total":"400","fecha":"2019-03-01T10:00:00", ...})`
→ `{'decision': 'cancelacion_directa', 'requiere_aceptacion_receptor': False}`.

`evaluate_cancellation` lee `tipo`, `total`, `metodo_pago`, `cfdi_relacionados` y
`folio_fiscal`. **Nunca lee `fecha`.** Desde la reforma de 2022, el CFF art. 29-A
sólo permite cancelar en el ejercicio en que se expidió el comprobante (con la
prórroga hasta la fecha de la declaración anual). Un CFDI de 2019 no es cancelable
y el módulo dice que sí, sin fricción.

Tres defectos más en el mismo módulo:
- **Umbral $500** (`cancellation.py:22`). La regla de la RMF que permite cancelar
  sin aceptación del receptor usa **$1,000**. Un CFDI de $900 recibe
  `requiere_aceptacion_receptor` cuando la regla no lo exige. El error va en
  dirección conservadora (fricción, no ilegalidad), pero es una cifra que no
  corresponde a ninguna regla.
- **La regla citada es la equivocada.** `validator.py:37` y `cancellation.py:21`
  citan «regla 2.7.1.47 RMF» para el umbral de cancelación. Esa no es la regla de
  cancelación sin aceptación.
- **`motivo` es texto libre** (`cancellation.py:95`), sin validar contra el
  catálogo de motivos (01–04) ni exigir el folio de sustitución que el motivo 01
  requiere. El payload que sale de aquí no lo acepta el PAC.

Consecuencia: si `prepare_cancellation_request` llegara a conectarse a un PAC real
—hoy es dry-run— la solicitud se rechaza; mientras tanto, el veredicto que ve el
contador es incorrecto.

---

### [ALTO] Inyección de atributos en el CFDI de nómina: `sx.escape` no escapa comillas y las fechas no se escapan
`b2b_ai/services/payroll.py:323`, `:333-338`, `:344-345`, `:355`, `:375`

Escenario (ejecutado). Con `empleado["rfc"] = 'CAPJ800101AB2" Rfc="XAXX010101000'`
y `periodo["fecha_pago"] = '2026-01-31" TipoDeComprobante="I'`, el XML generado
sale:

```
Fecha="2026-01-31" TipoDeComprobante="I"          ← el tipo N convertido en I
<cfdi:Receptor Rfc="CAPJ800101AB2" Rfc="XAXX010101000" Nombre="Juan "El Tigre" Perez"
XML parsea: NO -> Attribute TipoDeComprobante redefined, line 13
```

`xml.sax.saxutils.escape` escapa `&`, `<` y `>` pero **no** `"`, y todos estos
valores van dentro de atributos delimitados por comillas. Peor: el dict `fechas`
(línea 344) y `dias_pagados` (línea 375) se interpolan **sin escapar en absoluto**.

Consecuencia mínima y garantizada: cualquier trabajador cuyo nombre lleve comillas
rompe el XML. Consecuencia máxima: un valor controlado desde el portal redefine el
RFC del receptor o el `TipoDeComprobante` del comprobante fiscal. Solapa con el
rubro 5 (seguridad); lo reporto aquí porque el artefacto comprometido es el CFDI.

---

### [ALTO] El complemento Nómina 1.2 generado viola tres reglas de llenado y no lo timbraría un PAC
`b2b_ai/services/payroll.py:386-400`

Escenario (ejecutado, `calculate_payroll(..., bono=3000)` sobre sueldo 15,000):

```
TotalPercepciones="18000.00"
<nomina:Percepciones TotalSueldos="15000.00"       ← 18000 ≠ 15000
<nomina:Deducciones TotalOtrasDeducciones="2214.69">  ← incluye el ISR
<nomina:Deduccion TipoDeduccion="003" Concepto="INFONAVIT">
```

1. `TotalPercepciones` debe igualar `TotalSueldos + TotalSeparacionIndemnizacion +
   TotalJubilacionPensionRetiro`. Con cualquier bono, no cuadra: el bono se suma al
   total pero se emite dentro del único nodo `Percepcion` de tipo 001 (Sueldos),
   sin su propia clave de percepción.
2. El ISR va dentro de `TotalOtrasDeducciones` y el atributo
   `TotalImpuestosRetenidos` **no se emite**. La regla los separa: los impuestos
   retenidos (TipoDeducción 002) van en su propio total.
3. `TipoDeduccion="003"` no es INFONAVIT: el 003 del catálogo es «Aportaciones a
   retiro, cesantía en edad avanzada y vejez». El descuento por crédito de
   vivienda es 010.

Consecuencia: el PAC rechaza el timbrado. Y si un PAC laxo lo aceptara, la
declaración anual del trabajador leería mal el ISR retenido, porque quedó
clasificado como «otra deducción».

---

### [ALTO] La póliza se registra en el ERP sin que el gate de aprobación vea el resultado de la validación fiscal
`b2b_ai/services/pipeline.py:66`, `:86-97` · `b2b_ai/tools/tools.py:205-213` · `b2b_ai/services/approval.py:68-88`

Escenario (verificado leyendo la firma y ejecutando el validador): `validate_cfdi`
produce `validacion` en la línea 66, pero a `evaluate_approval` se le pasa
`invoice = dict(datos) + categoria + confianza` — **`validacion` no viaja**.
`_ApprovalManager.evaluate` decide únicamente con `total` contra
`DEFAULT_AUTO_THRESHOLD = 50000` (`approval.py:33`).

Con la factura de diésel de arriba: `ok=False` por `total_incoherente`, total
$1,508 < $50,000 → `auto_approved` → `register_erp`. Lo mismo con un RFC de emisor
inválido, un UsoCFDI fuera de catálogo o un total que no cuadra: cualquier CFDI
reprobado por debajo de $50,000 se asienta solo.

Consecuencia: el veredicto fiscal del producto no tiene efecto sobre la única
decisión con consecuencia contable. Solapa con el rubro 3 (agéntico) — que no se
cuente dos veces.

---

### [ALTO] El RFC genérico XAXX010101000 se acepta como receptor válido y como proveedor de DIOT
`b2b_ai/common/rfc.py:23` · `b2b_ai/cfdi/validator.py:202-206`, `:236-245`

Escenario (ejecutado): un CFDI con `Receptor Rfc="XAXX010101000"` pasa
`_ok("RFC receptor válido")` y entra al pipeline como gasto clasificable. Un CFDI
con `Emisor Rfc="XAXX010101000"` entraría a `diot.proveedores_reportables` como
proveedor.

XAXX010101000 es el RFC de operaciones con el público en general: un comprobante
así no ampara deducción para el receptor (CFF 29-A fr. IV exige el RFC de la
persona a favor de quien se expide). XEXX010101000 (residentes en el extranjero)
también pasa, y en la DIOT los extranjeros van en un bloque distinto, no como
proveedor nacional.

Consecuencia: gastos no deducibles asentados como deducibles, y renglones de DIOT
con un RFC que la autoridad no acepta como tercero.

---

### [ALTO] PTU: se calcula 10% de la utilidad fiscal, sin el tope de tres meses y sin distinguir «renta gravable»
`b2b_ai/services/payroll.py:141-151`

Escenario: `calc_ptu(1000000)` → `{"ptu": "100000.00", "referencia": "LFT art. 123
fracc. IX (PTU 10%)"}`. Dos problemas en una función de diez líneas:

1. El docstring y el parámetro llaman «renta gravable / utilidad fiscal» a lo
   mismo. No lo son: para la PTU, la renta gravable se determina **sin disminuir
   la PTU pagada en el ejercicio ni las pérdidas fiscales pendientes de amortizar**
   (LISR art. 9, penúltimo párrafo). Alimentar la utilidad fiscal del art. 9
   subvalúa la base.
2. Falta el tope de la reforma de 2021 (LFT art. 127 fr. VIII): el monto por
   trabajador tiene como límite el que resulte más favorable entre tres meses de
   su salario y el promedio de la PTU de los últimos tres años. Sin ese tope, la
   cifra que sale no es repartible tal cual.

Consecuencia: el reparto se calcula sobre una base equivocada y sin el límite
legal. La cifra sale con la cita del art. 123 constitucional al lado.

---

### [ALTO] La tarifa de ISR está clavada al ejercicio 2025, sin despacho por año, mientras el módulo afirma estar «versionada»
`b2b_ai/services/payroll.py:12-13`, `:25-37`, `:51`, `:80`

Escenario: el docstring del módulo declara «Las tasas son configurables y
versionadas (año fiscal)». En el código hay **una sola** tabla
(`TARIFA_ISR_2025_MENSUAL`), una constante `AÑO_FISCAL = 2025`, y `calc_isr` la usa
como default sin recibir jamás una fecha ni un ejercicio. `calculate_payroll` la
invoca sin argumento (`:258`). Hoy es 1-ago-2026: una nómina de 2026 sale con la
tabla rotulada 2025 y nada en la salida dice cuál se usó — `supuestos.tarifa_isr`
imprime literalmente `"LISR art. 96 (2025)"` sobre un cálculo de 2026.

Marco como **no verificable en esta ronda** si los límites y cuotas del ejercicio
2026 difieren de los transcritos (la tarifa se actualiza cuando la inflación
acumulada rebasa el 10%, y no hay ficha en el repo con la fuente ni la fecha de
publicación contra la cual comparar). El hallazgo que **sí** es verificable: no
existe el mecanismo para tener dos tarifas, ni para elegir por ejercicio, ni para
que el resultado declare cuál aplicó. Cuando la tarifa cambie, todo cálculo
histórico se reescribe en silencio.

Causa raíz probable: la trazabilidad normativa es un comentario, no una estructura.

---

### [ALTO] El paquete de contabilidad electrónica se marca «listo_para_timbrar» sin CodAgrup y con el Sello vacío
`b2b_ai/services/catalogo_cuentas.py:324` · `b2b_ai/services/balanza.py:220` · `b2b_ai/services/contabilidad_electronica.py:61-67`, `:109`

Escenario (ejecutado):

```xml
<Cat:Cta NumCta="1000" Desc="ACTIVO" Nivel="1" Natur="D"/>
...  Sello="" noCertificado="" Certificado="">
```

El catálogo de cuentas del Anexo 24 exige el **código agrupador del SAT**
(`CodAgrup`) en cada cuenta — es el atributo que mapea el catálogo del
contribuyente al estándar de la autoridad, y es la razón de ser del envío. No se
emite. `Sello`, `noCertificado` y `Certificado` salen como cadenas vacías, lo que
además reprueba el XSD.

Con eso, `generar_paquete` (`:109`) fija el estado en `"listo_para_timbrar"` y
`calcular_hash_sha1` devuelve un SHA-1 del archivo documentado como «requisito
SAT» (`:63`). Ese hash no es el sello: el sello es la firma con la e.firma sobre la
cadena original. El producto calcula una cosa y la etiqueta como si fuera la otra.

Consecuencia: el despacho cree tener el paquete mensual listo y el buzón lo
rechaza. La cifra que sí cuadra (`cuadrada: True`) da confianza sobre un archivo
impresentable.

---

### [MEDIO] Las tasas de IVA citan el artículo equivocado y confunden tasa 0% con exento
`b2b_ai/cfdi/validator.py:29-32`

El bloque se encabeza «Tasas de IVA vigentes (LIVA art. 1-C)» y la línea del 8%
cita «art. 1-C fracc. II». El art. 1-C de la LIVA trata de **documentos pendientes
de cobro** (factoraje). El 16% es el art. 1 segundo párrafo; el 8% de la zona
fronteriza no está en la LIVA en absoluto — sale de un decreto de estímulos
fiscales, que es un crédito equivalente al 50% de la tasa, no una tasa distinta.

Además `IVA_TASA_EXENTO = Decimal("0.00")  # 0% - Exento` mete en la misma
constante dos figuras que la ley separa: los actos a **tasa 0%** (art. 2-A) dan
derecho al acreditamiento del IVA trasladado; los actos **exentos** (arts. 9, 15,
20) no lo dan y obligan a prorratear (art. 5 fr. V). Tratarlos igual produce un
acreditamiento equivocado en cuanto haya operaciones mixtas.

Consecuencia: el único mecanismo de trazabilidad que tiene este repo son estos
comentarios, y apuntan a un artículo que dice otra cosa. Es el patrón que el rubro
nombra: una leyenda que cita un artículo que no dice eso.

---

### [MEDIO] `calculate_payroll` acepta `dias_pagados` y `falta` y no usa ninguno de los dos
`b2b_ai/services/payroll.py:236-238`, `:285`

Escenario (ejecutado): `calculate_payroll({"salario_diario":"500"}, 15000)` y
`calculate_payroll({"salario_diario":"500"}, 15000, dias_pagados=15, falta=True)`
devuelven **el mismo** `neto_a_pagar = "13409.33"`. `falta` no aparece en el cuerpo
de la función; `dias_pagados` sólo se copia al dict de salida (línea 285) y se
estampa en el CFDI como `NumDiasPagados`.

Consecuencia: un recibo por quince días con una falta se calcula como un mes
completo sin faltas. El CFDI declara `NumDiasPagados="15"` junto a las
percepciones de treinta.

---

### [MEDIO] La balanza inventa las cuentas que no están en el catálogo, con naturaleza deudora por defecto
`b2b_ai/services/balanza.py` (ruta de resolución de cuenta) · verificado ejecutando `BalanzaComprobacion.generar`

Escenario (ejecutado): asientos contra `101.01` y `601.01`, que no existen en el
catálogo generado (que usa claves de cuatro dígitos: 1000, 1100, 1101). La balanza
sale igual, con `descripcion: "Cuenta 601.01"`, `nivel: 3` deducido de los puntos y
`naturaleza: "D"` asumida — para una cuenta de la serie 600, que es de resultados.

Consecuencia: el SAT cruza la balanza contra el catálogo enviado. Cuentas que
aparecen en una y no en la otra son un rechazo. Además, asumir naturaleza deudora
hace que `saldos_anomalos` marque como anómalo lo que es normal, y viceversa.

---

### [MEDIO] La retención del 4% de autotransporte de carga no existe; sólo se contempla 2/3 de IVA y 10% de ISR
`b2b_ai/cfdi/validator.py:224-234`

El bloque compara cualquier `retenciones_iva` contra 2/3 del IVA y cualquier
`retenciones_isr` contra 10% del subtotal. La retención de IVA por servicios de
autotransporte terrestre de carga es del **4% del valor de la contraprestación**,
no 2/3. Un CFDI de flete correcto genera un warning falso.

Consecuencia: sólo warnings, no falla el comprobante — por eso es MEDIO. Pero
para un despacho con clientes transportistas, la casilla de advertencias se llena
de ruido y deja de leerse.

---

### [MEDIO] El RFC valida el formato pero acepta fechas imposibles
`b2b_ai/common/rfc.py:23`

Escenario (ejecutado): `is_valid_rfc("ABCD991332AB1")` → `True`. Mes 13, día 32.
Tampoco se verifica el dígito verificador de la homoclave, que es computable a
partir del resto.

Consecuencia: un RFC con un dedazo en la fecha pasa la validación, entra a la
línea de DIOT y la autoridad rechaza el renglón. El módulo se llama «canonical RFC
validation» y su docstring (`:20-22`) describe un patrón `{2,3}` que el código no
implementa (es `{3}`).

---

### [BAJO] Constantes muertas y ramas inalcanzables en las rutas fiscales
`b2b_ai/services/payroll.py:43` · `b2b_ai/services/diot_validator.py:136-143` · `b2b_ai/cfdi/cancellation.py:36`

`RATES["imss_total_trabajador"] = 0.0175` no se usa y contradice la suma de las que
sí (0.0225). `validate_rfc_format` tiene una rama `else: "longitud inválida"` que
el regex previo hace inalcanzable. `evaluate_cancellation` lee `metodo_pago` y
nunca lo usa — relevante porque un CFDI PPD con complemento de pago aplicado tiene
restricciones de cancelación que ese campo habría permitido detectar.

Consecuencia: quien mantenga esto lee 0.0175 y cree que esa es la tasa aplicada.

---

### [BAJO] No existe el mecanismo de trazabilidad normativa, sólo su apariencia
Todo el rubro

Cada función fiscal devuelve un campo `referencia` o `referencia_legal` con un
artículo, y el diseño lo presenta como el mecanismo de trazabilidad
(`cfdi/validator.py:17-19`: «cada salida con efecto fiscal lleva referencia legal +
supuesto + flag de revisión humana»). Pero la referencia es una cadena escrita a
mano junto al número, no un puntero a un texto transcrito con fecha de
verificación. Nada obliga a que el número y la cita concuerden, y este reporte
documenta ocho casos donde no concuerdan.

Consecuencia: la trazabilidad aparente es peor que su ausencia, porque produce
confianza. Confirma y agrava el punto 6 del MAPA: cuando una cifra sale mal, no
hay dónde ir a ver de dónde salió la regla.

---

## Lo que revisé y está bien

- **Tarifa de ISR mensual, aplicación del rango.** `payroll.py:85-100`. La lógica
  de búsqueda del rango, el cálculo `cuota_fija + excedente × porcentaje` y el
  redondeo `ROUND_HALF_UP` a dos decimales son correctos, y devuelve el rango
  aplicado en la salida, que es auditable. Verificado: `calc_isr(15000)` →
  `1552.78` = 1,182.88 + (15,000 − 12,935.83) × 0.1792. La estructura de once
  brackets corresponde a una tarifa real del art. 96 LISR; lo que está en duda es
  el ejercicio, no la aritmética.
- **Uso de `Decimal` en todo el cálculo de nómina y de CFDI.** `payroll.py:17`,
  `cfdi/validator.py:24`. Ni un `float` en la ruta que produce pesos y centavos.
  Es una decisión deliberada y correcta que muchos productos fiscales no toman.
  (El DIOT sí usa `float` — `diot_validator.py:422`; **intenté** provocar un
  descuadre falso acumulando 1,000 operaciones de 16.10 y **no lo reproduje**: la
  deriva fue 2.55e-10, muy por debajo del umbral de 0.01. Lo dejo anotado como
  riesgo latente, no como hallazgo.)
- **Aritmética por concepto y suma de conceptos.** `cfdi/validator.py:101-140`.
  `cantidad × valor_unitario = importe` y `Σ importes = SubTotal` con tolerancia de
  0.02. Verificado con las tres facturas de prueba: detecta el descuadre y no
  produce falsos positivos por redondeo. Es la parte más sólida del validador.
- **Aguinaldo proporcional.** `payroll.py:158-181`. `salario_diario × 15 ×
  (días/365)` con 15 días como mínimo de ley (LFT art. 87) y el caso no
  proporcional separado. Correcto.
- **Vacaciones años 1 a 5.** `payroll.py:193`. `12 + 2×(a−1)` da 12/14/16/18/20,
  que es exactamente el escalón de la reforma. El error empieza en el año 6.
- **Prima vacacional al 25%.** `payroll.py:211-223`. La tasa y la base (el pago de
  los días de vacaciones) son las del art. 80. Hereda el error de los días, pero
  la fórmula es correcta.
- **La cancelación no se ejecuta sola.** `cancellation.py:95-119`.
  `prepare_cancellation_request` exige `confirmacion_humana=True`, devuelve
  `dry_run: True` y `estado: "preparado_para_revision_humana"`, y
  `evaluate_cancellation` fija `requires_human_review: True` incondicionalmente
  (`:90`). Intenté encontrar un camino de auto-cancelación y no existe: es un
  guardarraíl deliberado y cerrado. El contenido de la evaluación está mal (ver
  hallazgo), pero el efecto irreversible está bien gateado.
- **`requires_human_review` en las salidas con efecto fiscal.**
  `cfdi/validator.py:268-271` lo enciende ante cualquier issue, ante una línea de
  DIOT, ante nómina y ante tipos E/P. `payroll.py:301` lo fija siempre. Es
  consistente con el aviso del docstring y es la defensa que evita que estos
  errores lleguen solos a una declaración.
- **Namespaces y versiones del Anexo 24.** `balanza.py:220`,
  `catalogo_cuentas.py:324`. `ContabilidadE/1_3`, `Version="1.3"`, `TipoEnvio="B"`,
  `Mes` con dos dígitos, `Anio` de cuatro. Los identificadores del esquema son los
  correctos; lo que falta es el contenido obligatorio (ver hallazgo).
- **Cuadratura de la balanza.** `balanza.py:167`. `Σ debe == Σ haber` verificada y
  devuelta como `cuadrada`, más una lista de `saldos_anomalos` por naturaleza de
  cuenta. Verificado con un asiento balanceado: `total_debe='1000.00'`,
  `total_haber='1000.00'`, `cuadrada=True`.
- **Regex de RFC centralizada.** `common/rfc.py`. Una sola definición importada por
  `cfdi/validator.py:27` y `sat/validator.py:23`, con `Ñ` y `&` contemplados y
  normalización a mayúsculas. Es la estructura correcta; verifiqué que
  `diot_validator.py:36` mantiene una **segunda** regex propia sin la `Ñ` —
  divergencia anotada, pero la canónica está bien.
- **Nota sobre `ClaveProdServ` 84111505.** `catalogs.py:120-121`. El comentario
  advierte que esa clave también se usa en honorarios y que la nómina se detecta
  por `TipoDeComprobante=N`, no por la clave. Es exactamente el tipo de precisión
  que le falta al resto del archivo.
- **El desglose de impuestos por concepto sí se parsea completo.**
  `parser.py:156-171`. Traslados y retenciones por concepto se leen como lista, con
  base, tipo de factor y tasa. La materia prima para calcular bien el IVA está
  ahí; el problema es que el validador consume el atajo del `next()` global.

---

## Lo que NO alcancé a revisar

- **`b2b_ai/features/` — la segunda y tercera implementación de lo mismo.** Hay
  `features/diot/validators.py` (517 líneas) y `features/diot/models.py` (298)
  además de `services/diot_validator.py`; y `features/contabilidad/validators.py`
  (290) **y** `features/contabilidad_electronica/validators.py` (206) además de
  `services/contabilidad_electronica.py`. También `features/nomina/` y
  `features/nomina_completa/` — dos módulos de nómina. El commit `e643695` acaba de
  registrar siete de estos routers en la app de FastAPI, así que **es probable que
  el camino que un usuario ejecuta hoy sea el de `features/`, no el que audité**.
  No sé si esas copias repiten estos errores, los corrigen, o introducen otros
  distintos. Es el hueco más grande de esta ronda y el que más pesa sobre la nota.
- **`features/devolucion_iva/`, `features/declaraciones/`,
  `features/pre_auditoria/`, `features/conciliacion_fiscal/`.** Cuatro módulos con
  efecto fiscal directo que no abrí.
- **`b2b_ai/sat/downloader.py` (293 líneas) y `sat/scheduler.py` (197).** Sólo leí
  las llamadas al validador mock. No verifiqué qué hace la descarga masiva de CFDI
  ni cada cuándo corre el scheduler que manda las alertas de cancelación falsas.
- **Las pruebas del rubro.** No medí mutantes contra `tests/` para las funciones
  fiscales. Dado que los 4,900 tests pasan y estos nueve errores están vivos, la
  hipótesis obvia es que las pruebas fijan el comportamiento actual como esperado
  (p. ej. que exista un test que afirme `dias_vacaciones(6) == 20`) — pero es una
  hipótesis, no la verifiqué. Corresponde al rubro 9.
- **El ejercicio fiscal vigente de la tarifa de ISR y del subsidio.** Sin fuente
  primaria en el repo ni acceso a la publicación del Anexo 8 de la RMF, no puedo
  afirmar si los once brackets transcritos siguen vigentes en 2026. Lo dejé marcado
  como no verificable dentro del hallazgo, no lo conté como cifra equivocada.
- **`erp/contpaqi.py` y la póliza generada.** Verifiqué que se registra sin
  validación; no revisé si el asiento contable resultante (cuentas, IVA acreditable
  por pagar vs. acreditable) está bien armado.
