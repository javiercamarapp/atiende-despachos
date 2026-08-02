# -*- coding: utf-8 -*-
"""
test_nomina_fixes.py — Regression tests para los 6 bugs P1 del módulo
Nómina Completa (QA 187).

Cubre:
  P1-1  INFONAVIT patronal NO se descuenta del salario neto del trabajador.
  P1-2  Tasas IMSS correctas 2026 con SBC topado a 25 UMA (LSS art. 28).
  P1-3  Generación real de XML CFDI Nómina 4.0 conforme al XSD del SAT.
  P1-4  IDOR multi-tenant: payslip/summary usan tenant de auth, no del query.
  P1-5  Edge cases: aguinaldo (art. 87 LFT) y prima vacacional (art. 80 LFT).
  P1-6  Tablas ISR parametrizables por ejercicio fiscal (2026 vigente).
"""
from __future__ import annotations

import pytest

from b2b_ai.features.nomina_completa.service import (
    calculate_taxes,
    process_payroll,
    generate_payslip,
    generate_cfdi_nomina_xml,
    calculate_aguinaldo,
    calculate_prima_vacacional,
    _sbc_diario_topado,
    _UMA_DIARIA_2026,
)
from b2b_ai.features.nomina_completa.routes import build_nomina_completa_router


# ---------------------------------------------------------------------------
# P1-1: INFONAVIT patronal es gasto del patrón, no deducción al trabajador
# ---------------------------------------------------------------------------
class TestP1_1InfonavitNoDescontado:
    def test_deducciones_no_incluyen_infonavit(self):
        """Las deducciones del trabajador = ISR + IMSS obrero, SIN INFONAVIT."""
        period = {"month": 7, "year": 2026, "dias_pagados": 30}
        employees = [{
            "employee_id": "E1", "nombre": "Juan", "salario_bruto": 20000,
            "percepciones": 0, "salario_diario": 666.67,
        }]
        result = process_payroll(period, employees, tenant_id=1)
        emp = result.employees[0]
        expected_deducciones = round(emp.taxes.isr + emp.taxes.imss_obrero, 2)
        assert emp.deducciones == pytest.approx(expected_deducciones, abs=0.01)
        # El INFONAVIT patronal sí se calcula (como costo del patrón)…
        assert emp.taxes.infonavit > 0
        # …pero no forma parte de las deducciones al trabajador.
        assert emp.deducciones < emp.taxes.isr + emp.taxes.imss_obrero + emp.taxes.infonavit

    def test_neto_solo_resta_isr_e_imss_obrero(self):
        period = {"month": 7, "year": 2026, "dias_pagados": 30}
        employees = [{
            "employee_id": "E1", "nombre": "Juan", "salario_bruto": 20000,
            "percepciones": 0, "salario_diario": 666.67,
        }]
        result = process_payroll(period, employees, tenant_id=1)
        emp = result.employees[0]
        expected_neto = round(
            20000 - (emp.taxes.isr + emp.taxes.imss_obrero), 2
        )
        assert emp.neto == pytest.approx(expected_neto, abs=0.01)

    def test_payslip_total_deducciones_sin_infonavit(self):
        """El recibo reporta INFONAVIT como aportación patronal (es_patronal)."""
        taxes = calculate_taxes(20000, salary_per_day=0)
        payslip = generate_payslip({
            "employee": {"employee_id": "E1", "nombre": "Juan",
                         "puesto": "Dev", "departamento": "TI"},
            "period": {"month": 7, "year": 2026, "dias_pagados": 30},
            "taxes": taxes.to_dict(),
            "sueldo_base": 20000, "bonos": 0, "prestaciones": 0,
            "subtotal": 20000, "neto": 17365.29,
        })
        d = payslip["deducciones"]
        assert d["total"] == pytest.approx(taxes.isr + taxes.imss_obrero, abs=0.01)
        assert d["es_patronal"]["infonavit"] is True


# ---------------------------------------------------------------------------
# P1-2: Tasas IMSS correctas 2026 con SBC topado a 25 UMA
# ---------------------------------------------------------------------------
class TestP1_2TasasIMSS:
    def test_sbc_topado_a_25_uma(self):
        """El SBC no puede exceder 25 UMA diarias (LSS art. 28)."""
        max_sbc = round(_UMA_DIARIA_2026 * 25, 2)
        assert _sbc_diario_topado(5000) == max_sbc
        assert _sbc_diario_topado(100) == 100

    def test_tasas_obrero_y_patronal(self):
        """Cuota obrera 1.25% y patronal 14.25% sobre SBC × días."""
        taxes = calculate_taxes(salary=20000, salary_per_day=0)
        sbc = min(20000 / 30, round(_UMA_DIARIA_2026 * 25, 2))
        assert taxes.imss_obrero == pytest.approx(sbc * 30 * 0.0125, abs=0.5)
        assert taxes.imss_patronal == pytest.approx(sbc * 30 * 0.1425, abs=0.5)


