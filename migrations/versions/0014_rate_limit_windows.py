"""rate limiting persistido en Postgres, por tenant (ventana fija)

Revision ID: 0014_rate_limit_windows
Revises: 0013_polizas_bloqueadas
Create Date: 2026-09-08

Ver b2b_ai/infrastructure/rate_limit_store.py para el diseño completo
(por qué ventana fija en vez de sliding log, por qué tenant_id es columna
propia y no solo texto embebido en `key`, y por qué este módulo evita a
propósito tocar b2b_ai/db/db.py).

Tabla `rate_limit_windows`: un contador por (key, window_start). `key` es la
clave lógica de rate limiting que ya arma el código llamador (por ejemplo
`rl:tenant:42:api` o `rl:ip:1.2.3.4:api` — el mismo esquema que usan hoy los
backends Redis/memoria de b2b_ai/api/rate_limiter.py, así que este backend es
un reemplazo directo). `tenant_id` se persiste ADEMÁS como columna propia
(nullable — las peticiones sin tenant resuelto se limitan por IP) para poder
sumar consumo por tenant sin parsear `key`.

No hay TTL nativo en PostgreSQL: la tabla crece una fila por (key, ventana)
usada. `RateLimitStore.purge_expired()` es el mecanismo de limpieza — debe
programarse como tarea periódica (cron/worker), fuera del alcance de esta
migración.
"""
from alembic import op
import sqlalchemy as sa

revision = "0014_rate_limit_windows"
down_revision = "0013_polizas_bloqueadas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_windows",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=True),
        sa.Column("window_start", sa.BigInteger(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key", "window_start",
                                name="pk_rate_limit_windows"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"],
            name="fk_rate_limit_windows_tenant",
            ondelete="CASCADE",
        ),
    )
    # Soporta usage_by_tenant() (SUM(count) por tenant_id + window_start) y
    # el borrado en cascada al eliminar un tenant.
    op.create_index(
        "idx_rate_limit_windows_tenant",
        "rate_limit_windows",
        ["tenant_id", "window_start"],
    )
    # Soporta purge_expired() (DELETE ... WHERE window_start < cutoff) sin
    # escanear toda la tabla.
    op.create_index(
        "idx_rate_limit_windows_window_start",
        "rate_limit_windows",
        ["window_start"],
    )


def downgrade() -> None:
    op.drop_index("idx_rate_limit_windows_window_start",
                  table_name="rate_limit_windows")
    op.drop_index("idx_rate_limit_windows_tenant",
                  table_name="rate_limit_windows")
    op.drop_table("rate_limit_windows")
