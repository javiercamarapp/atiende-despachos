# Transcripción de la demo — Likida AI Enterprise

Fecha : 2026-08-02 12:23
Comando: `/private/tmp/likida_demo/.venv/bin/python /private/tmp/likida_demo/scripts/demo_pilot.py`

## Salida

```text
══════════════════════════════════════════════════════════════════════════════
                    LIKIDA AI ENTERPRISE — DEMO AUTOMÁTICA                    
══════════════════════════════════════════════════════════════════════════════
  Pipeline contable end-to-end para presentación a prospecto
▸ Poblando base de datos demo (seed_demo.py)
    Base previa eliminada: demo_pilot_rec.db
    $ /private/tmp/likida_demo/.venv/bin/python /private/tmp/likida_demo/scripts/seed_demo.py --db /private/tmp/likida_demo/scripts/demo_data/demo_pilot_rec.db
      BD poblada correctamente.
    === RESUMEN DEMO ===
      Tenants              : 3
      Clientes/tenant      : 5
      CFDIs (emitidos+recibidos) : 300  (100 por tenant)
      Transacciones        : 150  (50 por tenant)
      Nóminas              : 30  (10 por tenant)
      Documentos           : 15  (5 por tenant)
      Roles                : admin, contador, auditor, readonly
      Usuario admin/tenant : 1
        tenant 1 admin: admin@bajio.contadores.mx (role=admin)
        tenant 2 admin: admin@norte.grupofiscal.mx (role=admin)
        tenant 3 admin: admin@pacifico.despacho.mx (role=admin)
  ✔ Base demo lista: /private/tmp/likida_demo/scripts/demo_data/demo_pilot_rec.db
▸ Levantando servidor API en http://127.0.0.1:8000
  ✔ Servidor listo · API key demo: demo-key-likida-2026 · tenant_id=1
══════════════════════════════════════════════════════════════════════════════
 ESCENARIO S0 · Pipeline completo (CFDI → parse → bookkeeping → conciliación) 
══════════════════════════════════════════════════════════════════════════════
▸ POST /api/v1/pipeline/run
    Subiendo 5 CFDIs y 6 movimientos bancarios …
  ✔ status=completed  job_id=19056e62-20f
    CFDIs parseados:    5
    Clasificaciones:    5
    Pólizas generadas:  5
    Referencias ERP:    5
▸ Conciliación bancaria (motor real)
    Transacciones a conciliar:6
    Conciliadas:        4
    Sin conciliar:      2
    Discrepancias:      0
    Tasa de conciliación:66.67%
      · BBVA-202607-0001 → póliza 494d7e67-328 [PARTIAL_REFERENCE · conf 0.6]
      · BANORTE-202607-0001 → póliza bc586f88-e4b [PARTIAL_REFERENCE · conf 0.6]
      · BANORTE-202607-0002 → póliza 6aa367a1-763 [PARTIAL_REFERENCE · conf 0.6]
══════════════════════════════════════════════════════════════════════════════
  ESCENARIO A · Procesamiento de CFDI (upload → validar → clasificar → ERP)   
══════════════════════════════════════════════════════════════════════════════
▸ POST /api/v1/invoices/process (multipart)
    Archivo:            tmp23d1uhid.xml
    RFC emisor:         PMD890303OP8
    Total:              $3,480.00 MXN
    Válido:             Sí
    Requiere revisión humana:Sí
    Categoría:          inversion
    Confianza:          98.0%
    Póliza ERP:         POL-640E6F0285
    Estado ERP:         registrada
  ✔ CFDI procesado e insertado en la BD
══════════════════════════════════════════════════════════════════════════════
               ESCENARIO B · Nómina (cálculo ISR · IMSS · neto)               
══════════════════════════════════════════════════════════════════════════════
▸ POST /api/v1/payroll/calculate
    Empleado:           María Guadalupe López Hernández
    RFC:                LOHG900101MNC
    Sueldo bruto:       $25,500.00 MXN
    Total gravado:      $25,500.00 MXN
    ISR retenido:       $3,632.53 MXN
    IMSS:               $996.90 MXN
    Neto a pagar:       $20,870.57 MXN
  ✔ Nómina calculada correctamente
══════════════════════════════════════════════════════════════════════════════
       ESCENARIO C · Conciliación bancaria (CFDIs vs estado de cuenta)        
══════════════════════════════════════════════════════════════════════════════
▸ POST /api/v1/reconcile/run
    Facturas en el periodo:10
    Movimientos bancarios:10
    Conciliados:        8
    Pendientes banco:   2
    Pendientes facturas:2
    Monto conciliado:   $64,960.00 MXN
    Tasa de conciliación:32.42%
      · 11111111-222…  $5,800.00 MXN  vía monto+fecha
      · 11111111-222…  $29,000.00 MXN  vía monto+fecha
      · 11111111-222…  $8,120.00 MXN  vía monto+fecha
      · 21111111-222…  $1,160.00 MXN  vía monto+fecha
  ✔ Reporte de conciliación generado
══════════════════════════════════════════════════════════════════════════════
                                   RESUMEN                                    
══════════════════════════════════════════════════════════════════════════════
  ✔ Demo completada correctamente (3 escenarios + pipeline end-to-end).
  ✔ Base demo: /private/tmp/likida_demo/scripts/demo_data/demo_pilot_rec.db
  ✔ Servidor: http://127.0.0.1:8000  ·  documentación OpenAPI: http://127.0.0.1:8000/docs
  Apagando servidor …
```