# ---------------------------------------------------------------------------
# P1-3: XML real de CFDI Nómina 4.0 conforme al XSD del SAT
# ---------------------------------------------------------------------------
class TestP1_3CFDIXMLReal:
    def _data(self):
        return {
            "emisor": {"rfc": "EMP850101AB1", "nombre": "Empresa SA",
                       "regimen_fiscal": "601"},
            "receptor": {"rfc": "JUAN800101T1A", "nombre": "Juan Perez",
                         "regimen_fiscal": "605"},
            "period": {"year": 2026, "month": 7, "dias_pagados": 30},
            "taxes": {"isr": 2384.71, "imss_obrero": 250.0, "infonavit": 1000.0},
            "subtotal": 20000.0, "total": 17365.29,
        }

    def test_genera_xml_cfdi_4(self):
        xml = generate_cfdi_nomina_xml(self._data())
        assert "http://www.sat.gob.mx/cfd/4" in xml
        assert "Comprobante" in xml
        assert 'Version="4.0"' in xml

    def test_incluye_complemento_nomina_12(self):
        xml = generate_cfdi_nomina_xml(self._data())
        assert "Nomina" in xml
        assert 'Version="1.2"' in xml
        assert "Percepciones" in xml

    def test_incluye_rfc_emisor_y_receptor(self):
        xml = generate_cfdi_nomina_xml(self._data())
        assert "EMP850101AB1" in xml
        assert "JUAN800101T1A" in xml

    def test_rfc_vacio_lanza_error(self):
        data = self._data()
        data["emisor"]["rfc"] = ""
        with pytest.raises(ValueError):
            generate_cfdi_nomina_xml(data)


# ---------------------------------------------------------------------------
# P1-4: IDOR multi-tenant payslip/summary
# ---------------------------------------------------------------------------
class TestP1_4IDOR:
    def test_summary_deriva_tenant_de_auth(self):
        """El tenant viene de auth_info, no del query param del cliente."""
        app = _build_app(auth_info={"tenant_id": 42})
        # Procesar nómina del tenant 42
        client = _make_client(app)
        client.post("/nomina-completa/process", json={
            "period": {"month": 7, "year": 2026, "dias_pagados": 30},
            "employees": [{"employee_id": "E1", "nombre": "Juan",
                           "salario_bruto": 20000, "percepciones": 0}],
            "tenant_id": 42,
        })
        # El query param tenant_id=1 es IGNORADO: se usa auth_info[tenant_id]=42.
        resp = client.get(
            "/nomina-completa/summary",
            params={"month": 7, "year": 2026, "tenant_id": 1},
        )
        assert resp.status_code == 200
        assert resp.json()["summary"]["employee_count"] == 1

    def test_summary_tenant_ausente_no_lee_otro_tenant(self):
        app = _build_app(auth_info={"tenant_id": 1})
        client = _make_client(app)
        client.post("/nomina-completa/process", json={
            "period": {"month": 7, "year": 2026, "dias_pagados": 30},
            "employees": [{"employee_id": "E1", "nombre": "Juan",
                           "salario_bruto": 20000, "percepciones": 0}],
            "tenant_id": 1,
        })
        # auth tenant = 1, pide tenant=99 → 404 (nunca ve datos de 99)
        resp = client.get(
            "/nomina-completa/summary",
            params={"month": 7, "year": 2026, "tenant_id": 99},
        )
        assert resp.status_code == 200  # tenant autorizado es 1, no 99
        assert resp.json()["summary"]["employee_count"] == 1


def _build_app(auth_info: dict):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    def require_api_key():
        return dict(auth_info)

    app = FastAPI()
    router = build_nomina_completa_router(require_api_key=require_api_key)
    app.include_router(router)
    return app


def _make_client(app):
    from fastapi.testclient import TestClient
    return TestClient(app)


# ---------------------------------------------------------------------------
# P1-5: Edge cases — aguinaldo (art. 87) y prima vacacional (art. 80)
# ---------------------------------------------------------------------------
class TestP1_5EdgeCases:
    def test_aguinaldo_minimo_legal(self):
        """Aguinaldo = al menos 15 días de salario (LFT art. 87)."""
        assert calculate_aguinaldo(666.67) == pytest.approx(666.67 * 15, abs=0.01)

    def test_aguinaldo_cero_no_negativo(self):
        assert calculate_aguinaldo(0) == 0
        assert calculate_aguinaldo(-100) == 0

    def test_prima_vacacional_25(self):
        """Prima vacacional = 25% de los días de vacaciones (LFT art. 80)."""
        assert calculate_prima_vacacional(666.67, 6) == pytest.approx(
            666.67 * 6 * 0.25, abs=0.01
        )

    def test_prima_vacacional_primer_ano_6_dias(self):
        assert calculate_prima_vacacional(1000, 6, 0.25) == pytest.approx(1500, abs=0.01)


# ---------------------------------------------------------------------------
# P1-6: Tablas ISR parametrizables por ejercicio fiscal
# ---------------------------------------------------------------------------
class TestP1_6ISRTablas:
    def test_tabla_2026_vigente(self):
        from b2b_ai.fiscal_tables import get_isr_table
        tabla = get_isr_table(2026, "monthly")
        assert len(tabla) > 0
        # Tope marginal 35% para el último tramo.
        assert tabla[-1][3] == 0.35

    def test_isr_usa_tabla_vigente(self):
        """calculate_isr de compliance usa la tabla 2026 (no 0 para ingresos normales)."""
        from b2b_ai.features.compliance import calculate_isr
        assert calculate_isr(20000) > 0
        assert calculate_isr(0) == 0
