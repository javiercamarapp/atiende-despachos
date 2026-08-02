# -*- coding: utf-8 -*-
"""
templates.py — Plantillas de cierre mensual para el módulo monthly_close.

Plantilla por defecto (~15 tareas) que cubre el flujo de cierre de un
despacho contable mexicano:
    a. CFDIs del mes procesados (verificación automática)
    b. Conciliación bancaria (bank_feeds)
    c. Nóminas timbradas
    d. DIOT generada
    e. Contabilidad electrónica generada
    f. Declaraciones mensuales revisadas
    g. Auxiliares actualizados
    h. Reportes gerenciales generados

Los `auto_check_query` son nombres simbólicos de verificación que el servicio
resuelve contra el estado de otros módulos (bank_feeds, cfdi, nomina, etc.)
vía `auto_check_tasks()`. `depends_on` referencian `key` de otras tareas de la
plantilla (se resuelven a IDs concretos al instanciar el período).
"""
from __future__ import annotations

from typing import Optional

from b2b_ai.features.monthly_close.models import (
    CloseTemplate,
    CloseTemplateTask,
    TaskCategory,
)


def default_monthly_close_template() -> CloseTemplate:
    """Plantilla por defecto del cierre mensual (~15 tareas)."""
    t = CloseTemplate(
        name="cierre_mensual",
        description=(
            "Cierre mensual estándar de despacho contable: CFDI, conciliación "
            "bancaria, nómina, DIOT, contabilidad electrónica, declaraciones, "
            "auxiliares y reportes gerenciales."
        ),
    )
    t.tasks = [
        # --- CFDI ---------------------------------------------------------
        CloseTemplateTask(
            title="Verificar CFDIs del mes procesados",
            description=(
                "Confirmar que todos los CFDIs emitidos/recibidos del período "
                "fueron procesados (auto-check: conteo de CFDIs pendientes = 0)."
            ),
            category=TaskCategory.CFDI,
            auto_check_query="cfdi_pending_count",
            key="cfdi_verificado",
        ),
        CloseTemplateTask(
            title="Validar folios fiscales y sellos",
            description=(
                "Revisar que los CFDIs tengan folio fiscal válido y sellos "
                "SAT correctos."
            ),
            category=TaskCategory.CFDI,
            depends_on=["cfdi_verificado"],
            auto_check_query="cfdi_validacion",
        ),
        # --- Bank / conciliación ------------------------------------------
        CloseTemplateTask(
            title="Conciliación bancaria completada",
            description=(
                "Conciliar los estados de cuenta del mes contra pólizas y "
                "CFDIs (bank_feeds)."
            ),
            category=TaskCategory.BANK,
            depends_on=["cfdi_verificado"],
            auto_check_query="bank_feeds_sync_status",
            key="conciliacion",
        ),
        CloseTemplateTask(
            title="Revisar movimientos sin conciliar",
            description=(
                "Investigar transacciones bancarias que no matchearon con "
                "ningún CFDI o póliza."
            ),
            category=TaskCategory.BANK,
            depends_on=["conciliacion"],
        ),
        # --- Nómina -------------------------------------------------------
        CloseTemplateTask(
            title="Nóminas del mes timbradas",
            description="Verificar que todas las nóminas del mes estén timbradas.",
            category=TaskCategory.NOMINA,
            auto_check_query="nomina_status",
            key="nomina_timbrada",
        ),
        CloseTemplateTask(
            title="Validar previsión social y percepciones",
            description="Revisar percepciones, deducciones y exentos de nómina.",
            category=TaskCategory.NOMINA,
            depends_on=["nomina_timbrada"],
        ),
        # --- Declaraciones ------------------------------------------------
        CloseTemplateTask(
            title="Generar DIOT del mes",
            description="Generar la Declaración Informativa de Operaciones con Terceros.",
            category=TaskCategory.DECLARACION,
            depends_on=["cfdi_verificado"],
            auto_check_query="diot_generada",
            key="diot",
        ),
        CloseTemplateTask(
            title="Revisar declaraciones mensuales (ISR/IVA)",
            description=(
                "Revisar y validar las declaraciones mensuales de ISR e IVA "
                "antes de presentarlas."
            ),
            category=TaskCategory.DECLARACION,
            depends_on=["conciliacion", "nomina_timbrada"],
            auto_check_query="declaraciones_revisadas",
            key="declaraciones",
        ),
        # --- Contabilidad electrónica -------------------------------------
        CloseTemplateTask(
            title="Generar contabilidad electrónica del mes",
            description="Generar balanza, pólizas y catálogo de contabilidad electrónica.",
            category=TaskCategory.ELECTRONICA,
            depends_on=["conciliacion", "diot"],
            auto_check_query="contabilidad_electronica",
            key="contabilidad_elect",
        ),
        # --- Auxiliares ---------------------------------------------------
        CloseTemplateTask(
            title="Actualizar auxiliares contables",
            description="Actualizar auxiliares por cuenta (clientes, proveedores, bancos).",
            category=TaskCategory.CUSTOM,
            depends_on=["contabilidad_elect"],
            auto_check_query="auxiliares_actualizados",
            key="auxiliares",
        ),
        # --- Reportes gerenciales ------------------------------------------
        CloseTemplateTask(
            title="Generar reportes gerenciales",
            description="Generar estado de resultados, balance y flujo del mes.",
            category=TaskCategory.CUSTOM,
            depends_on=["auxiliares", "declaraciones"],
            auto_check_query="reportes_gerenciales",
            key="reportes",
        ),
        CloseTemplateTask(
            title="Conciliar cuentas por cobrar / pagar",
            description=(
                "Revisar saldos de clientes y proveedores contra auxiliares "
                "y conciliar diferencias."
            ),
            category=TaskCategory.CUSTOM,
            depends_on=["auxiliares"],
        ),
        # --- Cierre / validación final -------------------------------------
        CloseTemplateTask(
            title="Revisión final del contador",
            description="Revisión integral del cierre por el contador responsable.",
            category=TaskCategory.CUSTOM,
            depends_on=["reportes", "contabilidad_elect", "declaraciones"],
            key="revision_final",
        ),
        CloseTemplateTask(
            title="Cerrar período y habilitar corte",
            description=(
                "Cerrar oficialmente el período: bloquear cambios y habilitar "
                "el corte contable."
            ),
            category=TaskCategory.CUSTOM,
            depends_on=["revision_final"],
            key="cerrar_periodo",
        ),
        CloseTemplateTask(
            title="Resguardar documentación del cierre",
            description=(
                "Archivar y resguardar la documentación soporte del cierre "
                "en el gestor documental."
            ),
            category=TaskCategory.CUSTOM,
            depends_on=["cerrar_periodo"],
        ),
    ]
    return t


def get_template(template_name: Optional[str] = None) -> CloseTemplate:
    """Devuelve una plantilla por nombre (solo existe la por defecto)."""
    if template_name in (None, "", "cierre_mensual", "default"):
        return default_monthly_close_template()
    raise ValueError(f"Plantilla desconocida: {template_name}")
