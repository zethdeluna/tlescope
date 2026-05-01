"""
Tests for the APScheduler-based TLE caching layer

All tests mock the HTTP layer (httpx.get) so no live network calls are made. 
The fixture TLE data uses the ISS and a fictitious second satellite (NORAD 99999) 
so the tests remain deterministic regardless of Celestrak's current data.

Tests:
	1. refresh_tle_cache	- basic population, dict contents, disk persistence
	2. get_tle				- in-memory reads, miss behavior
	3. fetch_tle_by_norad	- layered cache fallback (memory -> disk -> live fetch)
	4. Failure handling		- Celestrak down, malformed response
	5. Lock / thread safety	- concurrent reads during a refresh
"""

import threading
import time
from unittest.mock import MagicMock, patch
import pytest
import app.tle_fetcher as tf
from app.tle_fetcher import get_tle, refresh_tle_cache, fetch_tle_by_norad
from app.orbital import TLE

# --------------------------------------------------------------------------------
# Shared fixtures
# --------------------------------------------------------------------------------

ISS_TLE_TEXT = (
    "ISS (ZARYA)\n"
    "1 25544U 98067A   26104.52178440  .00006465  00000+0  12575-3 0  9997\n"
    "2 25544  51.6319 255.1813 0006495 311.8952  48.1482 15.48913360561880"
)
 
FAKE_TLE_TEXT = (
    "FAKESAT\n"
    "1 99999U 00001A   26104.50000000  .00000000  00000+0  00000-0 0  9999\n"
    "2 99999  98.0000 100.0000 0001000 000.0000 360.0000 14.00000000000001"
)
 
CATALOG_TLE_TEXT = f"{ISS_TLE_TEXT}\n{FAKE_TLE_TEXT}"


def _make_mock_response(text: str, status_code: int = 200) -> MagicMock:
	"""Return a minimal httpx.Response mock."""

	mock = MagicMock()
	mock.text = text
	mock.status_code = status_code
	mock.raise_for_status = MagicMock()

	return mock


@pytest.fixture(autouse=True)
def clear_tle_cache():
	"""
	Wipe the in-memory cache before and after every test so tests are isolated.

	autouse=Ture means this fixture runs for every test in the file without 
	needing to be listed in each test's parameter list. Using the real lock 
	here mirrors what the application does, so the fixture itself tests that 
	the lock is released after a clear().
	"""

	with tf._tle_lock:
		tf._tle_cache.clear()

	yield

	with tf._tle_lock:
		tf._tle_cache.clear()


# --------------------------------------------------------------------------------
# 1. refresh_tle_cache
# --------------------------------------------------------------------------------

