# -*- coding: utf-8 -*-
"""
REQ-IVA-011 (docs/BLUEPRINT-AGENTES-FISCALES.md, matriz REQ-IVA —
Devolución de IVA). Ver ADR-4.

Criterio de aceptación exacto:
  "El sistema nunca debe negar ni reducir automáticamente una devolución
  de IVA solo por depósitos bancarios clasificados como sospechosos (sin
  documento de soporte o con score bajo); ante esa condición debe marcar
  el caso como `requiere_revision_humana=True` con la nota "Art. 59 fr.
  III CFF exige facultades de comprobación previas (PRODECON 1/2026)" y
  nunca setear `estado="rechazada"` automáticamente."

Este archivo ejercita el servicio real
(`ReconciliacionIngresosEgresosService.evaluar_caso_deposito_sospechoso` /
`evaluar_casos_depositos_sospechosos`, y su integración en
`generar_papel_trabajo`), sin mocks, contra una batería adversarial de
combinaciones (clasificación × presencia de documento × score), más un
chequeo estático de que ninguno de los módulos de este blueprint contiene
una rama de código que asigne automáticamente un estado de rechazo/negación
por causa de un depósito. También cubre el lado de `devolucion_iva`: que
`preparar_solicitud` nunca produce un estado equivalente a "rechazada" ni
siquiera en escenarios extremos de congruencia.
"""
from __future__ import annotations

import inspect
import itertools

import pytest
from pydantic import ValidationError

from b2b_ai.features.reconciliacion_ingresos_egresos import models as rie_models
from b2b_ai.features.reconciliacion_ingresos_egresos import service as rie_service_module
from b2b_ai.features.reconciliacion_ingresos_egresos import routes as rie_routes_module
from b2b_ai.features.reconciliacion_ingresos_egresos.models import (
    NOTA_ART_59_FR_III_CFF,
    CasoDepositoSospechoso,
    ClasificacionDeposito,
    ClasificacionDepositoResult,
    DepositoBancario,
    EstadoCasoDeposito,
)
from b2b_ai.features.reconciliacion_ingresos_egresos.service import (
    ReconciliacionIngresosEgresosService,
)

from b2b_ai.features.devolucion_iva import service as devolucion_iva_service_module
from b2b_ai.features.devolucion_iva import routes as devolucion_iva_routes_module
from b2b_ai.features.devolucion_iva.models import EstatusDevolucion
from b2b_ai.features.devolucion_iva.service import preparar_solicitud


NOTA_EXACTA = "Art. 59 fr. III CFF exige facultades de comprobación previas (PRODECON 1/2026)"

# Categorías bajo la presunción del Art. 59 fr. III CFF (REQ-IVA-001):
# aquellas que "sacan" un depósito de ingreso gravado y por lo tanto exigen
# evidencia documental real para sostenerse.
CATEGORIAS_PRESUNTIVAS = (
    ClasificacionDeposito.FINANCIAMIENTO,
    ClasificacionDeposito.APORTACION_SOCIO,
    ClasificacionDeposito.GARANTIA,
)
CATEGORIAS_NO_PRESUNTIVAS = (
    ClasificacionDeposito.INGRESO,
    ClasificacionDeposito.OTRO_NO_GRAVABLE,
)


def _deposito(id_="DEP-1", documento_soporte_id=None) -> DepositoBancario:
    return DepositoBancario(
        id=id_,
        fecha="2026-06-15",
        monto=50000.0,
        descripcion="Depósito de prueba",
        referencia="REF-1",
        banco="BBVA",
        cuenta="0123456789",
        es_credito=True,
        documento_soporte_id=documento_soporte_id,
    )


def _clasificacion(
    clasificacion: ClasificacionDeposito,
    confianza: float,
    deposito_id: str = "DEP-1",
) -> ClasificacionDepositoResult:
    return ClasificacionDepositoResult(
        deposito_id=deposito_id,
        clasificacion=clasificacion,
        confianza=confianza,
        razon="Regla de prueba",
        articulo_cff="CFF Art. 59 fracción III" if clasificacion in CATEGORIAS_PRESUNTIVAS else None,
    )


# ---------------------------------------------------------------------------
# La nota exacta del blueprint debe coincidir carácter por carácter con la
# constante que usa el servicio — si alguna cambia sin la otra, el criterio
# de aceptación deja de cumplirse en silencio.
# ---------------------------------------------------------------------------

def test_la_nota_exacta_del_blueprint_coincide_con_la_constante_del_servicio():
    assert NOTA_ART_59_FR_III_CFF == NOTA_EXACTA


