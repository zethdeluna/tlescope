"""
alembic/env.py — Alembic migration environment.

This file is executed by every `alembic` command. Its two jobs are:

	1. Point Alembic at the real database URL (read from the DATABASE_URL
	   environment variable rather than alembic.ini, so the config works
	   unchanged across local, CI, and production environments).

	2. Point Alembic at the SQLAlchemy metadata (Base.metadata), which is
	   how `alembic revision --autogenerate` knows what the current model
	   schema looks like when generating a new migration script.

The `import app.models` line below has a critical side-effect: it causes
the Satellite and TLESnapshot classes to register themselves with
Base.metadata. Without it, autogenerate would see an empty schema.
"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make `app` importable when alembic is run from the backend/ directory
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.database import Base, DATABASE_URL  # noqa: E402
import app.models  # noqa: F401 — registers Satellite + TLESnapshot with Base.metadata

# ── Alembic Config object, provides access to values in alembic.ini ──────────
config = context.config

# Set up Python logging from the alembic.ini [loggers] section
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override the placeholder URL in alembic.ini with the real DATABASE_URL
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# The metadata whose schema Alembic tracks
target_metadata = Base.metadata


# ── Offline mode ──────────────────────────────────────────────────────────────
def run_migrations_offline() -> None:
    """
    Emit SQL to stdout without connecting to a live database.

    Useful when the DBA wants to review the migration SQL before applying it,
    or when the CI pipeline can't reach the database. Run with:

        alembic upgrade head --sql
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online mode ───────────────────────────────────────────────────────────────
def run_migrations_online() -> None:
    """
    Connect to the live database and apply migrations directly.

    This is the normal path for `alembic upgrade head`. NullPool is used so
    the migration process gets a fresh connection and releases it when done,
    rather than leaving it parked in the connection pool.
    """
    # For PostgreSQL, fail fast if the DB is unreachable rather than hanging
    # indefinitely. 5 seconds is enough for a healthy Railway DB; a hung
    # connection would otherwise block uvicorn from ever starting.
    connect_args = {"connect_timeout": 5} if DATABASE_URL.startswith(("postgresql", "postgres")) else {}

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()