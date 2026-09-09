# -*- coding: utf-8 -*-
"""invoices: subtotal/iva/total de TEXT a NUMERIC(18,2)

Revision ID: 0014_invoices_money_numeric
Revises: 0013_polizas_bloqueadas
Create Date: 2026-09-08

Riesgo real de correctitud en un sistema fiscal/contable: `invoices.subtotal`,
`invoices.iva` e `invoices.total` se declararon TEXT en 0001_initial. TEXT no
impide guardar "" (vacío), "N/A" o cualquier basura, y agregaciones como
`SUM(CAST(total AS REAL))` (b2b_ai/db/db.py::invoice_stats) truncan/ignoran
esos valores en silencio en vez de fallar de forma ruidosa. Esta migración
los convierte a NUMERIC(18,2) -- misma precisión que
`lineas_poliza_migradas.debe/haber` (0013_polizas_bloqueadas).

Antes de tocar el esquema, valida que CADA valor no vacío de las tres
columnas sea un número decimal válido (regex ``^-?[0-9]+(\\.[0-9]+)?$`` tras
trim). Si encuentra basura, la migración ABORTA con RuntimeError listando
hasta 20 filas ofensoras (id, columna, valor) -- nunca migra a ciegas ni
descarta datos fiscales en silencio; corregir esos datos es una decisión de
negocio que le toca a un humano, no a esta migración.

Un valor vacío/blank se trata como NULL vía ``NULLIF(trim(col), '')`` -- la
columna ya era ``nullable=True`` desde 0001_initial, así que no se relaja
ninguna restricción; simplemente se deja de fingir que "" es un monto.
"""
from __future__ import annotations

import re

import sqlalchemy as sa
from alembic import op

revision = "0014_invoices_money_numeric"
down_revision = "0013_polizas_bloqueadas"
branch_labels = None
depends_on = None

_MONEY_COLS = ("subtotal", "iva", "total")
_NUMERIC_RE = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")
_MAX_SAMPLE = 20


def _find_invalid_rows(conn) -> list[tuple[int, str, str]]:
    """Filas de `invoices` cuyo subtotal/iva/total no vacío no es un número.

    Devuelve hasta `_MAX_SAMPLE` tuplas (id, columna, valor_crudo) para que
    el mensaje de error sea accionable. La validación real (qué SÍ cuenta
    como número) se hace en Python con `_NUMERIC_RE`, no confiando en un
    solo motor de regex; la consulta SQL solo trae candidatos.
    """
    candidate_clauses = " OR ".join(
        f"(trim({col}) IS NOT NULL AND trim({col}) <> '')" for col in _MONEY_COLS
    )
    rows = conn.execute(sa.text(
        f"SELECT id, subtotal, iva, total FROM invoices "
        f"WHERE {candidate_clauses} ORDER BY id"
    )).fetchall()

    bad: list[tuple[int, str, str]] = []
    for row in rows:
        row_id, subtotal, iva, total = row
        for col, val in (("subtotal", subtotal), ("iva", iva), ("total", total)):
            if val is None:
                continue
            v = val.strip()
            if v == "" or _NUMERIC_RE.match(v):
                continue
            bad.append((row_id, col, val))
            if len(bad) >= _MAX_SAMPLE:
                return bad
    return bad


def upgrade() -> None:
    conn = op.get_bind()

    bad = _find_invalid_rows(conn)
    if bad:
        sample = "; ".join(
            f"invoice id={row_id} {col}={val!r}" for row_id, col, val in bad
        )
        raise RuntimeError(
            "ABORTADO: invoices.subtotal/iva/total tiene valores no "
            "numéricos existentes -- no se puede convertir a NUMERIC(18,2) "
            "sin decidir qué hacer con ellos (¿NULL? ¿corregirlos a mano? "
            "¿son en realidad basura de un bug previo?). "
            f"No se alteró el esquema. Filas afectadas (hasta {_MAX_SAMPLE}): "
            f"{sample}"
        )

    for col in _MONEY_COLS:
        op.alter_column(
            "invoices",
            col,
            type_=sa.Numeric(18, 2),
            existing_type=sa.Text(),
            existing_nullable=True,
            postgresql_using=f"NULLIF(trim({col}), '')::numeric(18,2)",
        )


def downgrade() -> None:
    for col in _MONEY_COLS:
        op.alter_column(
            "invoices",
            col,
            type_=sa.Text(),
            existing_type=sa.Numeric(18, 2),
            existing_nullable=True,
            postgresql_using=f"{col}::text",
        )
