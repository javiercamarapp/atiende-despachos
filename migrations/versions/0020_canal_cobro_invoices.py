# -*- coding: utf-8 -*-
"""invoices/outstanding_invoices: agrega canal_cobro / id_terminal

Revision ID: 0020_canal_cobro_invoices
Revises: 0019_reconciliation_group_matches
Create Date: 2026-09-11

REQ-CONC-016 (`docs/BLUEPRINT-AGENTES-FISCALES.md`, matriz REQ-CONC).

`bank_reconciliation.py::_pass_group` cruza dicts con forma libre
(folio_fiscal + total + fecha, ver docstring de `_pass_group`); las dos
tablas reales que alimentan esos dicts en el flujo persistido son
`invoices` (Invoice: facturas emitidas, 0001_initial) y
`outstanding_invoices` (Collection: cartera de cobranza pendiente,
0001_initial + 0005_outstanding_unique) -- confirmado leyendo
`b2b_ai/db/db.py::insert_invoice/list_invoices/get_invoice` (usa
`_INVOICE_COLUMNS`, la misma lista para lectura y escritura) y
`upsert_outstanding_invoice/list_outstanding_invoices`.

Ambas columnas nuevas son NULLABLE y sin default distinto de NULL: dato
opcional que, cuando existe, acota el filtrado de candidatos de
`_pass_group` por canal (REQ-CONC-015); cuando no existe (todo el
histórico ya cargado antes de esta migración), el filtro se abstiene
-- no rompe ni reinterpreta filas existentes.

  - `canal_cobro`: terminal | spei | cheque | efectivo (TEXT libre, sin
    CHECK -- validado en la capa de aplicación, mismo patrón que
    `estado`/`tipo_match` de `mapeos_migracion_catalogo`, 0018).
  - `id_terminal`: identificador de terminal/cuenta destino (TEXT, p. ej.
    el merchant/terminal id de un agregador como Clip). Nunca una
    credencial -- solo un identificador de enrutamiento.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0020_canal_cobro_invoices"
down_revision = "0019_recon_group_matches"
branch_labels = None
depends_on = None

_COLUMNS = ("canal_cobro", "id_terminal")
_TABLES = ("invoices", "outstanding_invoices")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("canal_cobro", sa.Text(),
                                       nullable=True))
        op.add_column(table, sa.Column("id_terminal", sa.Text(),
                                       nullable=True))
    op.create_index("idx_invoices_canal_cobro", "invoices",
                    ["tenant_id", "canal_cobro"])
    op.create_index("idx_outstanding_canal_cobro", "outstanding_invoices",
                    ["tenant_id", "canal_cobro"])


def downgrade() -> None:
    op.drop_index("idx_outstanding_canal_cobro",
                  table_name="outstanding_invoices")
    op.drop_index("idx_invoices_canal_cobro", table_name="invoices")
    for table in _TABLES:
        for col in reversed(_COLUMNS):
            op.drop_column(table, col)
