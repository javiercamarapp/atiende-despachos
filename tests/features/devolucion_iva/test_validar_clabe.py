# -*- coding: utf-8 -*-
"""
test_validar_clabe.py — REQ-IVA-015.

La CLABE de 18 dígitos capturada para el depósito de la devolución debe
validarse con el algoritmo de dígito verificador (módulo 10 ponderado
3-7-1) antes de aceptar la solicitud; una CLABE con dígito verificador
incorrecto debe rechazarse con `ValueError` y nunca persistirse.

Antes de este fix, `devolucion_iva/validators.py::validate_clabe` sólo
comprobaba longitud (18) y que fueran únicamente dígitos — un typo en
cualquier posición que preservara esas dos propiedades pasaba como
"válido" y podía quedar registrado como la cuenta de depósito de una
devolución real. El fix reutiliza el algoritmo de dígito verificador ya
implementado en `b2b_ai.api.validators.validate_clabe` (compartido, no
reimplementado) para cerrar ese hueco.

Sin mocks: se llama a la función real de validación y al flujo real de
`preparar_solicitud` / `DevolucionIVAService`.
"""
from __future__ import annotations

import pytest

from b2b_ai.features.devolucion_iva.service import (
    DevolucionIVAService,
    listar_solicitudes,
    preparar_solicitud,
)
from b2b_ai.features.devolucion_iva.validators import validate_clabe

# CLABE realmente válida (dígito verificador correcto: 7), banco 072
# (Banco Regional). Usada en el resto de la suite de devolucion_iva.
CLABE_VALIDA = "072180001234567897"

# Misma base de 17 dígitos que CLABE_VALIDA, pero con el dígito
# verificador (posición 18) alterado a 0 en vez del 7 correcto.
CLABE_DIGITO_VERIFICADOR_INVALIDO = "072180001234567890"

# Otra base de 17 dígitos, con su propio dígito verificador correcto (7)
# — para probar que el validador funciona con más de una CLABE base y no
# está de alguna forma atado a CLABE_VALIDA.
CLABE_VALIDA_2 = "014180655208094807"
CLABE_VALIDA_2_DIGITO_INVALIDO = "014180655208094809"


class TestValidateClabeChecksum:
    """Pruebas directas sobre `validators.py::validate_clabe`."""

    def test_clabe_valida_pasa(self):
        assert validate_clabe(CLABE_VALIDA) is None

    def test_clabe_digito_verificador_incorrecto_se_rechaza(self):
        error = validate_clabe(CLABE_DIGITO_VERIFICADOR_INVALIDO)
        assert error is not None
        assert "dígito verificador" in error

    def test_segunda_clabe_valida_pasa(self):
        """Confirma que el validador no depende de una sola CLABE fija."""
        assert validate_clabe(CLABE_VALIDA_2) is None

    def test_segunda_clabe_digito_verificador_incorrecto_se_rechaza(self):
        error = validate_clabe(CLABE_VALIDA_2_DIGITO_INVALIDO)
        assert error is not None
        assert "dígito verificador" in error

    def test_formato_incorrecto_sigue_rechazandose_antes_del_checksum(self):
        """Longitud/dígitos siguen validándose primero (regresión)."""
        assert validate_clabe("123") is not None
        assert validate_clabe("07218000123456789A") is not None
        assert validate_clabe("") is not None

    def test_typo_en_un_solo_digito_de_una_clabe_valida_se_detecta(self):
        """Caso central de REQ-IVA-015: cambiar UN dígito interno (no el
        verificador) de una CLABE válida produce otra cadena de 18 dígitos
        numéricos con formato correcto pero checksum roto — debe
        rechazarse, no colarse como "parece bien"."""
        # CLABE_VALIDA con un dígito interno (posición 10, índice 9)
        # cambiado de '2' a '3'.
        typo = CLABE_VALIDA[:9] + "3" + CLABE_VALIDA[10:]
        assert len(typo) == 18
        assert typo != CLABE_VALIDA
        error = validate_clabe(typo)
        assert error is not None
        assert "dígito verificador" in error


class TestPrepararSolicitudRechazaClabeInvalida:
    """Extremo a extremo: `preparar_solicitud` nunca debe construir ni
    devolver una `SolicitudDevolucion` cuando la CLABE tiene un dígito
    verificador incorrecto."""

    def test_preparar_solicitud_lanza_valueerror_con_digito_verificador_incorrecto(self):
        saldo = {"monto_devolucion_sugerido": 15000.0}
        with pytest.raises(ValueError, match="dígito verificador"):
            preparar_solicitud(
                "2025-02", saldo, "Banorte", CLABE_DIGITO_VERIFICADOR_INVALIDO
            )

    def test_preparar_solicitud_acepta_clabe_con_digito_verificador_correcto(self):
        saldo = {"monto_devolucion_sugerido": 15000.0}
        sol = preparar_solicitud("2025-02", saldo, "Banorte", CLABE_VALIDA)
        assert sol.clabe == CLABE_VALIDA

    def test_clabe_invalida_nunca_se_persiste(self):
        """No debe crecer la lista de solicitudes registradas cuando la
        CLABE es rechazada — la solicitud nunca llega a construirse, por lo
        que tampoco hay nada que un llamador pudiera registrar después."""
        antes = len(listar_solicitudes())

        saldo = {"monto_devolucion_sugerido": 20000.0}
        with pytest.raises(ValueError):
            preparar_solicitud(
                "2025-02", saldo, "Banorte", CLABE_DIGITO_VERIFICADOR_INVALIDO
            )

        despues = len(listar_solicitudes())
        assert despues == antes

    def test_service_preparar_solicitud_propaga_el_rechazo(self):
        """El wrapper `DevolucionIVAService.preparar_solicitud` (usado por
        el endpoint HTTP) debe propagar el mismo `ValueError`, no
        silenciarlo ni degradarlo a una solicitud con estado distinto."""
        svc = DevolucionIVAService()
        saldo = {"monto_devolucion_sugerido": 12000.0}
        with pytest.raises(ValueError, match="dígito verificador"):
            svc.preparar_solicitud(
                "2025-02", saldo, "Banorte", CLABE_DIGITO_VERIFICADOR_INVALIDO
            )
