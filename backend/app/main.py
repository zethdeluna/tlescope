"""
FastAPI application exposing the orbital propagation as a REST API.

Endpoints:
    GET /health								- liveness check
    GET /iss/position						- current ISS position
    GET /iss/groundtrack					- 90-min ground track as GeoJSON
    GET /satellite/{norad_id}/groundtrack	- same, any NORAD catalog ID + optional ?snapshot_id= for historical TLE from the DB
    GET /satellite/{norad_id}/passes		- upcoming passes over a ground station
    GET /satellite/{norad_id}/tle_history	- list of stored TLE snapshots
    GET /satellite/{norad_id}/orbit3d		- ECEF positions for CesiumJS
    GET /satellites							- full catalog of active satellites

Lifecycle:
	APScheduler BackgroundScheduler via 'lifespan' from scheduler.py fires 
    refresh_tle_cache() immediately on startup and every four hours thereafter.
    Each refresh also persists TLE snapshots to PostgreSQL.
"""

from datetime import datetime, timezone, timedelta
from typing import Annotated, Optional

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.orbital import build_ground_track, propagate_eci, eci_to_geodetic, eci_to_ecef, TLE
from app.tle_fetcher import fetch_tle_by_norad, fetch_iss_tle, fetch_satellite_catalog, NORAD_ISS
from app.pass_predictor import predict_passes, SatellitePass
from app.scheduler import lifespan
from app.database import Session, engine
from app.models import TLESnapshot, Satellite


app = FastAPI(
	title="Satellite Tracker API",
	description="SGP4-based orbit propagator serving ground track as GeoJSON",
	version="0.4.0",
	lifespan=lifespan
)

app.add_middleware(
	CORSMiddleware,
	allow_origins=["http://localhost:5173", "http://localhost"],
	allow_methods=["GET"],
	allow_headers=["*"]
)


# Liveness
@app.get("/health")
def health():
	return {"status": "ok"}


# Catalog
@app.get("/satellites")
def satellites():
	try:
		return fetch_satellite_catalog()
	except Exception as e:
		raise HTTPException(status_code=503, detail=f"Failed to fetch satellite catalog: {e}")


# Ground track
@app.get("/satellite/{norad_id}/groundtrack")
def satellite_groundtrack(
	norad_id: int,
	duration_minutes: Annotated[float, Query(ge=1, le=720)] = 90.0,
	step_seconds: Annotated[float, Query(ge=10, le=300)] = 60.0,
	snapshot_id: Optional[int] = None
):
	"""
	Returns the satellite's ground track as a GeoJSON FeatureCollection.

	When snapshot_id is provided, the TLE is loaded from tle_snapshots. Otherwise the live 
	three-layer cache is used.
	"""

	if snapshot_id is not None:
		try:
			with Session() as session:
				row = session.scalar(
					select(TLESnapshot).where(TLESnapshot.id == snapshot_id)
				)

				if row is None or row.norad_id != norad_id:
					raise HTTPException(status_code=404, detail=f"No TLE snapshot {snapshot_id} for NORAD {norad_id}")
				
				tle = TLE(
					name=row.satellite.name if row.satellite else f"NORAD {norad_id}",
					line1=row.line1,
					line2=row.line2
				)
		except HTTPException:
			raise
		except Exception as e:
			raise HTTPException(status_code=503, detail=f"Database error: {e}")
	else:
		try:
			tle = fetch_tle_by_norad(norad_id)
		except ValueError as e:
			raise HTTPException(status_code=404, detail=str(e))
		except Exception as e:
			raise HTTPException(status_code=503, detail=f"Failed to fetch TLE: {e}")
		
	return _groundtrack_response(tle, norad_id, duration_minutes, step_seconds)


