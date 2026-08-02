# -*- coding: utf-8 -*-
"""csv_importer.py — Importación de datos desde archivos CSV.

Parsea un CSV exportado de CONTPAQi (o generado a mano) y produce ítems de
migración normalizados para:

    - Clientes (RFC, razón social, régimen fiscal)
    - CFDIs (UUID, emisor, receptor, total, fecha, conceptos)
    - Cuentas bancarias (número, banco, saldo)
    - Empleados (RFC, nombre, salario, puesto)

El tipo de datos se infiere del nombre del archivo, de la primera columna, o
se fuerza explícitamente al instanciar la clase. Se soportan encabezados
variantes mediante alias (ver importers/base.py).
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any, Dict, List, Optional

from b2b_ai.features.data_migration.importers.base import (
    detect_sheet_type,
    normalize_row,
)
from b2b_ai.features.data_migration.models import (
    MigrationDataType,
    MigrationItem,
)

MAX_ROWS = 100_000

# Mapeo de tokens del nombre de archivo -> tipo de datos.
_FILENAME_TOKENS: List[tuple] = [
    (("cliente", "clientes"), MigrationDataType.CLIENTE),
    (("cuenta", "cuentas", "bancar", "banco"), MigrationDataType.CUENTA_BANCARIA),
    (("cfdi", "factura", "comprobante", "invoice"), MigrationDataType.CFDI),
    (("emplead", "nomina", "trabajador", "personal"), MigrationDataType.EMPLEADO),
]


class CSVImportError(Exception):
    """Error al abrir o parsear el archivo CSV."""


class ImportCSVData:
    """Parsea un CSV y produce ítems de migración normalizados."""

    def __init__(self, data_type: Optional[MigrationDataType] = None,
                 delimiter: str = ","):
        self.forced_type = data_type
        self.delimiter = delimiter

    # ------------------------------------------------------------------
    def parse_csv(self, path) -> List[MigrationItem]:
        """Abre el CSV y devuelve los ítems del tipo inferido."""
        file_path = Path(path)
        if not file_path.exists():
            raise CSVImportError(f"El archivo no existe: {file_path}")
        try:
            text = file_path.read_text(encoding="utf-8-sig", errors="replace")
        except Exception as exc:  # noqa: BLE001
            raise CSVImportError(f"No se pudo leer el CSV: {exc}") from exc
        return self.parse_text(text, filename=file_path.name)

    def parse_text(self, text: str, filename: str = "datos.csv") -> List[MigrationItem]:
        """Parsea el contenido CSV (str) y devuelve los ítems."""
        data_type = self.forced_type or self._infer_type(filename, text)
        if data_type is None:
            raise CSVImportError(
                "No se pudo inferir el tipo de datos del CSV. Pasa data_type "
                "explícitamente (cliente, cfdi, cuenta_bancaria, empleado)."
            )
        try:
            reader = csv.DictReader(io.StringIO(text), delimiter=self.delimiter)
            rows = list(reader)
        except Exception as exc:  # noqa: BLE001
            raise CSVImportError(f"CSV inválido: {exc}") from exc

        items: List[MigrationItem] = []
        for idx, row in enumerate(rows, start=2):  # fila 1 = encabezado
            if idx - 1 > MAX_ROWS:
                break
            if not row:
                continue
            if not any((v or "").strip() for v in row.values()):
                continue
            data = normalize_row(dict(row), data_type)
            items.append(MigrationItem(
                data_type=data_type,
                source=filename,
                row=idx,
                data=data,
            ))
        return items

    def _infer_type(self, filename: str, text: str) -> Optional[MigrationDataType]:
        name = (filename or "").lower()
        for tokens, data_type in _FILENAME_TOKENS:
            if any(tok in name for tok in tokens):
                return data_type
        # Fallback: primera línea como "hoja" (primera columna de cabecera).
        first_line = (text or "").splitlines()[0].lower() if text else ""
        return detect_sheet_type(first_line)
