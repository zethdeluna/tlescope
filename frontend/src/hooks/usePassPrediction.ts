/**
 * Custom hook that fetches upcoming satellite pass predictions from the 
 * /satellite/{norad_id}/passes endpoint.
 * 
 * Mirrors the structure of useGroundTrack:
 * 	- owned fetch lifecycle (fetch on mount, re-fetch when deps change)
 * 	- returns { data, loading, error, generatedAt, refresh }
 * 	- components using this hook are decoupled from transport details
 * 
 * Key differences from useGroundTrack:
 * 	- This hook is inert when groundStation is null. Pass predictions are
 * 	  meaningless without an observer location, so we skip the fetch 
 * 	  entirely rather than calling the endpoint with (0, 0, 0).
 * 	- Polling interval is 15min - much longer than the 60s ground track 
 * 	  refresh because pass predictions for the next 3 days don't change
 * 	  second to second. The primary re-fetch trigger is a change in 
 * 	  groundStation or noradId, not the passage of time.
 */

import { useState, useEffect, useCallback } from 'react';
import type { GroundStation } from '../store/satelliteStore';

// A single point-in-time snapshot of the satellite's position and direction,
// used for rise, apex, and set events within a pass.
export interface PassEvent {
	time: string; // UTC ISO-8601 string: "2025-04-24T14:32:00Z"
	az_deg: number; // Compass bearing to satellite, 0-360° clockwise from North
	el_deg: number; // Verticali angle above horizon, -90° to +90°
	range_km: number; // Slant distance from observer to satellite in km
}

// One visibility window for the satellite over the observer's location
export interface SatellitePass {
	rise: PassEvent;
	apex: PassEvent;
	set: PassEvent;
	duration_seconds: number; // total visibility duration in seconds (set.time - rise.time)
	partial: boolean;
}

// Full response envelope from GET /satellite/{norad_id}/passes
export interface PassesResponse {
	satellite: string;
	norad_id: number;
	observer: { lat: number; lon: number; alt_m: number };
	generated_at: string;
	passes: SatellitePass[];
	note: string | null;
}

// Hook return type
interface UsePassPredictionResult {
	data: SatellitePass[] | null;
	note: string | null;
	loading: boolean;
	error: string | null;
	generatedAt: Date | null;
	refresh: () => void;
}

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";
const REFRESH_INTERVAL_MS = 15 * 60 * 1000;

export function usePassPrediction(
	noradId: number,
	groundStation: GroundStation | null,
	days = 3,
	minElevationDeg = 10
): UsePassPredictionResult {

	const [data, setData] = useState<SatellitePass[] | null>(null);
	const [note, setNote] = useState<string | null>(null);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [generatedAt, setGeneratedAt] = useState<Date | null>(null);

	const fetchPasses = useCallback(async () => {

		if ( !groundStation ) {
			setData(null);
			setNote(null);
			setLoading(false);
			return;
		}

		try {

			setError(null);
			setLoading(true);

			const { lat, lon, alt_m } = groundStation;

			const url = 
				`${API_BASE}/satellite/${noradId}/passes` +
				`?lat=${lat}&lon=${lon}&alt_m=${alt_m}` +
				`&days=${days}&min_elevation_deg=${minElevationDeg}`
			;

			const response = await fetch(url);

			if ( !response.ok ) {
				throw new Error(`API returned ${response.status}: ${response.statusText}`);
			}

			const json: PassesResponse = await response.json();

			setData(json.passes);
			setNote(json.note);
			setGeneratedAt(new Date());

		} catch (err) {

			setError(err instanceof Error ? err.message : "Unknown error fetching passes");

		} finally {

			setLoading(false);

		}

	}, [noradId, groundStation, days, minElevationDeg]);

	useEffect(() => {

		setData(null);
		setNote(null);

		if ( groundStation ) {
			setLoading(true);
		}

		fetchPasses();

		if ( !groundStation ) return;

		const intervalId = setInterval(fetchPasses, REFRESH_INTERVAL_MS);
		
		return () => clearInterval(intervalId);

	}, [fetchPasses, groundStation]);

	return { data, note, loading, error, generatedAt, refresh: fetchPasses };

}