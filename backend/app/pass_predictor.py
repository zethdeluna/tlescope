"""
Pass prediction algorithm for ground observers.

Given a TLE and a ground station location, computes when a satellite will
rise above the observer's horizon, reach its peak elevation, and set again.

Pipeline:
    TLE + observer + time window
        -> Phase 1: coarse scan (every 30s) to detect horizon crossings
        -> Phase 2: binary refinement to pinpoint rise/set to <1s precision
        -> Peak search (every 10s within the pass) to find apex
        -> List of SatellitePass objects, sorted chronologically

Physics background:
    A satellite is "visible" (in the radio/tracking sense) when its elevation
    angle above the local horizon is >= some minimum (typically 10°). Elevation
    is computed in the AER (Azimuth-Elevation-Range) frame, which is centred on
    the observer and answers observer-centric questions directly.

    The ECI position from SGP4 is converted to AER via:
        ECI -> ECEF (rotate by GMST at time t)
        ECEF -> AER (translate to observer, then spherical projection)
        
    pymap3d.eci2aer chains these two steps in a single call.
"""

import pymap3d
from datetime import datetime, timezone, timedelta
from typing import NamedTuple
from sgp4.api import Satrec, jday


# -------------------------------------------------------------------------------------
# Data types
# -------------------------------------------------------------------------------------

class PassEvent(NamedTuple):
    """
    A single moment during a pass: the satellite's position in the observer's sky.

    az_deg  : compass bearing, 0-360° clockwise from north
    el_deg  : vertical angle above horizon, 0-90° (negative means below horizon)
    range_km: slant distance from observer to satellite
    """
    time: datetime
    az_deg: float
    el_deg: float
    range_km: float


class SatellitePass(NamedTuple):
    """
    A complete overhead pass, defined by three key moments.

    rise     			: when the satellite crosses above min_elevation (AOS - Acquisition of Signal)
    apex     			: the highest elevation point of the pass
    set      			: when the satellite drops back below min_elevation (LOS - Loss of Signal)
    duration_seconds	: wall-clock length of the pass (set.time - rise.time)
    partial  			: True if the pass was clipped by the prediction window boundary.
               			  A partial pass at the start means we joined mid-pass; at the end
               			  means the pass was still ongoing when the window closed.
    """
    rise: PassEvent
    apex: PassEvent
    set: PassEvent
    duration_seconds: float
    partial: bool


# -------------------------------------------------------------------------------------
# Core transform: ECI -> AER
# -------------------------------------------------------------------------------------

def compute_aer(
    tle_line1: str,
    tle_line2: str,
    obs_lat: float,
    obs_lon: float,
    obs_alt_m: float,
    t: datetime
) -> tuple[float, float, float]:
    """
    Compute azimuth, elevation, and range for a satellite relative to a ground observer.

    Observer altitude is in metres (consistent with GPS output and pymap3d's convention).
    The conversion to km for SGP4 happens internally — no caller needs to think about it.

    Returns (az_deg, el_deg, range_km).
    """
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)

    # Propagate the TLE to get an ECI position vector (kilometres)
    sat = Satrec.twoline2rv(tle_line1, tle_line2)
    jd, fr = jday(
        t.year, t.month, t.day,
        t.hour, t.minute, t.second + t.microsecond / 1e6
    )
    error_code, r_eci, _ = sat.sgp4(jd, fr)
    if error_code != 0:
        raise RuntimeError(f"SGP4 error {error_code} at {t.isoformat()}")

    x_km, y_km, z_km = r_eci

    # pymap3d.eci2aer converts ECI (metres) -> AER, chaining ECI->ECEF->AER in one call.
    # Observer altitude is passed in metres, consistent with pymap3d's expectation.
    az, el, rng = pymap3d.eci2aer(
        x_km * 1000,    # pymap3d expects metres
        y_km * 1000,
        z_km * 1000,
        obs_lat,
        obs_lon,
        obs_alt_m,      # metres — converted from GPS altitude, NOT from km
        t
    )

    # pymap3d may return NumPy scalars or shape-(1,) arrays rather than plain floats.
    # The same .item() extraction pattern used in orbital.py applies here.
    return float(az.item() if hasattr(az, 'item') else az), \
           float(el.item() if hasattr(el, 'item') else el), \
           float((rng.item() if hasattr(rng, 'item') else rng) / 1000)  # back to km


# -------------------------------------------------------------------------------------
# Two-phase pass prediction algorithm
# -------------------------------------------------------------------------------------

def _binary_refine_crossing(
    tle_line1: str,
    tle_line2: str,
    obs_lat: float,
    obs_lon: float,
    obs_alt_m: float,
    t_below: datetime,
    t_above: datetime,
    min_el: float,
    tolerance_seconds: float = 1.0
) -> PassEvent:
    """
    Given a bracket [t_below, t_above] where elevation crosses min_el, narrow it
    to within tolerance_seconds using binary search.

    Converges in ~7–8 iterations regardless of starting bracket size (log2(30) ≈ 5
    for a 30-second coarse step, with a bit of margin for the 1-second target).
    """
    while (t_above - t_below).total_seconds() > tolerance_seconds:
        t_mid = t_below + (t_above - t_below) / 2
        _, el_mid, _ = compute_aer(tle_line1, tle_line2, obs_lat, obs_lon, obs_alt_m, t_mid)
        if el_mid < min_el:
            t_below = t_mid
        else:
            t_above = t_mid

    # The refined crossing time is at the midpoint of the final bracket.
    t_cross = t_below + (t_above - t_below) / 2
    az, el, rng = compute_aer(tle_line1, tle_line2, obs_lat, obs_lon, obs_alt_m, t_cross)
    return PassEvent(time=t_cross, az_deg=az, el_deg=el, range_km=rng)


