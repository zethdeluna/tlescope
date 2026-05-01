"""
Core physics pipeline for SGP4 propagation.

Pipeline: TLE -> SGP4 (ECI) -> ECEF -> Geodetic (lat/lon/alt)
"""

import math
from datetime import datetime, timezone, timedelta
from typing import NamedTuple
import pymap3d
from sgp4.api import Satrec, jday

class GroundPoint(NamedTuple):
	"""
	A single propagated position on the ground track.
	"""

	timestamp: datetime
	lat_deg: float
	lon_deg: float
	alt_km: float


class TLE(NamedTuple):
	"""
	A parsed Two-Line Element set with its catalog name.
	"""

	name: str
	line1: str
	line2: str


def parse_tle(raw: str) -> TLE:
	"""
	Parse a raw 3-line TLE string into a TLE namedtuple.

	Celestrak returns TLEs in this format:
		ISS (Zarya)
        1 25544U 98067A   24001.00000000  .00001234 00000-0 12345-4 0  9999
        2 25544 51.6400 123.4567 0007654 89.1234 270.9876 15.50000000123456

	The name is on line 0, TLE data on lines 1 and 2.
	"""

	lines = [l.strip() for l in raw.strip().splitlines() if l.strip()]

	if len(lines) != 3:
		raise ValueError(f"Expected 3 lines in TLE block, got {len(lines)}")
	
	return TLE(name=lines[0], line1=lines[1], line2=lines[2])


def propagate_eci(tle: TLE, t: datetime) -> tuple[list[float], list[float]]:
	"""
	Run SGP4 on the TLE at time t, returning (position_eci_km, velocity_eci_km_s).

	SGP4 outputs in the ECI (Earth-Centered Inertial) frame: origin at Earth's center, 
	x-axis toward vernal equinox, does not rotate with Earth.

	Time is passed as a split Julian date to avoid floating-point precision loss in 
	the fractional-day component.
	"""

	sat = Satrec.twoline2rv(tle.line1, tle.line2)

	jd, fr = jday(
		t.year, t.month, t.day,
		t.hour, t.minute, t.second + t.microsecond / 1e6
	)

	error_code, r_eci, v_eci = sat.sgp4(jd, fr)

	if error_code != 0:
		raise RuntimeError(f"SGP4 propagation failed with error code {error_code}")
	
	return list(r_eci), list(v_eci)


def eci_to_ecef(r_eci: list[float], t: datetime) -> tuple[float, float, float]:
	"""
	Convert an ECI position vector (km) to ECEF coordinates (km).

	This is the first step of the ECI -> geodetic pipeline, exposed here as its own 
	function. The /orbit3d endpoint needs ECEF Cartesian coordinates, CesiumJS 
	consumes them directly as Cartesian3 (in meters, so the frontend multiplies by 
	1000). Stopping here avoids the unnecessary geodetic conversion that 
	build_ground_track needs but orbit3d doesn't.

	pymap3d.eci2ecef performs the CMST rotation internally using the UTC time. 
	It returns shape-(1,) numpy arrays; .item() converts each to a Python float.
	Input/output are both in kilometers; pymap3d works internally in meters so we 
	scale in and out.
	"""

	if t.tzinfo is None:
		t = t.replace(tzinfo=timezone.utc)

	x_eci, y_eci, z_eci = r_eci

	x_ecef, y_ecef, z_ecef = pymap3d.eci2ecef(
		x_eci * 1000,
		y_eci * 1000,
		z_eci * 1000,
		t
	)

	return x_ecef.item() / 1000, y_ecef.item() / 1000, z_ecef.item() / 1000


def eci_to_geodetic(r_eci: list[float], t: datetime) -> tuple[float, float, float]:
	"""
	Convert an ECI position vector to geodetic lat/lon/alt.

	Two-step transform using the same time t as the propagation:
		Step 1:	ECI -> ECEF via GMST rotation (pymap3d handles this internally)
		Step 2:	ECEF -> geodetic using the WGS-84 ellipsoid (Bowring's method)
	"""

	if t.tzinfo is None:
		t = t.replace(tzinfo=timezone.utc)

	x_eci, y_eci, z_eci = r_eci

	lat, lon, alt = pymap3d.eci2geodetic(
		x_eci * 1000,
		y_eci * 1000,
		z_eci * 1000,
		t
	)

	return lat.item(), lon.item(), alt.item() / 1000


def build_ground_track(
	tle: TLE,
	start: datetime,
	duration_minutes: float = 90.0,
	step_seconds: float = 60.0
) -> list[GroundPoint]:
	"""
	Propagate the satellite from 'start' for 'duration_minutes', sampling every 
	'step_seconds', and return the ground track as a list of GroundPoints.

	90 minutes at 60-second steps -> 91 points, one full ISS orbit.
	"""

	if start.tzinfo is None:
		start = start.replace(tzinfo=timezone.utc)

	n_steps = int(duration_minutes * 60 / step_seconds) + 1
	track = []

	for i in range(n_steps):
		t = start + timedelta(seconds=i * step_seconds)
		r_eci, _ = propagate_eci(tle, t)
		lat, lon, alt = eci_to_geodetic(r_eci, t)
		track.append(GroundPoint(timestamp=t, lat_deg=lat, lon_deg=lon, alt_km=alt))

	return track