class TestRefreshTleCache:

	@patch("app.tle_fetcher.httpx.get")
	def test_populates_in_memory_cache(self, mock_get):
		"""
		After a successful refresh, _tle_cache should contain every satellite 
		in the catalog response.
		"""

		mock_get.return_value = _make_mock_response(CATALOG_TLE_TEXT)

		refresh_tle_cache()

		assert 25544 in tf._tle_cache, "ISS should be in cache after refresh"
		assert 99999 in tf._tle_cache, "FAKESAT should be in cache after refresh"


	@patch("app.tle_fetcher.httpx.get")
	def test_cache_entries_are_tle_namedtuples(self, mock_get):
		"""
		Values in _tle_cache must be TLE namedtuples, not raw dicts. 
		The endpoints call parse_tle() on the returned value, so the type 
		must match what parse_tle() returns.
		"""

		mock_get.return_value = _make_mock_response(CATALOG_TLE_TEXT)

		refresh_tle_cache()

		tle = tf._tle_cache[25544]

		assert isinstance(tle, TLE), f"Expected TLE namedtuple, got {type(tle)}"
		assert tle.name == "ISS (ZARYA)"
		assert tle.line1.startswith("1 25544")
		assert tle.line2.startswith("2 25544")


	@patch("app.tle_fetcher.httpx.get")
	def test_replaces_stale_entries(self, mock_get):
		"""
		A second refresh should overwrite existing entries rather than 
		accumulating them. We inject a different name for NORAD 25544 on 
		the second call to verify the swap.
		"""

		mock_get.return_value = _make_mock_response(CATALOG_TLE_TEXT)
		refresh_tle_cache()

		# Inject an "old" entry manually to simulate a stale cache state
		old_tle = TLE(name="STALE_ISS", line1=tf._tle_cache[25544].line1, line2=tf._tle_cache[25544].line2)

		with tf._tle_lock:
			tf._tle_cache[25544] = old_tle

		# Second refresh should overwrite with fresh data
		mock_get.return_value = _make_mock_response(CATALOG_TLE_TEXT)
		refresh_tle_cache()

		assert tf._tle_cache[25544].name == "ISS (ZARYA)", (
			"Refresh should replace stale cache entry with fresh data"
		)


	@patch("app.tle_fetcher.httpx.get")
	def test_celestrak_failure_leaves_cache_intact(self, mock_get):
		"""
		If Celestrak is unavailable during a refresh, the existing in-memory 
		cache should remain untouched.
		"""

		# Populate the cache with valid data first
		mock_get.return_value = _make_mock_response(CATALOG_TLE_TEXT)
		refresh_tle_cache()

		# Simulate Celestrak being down on the next refresh
		mock_get.side_effect = Exception("Connection refused")
		refresh_tle_cache()

		# Cache should still have the data from the first refresh
		assert 25544 in tf._tle_cache, (
			"Stale cache should be preserved when Celestrak is unreachable"
		)


	@patch("app.tle_fetcher.httpx.get")
	def test_malformed_response_leaves_cache_intact(self, mock_get):
		"""
		A response that doesn't match the expected TLE triplet format should 
		trigger a ValueError inside refresh_tle_cache, which catches it and 
		leaves the existing cache in place.
		"""

		mock_get.return_value = _make_mock_response(CATALOG_TLE_TEXT)
		refresh_tle_cache()

		mock_get.return_value = _make_mock_response("this is not a tle\n")
		refresh_tle_cache() # should not raise

		assert 25544 in tf._tle_cache, "Cache should survive a malformed refresh response"


	@patch("app.tle_fetcher.httpx.get")
	@patch.object(tf, "_cache")
	def test_persists_to_disk_cache(self, mock_disk, mock_get):
		"""
		After a successful refresh, each TLE should be written to the DiskCache 
		so it is available after a process restart.
		"""

		mock_get.return_value = _make_mock_response(CATALOG_TLE_TEXT)

		refresh_tle_cache()

		# _cache.set should have been called once per satellite in the catalog
		assert mock_disk.set.call_count == 2, (
			f"Expected 2 disk cache writes, got {mock_disk.set.call_count}"
		)

		# Verify the key format
		call_keys = {call.args[0] for call in mock_disk.set.call_args_list}
		assert "tle:25544" in call_keys
		assert "tle:99999" in call_keys


# --------------------------------------------------------------------------------
# 2. get_tle
# --------------------------------------------------------------------------------

class TestGetTle:

	def test_returns_none_on_empty_cache(self):
		"""get_tle should return None when the in-memory cache is empty."""

		result = get_tle(25544)
		assert result is None


	@patch("app.tle_fetcher.httpx.get")
	def test_returns_tle_after_refresh(self, mock_get):
		"""get_tle should return a TLE after a successful refresh."""

		mock_get.return_value = _make_mock_response(CATALOG_TLE_TEXT)
		refresh_tle_cache()

		tle = get_tle(25544)
		assert tle is not None
		assert tle.name == "ISS (ZARYA)"


	@patch("app.tle_fetcher.httpx.get")
	def test_returns_none_for_unknown_norad_id(self, mock_get):
		"""
		get_tle returns None for a NORAD ID not in the catalog.
		Endpoints treat a None return as "not found" and hit the disk cache 
		fallback or live Celestrak fetch.
		"""

		mock_get.return_value = _make_mock_response(CATALOG_TLE_TEXT)
		refresh_tle_cache()

		result = get_tle(99998) # not in CATALOG_TLE_TEXT
		assert result is None


# --------------------------------------------------------------------------------
# 3. fetch_tle_by_norad - layerd fallback
# --------------------------------------------------------------------------------

