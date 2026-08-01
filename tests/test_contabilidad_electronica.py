# -*- coding: utf-8 -*-
"""Tests — flujo completo de contabilidad electrónica (FASE 3)."""
import hashlib

import pytest

from b2b_ai.services.catalogo_cuentas import CatalogoCuentas
from b2b_ai.services.contabilidad_electronica import (ContabilidadElectronica,
                                                      ESTADOS)

ASIENTOS = [
    {"cuenta": "1202", "debe": "5800.00", "haber": "0", "fecha": "2026-07-03"},
    {"cuenta": "1101", "debe": "0", "haber": "5800.00", "fecha": "2026-07-03"},
    {"cuenta": "1101", "debe": "9000.00", "haber": "0", "fecha": "2026-07-10"},
    {"cuenta": "4100", "debe": "0", "haber": "9000.00", "fecha": "2026-07-10"},
]


def test_hash_sha1():
    mgr = ContabilidadElectronica()
    h = mgr.calcular_hash_sha1(b"hola")
    assert h == hashlib.sha1(b"hola").hexdigest()
    assert len(h) == 40


def test_flujo_completo_paquete():
    mgr = ContabilidadElectronica(catalogo=CatalogoCuentas(),
                                  rfc="DESP820101AB1",
                                  ejercicio=2026, mes=7)
    paquete = mgr.generar_paquete(ASIENTOS)
    # Contenido del paquete
    assert paquete["periodo"] == "2026-07"
    assert paquete["catalogo"]["cuentas"] > 20
    assert paquete["balanza"]["cuadrada"] is True
    assert paquete["estado"] == "listo_para_timbrar"
    # XML presentes y con XML válido
    assert "<?xml" in paquete["catalogo"]["xml"]
    assert "<?xml" in paquete["balanza"]["xml"]
    assert paquete["catalogo"]["sha1"] == mgr.calcular_hash_sha1(
        paquete["catalogo"]["xml"].encode("utf-8"))


def test_estados_avanzan():
    mgr = ContabilidadElectronica(catalogo=CatalogoCuentas(),
                                  ejercicio=2026, mes=7)
    assert mgr.estado_actual() == "borrador"
    mgr.marcar_listo_para_timbrar()
    assert mgr.estado_actual() == "listo_para_timbrar"
    mgr.marcar_timbrado()
    assert mgr.estado_actual() == "timbrado"
    mgr.marcar_enviado()
    assert mgr.estado_actual() == "enviado"


def test_transicion_invalida():
    mgr = ContabilidadElectronica(catalogo=CatalogoCuentas(),
                                  ejercicio=2026, mes=7)
    # No se puede timbrar desde borrador (falta listo_para_timbrar).
    with pytest.raises(ValueError):
        mgr.marcar_timbrado()


def test_resumen_mensual():
    mgr = ContabilidadElectronica(catalogo=CatalogoCuentas(),
                                  rfc="DESP820101AB1",
                                  ejercicio=2026, mes=7)
    paquete = mgr.generar_paquete(ASIENTOS)
    resumen = mgr.generar_resumen_mensual(paquete=paquete)
    assert resumen["periodo"] == "2026-07"
    assert resumen["rfc"] == "DESP820101AB1"
    assert resumen["total_debe"] == "14800.00"
    assert resumen["cuadrada"] is True
    assert resumen["estado"] == "listo_para_timbrar"


def test_estados_constantes():
    assert ESTADOS == ("borrador", "listo_para_timbrar", "timbrado", "enviado")


def test_persistencia_db(tmp_db):
    """Con DB, el paquete se persiste y los estados se reflejan en la DB."""
    tenant = tmp_db.create_tenant("Despacho Test")
    mgr = ContabilidadElectronica(catalogo=CatalogoCuentas(), db=tmp_db,
                                  tenant_id=tenant, rfc="DESP820101AB1",
                                  ejercicio=2026, mes=7)
    paquete = mgr.generar_paquete(ASIENTOS)
    assert paquete["estado"] == "listo_para_timbrar"
    rows = tmp_db.list_paquetes_contabilidad(tenant_id=tenant)
    assert len(rows) == 1
    assert rows[0]["estado"] == "listo_para_timbrar"
    # Avanzar estado y verificar que se refleja en DB.
    mgr.marcar_timbrado()
    rows = tmp_db.list_paquetes_contabilidad(tenant_id=tenant)
    assert rows[0]["estado"] == "timbrado"
    # El payload guardado contiene el XML de la balanza.
    pkg = tmp_db.get_paquete_contabilidad(rows[0]["id"], tenant_id=tenant)
    assert "<?xml" in pkg["payload"]["balanza"]["xml"]


def test_persistencia_cuentas_y_balanza(tmp_db):
    tenant = tmp_db.create_tenant("Despacho Test")
    cta_id = tmp_db.upsert_cuenta_contable(tenant, "1101", "BANCOS", 3, "D", "")
    assert tmp_db.upsert_cuenta_contable(tenant, "1101", "BANCOS", 3, "D", "")
    assert len(tmp_db.list_cuentas_contables(tenant_id=tenant)) == 1
    tmp_db.upsert_balanza_mensual(tenant, "2026-07", cta_id,
                                  "0.00", "9000.00", "5800.00", "3200.00")
    bal = tmp_db.list_balanzas_mensuales(tenant_id=tenant, periodo="2026-07")
    assert len(bal) == 1
    assert bal[0]["debe"] == "9000.00"
