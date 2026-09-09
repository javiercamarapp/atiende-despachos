# -*- coding: utf-8 -*-
"""
REQ-IVA-016 (docs/BLUEPRINT-AGENTES-FISCALES.md, matriz REQ-IVA —
Devolución de IVA).

Criterio de aceptación exacto:
  "El plazo de 40 días hábiles (20 si hay dictamen/garantía, Art. 22 CFF)
  debe calcularse y exponerse en `GET /papel-trabajo/{periodo}` como
  `fecha_limite_resolucion`, contando solo días hábiles (excluyendo
  sábados, domingos y el calendario oficial de días inhábiles del SAT
  publicado en el Anexo correspondiente de la RMF vigente); prueba con
  una solicitud presentada un jueves debe dar una fecha 40 días hábiles
  después, no 40 días naturales."

Sin mocks: se usa el motor de conteo de días hábiles real
(`sumar_dias_habiles`/`calcular_fecha_limite_resolucion` de
`b2b_ai.features.devolucion_iva.service`), que reutiliza el mismo
calendario oficial de días inhábiles del SAT
(`MEXICO_HOLIDAYS_2026`/`is_business_day`) ya usado por
`b2b_ai.features.alertas.deadline_engine` para el resto de los plazos
fiscales del sistema, y el router HTTP real de `devolucion_iva`
(`build_devolucion_iva_router`) vía `TestClient`.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from b2b_ai.features.alertas.deadline_engine import MEXICO_HOLIDAYS_2026
from b2b_ai.features.devolucion_iva.routes import build_devolucion_iva_router
from b2b_ai.features.devolucion_iva.service import (
    DIAS_HABILES_PLAZO_RESOLUCION,
    DIAS_HABILES_PLAZO_RESOLUCION_CON_DICTAMEN_O_GARANTIA,
    calcular_fecha_limite_resolucion,
    sumar_dias_habiles,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sumar_solo_fin_de_semana(fecha_inicio: date, n: int) -> date:
    """Referencia de comparación: cuenta días hábiles excluyendo SOLO
    sábado/domingo (sin el calendario oficial de días inhábiles del SAT).
    Sirve para probar que el motor real hace algo distinto (más estricto)
    que solo saltar fines de semana.
    """
    d = fecha_inicio
    contados = 0
    while contados < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            contados += 1
    return d


def _sumar_dias_naturales(fecha_inicio: date, n: int) -> date:
    return fecha_inicio + timedelta(days=n)


def _auth_for(tenant_id):
    async def _dep():
        return {"key": "test-key", "tenant_id": tenant_id, "user_id": "u1"}
    return _dep


def _client(tenant_id="T1"):
    router = build_devolucion_iva_router(
        db=None,
        require_api_key=_auth_for(tenant_id),
    )
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# 2026-01-08 es jueves (verificado: date(2026, 1, 8).weekday() == 3).
JUEVES_PRESENTACION = date(2026, 1, 8)
assert JUEVES_PRESENTACION.weekday() == 3, "fixture debe ser un jueves real"


# ---------------------------------------------------------------------------
# Nivel unitario: b2b_ai/features/devolucion_iva/service.py
# ---------------------------------------------------------------------------

class TestSumarDiasHabiles:
    def test_presentacion_jueves_da_40_dias_habiles_no_naturales(self):
        """Criterio exacto de REQ-IVA-016: una solicitud presentada un
        jueves debe dar una fecha 40 días hábiles después, NUNCA 40 días
        naturales."""
        resultado = sumar_dias_habiles(JUEVES_PRESENTACION, 40)
        naturales = _sumar_dias_naturales(JUEVES_PRESENTACION, 40)

        assert resultado != naturales, (
            "fecha_limite_resolucion no debe coincidir con 40 días "
            "naturales después de la presentación."
        )
        # Verificado independientemente contando día por día con el mismo
        # calendario oficial (sábado/domingo + MEXICO_HOLIDAYS_2026).
        assert resultado == date(2026, 3, 6)
        assert naturales == date(2026, 2, 17)

    def test_excluye_calendario_oficial_sat_no_solo_fin_de_semana(self):
        """El plazo debe excluir también el calendario oficial de días
        inhábiles del SAT, no únicamente sábados/domingos: entre
        2026-01-08 y el resultado cae el feriado oficial del 2 de febrero
        (MEXICO_HOLIDAYS_2026), así que el resultado real debe caer un día
        después de lo que daría contar solo fin de semana."""
        resultado_real = sumar_dias_habiles(JUEVES_PRESENTACION, 40)
        resultado_solo_finde = _sumar_solo_fin_de_semana(JUEVES_PRESENTACION, 40)

        assert (2, 2) in MEXICO_HOLIDAYS_2026, (
            "fixture asume que el 2 de febrero está en el calendario "
            "oficial de días inhábiles reutilizado."
        )
        assert resultado_real != resultado_solo_finde
        assert resultado_real > resultado_solo_finde

    def test_20_dias_habiles_si_hay_dictamen_o_garantia(self):
        con_dictamen = calcular_fecha_limite_resolucion(
            JUEVES_PRESENTACION, hay_dictamen_o_garantia=True,
        )
        sin_dictamen = calcular_fecha_limite_resolucion(
            JUEVES_PRESENTACION, hay_dictamen_o_garantia=False,
        )

        assert con_dictamen == date(2026, 2, 6)
        assert con_dictamen < sin_dictamen
        assert DIAS_HABILES_PLAZO_RESOLUCION == 40
        assert DIAS_HABILES_PLAZO_RESOLUCION_CON_DICTAMEN_O_GARANTIA == 20

    def test_resultado_nunca_cae_en_fin_de_semana_ni_feriado_oficial(self):
        for inicio in (
            date(2026, 1, 8),
            date(2026, 3, 2),
            date(2025, 12, 30),
            date(2026, 8, 31),
        ):
            for dias, con_dictamen in (
                (DIAS_HABILES_PLAZO_RESOLUCION, False),
                (DIAS_HABILES_PLAZO_RESOLUCION_CON_DICTAMEN_O_GARANTIA, True),
            ):
                resultado = calcular_fecha_limite_resolucion(
                    inicio, hay_dictamen_o_garantia=con_dictamen,
                )
                assert resultado.weekday() < 5, (
                    f"{resultado} (desde {inicio}) cae en fin de semana"
                )
                assert (resultado.month, resultado.day) not in MEXICO_HOLIDAYS_2026, (
                    f"{resultado} (desde {inicio}) cae en día inhábil oficial"
                )

    def test_fecha_inicio_se_excluye_del_conteo(self):
        """Art. 12 CFF: el plazo corre a partir del día siguiente — sumar 0
        días hábiles a un jueves no debe devolver el propio jueves."""
        resultado = sumar_dias_habiles(JUEVES_PRESENTACION, 1)
        assert resultado != JUEVES_PRESENTACION
        assert resultado == date(2026, 1, 9)  # viernes siguiente

    def test_num_dias_habiles_negativo_rechazado(self):
        with pytest.raises(ValueError):
            sumar_dias_habiles(JUEVES_PRESENTACION, -1)

    def test_acepta_fecha_como_texto_iso_o_como_date(self):
        desde_texto = sumar_dias_habiles("2026-01-08", 40)
        desde_date = sumar_dias_habiles(date(2026, 1, 8), 40)
        assert desde_texto == desde_date == date(2026, 3, 6)


# ---------------------------------------------------------------------------
# Nivel HTTP: GET /api/v1/devolucion-iva/papel-trabajo/{periodo}
# ---------------------------------------------------------------------------

class TestEndpointPapelTrabajoFechaLimite:
    def test_endpoint_expone_fecha_limite_resolucion_40_dias_habiles(self):
        client = _client(tenant_id="T1")
        resp = client.get(
            "/api/v1/devolucion-iva/papel-trabajo/2026-01",
            params={"fecha_presentacion": "2026-01-08"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["fecha_limite_resolucion"] == "2026-03-06"

    def test_endpoint_reduce_a_20_dias_habiles_con_dictamen_o_garantia(self):
        client = _client(tenant_id="T1")
        resp = client.get(
            "/api/v1/devolucion-iva/papel-trabajo/2026-01",
            params={
                "fecha_presentacion": "2026-01-08",
                "hay_dictamen_o_garantia": "true",
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["fecha_limite_resolucion"] == "2026-02-06"

    def test_endpoint_sin_fecha_presentacion_no_inventa_fecha_limite(self):
        """Sin `fecha_presentacion` en el request, el endpoint nunca debe
        inventar una fecha límite — debe quedar explícitamente en None,
        y el resto del papel de trabajo se sigue generando igual
        (compatibilidad con el comportamiento previo del endpoint)."""
        client = _client(tenant_id="T1")
        resp = client.get("/api/v1/devolucion-iva/papel-trabajo/2026-01")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["fecha_limite_resolucion"] is None
        assert len(data["secciones"]) == 7  # forma previa del endpoint intacta
        assert data["periodo"] == "2026-01"

    def test_endpoint_rechaza_fecha_presentacion_con_formato_invalido(self):
        client = _client(tenant_id="T1")
        resp = client.get(
            "/api/v1/devolucion-iva/papel-trabajo/2026-01",
            params={"fecha_presentacion": "08-enero-2026"},
        )
        assert resp.status_code == 422, resp.text
