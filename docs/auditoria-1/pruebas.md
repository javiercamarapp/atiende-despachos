# Pruebas — auditoría 1

**Nota: 3/10** (ronda 1, sin nota previa)

La suite tiene 4900+ pruebas verdes, pero en las tres cifras de dinero que rompí a
propósito en `services/payroll.py` y `cfdi/validator.py` — la tasa IMSS, la tasa
general de IVA y el Total del XML de nómina — la mutación sobrevivió el 100% de
las pruebas relacionadas (441, 552 y 2 pruebas respectivamente): el número sale
mal y ninguna prueba se entera. Y la única suite que sí detecta los 3 bugs reales
de Postgres ya documentados (`PG_BUG_REPORT.md`) está apagada por diseño en cada
corrida, incluida la de CI.

## Metodología

Elegí 5 mutaciones reales (no mentales) sobre `b2b_ai/services/payroll.py`,
`b2b_ai/cfdi/validator.py` y `b2b_ai/services/pipeline.py`. Cada mutación se
aplicó con Python (`open().write()`), se corrió la prueba puntual con
`pytest -q`, y se revirtió de inmediato con `git checkout -- <archivo>` (el repo
sí es un `git` local pese a lo que dice el entorno). Verifiqué el árbol limpio
después de cada revert con `git diff --stat` sobre esos tres archivos — ninguno
quedó modificado. No toqué ningún otro archivo del repo.

| # | Mutación | Archivo:línea | Pruebas ejecutadas | Resultado |
|---|---|---|---|---|
| A | ISR: quitar `excedente * pct` del cálculo | `payroll.py:90` | `test_isr_rango_bajo` + `TestCalcISR` (6 pruebas) | **Muere** — 3 failed |
| B | IMSS: tasa `imss_trabajador_eym` 0.01125 → 0.05 (4.4× la tasa real) | `payroll.py:41` | Todo `test_payroll.py` + `services/test_payroll.py` + `test_services_coverage.py` + `test_nomina*.py` (441 pruebas) | **Sobrevive** — 441 passed, 0 failed |
| C | IVA: `IVA_TASA_GENERAL` 0.16 → 0.08 (mitad de la tasa legal) | `validator.py:30` | Todo lo que toca `cfdi`/`validator`/`validate` (552 pruebas) | **Sobrevive** — 552 passed, 0 failed |
| D | Aprobación: `if aprobacion["decision"] in (...)` → `if True:` (bypass total del gate) | `pipeline.py:88` | `test_pipeline_v2.py`, `test_pipeline_fase2.py`, `test_integration_pipeline.py`, `test_services_coverage.py` (pipeline/approval, 70 pruebas) | **Muere** — 3 failed |
| E | XML de nómina: `Total="{_fmt(total)}"` en vez de `Total − TotalDeducciones` | `payroll.py:359` | `test_generate_payroll_cfdi_xml` + `TestGeneratePayrollCFDI::test_basic` | **Sobrevive** — 2 passed, 0 failed |

Tres de cinco mutaciones de dinero real pasaron sin que la suite se enterara.

## Hallazgos

### [CRÍTICO] La tasa de cuota IMSS del trabajador puede estar mal por un factor de 4× y las 441 pruebas de nómina siguen verdes
`b2b_ai/services/payroll.py:41` (`RATES["imss_trabajador_eym"]`), consumida en `calc_imss` (`payroll.py:110-125`, uso en línea 117).
Escenario: con el valor real `Decimal("0.01125")` un trabajador con SBC=$1000 paga $11.25 de EyM. Cambié la constante a `Decimal("0.05")` (4.4× el valor real) y corrí las 441 pruebas de `test_payroll.py`, `services/test_payroll.py`, `test_services_coverage.py`, `test_nomina.py` y `test_nomina_completa.py`: **las 441 pasaron**. Las pruebas que tocan `calc_imss` (`services/test_payroll.py:46-58`, `test_payroll.py:27-30`, `test_services_coverage.py:444-448`) solo verifican `total > 0` y `total == eym + rcva` — una consistencia interna con la propia fórmula, no un valor ancla contra la ley (LSS). Cualquier cambio a la tasa, en cualquier dirección, pasa igual.
Consecuencia: si alguien (agente o humano) toca esa constante por error — o si cambia el año fiscal y alguien copia mal el valor — la nómina real del despacho retiene de más o de menos al trabajador y nadie lo nota hasta que el trabajador o el IMSS lo reclamen. Es dinero de un tercero (el empleado), no del despacho.
Causa raíz probable: las pruebas de IMSS verifican la forma del resultado (`eym + rcva == total`), no el valor esperado contra un caso de la ley.

