# -*- coding: utf-8 -*-
"""
test_batch_processors.py — Tests de los procesadores batch de CFDIs.

Cubre:
  - bulk_parser.extract_cfdi_pairs : extracción de XML desde un ZIP
  - bulk_parser.parse_cfdi_document : parseo de un CFDI (RFC, total, UUID,
    fecha, conceptos)
  - bulk_parser.parse_cfdi_pairs : parseo en lote (ok / skip / raise)
  - aggregator.aggregate_results : resumen total/processed/failed/by_rfc
  - aggregator.summarize_batch_job : resumen a partir de un BatchJob
"""
from __future__ import annotations

import io
import zipfile

import pytest

from b2b_ai.features.batch.models import BatchItem, BatchItemStatus, BatchJob
from b2b_ai.features.batch.processors.aggregator import (
    aggregate_results,
    summarize_batch_job,
)
from b2b_ai.features.batch.processors.bulk_parser import (
    extract_cfdi_pairs,
    parse_cfdi_document,
    parse_cfdi_pairs,
)


SAMPLE_CFDI = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
    Version="4.0" Serie="D" Folio="100"
    Fecha="2026-07-03T10:00:00"
    FormaPago="03" MetodoPago="PUE" Moneda="MXN"
    TipoDeComprobante="I" Exportacion="01"
    LugarExpedicion="06600" SubTotal="1000.00" Descuento="0.00" Total="1160.00">
    <cfdi:Emisor Rfc="PAP850101JKL" Nombre="PAPELERIA TEST" RegimenFiscal="601"/>
    <cfdi:Receptor Rfc="XAXX010101000" Nombre="RECEPTOR TEST"
        DomicilioFiscalReceptor="06600" RegimenFiscalReceptor="603" UsoCFDI="G03"/>
    <cfdi:Conceptos>
        <cfdi:Concepto ClaveProdServ="44122000" Cantidad="1"
            ClaveUnidad="E48" Unidad="Servicio"
            Descripcion="Papeleria y articulos de oficina"
            ValorUnitario="1000.00" Importe="1000.00" ObjetoImp="02">
            <cfdi:Impuestos>
                <cfdi:Traslados>
                    <cfdi:Traslado Base="1000.00" Impuesto="002" TipoFactor="Tasa"
                        TasaOCuota="0.160000" Importe="160.00"/>
                </cfdi:Traslados>
            </cfdi:Impuestos>
        </cfdi:Concepto>
    </cfdi:Conceptos>
    <cfdi:Impuestos TotalImpuestosTrasladados="160.00">
        <cfdi:Traslados>
            <cfdi:Traslado Base="1000.00" Impuesto="002" TipoFactor="Tasa"
                TasaOCuota="0.160000" Importe="160.00"/>
        </cfdi:Traslados>
    </cfdi:Impuestos>
    <cfdi:Complemento>
        <tfd:TimbreFiscalDigital Version="1.1"
            UUID="550e8400-e29b-41d4-a716-446655440000"
            FechaTimbrado="2026-07-03T10:01:00" RfcProvCertif="SAT970701NN3"
            SelloCFD="AABBCC" NoCertificado="00001000000000000000" SelloSAT="DDEEFF"/>
    </cfdi:Complemento>
