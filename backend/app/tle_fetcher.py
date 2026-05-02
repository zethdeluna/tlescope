"""
tle_fetcher.py — Celestrak client, in-memory TLE cache, and PostgreSQL persistence.

The module now has three layers of concern:

  1. In-memory cache (_tle_cache dict + _tle_lock)
     The fast path for every endpoint request. Populated wholesale by the
     APScheduler background job every four hours; O(1) reads with no I/O.

  2. DiskCache (file-backed JSON fallback)
     Survives process restarts. Bridges the brief window between startup and
     the first scheduler tick completing, so endpoints can serve stale-but-valid
     TLEs immediately rather than waiting for the background refresh.

  3. PostgreSQL TLE history (_persist_snapshots)
     NEW in Pillar 2. Every scheduler refresh also writes to the database,
     deduplicated by (norad_id, epoch). The database is not in the request
     path — endpoints never query it for position data. Its only purpose is
     the historical record that powers the TLETimeline slider in the frontend.

Call hierarchy at request time (unchanged from Pillar 1):
  endpoint  →  fetch_tle_by_norad()
                  ↓ 1. in-memory _tle_cache   (fast path)
                  ↓ 2. DiskCache              (startup bridge)
                  ↓ 3. live Celestrak fetch   (truly cold start only)

The DB write is on a separate path triggered only by refresh_tle_cache().
A DB failure does not affect the in-memory cache or the DiskCache, so the
API remains available even when PostgreSQL is down.
"""

import json
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
from sqlalchemy import select

from app.orbital import TLE, parse_tle
from app.database import Session, engine
from app.models import Satellite, TLESnapshot

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CELESTRAK_BASE = "https://celestrak.org/NORAD/elements/gp.php"
NORAD_ISS = 25544
TLE_TTL_SECONDS = 4 * 60 * 60       # individual TLE disk-cache TTL
CATALOG_TTL_SECONDS = 24 * 60 * 60  # name-only catalog disk-cache TTL
# Bulk fetches produce ~10 000 entries; individual lookups stay well below this
_MIN_BULK_ENTRIES = 500
CACHE_PATH = Path(__file__).parent.parent / ".tle_cache.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; satellite-tracker/1.0)"}

_FALLBACK_ISS_TLE = """
ISS (ZARYA)
1 25544U 98067A   26104.52178440  .00006465  00000+0  12575-3 0  9997
2 25544  51.6319 255.1813 0006495 311.8952  48.1482 15.48913360561880
"""

# ---------------------------------------------------------------------------
# In-memory TLE cache (Pillar 1)
# ---------------------------------------------------------------------------

# Primary store: populated by refresh_tle_cache() every 4 hours.
# Keys are int NORAD IDs; values are TLE namedtuples.
_tle_cache: dict[int, TLE] = {}

# Protects _tle_cache against the clear()+update() race condition.
# Python's GIL guards individual dict operations but not sequences of them;
# a reader waking between clear() and update() would see an empty cache.
_tle_lock = threading.Lock()


def get_tle(norad_id: int) -> TLE | None:
    """
    Read a single TLE from the in-memory cache.
    Returns None on a miss. Used by tests and by the scheduler health check.
    """
    with _tle_lock:
        return _tle_cache.get(norad_id)


def refresh_tle_cache() -> None:
    """
    Background job: fetch the full active-satellite catalog from Celestrak,
    atomically replace the in-memory cache, warm the DiskCache, and persist
    new TLE snapshots to PostgreSQL.

    The DB write (_persist_snapshots) happens after the in-memory swap so
    that a slow or failing database write never delays serving requests.
    A try/except around _persist_snapshots ensures the scheduler continues
    even if PostgreSQL is temporarily unreachable.
    """
    print("[scheduler] TLE refresh started")

    # If the disk cache has enough fresh entries from a prior bulk fetch, warm
    # memory from disk instead of hitting Celestrak — avoids rate-limiting on
    # rapid Uvicorn restarts during development. Individual satellite lookups
    # produce far fewer than _MIN_BULK_ENTRIES entries, so this only triggers
    # after a real full-catalog refresh.
    disk_tles_raw = _cache.load_all_tles(TLE_TTL_SECONDS)
    if len(disk_tles_raw) >= _MIN_BULK_ENTRIES:
        disk_tles = {nid: TLE(**data) for nid, data in disk_tles_raw.items()}
        with _tle_lock:
            _tle_cache.clear()
            _tle_cache.update(disk_tles)
        print(f"[scheduler] loaded {len(disk_tles)} TLEs from disk cache (Celestrak fetch skipped)")
        return

    try:
        fresh = _fetch_active_tles()
    except Exception as exc:
        print(f"[scheduler] TLE refresh failed: {exc}")
        return

    # Atomically swap the in-memory cache
    with _tle_lock:
        _tle_cache.clear()
        _tle_cache.update(fresh)

    # Write to disk so the data survives a process restart before the next
    # scheduler tick completes
    for norad_id, tle in fresh.items():
        _cache.set(
            f"tle:{norad_id}",
            {"name": tle.name, "line1": tle.line1, "line2": tle.line2}
        )
    print(f"[scheduler] TLE refresh complete — {len(fresh)} satellites cached")

    # Persist to PostgreSQL; wrapped so a DB failure doesn't crash the scheduler
    _persist_snapshots(fresh)