### [CRÍTICO] La tasa general de IVA usada para validar CFDI puede estar a la mitad de su valor legal y las 552 pruebas del validador siguen verdes
`b2b_ai/cfdi/validator.py:30` (`IVA_TASA_GENERAL = Decimal("0.16")`), usada en la línea 144 dentro de `validate_cfdi`.
Escenario: cambié la constante a `Decimal("0.08")` (la mitad) y corrí las 552 pruebas que tocan `cfdi`/`validator`/`validate` en todo `tests/`: **las 552 pasaron**. La razón estructural: el chequeo de IVA global (`validator.py:142-150`) solo agrega un *warning* (`warnings.append(...)`), nunca marca `ok=False` ni incrementa `checks["fail"]`. Ninguna prueba en el repo compara el valor numérico exacto de `esperado` contra el 16% real — `test_iva_global_mismatch` (`tests/test_cfdi_coverage.py:521-525`) solo verifica que *algún* warning con el texto "IVA global" aparezca, y con la tasa mutada a 8% ese warning también dispara (por una razón distinta), así que la prueba no distingue entre "la tasa está mal" y "el warning existe".
Consecuencia: un CFDI de ingreso con IVA facturado al 16% legítimo generaría un warning falso (o uno real se dejaría de generar), y como es solo warning, el campo `ok` del validador seguiría en `True`. El despacho podría reportar coherencia fiscal falsa en un CFDI cuyo IVA no cuadra con la tasa real, sin que la suite ni el flujo de aprobación lo detecten (el warning no bloquea nada en `pipeline.py`).
Causa raíz probable: la comparación contra `IVA_TASA_GENERAL` es un *warning*, no un *fail*, y ninguna prueba ancla el valor numérico esperado a la tasa legal real.

### [CRÍTICO] El Total del XML de nómina (CFDI que se manda a timbrar) puede omitir las deducciones sin que ninguna prueba lo note
`b2b_ai/services/payroll.py:359` (`Total="{_fmt(_round2(total - total_ded))}"` dentro de `generate_payroll_cfdi`).
Escenario: cambié el atributo `Total` del `cfdi:Comprobante` para que fuera igual a `SubTotal` (ignorando `TotalDeducciones`, es decir, ISR+IMSS+INFONAVIT no se restan del monto reportado como Total). Corrí las dos únicas pruebas que ejercitan `generate_payroll_cfdi` (`tests/test_payroll.py:80-91` y `tests/test_services_coverage.py:524-532`): **ambas pasaron**. Ambas pruebas solo verifican presencia de subcadenas (`"Comprobante" in xml`, `"TotalDeducciones" in xml`, el RFC del empleado en el string) — ninguna parsea el XML y compara el atributo `Total` contra `SubTotal − TotalDeducciones`.
Consecuencia: el CFDI de nómina es el documento que un PAC timbraría y el SAT recibiría. Un `Total` que no descuenta ISR/IMSS/INFONAVIT es una inconsistencia fiscal visible para cualquier contador o para el propio SAT en la validación del complemento de Nómina 1.2, y el repo la generaría sin aviso.
Causa raíz probable: las únicas dos pruebas de esta función verifican forma (tags presentes), no aritmética del documento generado.