# TLE history
@app.get("/satellite/{norad_id}/tle_history")
def satellite_tle_history(
	norad_id: int, 
	start: Optional[str] = None,
	end: Optional[str] = None
):
	"""
	Returns stored TLE snapshots sorted by epoch ascending.
	Optional start/end filters are ISO 8601 date strings.
	"""

	start_dt: Optional[datetime] = None
	end_dt: Optional[datetime] = None

	if start:
		try:
			start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
		except ValueError:
			raise HTTPException(status_code=422, detail=f"Invalid start date: {start!r}")
		
	if end:
		try:
			end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
		except ValueError:
			raise HTTPException(status_code=422, detail=f"Invalid end date: {end!r}")
		
	try:
		with Session() as session:
			sat = session.get(Satellite, norad_id)
			if sat is None:
				return {"norad_id": norad_id, "snapshots": []}
			
			stmt = (
				select(TLESnapshot)
				.where(TLESnapshot.norad_id == norad_id)
				.order_by(TLESnapshot.epoch)
			)

			if start_dt:
				stmt = stmt.where(TLESnapshot.epoch >= start_dt)
			if end_dt:
				stmt = stmt.where(TLESnapshot.epoch <= end_dt)

			snapshots = session.scalars(stmt).all()

			return {
				"norad_id": norad_id,
				"satellite": sat.name,
				"snapshots": [
					{
						"id":			snap.id,
						"epoch":		snap.epoch.strftime("%Y-%m-%dT%H:%M:%SZ"),
						"fetched_at":	snap.fetched_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
						"line1":		snap.line1,
						"line2":		snap.line2
					}
					for snap in snapshots
				]
			}
	
	except Exception as e:
		raise HTTPException(status_code=503, detail=f"Database error: {e}")
	

# 3D Orbit data
@app.get("/satellite/{norad_id}/orbit3d")
def satellite_orbit3d(
	norad_id: int,
	steps: Annotated[int, Query(ge=50, le=500)] = 200
):
	"""
	Returns one full orbital period of timestamped ECEF positions for CesiumJS.

	The orbital period is derived from mean motion in TLE line 2 
	(chars 52-63, revolutions/day): period_minutes = 1440 / mean_motion

	For LEO satellites like the ISS (~15.5 rev/day) this is ~93 minutes.
	For GEO (~1.0 rev/day) it would be 1440 min; we cap propagatoin at 200 minutes 
	so step density stays fine for Cesium's interpolation.

	Response:
	{
		"satellite":		"ISS (ZARYA)",
		"norad_id":			25544,
		"period_minutes":	92.9,
		"steps":			200,
		"positions":		[
			{ "time": "2026-04-30T12:00:00Z", "x_km": 3452.1, "y_km": 5821.3, "z_km": 1203.4 },
			...
		]
	}

	Coordinates are ECEF in kilometers. The frontend multiplies by 1000 for 
	Cesium's Cartesian3 (which expects meters).
	"""

	try:
		tle = fetch_tle_by_norad(norad_id)
	except ValueError as e:
		raise HTTPException(status_code=404, detail=str(e))
	except Exception as e:
		raise HTTPException(status_code=503, detail=f"Failed to fetch TLE: {e}")
	
	# Parse mean motion from TLE line 2 characters 52-63 (revolutions / day)
	try:
		mean_motion_rev_per_day = float(tle.line2[52:63])
		if mean_motion_rev_per_day <= 0:
			raise ValueError("Non-positive mean motion")
		
		period_minutes = 1440.0 / mean_motion_rev_per_day

	except (ValueError, IndexError) as e:
		raise HTTPException(status_code=422, detail=f"Could not parse mean motion from TLE: {e}")
	
	# Cap to 200 min so GEO/HEO steps aren't too sparse for Cesium inerpolation
	propagate_minutes = min(period_minutes, 200.0)
	step_seconds = (propagate_minutes * 60.0) / steps

	now = datetime.now(tz=timezone.utc)

	try:
		positions = []
		for i in range(steps + 1):
			t = now + timedelta(seconds=i * step_seconds)
			r_eci, _ = propagate_eci(tle, t)
			x_km, y_km, z_km = eci_to_ecef(r_eci, t)

			positions.append({
				"time":	t.strftime("%Y-%m-%dT%H:%M:%SZ"),
				"x_km":	round(x_km, 3),
				"y_km":	round(y_km, 3),
				"z_km":	round(z_km, 3)
			})

	except RuntimeError as e:
		raise HTTPException(status_code=500, detail=f"Propagation failed: {e}")
	
	return {
		"satellite":		tle.name,
		"norad_id":			norad_id,
		"period_minutes":	round(period_minutes, 3),
		"steps":			steps,
		"positions":		positions
	}