# ---------------------------------------------------------------------------
# Database persistence helpers (Pillar 2)
# ---------------------------------------------------------------------------

def _parse_tle_epoch(line1: str) -> datetime:
    """
    Parse the epoch from TLE line 1 and return a UTC datetime.

    TLE line 1 columns 19–32 (0-indexed 18:32) contain a string like
    "26104.52178440": two-digit year (26 → 2026) followed by day-of-year
    with fractional day (104.52178440 = day 104, 12:31:22 UTC).

    The two-digit year convention: 57–99 maps to 1957–1999 (Sputnik era);
    00–56 maps to 2000–2056. TLEs for operating satellites will always be
    in the 2000–2056 window for the foreseeable future.
    """
    epoch_str = line1[18:32].strip()
    year_2d = int(epoch_str[:2])
    day_frac = float(epoch_str[2:])

    # Two-digit year decoding convention per the TLE specification
    year = (1900 + year_2d) if year_2d >= 57 else (2000 + year_2d)

    # Day 1.0 = midnight Jan 1; subtract 1 so timedelta starts from Jan 1 00:00
    return datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=day_frac - 1)


def _persist_snapshots(tles: dict[int, TLE]) -> None:
    """
    Write new TLE snapshots to PostgreSQL, skipping epochs already stored.

    The function works in three phases to minimise round-trips:

      Phase 1 — Upsert satellite names.
        session.merge() does an INSERT on new NORAD IDs and a no-op (or
        silent UPDATE for name changes) on existing ones. All merges are
        flushed to the DB before Phase 2 so that the foreign-key constraint
        in tle_snapshots is satisfied when we insert new snapshot rows.

      Phase 2 — Load already-stored epochs.
        One SELECT returns all (norad_id, epoch) pairs currently in the
        tle_snapshots table for the satellites we just refreshed. Building
        a Python set from this result lets Phase 3 skip the DB entirely for
        every duplicate — no per-row SELECT needed.

      Phase 3 — Batch insert new snapshots.
        Only TLEs whose (norad_id, epoch) pair is absent from the known set
        get inserted. session.add_all() batches them into the session;
        commit() flushes them in a single transaction.

    A try/except wraps the entire function. If the database is unreachable,
    the error is logged and the function returns without raising. The
    in-memory cache (already updated by the time this function is called)
    remains fully operational — the only consequence of a DB failure is that
    the historical archive does not grow for that refresh cycle.

    Note on scale: with ~10 000 active satellites and a four-hour refresh
    interval, Phase 2's IN query touches at most ~10 000 norad_id values.
    SQLite has a default variable limit of 999; for environments using SQLite
    (local dev / CI) consider chunking the IN clause if you ever exceed that
    limit. PostgreSQL has no practical limit here.
    """
    now = datetime.now(tz=timezone.utc)

    try:
        with Session() as session:

            # ── Phase 1: upsert satellite names ──────────────────────────────
            for norad_id, tle in tles.items():
                session.merge(Satellite(norad_id=norad_id, name=tle.name))
            session.flush()

            # ── Phase 2: fetch existing (norad_id, epoch) pairs ──────────────
            norad_ids = list(tles.keys())

            # Chunk to 900 to stay safely below SQLite's variable limit
            existing: set[tuple[int, datetime]] = set()
            for chunk_start in range(0, len(norad_ids), 900):
                chunk = norad_ids[chunk_start : chunk_start + 900]
                rows = session.execute(
                    select(TLESnapshot.norad_id, TLESnapshot.epoch)
                    .where(TLESnapshot.norad_id.in_(chunk))
                ).all()
                existing.update((r.norad_id, r.epoch) for r in rows)

            # ── Phase 3: batch-insert new snapshots ───────────────────────────
            new_snapshots: list[TLESnapshot] = []
            for norad_id, tle in tles.items():
                try:
                    epoch = _parse_tle_epoch(tle.line1)
                except Exception as exc:
                    # Malformed line 1 — skip rather than crash the whole batch
                    print(f"[db] epoch parse failed for NORAD {norad_id}: {exc}")
                    continue

                if (norad_id, epoch) not in existing:
                    new_snapshots.append(TLESnapshot(
                        norad_id=norad_id,
                        line1=tle.line1,
                        line2=tle.line2,
                        epoch=epoch,
                        fetched_at=now,
                    ))

            session.add_all(new_snapshots)
            session.commit()

            print(f"[db] persisted {len(new_snapshots)} new TLE snapshots "
                  f"({len(tles) - len(new_snapshots)} duplicates skipped)")

    except Exception as exc:
        print(f"[db] _persist_snapshots failed: {exc}")


