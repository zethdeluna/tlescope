"""
SQLAlchemy ORM models for the TLE history store.

Two tables:
	satellites     — one row per NORAD catalog entry (id + name, grows lazily)
	tle_snapshots  — one row per distinct TLE epoch, deduplicated by (norad_id, epoch)

Why deduplicate on epoch and not on fetched_at?
	Celestrak updates TLEs only when a new observation produces a meaningfully
	different orbit solution. Two scheduler runs four hours apart will often
	return the same TLE (same epoch, same lines). Storing duplicates would
	bloat the table and cause the timeline slider to show spurious entries.
	The epoch uniqueness constraint ensures one row per orbit solution per
	satellite — exactly what the historical animation needs.
"""

from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Satellite(Base):
    """
    One row per satellite that has ever appeared in a TLE refresh cycle.

    Rows are created lazily by the scheduler and the name column is kept
    current (satellites are occasionally renamed in the Celestrak catalog).
    """

    __tablename__ = "satellites"

    norad_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # One satellite → many TLE snapshots, ordered by epoch ascending
    snapshots: Mapped[list["TLESnapshot"]] = relationship(
        back_populates="satellite",
        cascade="all, delete-orphan",
        order_by="TLESnapshot.epoch",
    )

    def __repr__(self) -> str:
        return f"<Satellite norad_id={self.norad_id} name={self.name!r}>"


class TLESnapshot(Base):
    """
    A single historical TLE for a satellite at a specific epoch.

    The 'epoch' field is parsed from TLE line 1 (columns 19–32) and
    represents when the orbit element set was generated — not when we
    fetched it. Two fetches within the same scheduler window usually produce
    the same epoch, so the unique constraint prevents duplicate storage.

    'fetched_at' records the wall-clock time of the scheduler run that wrote
    this row, which is useful for auditing cache freshness and debugging.
    """

    __tablename__ = "tle_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    norad_id: Mapped[int] = mapped_column(
        ForeignKey("satellites.norad_id", ondelete="CASCADE"),
        nullable=False,
    )
    line1: Mapped[str] = mapped_column(String(70), nullable=False)
    line2: Mapped[str] = mapped_column(String(70), nullable=False)

    # Parsed from TLE line 1 — the orbit solution's reference time
    epoch: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Wall-clock time of the scheduler run that wrote this row
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    satellite: Mapped["Satellite"] = relationship(back_populates="snapshots")

    __table_args__ = (
        # One row per (satellite, orbit-solution epoch)
        UniqueConstraint("norad_id", "epoch", name="uq_snapshot_norad_epoch"),
        # Speed up the /tle_history range queries without a full table scan
        Index("ix_snapshot_norad_epoch", "norad_id", "epoch"),
    )

    def __repr__(self) -> str:
        return (
            f"<TLESnapshot id={self.id} norad_id={self.norad_id} "
            f"epoch={self.epoch.isoformat()!r}>"
        )