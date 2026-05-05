/**
 * Custom hook that owns all data fetching for the satellite ground track.
 * 
 * Returns the raw GeoJSON FeatureCollection, plus loading/error state.
 * 
 * This hook is the only place in the app that knows about the API URL or 
 * the refresh interval. Components that use this hook are completely 
 * decoupled from transport concerns.
 */

import { useState, useEffect, useCallback } from 'react';

export interface GroundTrackProperties {
	satellite: string;
	norad_id: number;
	generated_at: string;
	duration_minutes: number;
	step_seconds: number;
	point_count: number;
	timestamps: string[];
	altitudes_km: number[];
}

export interface GroundTrackFeature {
	type: "Feature";
	geometry: {
		type: "LineString";
		coordinates: [number, number][];
	};
	properties: GroundTrackProperties;
}

export interface GroundTrackCollection {
	type: "FeatureCollection";
	features: [GroundTrackFeature];
}

interface UseGroundTrackResult {
	data: GroundTrackCollection | null;
	loading: boolean;
	error: string | null;
	lastUpdated: Date | null;
	refresh: () => void;
}

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";
const REFRESH_INTERVAL_MS = 60_000; // re-fetch every 60s

export function useGroundTrack( noradId = 25544, durationMinutes = 90, stepSeconds = 60 ): UseGroundTrackResult {

	const [data, setData] = useState<GroundTrackCollection | null>(null);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

	const fetchTrack = useCallback(async () => {

		try {

			setError(null);

			const url = 
				`${API_BASE}/satellite/${noradId}/groundtrack` +
				`?duration_minutes=${durationMinutes}&step_seconds=${stepSeconds}`
			;

			const response = await fetch(url);

			if ( !response.ok ) {
				throw new Error(`API returned ${response.status}: ${response.statusText}`);
			}

			const json: GroundTrackCollection = await response.json();
			setData(json);
			setLastUpdated(new Date());

		} catch (err) {

			setError(err instanceof Error ? err.message : "Unknown error fetching ground track");

		} finally {

			setLoading(false);

		}

	}, [noradId, durationMinutes, stepSeconds]);

	useEffect(() => {

		setData(null);
		setLoading(true);

		fetchTrack();

		const intervalId = setInterval(fetchTrack, REFRESH_INTERVAL_MS);

		return () => clearInterval(intervalId);

	}, [fetchTrack]);

	return { data, loading, error, lastUpdated, refresh: fetchTrack }

}