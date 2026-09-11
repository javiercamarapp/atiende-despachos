# -*- coding: utf-8 -*-
"""reconciliation_group_matches: persistencia de decisiones de _pass_group

Revision ID: 0019_recon_group_matches
Revises: 0018_mapeos_migracion_catalogo
Create Date: 2026-09-11

REQ-CONC-013 (`docs/BLUEPRINT-AGENTES-FISCALES.md`, matriz REQ-CONC).

Contexto verificado antes de escribir esta migración (para no duplicar
columnas ya existentes, como pide el requisito): se revisó el esquema real
de `migrations/versions/0005b_bank_reconciliation_state.py`
(`bank_transactions`/`bank_confirmations`, revision id
`0005_bank_reconciliation_state`). Esas dos tablas persisten los
movimientos SUBIDOS y las confirmaciones MANUALES -- ninguna de las dos
tiene columnas para `group_id`, `naturaleza`, `confidence`, `estado` ni
`score`, así que no hay solape: `reconciliation_group_matches` es una
tabla nueva, complementaria, pensada específicamente para las decisiones
que produce `_pass_group()` (REQ-CONC-003/008/009, `bank_reconciliation.py`)
-- auto-confirmadas, sugeridas (ambigüedad real o score bajo, ADR-2) o
sin_conciliar (ningún candidato en la banda, ADR-1, REQ-CONC-014).

Una fila por (transaction_id, invoice_ref) del grupo -- igual granularidad
que las filas que ya arma `_build_group_match()` en memoria (una por
factura del subconjunto, todas compartiendo `group_id`/`transaction_id`) --
para poder reconstruir exactamente el mismo resultado que ve hoy el
usuario en el reporte, ahora persistido y consultable entre requests
(mismo problema de "más de un worker" que documenta 0005b para
`bank_transactions`/`bank_confirmations`).

Columnas del criterio de aceptación (REQ-CONC-013), en el orden literal
del requisito: `group_id`, `transaction_id`, `tenant_id`, `naturaleza`,
`confidence`, `estado`, `score`, `aprobado_por`, `aprobado_en`. Se agrega
además `invoice_ref` (no está en el texto del requisito, pero sin ella la
tabla no podría representar más de una fila por grupo -- sería imposible
guardar las N filas de un grupo de N facturas) y las columnas de
trazabilidad estándar del resto del módulo (`id`, `created_at`).

`estado` cubre los tres valores reales que ya produce `_pass_group()` hoy:
  - "confirmado"   -- auto-confirmado (score >= UMBRAL_AUTO_CONFIRMA_GRUPO
                       Y candidato único, REQ-CONC-008).
  - "sugerido"      -- 2+ candidatos (ambigüedad real, ADR-2) o único
                       candidato con score por debajo del umbral; requiere
                       decisión humana explícita.
  - "sin_conciliar" -- ningún subconjunto cae en la banda de tolerancia
                       para ese movimiento (ADR-1, REQ-CONC-014).
No se declara un CHECK constraint sobre esos 3 valores: el motor de
matching es quien controla qué se escribe aquí (capa de aplicación), igual
que `mapeos_migracion_catalogo` (0018) deja `tipo_match`/`estado` como TEXT
libre validado en Python (pydantic), no en el esquema.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0019_recon_group_matches"
down_revision = "0018_mapeos_migracion_catalogo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reconciliation_group_matches",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), nullable=True),
        sa.Column("group_id", sa.Text(), nullable=False),
        sa.Column("transaction_id", sa.Text(), nullable=False),
        # Folio/id de la factura o comprobante individual dentro del grupo
        # (una fila por factura, igual que `_build_group_match()` en
        # memoria). Nula solo para una fila "sin_conciliar" (REQ-CONC-014),
        # donde no hay un grupo de facturas que registrar todavía -- el
        # movimiento bancario quedó sin ningún candidato válido.
        sa.Column("invoice_ref", sa.Text(), nullable=True),
        sa.Column("naturaleza", sa.Text(), nullable=False),
        # "abono" | "cargo" -- ver REQ-CONC-012.
        # Cualitativo ("alta"/"media"/"baja", como ya emite
        # `_build_group_match()`) o numérico según el caller; TEXT libre
        # por la misma razón que `bank_transactions.data` en 0005b: se
        # serializa/deserializa igual en los dos backends sin necesitar
        # tipos distintos por dimensión de "confianza".
        sa.Column("confidence", sa.Text(), nullable=True),
        sa.Column("estado", sa.Text(), nullable=False),
        # confirmado | sugerido | sin_conciliar
        sa.Column("score", sa.Numeric(5, 2), nullable=True),
        # 0-100 (REQ-CONC-009); NULL para ambigüedad real (2+ candidatos,
        # ADR-2) donde ningún score individual decide nada, y para
        # sin_conciliar (no hay candidato que puntuar).
        sa.Column("aprobado_por", sa.Text(), nullable=True),
        sa.Column("aprobado_en", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
    )
    op.create_index("idx_recon_group_matches_tenant",
                    "reconciliation_group_matches", ["tenant_id"])
    op.create_index("idx_recon_group_matches_group",
                    "reconciliation_group_matches", ["group_id"])
    op.create_index("idx_recon_group_matches_tx",
                    "reconciliation_group_matches", ["transaction_id"])
    op.create_index("idx_recon_group_matches_estado",
                    "reconciliation_group_matches", ["estado"])


def downgrade() -> None:
    op.drop_index("idx_recon_group_matches_estado",
                  table_name="reconciliation_group_matches")
    op.drop_index("idx_recon_group_matches_tx",
                  table_name="reconciliation_group_matches")
    op.drop_index("idx_recon_group_matches_group",
                  table_name="reconciliation_group_matches")
    op.drop_index("idx_recon_group_matches_tenant",
                  table_name="reconciliation_group_matches")
    op.drop_table("reconciliation_group_matches")
