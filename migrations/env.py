from logging.config import fileConfig
import os

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# --- B&B AI: la URL real viene de B2B_DB_URL o B2B_DB_PATH (postgresql://).
# El fallback en alembic.ini solo se usa si no hay variable de entorno.
_dsn = os.environ.get("B2B_DB_URL") or os.environ.get("B2B_DB_PATH")
if _dsn:
    if _dsn.lower().startswith("sqlite"):
        # Alembic apunta a PostgreSQL (producción). SQLite es el backend de
        # dev/test y no usa alembic (lo gestiona db.py con models.MIGRATIONS).
        raise RuntimeError(
            "Alembic solo se usa contra PostgreSQL. "
            "Pon B2B_DB_URL=postgresql://... para migrar producción.")
    # Fuerza el driver psycopg3 (SQLAlchemy 2.x usa psycopg2 por defecto para
    # postgresql://; el pool de la app corre sobre psycopg3).
    if _dsn.lower().startswith("postgresql://") and "+psycopg" not in _dsn:
        _dsn = _dsn.replace("postgresql://", "postgresql+psycopg://", 1)
    if _dsn.lower().startswith("postgres://") and "+psycopg" not in _dsn:
        _dsn = _dsn.replace("postgres://", "postgres+psycopg://", 1)
    config.set_main_option("sqlalchemy.url", _dsn)

target_metadata = None


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
