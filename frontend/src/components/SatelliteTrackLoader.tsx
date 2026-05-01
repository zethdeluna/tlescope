/**
 * A headless component: renders nothing to the DOM but manages the full 
 * data-fetch lifecycle for one satellite and syncs results into the Zustand store.
 */

import { useEffect } from "react";
import { useGroundTrack } from "../hooks/useGroundTrack";
import { usePassPrediction } from "../hooks/usePassPrediction";
import { useOrbit3D } from "../hooks/useOrbit3D";
import { useSatelliteStore } from "../store/satelliteStore";
import type { SatelliteEntry } from "../store/satelliteStore";

interface Props {
	satellite: SatelliteEntry;
}

export function SatelliteTrackLoader({ satellite }: Props) {

	// Ground track (60s polling)
	const { data, loading, error, lastUpdated } = useGroundTrack(satellite.noradId);
	const setTrackState = useSatelliteStore(s => s.setTrackState);

	useEffect(() => {

		setTrackState(satellite.noradId, { data, loading, error, lastUpdated });

	}, [satellite.noradId, data, loading, error, lastUpdated, setTrackState]);

	// Pass prediction (15min polling)
	const groundStation = useSatelliteStore(s => s.groundStation);
	const setPassState = useSatelliteStore(s => s.setPassState);

	const {
		data: passData,
		note: passNote,
		loading: passLoading,
		error: passError,
		generatedAt: passGeneratedAt
	} = usePassPrediction(satellite.noradId, groundStation);

	useEffect(() => {

		setPassState(satellite.noradId, {
			data: passData,
			note: passNote,
			loading: passLoading,
			error: passError,
			generatedAt: passGeneratedAt
		});

	}, [satellite.noradId, passData, passNote, passLoading, passError, passGeneratedAt, setPassState]);

	// 3D orbit data (fetch once)
	useOrbit3D(satellite.noradId);

	return null;

}