def predict_passes(
    tle_line1: str,
    tle_line2: str,
    obs_lat: float,
    obs_lon: float,
    obs_alt_m: float,
    start: datetime,
    days: float = 3.0,
    min_el: float = 10.0,
    coarse_step_s: float = 30.0,
    drop_partial: bool = True
) -> list[SatellitePass]:
    """
    Predict all passes of a satellite over a ground station within a time window.

    Parameters
    ----------
    tle_line1, tle_line2 : TLE strings (lines 1 and 2 of the TLE block)
    obs_lat, obs_lon     : observer geodetic latitude/longitude in degrees
    obs_alt_m            : observer altitude above sea level in metres
    start                : prediction window start (UTC)
    days                 : prediction window length in days (default 3)
    min_el               : minimum elevation angle to count as a pass (default 10°)
    coarse_step_s        : coarse scan step in seconds (default 30, good for LEO)
    drop_partial         : if True (default), discard passes that are clipped by the
                           window boundaries (satellite already above horizon at 'start',
                           or still above at window end)

    Returns
    -------
    List of SatellitePass objects, sorted by rise time.
    """
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)

    end = start + timedelta(days=days)
    total_seconds = days * 86400
    n_steps = int(total_seconds / coarse_step_s) + 1

    passes: list[SatellitePass] = []

    # Phase 1: coarse scan — step through the window and watch for sign changes
    # across the min_el threshold. Each transition brackets a horizon crossing.
    prev_el = None
    prev_t = None
    in_pass = False
    rise_event: PassEvent | None = None

    for i in range(n_steps):
        t = start + timedelta(seconds=i * coarse_step_s)
        if t > end:
            t = end

        az, el, rng = compute_aer(tle_line1, tle_line2, obs_lat, obs_lon, obs_alt_m, t)

        if prev_el is not None:
            was_above = prev_el >= min_el
            is_above  = el      >= min_el

            if not was_above and is_above:
                # Rising edge: satellite just crossed above min_el
                # Phase 2: binary refinement to find the exact crossing time
                refined_rise = _binary_refine_crossing(
                    tle_line1, tle_line2, obs_lat, obs_lon, obs_alt_m,
                    prev_t, t, min_el
                )
                rise_event = refined_rise
                in_pass = True

            elif was_above and not is_above and in_pass and rise_event is not None:
                # Falling edge: satellite just crossed back below min_el
                refined_set = _binary_refine_crossing(
                    tle_line1, tle_line2, obs_lat, obs_lon, obs_alt_m,
                    prev_t, t, min_el
                )

                # Peak search: step at 10-second intervals through the confirmed pass
                # window to find the maximum elevation. Elevation is a smooth
                # single-peaked function within a pass, so a linear sweep is correct.
                apex_event = _find_apex(
                    tle_line1, tle_line2, obs_lat, obs_lon, obs_alt_m,
                    rise_event.time, refined_set.time, peak_step_s=10.0
                )

                duration = (refined_set.time - rise_event.time).total_seconds()
                passes.append(SatellitePass(
                    rise=rise_event,
                    apex=apex_event,
                    set=refined_set,
                    duration_seconds=duration,
                    partial=False
                ))
                in_pass = False
                rise_event = None

        # Handle the satellite being above the horizon at the very start of the window.
        # This is a partial pass — we joined mid-pass.
        if i == 0 and el >= min_el:
            # Treat the window start as the "rise" (it's really mid-pass)
            rise_event = PassEvent(time=t, az_deg=az, el_deg=el, range_km=rng)
            in_pass = True

        prev_el = el
        prev_t = t

    # Handle a satellite that is still above the horizon at window end (partial pass)
    if in_pass and rise_event is not None:
        az_end, el_end, rng_end = compute_aer(
            tle_line1, tle_line2, obs_lat, obs_lon, obs_alt_m, end
        )
        set_event = PassEvent(time=end, az_deg=az_end, el_deg=el_end, range_km=rng_end)
        apex_event = _find_apex(
            tle_line1, tle_line2, obs_lat, obs_lon, obs_alt_m,
            rise_event.time, set_event.time, peak_step_s=10.0
        )
        duration = (set_event.time - rise_event.time).total_seconds()
        passes.append(SatellitePass(
            rise=rise_event,
            apex=apex_event,
            set=set_event,
            duration_seconds=duration,
            partial=True
        ))

    if drop_partial:
        passes = [p for p in passes if not p.partial]

    return sorted(passes, key=lambda p: p.rise.time)


def _find_apex(
    tle_line1: str,
    tle_line2: str,
    obs_lat: float,
    obs_lon: float,
    obs_alt_m: float,
    t_rise: datetime,
    t_set: datetime,
    peak_step_s: float = 10.0
) -> PassEvent:
    """
    Find the moment of maximum elevation within a confirmed pass window [t_rise, t_set].
    Sweeps at peak_step_s resolution and returns the point with the highest elevation.
    """
    duration_s = (t_set - t_rise).total_seconds()
    n_steps = max(int(duration_s / peak_step_s) + 1, 2)

    best_el = -90.0
    best_event = None

    for i in range(n_steps):
        t = t_rise + timedelta(seconds=i * peak_step_s)
        if t > t_set:
            t = t_set
        az, el, rng = compute_aer(tle_line1, tle_line2, obs_lat, obs_lon, obs_alt_m, t)
        if el > best_el:
            best_el = el
            best_event = PassEvent(time=t, az_deg=az, el_deg=el, range_km=rng)

    # Fallback: if somehow no point was found (shouldn't happen), use rise as apex
    return best_event or PassEvent(
        time=t_rise, az_deg=0.0, el_deg=best_el, range_km=0.0
    )