# ---------------------------------------------------------------------------
# 1) El tipo mismo no puede representar una negación automática.
# ---------------------------------------------------------------------------

def test_estado_caso_deposito_no_contiene_ningun_valor_de_rechazo():
    """ADR-4: `EstadoCasoDeposito` no debe tener valor de rechazo/negación
    bajo ningún nombre razonable — ni siquiera como posibilidad futura
    accidental."""
    valores = {v.value for v in EstadoCasoDeposito}
    assert valores == {"evidencia_suficiente", "requiere_revision_humana"}
    for valor in valores:
        assert "rechaz" not in valor
        assert "denieg" not in valor
        assert "niega" not in valor


def test_caso_deposito_sospechoso_rechaza_construirse_con_estado_inventado():
    """Ni siquiera pasando el string crudo "rechazada" se puede construir
    un `CasoDepositoSospechoso` con ese estado: pydantic debe rechazarlo
    porque el enum no lo contempla."""
    with pytest.raises(ValidationError):
        CasoDepositoSospechoso(
            deposito_id="DEP-1",
            clasificacion=ClasificacionDeposito.FINANCIAMIENTO,
            confianza=0.5,
            documento_soporte_id=None,
            estado="rechazada",
            requiere_revision_humana=True,
            nota=NOTA_ART_59_FR_III_CFF,
        )


# ---------------------------------------------------------------------------
# 2) Comportamiento adversarial exhaustivo de
#    evaluar_caso_deposito_sospechoso: para TODA combinación posible de
#    clasificación × documento × score, nunca debe aparecer una negación,
#    y la nota debe ser exactamente la del blueprint cuando corresponde.
# ---------------------------------------------------------------------------

DOCUMENTOS = (None, "", "DOC-123")
SCORES = (0.0, 0.3, 0.69, 0.699999, 0.7, 0.71, 0.85, 0.9, 0.95, 1.0)
CLASIFICACIONES = CATEGORIAS_PRESUNTIVAS + CATEGORIAS_NO_PRESUNTIVAS


@pytest.mark.parametrize(
    "clasificacion,documento_soporte_id,confianza",
    list(itertools.product(CLASIFICACIONES, DOCUMENTOS, SCORES)),
)
def test_evaluar_caso_deposito_sospechoso_nunca_niega_automaticamente(
    clasificacion, documento_soporte_id, confianza
):
    service = ReconciliacionIngresosEgresosService()
    deposito = _deposito(documento_soporte_id=documento_soporte_id)
    clas = _clasificacion(clasificacion, confianza)

    caso = service.evaluar_caso_deposito_sospechoso(deposito, clas)

    # Nunca puede aparecer ningún vestigio de rechazo/negación.
    assert caso.estado in (
        EstadoCasoDeposito.EVIDENCIA_SUFICIENTE,
        EstadoCasoDeposito.REQUIERE_REVISION_HUMANA,
    )
    assert caso.model_dump()["estado"] != "rechazada"

    sin_documento = not documento_soporte_id
    score_bajo = confianza < ReconciliacionIngresosEgresosService.UMBRAL_CONFIANZA_SOSPECHOSA
    bajo_presuncion = clasificacion in CATEGORIAS_PRESUNTIVAS
    deberia_ser_sospechoso = bajo_presuncion and (sin_documento or score_bajo)

    if deberia_ser_sospechoso:
        assert caso.requiere_revision_humana is True
        assert caso.estado == EstadoCasoDeposito.REQUIERE_REVISION_HUMANA
        assert caso.nota == NOTA_EXACTA
    else:
        assert caso.requiere_revision_humana is False
        assert caso.estado == EstadoCasoDeposito.EVIDENCIA_SUFICIENTE
        assert caso.nota is None


def test_categorias_no_presuntivas_nunca_se_marcan_sospechosas_sin_importar_el_score():
    """INGRESO y OTRO_NO_GRAVABLE quedan fuera de la presunción del Art. 59
    fr. III CFF (REQ-IVA-001 solo aplica a financiamiento/aportación/
    garantía): un score bajo o la ausencia de documento en esas categorías
    no debe disparar `requiere_revision_humana` por esta regla."""
    service = ReconciliacionIngresosEgresosService()
    for clasificacion in CATEGORIAS_NO_PRESUNTIVAS:
        deposito = _deposito(documento_soporte_id=None)
        clas = _clasificacion(clasificacion, confianza=0.0)
        caso = service.evaluar_caso_deposito_sospechoso(deposito, clas)
        assert caso.requiere_revision_humana is False
        assert caso.estado == EstadoCasoDeposito.EVIDENCIA_SUFICIENTE


