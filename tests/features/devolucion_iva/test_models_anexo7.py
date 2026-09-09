# -*- coding: utf-8 -*-
"""
test_models_anexo7.py — REQ-IVA-008.

`FacturaCFDI` gana `folio_factura`, `forma_pago`, `metodo_pago` y
`referencia_complemento_pago`. Estos 4 campos son requeridos para poder
marcar la factura como "lista para anexo 7/7-A"; sin
`referencia_complemento_pago` la factura nunca cuenta como IVA acreditable
"efectivamente pagado" (LIVA Art. 5 fracc. III), sin importar `iva` o
`proporcionalidad`.

Sin mocks: se instancia el modelo real (pydantic v2) y se llaman sus
validadores y métodos de negocio reales.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from b2b_ai.features.devolucion_iva.models import FacturaCFDI, TipoFactura, ClasificacionIVA


UUID_FACTURA = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
UUID_REP = "9f8e7d6c-5b4a-3210-fedc-ba9876543210"


def _base_kwargs(**overrides) -> dict:
    base = dict(
        uuid=UUID_FACTURA,
        rfc_emisor="EMP850101AB1",
        rfc_receptor="REC850101CD2",
        fecha="2025-01-15",
        subtotal=10000.0,
        iva=1600.0,
        total=11600.0,
        tipo=TipoFactura.INGRESO,
        categoria=ClasificacionIVA.CREDITABLE_100,
    )
    base.update(overrides)
    return base


def _factura_completa(**overrides) -> FacturaCFDI:
    kwargs = _base_kwargs(
        folio_factura="A-1042",
        forma_pago="03",  # Transferencia electrónica de fondos (c_FormaPago)
        metodo_pago="PUE",
        referencia_complemento_pago=UUID_REP,
    )
    kwargs.update(overrides)
    return FacturaCFDI(**kwargs)


# ---------------------------------------------------------------------------
# Los 4 campos existen y son opcionales por defecto (no rompen facturas
# antiguas que aún no tienen esta información capturada).
# ---------------------------------------------------------------------------

class TestCamposExisten:
    def test_factura_sin_campos_anexo7_sigue_siendo_valida(self):
        """El modelo no exige los 4 campos para *existir*; sólo para marcarse listo."""
        f = FacturaCFDI(**_base_kwargs())
        assert f.folio_factura is None
        assert f.forma_pago is None
        assert f.metodo_pago is None
        assert f.referencia_complemento_pago is None

    def test_factura_completa_guarda_los_4_campos(self):
        f = _factura_completa()
        assert f.folio_factura == "A-1042"
        assert f.forma_pago == "03"
        assert f.metodo_pago == "PUE"
        assert f.referencia_complemento_pago == UUID_REP


# ---------------------------------------------------------------------------
# folio_factura debe ser serie+folio, distinto del UUID/folio fiscal.
# ---------------------------------------------------------------------------

class TestFolioFacturaDistintoDelUUID:
    def test_folio_factura_igual_al_uuid_es_rechazado(self):
        with pytest.raises(ValidationError, match="folio_factura no puede ser igual al uuid"):
            FacturaCFDI(**_base_kwargs(folio_factura=UUID_FACTURA))

    def test_folio_factura_igual_al_uuid_case_insensitive_es_rechazado(self):
        with pytest.raises(ValidationError):
            FacturaCFDI(**_base_kwargs(folio_factura=UUID_FACTURA.upper()))

    def test_folio_factura_distinto_del_uuid_es_aceptado(self):
        f = FacturaCFDI(**_base_kwargs(folio_factura="SERIE-A FOLIO-1042"))
        assert f.folio_factura == "SERIE-A FOLIO-1042"

    def test_folio_factura_cadena_vacia_es_rechazado(self):
        with pytest.raises(ValidationError):
            FacturaCFDI(**_base_kwargs(folio_factura="   "))


# ---------------------------------------------------------------------------
# forma_pago / metodo_pago deben pertenecer al catálogo real del SAT
# (b2b_ai.cfdi.catalogs — c_FormaPago / c_MetodoPago, Anexo 20), no a un
# valor inventado.
# ---------------------------------------------------------------------------

class TestCatalogosOficiales:
    @pytest.mark.parametrize("codigo", ["01", "03", "04", "28", "99"])
    def test_forma_pago_valida_del_catalogo_sat(self, codigo):
        f = FacturaCFDI(**_base_kwargs(forma_pago=codigo))
        assert f.forma_pago == codigo

    def test_forma_pago_inventada_es_rechazada(self):
        with pytest.raises(ValidationError, match="c_FormaPago"):
            FacturaCFDI(**_base_kwargs(forma_pago="77"))

    @pytest.mark.parametrize("codigo", ["PUE", "PPD", "pue", "ppd"])
    def test_metodo_pago_valido_del_catalogo_sat(self, codigo):
        f = FacturaCFDI(**_base_kwargs(metodo_pago=codigo))
        assert f.metodo_pago == codigo.upper()

    def test_metodo_pago_inventado_es_rechazado(self):
        with pytest.raises(ValidationError, match="c_MetodoPago"):
            FacturaCFDI(**_base_kwargs(metodo_pago="CONTADO"))


# ---------------------------------------------------------------------------
# campos_faltantes_anexo7 / esta_lista_para_anexo7 / marcar_lista_para_anexo7
# ---------------------------------------------------------------------------

class TestListaParaAnexo7:
    def test_campos_faltantes_lista_los_4_cuando_ninguno_esta(self):
        f = FacturaCFDI(**_base_kwargs())
        faltantes = f.campos_faltantes_anexo7()
        assert set(faltantes) == {
            "folio_factura", "forma_pago", "metodo_pago", "referencia_complemento_pago",
        }

    @pytest.mark.parametrize("campo_presente", [
        "folio_factura", "forma_pago", "metodo_pago", "referencia_complemento_pago",
    ])
    def test_falta_un_solo_campo_no_esta_lista(self, campo_presente):
        """Con 3 de 4 campos, sigue sin poder marcarse lista (todos son requeridos)."""
        completos = dict(
            folio_factura="A-1042",
            forma_pago="03",
            metodo_pago="PUE",
            referencia_complemento_pago=UUID_REP,
        )
        del completos[campo_presente]
        f = FacturaCFDI(**_base_kwargs(**completos))
        assert f.esta_lista_para_anexo7 is False
        faltantes = f.campos_faltantes_anexo7()
        assert faltantes == [campo_presente]

    def test_esta_lista_para_anexo7_true_con_los_4_campos(self):
        f = _factura_completa()
        assert f.esta_lista_para_anexo7 is True
        assert f.campos_faltantes_anexo7() == []

    def test_marcar_lista_para_anexo7_retorna_true_cuando_completa(self):
        f = _factura_completa()
        assert f.marcar_lista_para_anexo7() is True

    def test_marcar_lista_para_anexo7_lanza_valueerror_si_falta_algo(self):
        f = FacturaCFDI(**_base_kwargs(folio_factura="A-1042"))
        with pytest.raises(ValueError, match="No se puede marcar la factura como lista"):
            f.marcar_lista_para_anexo7()

    def test_marcar_lista_para_anexo7_mensaje_incluye_campos_faltantes(self):
        f = FacturaCFDI(**_base_kwargs(folio_factura="A-1042", forma_pago="03"))
        with pytest.raises(ValueError) as exc_info:
            f.marcar_lista_para_anexo7()
        msg = str(exc_info.value)
        assert "metodo_pago" in msg
        assert "referencia_complemento_pago" in msg
        # Los que sí están presentes no deben aparecer como faltantes.
        assert "'folio_factura'" not in msg
        assert "'forma_pago'" not in msg


# ---------------------------------------------------------------------------
# iva_acreditable_efectivamente_pagado (LIVA Art. 5 fracc. III)
# ---------------------------------------------------------------------------

class TestIvaAcreditableEfectivamentePagado:
    def test_sin_referencia_complemento_pago_es_cero_aunque_haya_iva(self):
        """Sin el REP, el IVA nunca cuenta como 'efectivamente pagado'."""
        f = FacturaCFDI(**_base_kwargs(iva=1600.0, proporcionalidad=1.0))
        assert f.referencia_complemento_pago is None
        assert f.iva_acreditable_efectivamente_pagado == 0.0

    def test_sin_referencia_es_cero_incluso_con_los_otros_3_campos_completos(self):
        """No basta con folio_factura/forma_pago/metodo_pago: falta el REP."""
        f = FacturaCFDI(**_base_kwargs(
            iva=1600.0,
            folio_factura="A-1042",
            forma_pago="03",
            metodo_pago="PUE",
        ))
        assert f.iva_acreditable_efectivamente_pagado == 0.0

    def test_con_referencia_complemento_pago_se_reconoce_el_iva(self):
        f = _factura_completa(iva=1600.0, proporcionalidad=1.0)
        assert f.iva_acreditable_efectivamente_pagado == 1600.0

    def test_con_referencia_y_proporcionalidad_parcial(self):
        f = _factura_completa(iva=1600.0, proporcionalidad=0.5)
        assert f.iva_acreditable_efectivamente_pagado == 800.0

    def test_referencia_complemento_pago_en_blanco_no_cuenta(self):
        """Un valor en blanco no puede colarse por un validador laxo aguas arriba."""
        f = FacturaCFDI(**_base_kwargs(iva=1600.0))
        object.__setattr__(f, "referencia_complemento_pago", "   ")
        assert f.iva_acreditable_efectivamente_pagado == 0.0