# ---------------------------------------------------------------------------
# DiskCache (fallback layer — unchanged from Pillar 1)
# ---------------------------------------------------------------------------

class DiskCache:
    """
    A simple file-backed key-value cache with per-entry TTL expiration.

    JSON structure on disk:
        {
            "tle:25544": {
                "data": {"name": "ISS (ZARYA)", "line1": "...", "line2": "..."},
                "fetched_at": 1713000000.0
            },
            "catalog": {
                "data": [{"name": "ISS (ZARYA)", "norad_id": 25544}, ...],
                "fetched_at": 1713000000.0
            }
        }

    All reads and writes are guarded by a threading.Lock to prevent concurrent
    requests from corrupting the JSON file.
    """

    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()

    def _load(self) -> dict:
        try:
            return json.loads(self._path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save(self, store: dict) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(store, indent=2))
        tmp.rename(self._path)

    def get(self, key: str, ttl_seconds: float) -> dict | list | None:
        with self._lock:
            store = self._load()
            entry = store.get(key)
            if entry is None:
                return None
            age = time.time() - entry["fetched_at"]
            if age >= ttl_seconds:
                return None
            return entry["data"]

    def set(self, key: str, data: dict | list) -> None:
        with self._lock:
            store = self._load()
            store[key] = {"data": data, "fetched_at": time.time()}
            self._save(store)

    def load_all_tles(self, ttl_seconds: float) -> dict[int, dict]:
        """Return all tle:{norad_id} entries that are within TTL."""
        with self._lock:
            store = self._load()
        now = time.time()
        result = {}
        for key, entry in store.items():
            if not key.startswith("tle:"):
                continue
            try:
                norad_id = int(key[4:])
                if now - entry["fetched_at"] < ttl_seconds:
                    result[norad_id] = entry["data"]
            except (ValueError, KeyError):
                continue
        return result


_cache = DiskCache(CACHE_PATH)


# ---------------------------------------------------------------------------
# Private fetch helpers
# ---------------------------------------------------------------------------

def _fetch_active_tles() -> dict[int, TLE]:
    """
    Fetch Celestrak's full active-satellite TLE catalog.
    Returns a dict mapping each NORAD ID to its parsed TLE namedtuple.
    This is the only place that makes a catalog-scale HTTP call to Celestrak.
    """
    url = f"{CELESTRAK_BASE}?GROUP=active&FORMAT=TLE"
    response = httpx.get(url, timeout=30.0, headers=HEADERS)
    response.raise_for_status()

    lines = [l.strip() for l in response.text.splitlines() if l.strip()]

    if len(lines) < 3 or len(lines) % 3 != 0:
        raise ValueError(
            f"Unexpected catalog format: {len(lines)} lines "
            f"(expected a multiple of 3)"
        )

    result: dict[int, TLE] = {}
    for i in range(0, len(lines), 3):
        name, line1, line2 = lines[i], lines[i + 1], lines[i + 2]
        try:
            norad_id = int(line2[2:7].strip())
            tle = parse_tle(f"{name}\n{line1}\n{line2}")
            result[norad_id] = tle
        except Exception as exc:
            print(f"[warning] skipping malformed TLE block at line {i} ({name!r}): {exc}")
            continue

    return result


# ---------------------------------------------------------------------------
# Public fetching API
# ---------------------------------------------------------------------------

