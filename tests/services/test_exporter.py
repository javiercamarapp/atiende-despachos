# -*- coding: utf-8 -*-
"""Tests for b2b_ai/services/exporter.py — CSV, XLSX, PDF export."""
import pytest
from b2b_ai.services.exporter import (
    export_csv, export_xlsx, export_pdf, export, _headers,
)


class TestHeaders:
    def test_basic(self):
        data = [{"a": 1, "b": 2}]
        assert _headers(data) == ["a", "b"]

    def test_empty(self):
        assert _headers([]) == []

    def test_extra_keys_in_later_rows(self):
        data = [{"a": 1}, {"a": 2, "c": 3}]
        h = _headers(data)
        assert "c" in h


class TestExportCSV:
    def test_basic(self):
        data = [{"name": "Test", "value": 100}]
        csv_bytes = export_csv(data)
        assert isinstance(csv_bytes, bytes)
        text = csv_bytes.decode("utf-8")
        assert "name" in text
        assert "Test" in text

    def test_empty_data(self):
        csv_bytes = export_csv([])
        assert isinstance(csv_bytes, bytes)

    def test_none_values(self):
        data = [{"a": None, "b": "hello"}]
        csv_bytes = export_csv(data)
        text = csv_bytes.decode("utf-8")
        assert "hello" in text

    def test_columns_override(self):
        data = [{"a": 1, "b": 2, "c": 3}]
        csv_bytes = export_csv(data, columns=["a", "c"])
        text = csv_bytes.decode("utf-8")
        assert "a" in text
        assert "c" in text
        assert "b" not in text.split("\n")[0]


class TestExportXLSX:
    def test_basic(self):
        data = [{"name": "Test", "value": 100}]
        xlsx_bytes = export_xlsx(data)
        assert isinstance(xlsx_bytes, bytes)
        assert len(xlsx_bytes) > 100

    def test_valid_zip(self):
        import zipfile, io
        data = [{"a": 1}]
        xlsx_bytes = export_xlsx(data)
        with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as z:
            names = z.namelist()
            assert "xl/workbook.xml" in names
            assert "xl/worksheets/sheet1.xml" in names

    def test_title_in_workbook(self):
        data = [{"a": 1}]
        xlsx_bytes = export_xlsx(data, title="Mi Reporte")
        import zipfile, io
        with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as z:
            wb = z.read("xl/workbook.xml").decode("utf-8")
            assert "Mi Reporte" in wb


class TestExportPDF:
    def test_basic(self):
        data = [{"name": "Test", "value": 100}]
        pdf_bytes = export_pdf(data)
        assert isinstance(pdf_bytes, bytes)
        assert pdf_bytes.startswith(b"%PDF")

    def test_empty_data(self):
        pdf_bytes = export_pdf([])
        assert pdf_bytes.startswith(b"%PDF")

    def test_title_in_pdf(self):
        data = [{"a": 1}]
        pdf_bytes = export_pdf(data, title="My Title")
        text = pdf_bytes.decode("latin-1", errors="replace")
        assert "My Title" in text


class TestExport:
    def test_csv(self):
        data = [{"a": 1}]
        bytes_out, mt = export(data, "csv")
        assert mt == "text/csv"

    def test_xlsx(self):
        data = [{"a": 1}]
        bytes_out, mt = export(data, "xlsx")
        assert "spreadsheetml" in mt

    def test_pdf(self):
        data = [{"a": 1}]
        bytes_out, mt = export(data, "pdf")
        assert mt == "application/pdf"

    def test_invalid_format(self):
        with pytest.raises(ValueError, match="Formato no soportado"):
            export([], "xml")

    def test_case_insensitive(self):
        data = [{"a": 1}]
        bytes_out, mt = export(data, "CSV")
        assert mt == "text/csv"