def test_score_alto_no_salva_un_deposito_sin_documento_de_soporte():
    """La condición es un OR: aunque la regla haya matcheado con confianza
    altísima (0.99), la falta de documento real por sí sola basta para
    marcar el caso como sospechoso — ni el mejor score reemplaza la
    evidencia documental exigida por el Art. 59 fr. III CFF."""
    service = ReconciliacionIngresosEgresosService()
    deposito = _deposito(documento_soporte_id=None)
    clas = _clasificacion(ClasificacionDeposito.APORTACION_SOCIO, confianza=0.99)
    caso = service.evaluar_caso_deposito_sospechoso(deposito, clas)
    assert caso.requiere_revision_humana is True
    assert caso.nota == NOTA_EXACTA


def test_documento_presente_no_salva_un_score_bajo():
    """Simétrico: tener un documento adjunto no basta si la regla que
    clasificó el depósito tuvo muy baja confianza."""
    service = ReconciliacionIngresosEgresosService()
    deposito = _deposito(documento_soporte_id="DOC-CONTRATO-MUTUO-001")
    clas = _clasificacion(ClasificacionDeposito.FINANCIAMIENTO, confianza=0.2)
    caso = service.evaluar_caso_deposito_sospechoso(deposito, clas)
    assert caso.requiere_revision_humana is True
    assert caso.nota == NOTA_EXACTA


def test_documento_presente_y_score_alto_es_evidencia_suficiente():
    """Solo cuando hay documento real Y el score no es bajo el caso se
    considera con evidencia suficiente — nunca "aprobado" automáticamente
    como determinación firme (eso sigue exigiendo REQ-IVA-013), pero sí
    fuera del camino de "sospechoso" de este requisito."""
    service = ReconciliacionIngresosEgresosService()
    deposito = _deposito(documento_soporte_id="DOC-ACTA-ASAMBLEA-002")
    clas = _clasificacion(ClasificacionDeposito.GARANTIA, confianza=0.85)
    caso = service.evaluar_caso_deposito_sospechoso(deposito, clas)
    assert caso.requiere_revision_humana is False
    assert caso.estado == EstadoCasoDeposito.EVIDENCIA_SUFICIENTE
    assert caso.nota is None


# ---------------------------------------------------------------------------
# 3) Integración real end-to-end contra el servicio (sin mocks): un caso
#    sospechoso debe reflejarse en el papel de trabajo con
#    requires_human_review=True y la nota exacta en las conclusiones —
#    nunca con un campo de rechazo.
# ---------------------------------------------------------------------------

def test_papel_trabajo_marca_revision_humana_y_nota_exacta_para_deposito_sospechoso():
    service = ReconciliacionIngresosEgresosService()
    deposito_sospechoso = DepositoBancario(
        id="DEP-FIN-001",
        fecha="2026-06-10",
        monto=300000.0,
        descripcion="Préstamo de accionista sin contrato adjunto",
        referencia="PRESTAMO-SOCIO-2026",
        banco="Santander",
        cuenta="9988776655",
        es_credito=True,
        documento_soporte_id=None,
    )

    conciliacion = service.conciliar_depositos_auxiliares(
        [deposito_sospechoso], [], periodo="2026-06", tenant_id="T1"
    )
    papel = service.generar_papel_trabajo(conciliacion, conciliacion.clasificaciones)

    assert papel.requires_human_review is True
    assert any(NOTA_EXACTA in c for c in papel.conclusiones)

    # Ningún objeto producido por el flujo real trae un campo "estado" ni
    # "status" con valor "rechazada"/"rechazado".
    papel_json = papel.model_dump()
    assert _buscar_valor_rechazo(papel_json) is False


