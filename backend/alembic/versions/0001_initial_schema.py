"""
Initial schema: satellites and tle_snapshots tables.

Revision ID: 0001
Revises: (none — this is the root of the migration chain)
Create Date: 2026-04-30

Running `alembic upgrade head` on a fresh database executes this script
and creates both tables. Running `alembic downgrade -1` drops them.

Schema decisions worth noting:

  satellites.norad_id is the primary key (not a surrogate integer). NORAD
  catalog numbers are stable identifiers — they never change for a given
  satellite and are already the primary key in every other part of the system
  (the in-memory cache, the DiskCache, the API endpoints). Using the natural
  key avoids a JOIN whenever the API needs to go from snapshot → satellite name.

  tle_snapshots uses a surrogate integer primary key (id) even though
  (norad_id, epoch) could serve as a natural composite key. The surrogate key
  is used by the /tle_history API and by the frontend's useHistoricalTrack hook
  to identify a specific snapshot unambiguously in a URL parameter.

  The composite index on (norad_id, epoch) accelerates the /tle_history range
  query: WHERE norad_id = ? AND epoch BETWEEN ? AND ? — the two most common
  access patterns for the history endpoint.
"""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create satellites first — tle_snapshots has a FK pointing at it
    op.create_table(
        "satellites",
        sa.Column("norad_id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
    )

    op.create_table(
        "tle_snapshots",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "norad_id",
            sa.Integer,
            sa.ForeignKey("satellites.norad_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("line1", sa.String(70), nullable=False),
        sa.Column("line2", sa.String(70), nullable=False),
        sa.Column("epoch", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        # Unique constraint declared inline so SQLite can honour it at CREATE
        # TABLE time — SQLite has no support for ALTER TABLE ADD CONSTRAINT.
        sa.UniqueConstraint("norad_id", "epoch", name="uq_snapshot_norad_epoch"),
    )

    # CREATE INDEX compiles to its own DDL statement (not ALTER TABLE),
    # so this works correctly on both SQLite and PostgreSQL.
    op.create_index(
        "ix_snapshot_norad_epoch",
        "tle_snapshots",
        ["norad_id", "epoch"],
    )


def downgrade() -> None:
    # Drop in reverse dependency order to satisfy the foreign key constraint
    op.drop_table("tle_snapshots")
    op.drop_table("satellites")