### [ALTO] La única suite que detecta los 3 bugs ya documentados de Postgres nunca corre — ni localmente por defecto, ni en CI
`tests/test_db_pg_integration.py:27-28` (`pytestmark = pytest.mark.skipif(not _pg_available(), reason="B2B_DB_URL PostgreSQL no disponible")`); mismo patrón en `tests/test_pg_backend.py:27-28` y `tests/test_pg_migrations.py`; `.github/workflows/deploy.yml` (job `test`, sin variable `B2B_DB_URL` ni servicio de Postgres).
Escenario: `PG_BUG_REPORT.md` (raíz del repo, 31-jul-2026) documenta que `tests/test_db_pg_integration.py` corrido contra un Postgres real dio **4 failed / 2 passed**, con traceback real de los 3 bugs bloqueantes ya conocidos: `insert_invoice` con placeholders `:nombre` (`db/db.py:217`, `SyntaxError` en psycopg), `log_call` escribiendo `''` en una columna `jsonb` (`db/db.py:356`), y `upsert_outstanding_invoice` con `ON CONFLICT` sin constraint único (`db/db.py:627`). Verifiqué que hoy, sin `B2B_DB_URL`, los 6 tests de `test_db_pg_integration.py` (más 7 de `test_pg_backend.py` y 2 de `test_pg_migrations.py`, total 15 de los 16 `skipped` de la línea base) se saltan con el mensaje exacto `"B2B_DB_URL PostgreSQL no disponible"` — confirmado con `pytest -q -rs`. El workflow de CI (`.github/workflows/deploy.yml`) instala `psycopg[binary]` pero nunca define `B2B_DB_URL` ni levanta un servicio de Postgres, así que ese `skipif` es siempre verdadero también en GitHub Actions.
Consecuencia: el "0 failed" de la línea base no significa "Postgres funciona" — significa "no se revisó". Los 3 bugs que romperían el primer insert en producción (Railway/Postgres, según `DEPLOY-GUIDE.md`) tienen una prueba escrita que los detecta, pero esa prueba está estructuralmente apagada en todo lugar donde alguien correría `pytest` hoy, incluido el pipeline de CI que se supone es "la puerta de calidad" (comentario textual en `deploy.yml`).
Causa raíz probable: el `skipif` depende de una variable de entorno que nadie configura por defecto ni en CI; no hay un job de CI con servicio de Postgres.
(No es REINCIDENTE — ronda 1 — pero es la misma causa que MAPA.md ya señala como conocida desde antes de esta ronda; aquí la verifiqué y la até a la prueba específica que la detectaría si corriera.)

### [BAJO] Dos archivos de prueba son literalmente `assert True` — inflan el conteo sin probar nada
`tests/test_probe_tmp.py:1-3` (`def test_probe(): assert True`) y `tests/test_agentloop.py:1-4` (`def test_dummy(): assert True`).
Escenario: ambos archivos completos no importan ni ejercitan ningún código de producción; existen solo para pasar. No tocan dinero ni fiscal.
Consecuencia: son 2 de 4900+, así que no mueven la aguja de cobertura real, pero son residuo del proceso de generación (14 horas, un agente) que nadie limpió, y si se repite el patrón en otros archivos no revisados a fondo, la cifra "4900 passed" se vuelve menos confiable como señal de salud.
Causa raíz probable: archivos de prueba/diagnóstico dejados por el pipeline de generación (`test_probe_tmp.py`, `test_agentloop.py`) que nunca se depuraron.

## Lo que revisé y está bien