def _buscar_valor_rechazo(obj) -> bool:
    """Recorre recursivamente un dict/list buscando algún string que
    contenga 'rechaz' — usado para confirmar que ningún resultado real del
    flujo de conciliación/devolución contiene una negación automática."""
    if isinstance(obj, str):
        return "rechaz" in obj.lower()
    if isinstance(obj, dict):
        return any(_buscar_valor_rechazo(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_buscar_valor_rechazo(v) for v in obj)
    return False


def test_deposito_con_evidencia_suficiente_no_dispara_revision_por_esta_regla():
    """Caso simétrico: un depósito de financiamiento CON documento y buen
    score no debe, por esta regla, forzar `requires_human_review=True` en
    el papel de trabajo (puede seguir siendo True por otras razones, como
    discrepancias, pero no por falta de evidencia)."""
    service = ReconciliacionIngresosEgresosService()
    deposito_documentado = DepositoBancario(
        id="DEP-FIN-002",
        fecha="2026-06-11",
        monto=100000.0,
        descripcion="Préstamo bancario con contrato de mutuo adjunto",
        referencia="PRESTAMO-002",
        banco="BBVA",
        cuenta="1122334455",
        es_credito=True,
        documento_soporte_id="DOC-CONTRATO-MUTUO-002",
    )

    # Fuerza directamente una clasificación con score alto para aislar la
    # regla bajo prueba del motor de reglas por regex.
    clasificacion = _clasificacion(
        ClasificacionDeposito.FINANCIAMIENTO, confianza=0.9, deposito_id="DEP-FIN-002"
    )
    casos = service.evaluar_casos_depositos_sospechosos(
        [deposito_documentado], [clasificacion]
    )
    assert len(casos) == 1
    assert casos[0].requiere_revision_humana is False


# ---------------------------------------------------------------------------
# 4) Guarda estática: ningún módulo de este blueprint debe contener una
#    rama de código que asigne automáticamente un estado de rechazo por
#    causa de un depósito. Esto es un cinturón adicional al de tipos: si
#    alguna vez alguien agrega `estado="rechazada"` fuera del endpoint de
#    revisión humana, este test debe reventar.
# ---------------------------------------------------------------------------

def test_reconciliacion_service_no_asigna_estado_de_rechazo_por_deposito():
    fuente = inspect.getsource(rie_service_module)
    assert 'estado="rechazada"' not in fuente
    assert "estado = 'rechazada'" not in fuente
    assert "EstadoCasoDeposito.RECHAZADA" not in fuente
    # El único uso de la palabra "sospech" debe vivir junto a la lógica de
    # revisión humana, nunca junto a una negación.
    assert "requiere_revision_humana=True" in fuente


def test_reconciliacion_routes_no_asigna_estado_de_rechazo_por_deposito():
    fuente = inspect.getsource(rie_routes_module)
    assert 'estado="rechazada"' not in fuente
    assert "estado = 'rechazada'" not in fuente


def test_devolucion_iva_service_nunca_asigna_estatusdevolucion_rechazada_automaticamente():
    """El único valor de rechazo del módulo de devolución de IVA es
    `EstatusDevolucion.RECHAZADA`, y hoy (correctamente, según ADR-4) no
    aparece asignado en ningún flujo automático de `service.py` — solo
    existe como valor de enum para que un humano/SAT lo establezca vía
    seguimiento manual. Este test estático evita que una futura
    "optimización" automática lo empiece a asignar por causa de depósitos
    sospechosos."""
    fuente = inspect.getsource(devolucion_iva_service_module)
    assert "EstatusDevolucion.RECHAZADA" not in fuente
    assert 'status=EstatusDevolucion.RECHAZADA' not in fuente
    assert '"rechazada"' not in fuente


def test_devolucion_iva_routes_nunca_asigna_estatusdevolucion_rechazada_automaticamente():
    fuente = inspect.getsource(devolucion_iva_routes_module)
    assert "EstatusDevolucion.RECHAZADA" not in fuente


# ---------------------------------------------------------------------------
# 5) Lado devolución de IVA: incluso en escenarios extremos de congruencia
#    (REQ-IVA-010), `preparar_solicitud` nunca produce nada equivalente a
#    "rechazada" — como mucho, requiere_aclaracion.
# ---------------------------------------------------------------------------

def test_preparar_solicitud_en_escenario_extremo_nunca_rechaza_solo_marca_aclaracion():
    """Monto grande, sin DIOT, sin facturas, sin declaraciones: el peor
    escenario de congruencia posible. Ni así el sistema debe rechazar la
    solicitud — debe quedar `requiere_aclaracion`, con `status` inicial
    `PENDIENTE`, nunca `RECHAZADA`."""
    solicitud = preparar_solicitud(
        periodo="2026-06",
        saldo={"monto_devolucion_sugerido": 999999.99},
        tenant_id="T1",
        facturas=None,
        diot_entries=None,
        declaraciones=None,
    )
    assert solicitud.status == EstatusDevolucion.PENDIENTE
    assert solicitud.status != EstatusDevolucion.RECHAZADA
    assert solicitud.estado.value == "requiere_aclaracion"
    assert solicitud.model_dump()["status"] != "rechazada"