</cfdi:Comprobante>"""

BAD_CFDI = "<xml>no es un cfdi</xml>"


def make_zip(*xmls, names=None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i, xml in enumerate(xmls):
            name = (names[i] if names and i < len(names) else f"cfdi_{i}.xml")
            zf.writestr(name, xml)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# bulk_parser.extract_cfdi_pairs
# ---------------------------------------------------------------------------


class TestExtractCfdiPairs:
    def test_extracts_xml_from_zip(self):
        pairs = extract_cfdi_pairs(make_zip(SAMPLE_CFDI, SAMPLE_CFDI), "lote.zip")
        assert len(pairs) == 2
        assert all(n.endswith(".xml") for n, _ in pairs)
        assert all(SAMPLE_CFDI in content for _, content in pairs)

    def test_ignores_non_xml_entries(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("cfdi_0.xml", SAMPLE_CFDI)
            zf.writestr("readme.txt", "not xml")
            zf.writestr("nested/", "")
        pairs = extract_cfdi_pairs(buf.getvalue())
        assert [n for n, _ in pairs] == ["cfdi_0.xml"]

    def test_empty_zip_raises(self):
        with pytest.raises(ValueError):
            extract_cfdi_pairs(b"", "empty.zip")

    def test_bad_zip_raises(self):
        with pytest.raises(ValueError):
            extract_cfdi_pairs(b"not a zip", "file.zip")

    def test_zip_without_xml_raises(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("doc.txt", "hello")
        with pytest.raises(ValueError):
            extract_cfdi_pairs(buf.getvalue())


# ---------------------------------------------------------------------------
# bulk_parser.parse_cfdi_document
# ---------------------------------------------------------------------------


class TestParseCfdiDocument:
    def test_extracts_key_fields(self):
        parsed = parse_cfdi_document(SAMPLE_CFDI)
        assert parsed["rfc_emisor"] == "PAP850101JKL"
        assert parsed["rfc_receptor"] == "XAXX010101000"
        assert float(parsed["total"]) == 1160.0
        assert parsed["uuid"] == "550e8400-e29b-41d4-a716-446655440000"
        assert parsed["fecha"].startswith("2026-07-03")
        assert parsed["conceptos_resumen"] == ["Papeleria y articulos de oficina"]

    def test_bad_cfdi_raises_cfdi_error(self):
        from b2b_ai.cfdi.parser import CFDIError
        with pytest.raises(CFDIError):
            parse_cfdi_document(BAD_CFDI)


# ---------------------------------------------------------------------------
# bulk_parser.parse_cfdi_pairs
# ---------------------------------------------------------------------------


class TestParseCfdiPairs:
    def test_all_success(self):
        results = parse_cfdi_pairs([
            ("a.xml", SAMPLE_CFDI),
            ("b.xml", SAMPLE_CFDI),
        ])
        assert len(results) == 2
        assert all(r["ok"] for r in results)
        assert results[0]["parsed"]["rfc_emisor"] == "PAP850101JKL"

    def test_skip_on_error(self):
        results = parse_cfdi_pairs(
            [("ok.xml", SAMPLE_CFDI), ("bad.xml", BAD_CFDI)],
            on_error="skip",
        )
        assert len(results) == 2
        assert results[0]["ok"] is True
        assert results[1]["ok"] is False
        assert results[1]["error"]

    def test_raise_on_error_default(self):
        with pytest.raises(Exception):
            parse_cfdi_pairs([("bad.xml", BAD_CFDI)])

    def test_invalid_on_error_value(self):
        with pytest.raises(ValueError):
            parse_cfdi_pairs([("ok.xml", SAMPLE_CFDI)], on_error="bogus")


# ---------------------------------------------------------------------------
# aggregator.aggregate_results
# ---------------------------------------------------------------------------


class TestAggregateResults:
    def test_aggregates_counts_and_amounts(self):
        ok_a = {"ok": True, "parsed": {"rfc_emisor": "PAP850101JKL", "total": "1160.00"}}
        ok_b = {"ok": True, "parsed": {"rfc_emisor": "PAP850101JKL", "total": "500.00"}}
        ok_c = {"ok": True, "parsed": {"rfc_emisor": "AAA010101AAA", "total": "100.00"}}
        fail = {"ok": False, "error": "boom"}
        summary = aggregate_results([ok_a, ok_b, ok_c, fail])
        assert summary["total"] == 4
        assert summary["processed"] == 3
        assert summary["failed"] == 1
        assert summary["total_amount"] == 1760.0
        assert summary["by_rfc"]["PAP850101JKL"]["count"] == 2
        assert summary["by_rfc"]["PAP850101JKL"]["amount"] == 1660.0
        assert summary["by_rfc"]["AAA010101AAA"]["count"] == 1

    def test_uses_emisor_fallback(self):
        # Forma de parse_cfdi_4 sin rfc_emisor a nivel raíz
        parsed = {"emisor": {"rfc": "XYZ010101XYZ"}, "total": 10.0}
        summary = aggregate_results([{"ok": True, "parsed": parsed}])
        assert summary["by_rfc"]["XYZ010101XYZ"]["count"] == 1

    def test_empty_list(self):
        summary = aggregate_results([])
        assert summary == {
            "total": 0, "processed": 0, "failed": 0,
            "total_amount": 0.0, "by_rfc": {},
        }


# ---------------------------------------------------------------------------
# aggregator.summarize_batch_job
# ---------------------------------------------------------------------------


class TestSummarizeBatchJob:
    def test_summarizes_job_items(self):
        job = BatchJob(
            success_count=2,
            failed_count=1,
            items=[
                BatchItem(
                    filename="a.xml",
                    status=BatchItemStatus.SUCCESS,
                    total=1160.0,
                    result={"emisor": {"rfc": "PAP850101JKL"}},
                ),
                BatchItem(
                    filename="b.xml",
                    status=BatchItemStatus.SUCCESS,
                    total=500.0,
                    result={"emisor": {"rfc": "PAP850101JKL"}},
                ),
                BatchItem(
                    filename="c.xml",
                    status=BatchItemStatus.FAILED,
                    error="boom",
                ),
            ],
        )
        summary = summarize_batch_job(job)
        assert summary["processed"] == 2
        assert summary["failed"] == 1
        assert summary["total_amount"] == 1660.0
        assert summary["by_rfc"]["PAP850101JKL"]["count"] == 2

    def test_empty_job(self):
        summary = summarize_batch_job(BatchJob(items=[]))
        assert summary["processed"] == 0
        assert summary["failed"] == 0