- **`calc_isr` (`payroll.py:75-103`, LISR art. 96) sí está bien anclado.** Mutación A (quitar el término `excedente * pct`) mató 3 pruebas distintas con valores exactos: `tests/test_payroll.py:12-15` (compara contra un valor calculado a mano con tolerancia de un centavo), `tests/services/test_payroll.py:19-21` (`test_first_bracket`) y `:38-42` (`test_mid_bracket`, rango numérico ajustado). Es la cifra fiscal más grande de la nómina y es la mejor protegida de las cuatro que probé.
- **El gate de aprobación humana antes de tocar el ERP (`pipeline.py:88`) sí está bien anclado.** Mutación D (bypass total del `if`) mató 3 pruebas que verifican explícitamente `erp["status"] == "pending_approval"` con `register_erp` mockeado y verificable como NO llamado: `tests/test_pipeline_v2.py:197-210` (`test_process_file_pending_approval`), `:215-228` (`test_process_file_rejected`), y `tests/test_services_coverage.py:1597-1618`. A diferencia de `test_factura_sobre_umbral_bloquea_erp` (`test_pipeline_fase2.py:42-57`, que solo llama `_tool("evaluate_approval", ...)` directo y NO pasa por `process_file`), estas tres sí ejercitan el `if` real de `pipeline.py` de punta a punta.
- **La aritmética por concepto y el desglose de IVA por concepto del validador CFDI (`validator.py:101-129`) tienen una prueba end-to-end real, no un mock.** `tests/cfdi/test_validator.py:29-44` (`test_importe_concepto_incoherente`) copia un XML fixture real, rompe el atributo `Importe` con texto plano, reparsea con `parse_cfdi` de verdad, y verifica el código de error exacto. Es el patrón correcto de prueba de mutación hecha por el propio equipo, aplicado consistentemente también a `uso_cfdi_invalido` (`:46-56`).
- **La detección de duplicados y el aislamiento multi-tenant sobre SQLite** (`tests/test_integration_pipeline.py:44-55` y `:72-78`) corren el pipeline completo dos veces con datos reales y verifican conteos en DB, no mocks — cubren el camino que sí se ejecuta hoy en producción (SQLite).
- **Los catálogos SAT (`UsoCFDI`, `FormaPago`, `MetodoPago`, `TipoDeComprobante`, `RegimenFiscal`) están cubiertos con casos válidos e inválidos reales** (`tests/cfdi/test_validator.py:59-66`, `tests/cfdi/test_validator.py:61-70`, más `test_cfdi_coverage.py`).

## Lo que NO alcancé a revisar

- No corrí mutación real sobre `calc_infonavit`, `calc_ptu`, `calc_aguinaldo`, `calc_vacaciones` ni `calc_prima_vacacional` individualmente (solo ISR, IMSS y el Total del XML). Dado el patrón que sí encontré dos veces (pruebas que verifican consistencia interna de la fórmula, no el valor legal ancla), sospecho que al menos una de estas comparte el mismo problema, pero no lo verifiqué con una mutación real — no lo reporto como hallazgo.
- No corrí mutación sobre `services/diot_validator.py`, `services/contabilidad_electronica.py` ni `services/balanza.py` — son fiscales y están en `tests/`, pero quedan fuera de los tres archivos que me tocaban (`payroll.py`, `validator.py`, `pipeline.py`).
- No tengo un Postgres real disponible en esta máquina para confirmar en vivo que `test_db_pg_integration.py` sigue fallando hoy contra PG; me apoyé en `PG_BUG_REPORT.md` (31-jul-2026, con traceback real) y en que `git log -- b2b_ai/db/pg.py` no tiene commits desde el inicial — ambos datos ya verificados por el orquestador antes de esta ronda, no los reproduje yo mismo con un PG en vivo.
- No revisé los ~90 archivos de prueba restantes (`test_reportes*.py`, `test_dashboard*.py`, `test_bank_reconciliation*.py`, etc.) con la misma profundidad de mutación; solo hice una pasada de patrones (`assert True`, `assert ... is not None`) para descartar decoración masiva, sin encontrarla fuera de los dos archivos ya reportados.
- Mientras auditaba, `git status` mostró 45 archivos sin commitear bajo `b2b_ai/integrations/*` y un archivo sin trackear (`fix_integrations.py`) que yo no toqué ni causé — es consistente con la advertencia del MAPA de que "el árbol se está construyendo ahora mismo". No es de mi rubro (no es `tests/`) y no evalué su impacto.
