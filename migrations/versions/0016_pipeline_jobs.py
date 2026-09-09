"""jobs asincronos persistidos en Postgres (pipeline bookkeeping + batch v2)

Revision ID: 0016_pipeline_jobs
Revises: 0015_rate_limit_windows
Create Date: 2026-09-09

Ver b2b_ai/infrastructure/job_store.py para el diseño completo (por qué este
módulo evita a propósito tocar b2b_ai/db/db.py, y por qué el payload se
guarda como TEXT con JSON serializado en vez de JSONB).

Tabla `pipeline_jobs`: una fila por job, con upsert por `job_id`. `job_type`
distingue el namespace lógico del llamador (hoy: "bookkeeping_pipeline" de
b2b_ai/features/bookkeeping/pipeline.py::PipelineOrchestrator, y "batch_v2"
de b2b_ai/api/v2.py) para que ambos puedan compartir la misma tabla sin
colisionar. `tenant_id` es TEXT (no FK a `tenants.id`): ambos llamadores ya
tratan tenant_id como una cadena libre (incluye tenants de test como
"test_tenant" que no existen en la tabla `tenants`), así que forzar una FK
aquí rompería ese uso existente.
"""
from alembic import op
import sqlalchemy as sa

revision = "0016_pipeline_jobs"
down_revision = "0015_rate_limit_windows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pipeline_jobs",
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("progress_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("errors", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("job_id", name="pk_pipeline_jobs"),
    )
    # Soporta list_jobs(job_type=..., tenant_id=...) ordenado por
    # started_at DESC sin escanear toda la tabla.
    op.create_index(
        "idx_pipeline_jobs_type_tenant",
        "pipeline_jobs",
        ["job_type", "tenant_id", "started_at"],
    )
    op.create_index(
        "idx_pipeline_jobs_started_at",
        "pipeline_jobs",
        ["started_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_pipeline_jobs_started_at", table_name="pipeline_jobs")
    op.drop_index("idx_pipeline_jobs_type_tenant", table_name="pipeline_jobs")
    op.drop_table("pipeline_jobs")
