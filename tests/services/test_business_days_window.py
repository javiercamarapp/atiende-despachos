# -*- coding: utf-8 -*-
"""Tests para `_business_days_window` (REQ-CONC-002 del blueprint de
conciliación bancaria N-a-1, docs/BLUEPRINT-AGENTES-FISCALES.md §4).

Cubre: conteo en días hábiles (excluye sábado/domingo), corrimiento cuando
`fecha_banco` cae lunes (la ventana debe alcanzar viernes/sábado/domingo
anteriores), y el buffer configurable de 1-2 días hábiles para feriados
bancarios.
"""
from datetime import date

import pytest

from b2b_ai.services.bank_reconciliation import (
    _business_days_window,
    _subtract_business_days,
)

# Perfil Clip: liquidación fija T+1 día hábil (ver REQ-CONC-001, semilla
# "clip"). Se define aquí como dict simple porque `SettlementProfile`
# (REQ-CONC-001) todavía no existe — `_business_days_window` debe aceptar
# cualquier perfil dict-like u objeto con esos atributos.
PERFIL_CLIP = {
    "nombre": "clip",
    "liquidacion_dias_habiles_min": 1,
    "liquidacion_dias_habiles_max": 1,
    "incluye_fin_de_semana_en_lunes": True,
}


class TestSubtractBusinessDays:
    def test_retrocede_saltando_fin_de_semana(self):
        # Lunes 2026-09-07 menos 1 día hábil -> viernes 2026-09-04.
        assert _subtract_business_days(date(2026, 9, 7), 1) == date(2026, 9, 4)

    def test_retrocede_dos_dias_habiles_desde_lunes(self):
        # Lunes 2026-09-07 menos 2 días hábiles -> jueves 2026-09-03.
        assert _subtract_business_days(date(2026, 9, 7), 2) == date(2026, 9, 3)

    def test_cero_no_retrocede(self):
        assert _subtract_business_days(date(2026, 9, 9), 0) == date(2026, 9, 9)

    def test_nunca_aterriza_en_fin_de_semana(self):
        # Recorre 10 fechas base y confirma que el resultado nunca cae en
        # sábado (5) o domingo (6), sin importar cuántos días hábiles se
        # retrocedan.
        base = date(2026, 9, 1)
        for offset in range(10):
            for n in range(1, 6):
                d = _subtract_business_days(
                    date.fromordinal(base.toordinal() + offset), n)
                assert d.weekday() < 5


class TestBusinessDaysWindowCasoBlueprint:
    """El caso exacto exigido por REQ-CONC-002."""

    def test_lunes_incluye_viernes_y_fin_de_semana(self):
        inicio, fin = _business_days_window(date(2026, 9, 7), PERFIL_CLIP)

        # La ventana debe INCLUIR el viernes anterior y todo el fin de
        # semana (sábado y domingo), porque un cobro capturado cualquiera
        # de esos 3 días liquida el lunes bajo T+1 hábil.
        assert inicio <= date(2026, 9, 4) <= fin
        assert inicio <= date(2026, 9, 5) <= fin
        assert inicio <= date(2026, 9, 6) <= fin

        # Nunca debe incluir la propia fecha_banco (eso es liquidación, no
        # captura) ni el jueves si el buffer default no lo amplía tanto.
        assert fin < date(2026, 9, 7)
        assert inicio <= fin

    def test_devuelve_fechas_date_no_strings(self):
        inicio, fin = _business_days_window("2026-09-07", PERFIL_CLIP)
        assert isinstance(inicio, date)
        assert isinstance(fin, date)

    def test_acepta_perfil_como_objeto_con_atributos(self):
        class PerfilObj:
            liquidacion_dias_habiles_min = 1
            liquidacion_dias_habiles_max = 1
            incluye_fin_de_semana_en_lunes = True

        inicio, fin = _business_days_window(date(2026, 9, 7), PerfilObj())
        assert inicio <= date(2026, 9, 4) <= fin
        assert inicio <= date(2026, 9, 6) <= fin


class TestBusinessDaysWindowSinCorrimiento:
    def test_martes_no_amplia_a_fin_de_semana_previo(self):
        # Martes 2026-09-08, T+1 hábil -> el día hábil anterior es lunes
        # 2026-09-07 (no hay fin de semana entre ambos): la ventana no
        # necesita el corrimiento especial de lunes.
        inicio, fin = _business_days_window(date(2026, 9, 8), PERFIL_CLIP)
        assert fin == date(2026, 9, 7)
        # El fin de semana 05-06 no es la fecha "fin" de la ventana aquí
        # (no aplica el corrimiento de lunes), aunque puede quedar cubierto
        # por el buffer hacia atrás si éste lo alcanza.
        assert fin != date(2026, 9, 6)


class TestBusinessDaysWindowBuffer:
    def test_buffer_amplia_el_extremo_mas_antiguo(self):
        _, fin_1 = _business_days_window(
            date(2026, 9, 9), PERFIL_CLIP, buffer_dias_habiles=1)
        inicio_1, _ = _business_days_window(
            date(2026, 9, 9), PERFIL_CLIP, buffer_dias_habiles=1)
        inicio_2, _ = _business_days_window(
            date(2026, 9, 9), PERFIL_CLIP, buffer_dias_habiles=2)

        # Con buffer=2 el extremo antiguo debe ser igual o anterior al de
        # buffer=1 (la ventana nunca se angosta al pedir más buffer).
        assert inicio_2 <= inicio_1

    def test_buffer_fuera_de_rango_se_acota_a_1_o_2(self):
        inicio_0, fin_0 = _business_days_window(
            date(2026, 9, 9), PERFIL_CLIP, buffer_dias_habiles=0)
        inicio_1, fin_1 = _business_days_window(
            date(2026, 9, 9), PERFIL_CLIP, buffer_dias_habiles=1)
        inicio_99, fin_99 = _business_days_window(
            date(2026, 9, 9), PERFIL_CLIP, buffer_dias_habiles=99)
        inicio_2, fin_2 = _business_days_window(
            date(2026, 9, 9), PERFIL_CLIP, buffer_dias_habiles=2)

        # buffer=0 se acota a 1; buffer=99 se acota a 2.
        assert (inicio_0, fin_0) == (inicio_1, fin_1)
        assert (inicio_99, fin_99) == (inicio_2, fin_2)


class TestBusinessDaysWindowValidacion:
    def test_fecha_banco_invalida_lanza_valueerror(self):
        with pytest.raises(ValueError):
            _business_days_window("no-es-una-fecha", PERFIL_CLIP)

    def test_ventana_nunca_invertida(self):
        # Perfil degenerado (min > max declarado al revés) no debe producir
        # inicio > fin.
        perfil_raro = {
            "liquidacion_dias_habiles_min": 5,
            "liquidacion_dias_habiles_max": 1,
        }
        inicio, fin = _business_days_window(date(2026, 9, 9), perfil_raro)
        assert inicio <= fin
