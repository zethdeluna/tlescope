/**
 * Fetches one orbital period of ECEF position data from 
 * /satellite/{norad_id}/orbit3d and writes the result into the Zustand store.
 */

import { useEffect } from "react";
import { useSatelliteStore } from "../store/satelliteStore";

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

export function useOrbit3D(noradId: number): void {

	const orbit3DData = useSatelliteStore(s => s.orbit3DData);
	const setOrbit3dState = useSatelliteStore(s => s.setOrbit3DState)

	useEffect(() => {

		const existing = orbit3DData[noradId];

		// Skip if data is already present and valid
		if ( existing?.data && !existing.error ) return;

		// Skip if a fetch is already in flight for this satellite
		if ( existing?.loading ) return;

		let cancelled = false;

		setOrbit3dState(noradId, { data: null, loading: true, error: null });

		fetch(`${API_BASE}/satellite/${noradId}/orbit3d?steps=200`)
			.then(res => {
				if (!res.ok) throw new Error(`HTTP ${res.status}`);
				return res.json();
			})
			.then(data => {
				if (!cancelled) {
					setOrbit3dState(noradId, { data, loading: false, error: null });
				}
			})
			.catch(err => {
				if (!cancelled) {
					setOrbit3dState(noradId, { data: null, loading: false, error: err instanceof Error ? err.message : String(err) });
				}
			});

		return () => { cancelled = true; };

	}, [noradId]);

}