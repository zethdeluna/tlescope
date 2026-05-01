"""
database.py — SQLAlchemy engine, session factory, and declarative base.

All modules that need database access (models.py, tle_fetcher.py, main.py)
import from here. The engine is created once at module import time using
the DATABASE_URL environment variable, which lets the same codebase target:

  - PostgreSQL in production  (DATABASE_URL=postgresql://user:pass@host/db)
  - SQLite locally or in CI   (DATABASE_URL=sqlite:///./tle_history.db, or unset)

The SQLite fallback means the app starts without any configuration — useful
during early development and for CI pipelines that don't provision Postgres.

The declarative base lives here (rather than in models.py) to prevent a
circular import: models.py imports Base from here; tle_fetcher.py imports
from models.py; database.py imports nothing from our own codebase.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# ---------------------------------------------------------------------------
# Connection string
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "sqlite:///./tle_history.db",
)

# Some platforms (older Heroku/Render configs) emit "postgres://" instead of
# "postgresql://". SQLAlchemy 1.4+ rejects the legacy scheme, so patch it.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

# pool_pre_ping=True tests the connection before each use, which automatically
# reconnects if the database server has recycled an idle connection. This is
# important for our long-running FastAPI process where the scheduler may sit
# idle for hours between database writes.
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

# autocommit=False and autoflush=False are the SQLAlchemy defaults, but we
# spell them out: every session must explicitly commit or roll back.
Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    """
    Shared base class for all ORM models.

    When Alembic's env.py imports Base.metadata, it automatically sees every
    model that has been defined (as long as that model's module has been
    imported). The alembic/env.py file imports app.models to trigger this
    registration side-effect before calling context.run_migrations().
    """
    pass