def fetch_tle_by_norad(norad_id: int) -> TLE:
    """
    Return the current TLE for a satellite by NORAD catalog number.

    Lookup order (fastest to slowest):
      1. In-memory _tle_cache  — populated every 4h by the scheduler
      2. DiskCache             — startup bridge before the first scheduler tick
      3. Live Celestrak fetch  — last resort for a truly cold start
    """
    # 1. In-memory cache
    with _tle_lock:
        if norad_id in _tle_cache:
            print(f"[memory hit] NORAD {norad_id}")
            return _tle_cache[norad_id]

    # 2. Disk cache
    key = f"tle:{norad_id}"
    cached = _cache.get(key, TLE_TTL_SECONDS)
    if cached is not None:
        print(f"[disk hit] NORAD {norad_id}")
        return TLE(**cached)

    # 3. Live fetch
    print(f"[cache miss] fetching NORAD {norad_id} from Celestrak")
    url = f"{CELESTRAK_BASE}?CATNR={norad_id}&FORMAT=TLE"
    response = httpx.get(url, timeout=10.0, headers=HEADERS)
    response.raise_for_status()

    raw = response.text.strip()
    if not raw or "No GP data found" in raw:
        raise ValueError(f"No TLE data found for NORAD ID {norad_id}")

    tle = parse_tle(raw)
    _cache.set(key, {"name": tle.name, "line1": tle.line1, "line2": tle.line2})
    _persist_snapshots({norad_id: tle})
    return tle


def fetch_iss_tle() -> TLE:
    """Convenience wrapper — fetches the current ISS TLE with a hardcoded fallback."""
    try:
        return fetch_tle_by_norad(NORAD_ISS)
    except Exception as e:
        print(f"[warning] Celestrak fetch failed ({e}), using fallback TLE")
        tle = parse_tle(_FALLBACK_ISS_TLE)
        _cache.set(
            f"tle:{NORAD_ISS}",
            {"name": tle.name, "line1": tle.line1, "line2": tle.line2}
        )
        return tle


def fetch_satellite_catalog() -> list[dict]:
    """
    Fetch and parse Celestrak's full active satellite catalog.
    Returns a list of {"name": ..., "norad_id": ...} dicts for the search UI.
    Full TLE data is served by the groundtrack/passes endpoints from the
    in-memory cache; this catalog is name+id only.

    Falls back to the satellites table when Celestrak is unreachable (e.g.
    Docker container IPs are often rate-limited for bulk GROUP=active requests).
    """
    cached = _cache.get("catalog", CATALOG_TTL_SECONDS)
    if cached is not None:
        print(f"[cache hit] satellite catalog ({len(cached)} entries)")
        return cached

    print("[cache miss] fetching full satellite catalog from Celestrak")
    url = f"{CELESTRAK_BASE}?GROUP=active&FORMAT=TLE"
    try:
        response = httpx.get(url, timeout=30.0, headers=HEADERS)
        response.raise_for_status()
    except Exception as exc:
        print(f"[catalog] Celestrak fetch failed ({exc}), falling back to database")
        return _catalog_from_db()

    lines = [l.strip() for l in response.text.splitlines() if l.strip()]
    if len(lines) < 3 or len(lines) % 3 != 0:
        raise ValueError(
            f"Unexpected catalog format: {len(lines)} lines "
            f"(expected a multiple of 3)"
        )

    catalog = []
    for i in range(0, len(lines), 3):
        name = lines[i]
        line2 = lines[i + 2]
        try:
            norad_id = int(line2[2:7].strip())
        except (ValueError, IndexError):
            print(f"[warning] skipping malformed TLE block at line {i}: {name!r}")
            continue
        catalog.append({"name": name, "norad_id": norad_id})

    print(f"[catalog] parsed {len(catalog)} satellites")
    if catalog:
        _cache.set("catalog", catalog)
    return catalog


def _catalog_from_db() -> list[dict]:
    """Return the satellite list from PostgreSQL when Celestrak is unavailable."""
    with Session() as session:
        rows = session.execute(select(Satellite)).scalars().all()
    if rows:
        catalog = [{"name": row.name, "norad_id": row.norad_id} for row in rows]
        print(f"[catalog] served {len(catalog)} satellites from database fallback")
        return catalog

    # DB empty — try the in-memory TLE cache (grows as individual satellites are looked up)
    with _tle_lock:
        cache_entries = list(_tle_cache.items())
    if cache_entries:
        catalog = [{"name": tle.name, "norad_id": nid} for nid, tle in cache_entries]
        print(f"[catalog] served {len(catalog)} satellites from in-memory cache fallback")
        return catalog

    print("[catalog] all sources unavailable, returning empty catalog")
    return []