class TestFetchTleByNorad:

	@patch("app.tle_fetcher.httpx.get")
	def test_uses_in_memory_cache_after_refresh(self, mock_get):
		"""
		After a successful refresh, fetch_tle_by_norad should return data from 
		the in-memory cache without making an additional HTTP call.
		"""

		mock_get.return_value = _make_mock_response(CATALOG_TLE_TEXT)
		refresh_tle_cache()
		initial_call_count = mock_get.call_count

		tle = fetch_tle_by_norad(25544)

		# No new HTTP calls should have been made
		assert mock_get.call_count == initial_call_count, (
			"fetch_tle_by_norad should read from in-memory cache, not hit Celestrak"
		)
		assert tle.name == "ISS (ZARYA)"


	@patch("app.tle_fetcher.httpx.get")
	@patch.object(tf, "_cache")
	def test_falls_back_to_disk_cache_when_memory_cache_empty(self, mock_disk, mock_get):
		"""
		If the in-memory cache is empty (e.g., first seconds after startup), 
		fetch_tle_by_norad should check the disk cache before going to Celestrak.
		"""

		mock_disk.get.return_value = {
			"name": "ISS (ZARYA)",
			"line1": ISS_TLE_TEXT.splitlines()[1],
			"line2": ISS_TLE_TEXT.splitlines()[2]
		}

		tle = fetch_tle_by_norad(25544)

		mock_disk.get.assert_called_once()
		assert tle.name == "ISS (ZARYA)"

		# No live Celestrak call should have occurred
		mock_get.assert_not_called()


	@patch("app.tle_fetcher.httpx.get")
	@patch.object(tf, "_cache")
	def test_falls_back_to_celestrak_when_both_caches_empty(self, mock_disk, mock_get):
		"""
		If both in-memory and disk caches are cold (truly fresh install), 
		fetch_tle_by_norad should fetch from Celestrak as a last resort.
		"""

		mock_disk.get.return_value = None
		mock_get.return_value = _make_mock_response(ISS_TLE_TEXT)

		tle = fetch_tle_by_norad(25544)

		mock_get.assert_called_once()
		assert tle.name == "ISS (ZARYA)"


# --------------------------------------------------------------------------------
# 4. Thread safety
# --------------------------------------------------------------------------------

class TestThreadSafety:

	@patch("app.tle_fetcher.httpx.get")
	def test_concurrent_reads_during_refresh(self, mock_get):
		"""
		Spawn multiple reader threads while a refresh is in progress and verify 
		that every read either sees the old cache or the new cache — never an 
		empty intermediate state.
		"""

		# Pre-populate the cache with the ISS entry
		mock_get.return_value = _make_mock_response(ISS_TLE_TEXT.replace(
			"CATALOG", "ISS (ZARYA)"
		) + "\n" + FAKE_TLE_TEXT)

		# Seed with ISS only first
		mock_get.return_value = _make_mock_response(ISS_TLE_TEXT)

		# Manually pre-populate in-memory cache with the ISS TLE
		from app.orbital import parse_tle
		with tf._tle_lock:
			tf._tle_cache[25544] = parse_tle(ISS_TLE_TEXT)

		errors: list[str] = []

		def reader():
			"""Read the ISS TLE 100 times. It should never be None."""
			for _ in range(100):
				result = get_tle(25544)
				if result is None:
					errors.append("Reader saw empty cache mid-refresh")
					return
				
		def writer():
			"""Simulate a background refresh."""
			mock_get.return_value = _make_mock_response(CATALOG_TLE_TEXT)
			refresh_tle_cache()

		reader_threads = [threading.Thread(target=reader) for _ in range(8)]
		writer_thread = threading.Thread(target=writer)

		# Start readers first so some are mid-loop when the writer starts
		for t in reader_threads:
			t.start()
		time.sleep(0.001)
		writer_thread.start()

		for t in reader_threads:
			t.join()
		writer_thread.join()

		assert not errors, f"Thread safety violations: {errors}"


	@patch("app.tle_fetcher.httpx.get")
	def test_double_refresh_no_duplicate_entries(self, mock_get):
		"""
		Calling refresh_tle_cache twice should result in exactly the same 
		number of entries as a single call, not a doubled-up dict.

		This verifies that the clear() + update() pattern correctly replaces 
		rather than appends.
		"""

		mock_get.return_value = _make_mock_response(CATALOG_TLE_TEXT)
		refresh_tle_cache()
		count_after_first = len(tf._tle_cache)

		mock_get.return_value = _make_mock_response(CATALOG_TLE_TEXT)
		refresh_tle_cache()
		count_after_second = len(tf._tle_cache)

		assert count_after_first == count_after_second, (
			f"Double refresh produced {count_after_second} entries, "
			f"expected {count_after_first}"
		)