# Pass prediction
@app.get("/satellite/{norad_id}/passes")
def satellite_passes(
	norad_id:			int,
	lat: 				Annotated[float, Query(ge=-90, le=90)]		= 0.0,
	lon: 				Annotated[float, Query(ge=-180, le=180)]	= 0.0,
	alt_m: 				Annotated[float, Query(ge=-500, le=9000)]	= 0.0,
	days:				Annotated[float, Query(ge=0.5, le=14)]		= 3.0,
	min_elevation_deg:	Annotated[float, Query(ge=0, le=90)]		= 10.0
):
	"""
	Return upcoming passes of a satellite over a ground station.

	GEO satellites that stay continuously above the horizon return an empty 
	passes list with a human-readable note instead.
	"""

	try:
		tle = fetch_tle_by_norad(norad_id)
	except ValueError as e:
		raise HTTPException(status_code=404, detail=str(e))
	except Exception as e:
		raise HTTPException(status_code=503, detail=f"Failed to fetch TLE: {e}")
	
	now = datetime.now(tz=timezone.utc)

	try:
		all_passes = predict_passes(
			tle.line1, tle.line2,
			obs_lat=lat,
			obs_lon=lon,
			obs_alt_m=alt_m,
			start=now,
			days=days,
			min_el=min_elevation_deg,
			drop_partial=False
		)
	except Exception as e:
		raise HTTPException(status_code=500, detail=f"Pass prediction failed: {e}")
	
	complete_passes = [p for p in all_passes if not p.partial]
	partial_passes = [p for p in all_passes if p.partial]

	note = None
	window_seconds = days * 86400
	is_continuous = (
		len(complete_passes) == 0 and
		len(partial_passes) == 1 and 
		partial_passes[0].duration_seconds >= window_seconds * 0.95
	)

	if is_continuous:
		note = (
			f"{tle.name} is continuously above {min_elevation_deg:.0f}° elevation "
			f"from this location and does not rise or set within the "
			f"{days:.0f}-day window."
		)

	return {
		"satellite":	tle.name,
		"norad_id":		norad_id,
		"observer":		{"lat": lat, "lon": lon, "alt_m": alt_m},
		"generated_at":	now.strftime("%Y-%m-%dT%H:%M:%SZ"),
		"passes":		[_serialize_pass(p) for p in complete_passes],
		"note":			note
	}


# ISS convenience endpoints
@app.get("/iss/position")
def iss_position():
	try:
		tle = fetch_iss_tle()
	except Exception as e:
		raise HTTPException(status_code=503, detail=f"Failed to fetch TLE: {e}")
	
	now = datetime.now(tz=timezone.utc)
	r_eci, v_eci = propagate_eci(tle, now)
	lat, lon, alt = eci_to_geodetic(r_eci, now)

	return {
		"satellite":			tle.name,
		"norad_id":				NORAD_ISS,
		"timestamp":			now.isoformat(),
		"lat_deg":				round(lat, 4),
		"lon_deg":				round(lon, 4),
		"alt_km":				round(alt, 2),
		"velocity_eci_km_s":	[round(v, 4) for v in v_eci]
	}

@app.get("/iss/groundtrack")
def iss_groundtrack(
	duration_minutes:	Annotated[float, Query(ge=1, le=720)]	= 90.0,
	step_seconds:		Annotated[float, Query(ge=10, le=300)]	= 60.0
):
	try:
		tle = fetch_iss_tle()
	except Exception as e:
		raise HTTPException(status_code=503, detail=f"Failed to fetch TLE: {e}")
	
	return _groundtrack_response(tle, NORAD_ISS, duration_minutes, step_seconds)


# Helpers

def _groundtrack_response(tle, norad_id: int, duration_minutes: float, step_seconds: float):

	now = datetime.now(tz=timezone.utc)
	track = build_ground_track(tle, now, duration_minutes, step_seconds)

	coordinates	= [[round(pt.lon_deg, 5), round(pt.lat_deg, 5)] for pt in track]
	timestamps	= [pt.timestamp.isoformat() for pt in track]
	altitudes	= [round(pt.alt_km, 2) for pt in track]

	return {
		"type": "FeatureCollection",
		"features": [
			{
				"type": "Feature",
				"geometry": {
					"type": "LineString",
					"coordinates": coordinates
				},
				"properties": {
					"satellite":		tle.name,
					"norad_id":			norad_id,
					"generated_at":		now.isoformat(),
					"duration_minutes":	duration_minutes,
					"step_seconds":		step_seconds,
					"point_count":		len(track),
					"timestamps":		timestamps,
					"altitudes_km":		altitudes
				}
			}
		]
	}


def _serialize_pass(p: SatellitePass) -> dict:

	def serialize_event(e) -> dict:
		return {
			"time":		e.time.strftime("%Y-%m-%dT%H:%M:%SZ"),
			"az_deg":	round(e.az_deg, 1),
			"el_deg":	round(e.el_deg, 1),
			"range_km":	round(e.range_km, 1)
		}
	
	return {
		"rise":				serialize_event(p.rise),
		"apex":				serialize_event(p.apex),
		"set":				serialize_event(p.set),
		"duration_seconds":	round(p.duration_seconds),
		"partial":			p.partial
	}