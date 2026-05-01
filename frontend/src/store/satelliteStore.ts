/**
 * Zustand store for the currently selected satellites and their data.
 * 
 * Slices:
 * 		tracks				- live GeoJSON ground tracks, polled every 60s
 * 		passes				- upcoming pass predictions, polled every 15min
 * 		historicalTracks	- GeoJSON for a user-selected TLE snapshot
 * 		orbit3DData			- one full orbital period of ECEF positions for CesiumJS
 */

import { create } from "zustand";
import type { GroundTrackCollection } from "../hooks/useGroundTrack";
import type { SatellitePass } from "../hooks/usePassPrediction";

export interface SatelliteEntry {
	noradId:	number;
	name:		string;
	color:		string;
}

export interface TrackState {
	data:			GroundTrackCollection | null;
	loading:		boolean;
	error:			string | null;
	lastUpdated:	Date | null;
}

export interface GroundStation {
	lat:	number;
	lon:	number;
	alt_m:	number;
	label?:	string;
}

export interface PassState {
	data:			SatellitePass[] | null;
	note:			string | null;
	loading:		boolean;
	error:			string | null;
	generatedAt:	Date | null;
}

export interface Orbit3DPosition {
	time: string;
	x_km: number;
	y_km: number;
	z_km: number;
}

export interface Orbit3DResponse {
	satellite:		string;
	norad_id:		number;
	period_minutes: number;
	steps:			number;
	positions:		Orbit3DPosition[]
}

export interface Orbit3DState {
	data: 	 Orbit3DResponse | null;
	loading: boolean;
	error:	 string | null;
}

interface SatelliteStore {
	selectedSatellites:		SatelliteEntry[];
	tracks:					Record<number, TrackState>;
	groundStation:			GroundStation | null;
	passes:					Record<number, PassState>;
	historicalTracks:		Record<number, GroundTrackCollection | null>;
	orbit3DData:			Record<number, Orbit3DState>;
	
	addSatellite:			(noradId: number, name: string) => void;
	removeSatellite:		(noradId: number) => void;
	toggleSatellite:		(noradId: number, name: string) => void;
	isSelected:				(noradId: number) => boolean;
	setTrackState:			(noradId: number, state: TrackState) => void;
	setGroundStation:		(gs: GroundStation) => void;
	clearGroundStation:		() => void;
	setPassState:			(noradId: number, state: PassState) => void;
	setHistoricalTrack:		(noradId: number, track: GroundTrackCollection | null) => void;
	clearHistoricalTrack:	(noradId: number) => void;
	setOrbit3DState:		(noradId: number, state: Orbit3DState) => void;
}

// Constants
export const TRACK_COLORS = [
    "#00FF88",
    "#00AAFF",
    "#FF6B35",
    "#FF44AA",
    "#FFDD00"
] as const;
 
export const MAX_TRACKED = TRACK_COLORS.length;

// Store
export const useSatelliteStore = create<SatelliteStore>((set, get) => ({

	selectedSatellites: [
		{ noradId: 25544, name: "ISS (ZARYA)", color: TRACK_COLORS[0] }
	],

	tracks: {},
	groundStation: null,
	passes: {},
	historicalTracks: {},
	orbit3DData: {},

	addSatellite: (noradId, name) => {
		
		const { selectedSatellites } = get();

		if ( selectedSatellites.length >= MAX_TRACKED ) return;
		if ( selectedSatellites.some(s => s.noradId === noradId) ) return;

		const color = TRACK_COLORS[selectedSatellites.length];

		set(state => ({
			selectedSatellites: [...state.selectedSatellites, { noradId, name, color }]
		}));

	},

	removeSatellite: (noradId) => {

		if ( get().selectedSatellites.length <= 1 ) return;

		set(state => {

			const next = state.selectedSatellites.filter(s => s.noradId !== noradId);
			const { [noradId]: _t, ...remainingTracks }		= state.tracks;
			const { [noradId]: _p, ...remainingPasses }		= state.passes;
			const { [noradId]: _h, ...remainingHistorical }	= state.historicalTracks;
			const { [noradId]: _o, ...remainingOrbit3d }	= state.orbit3DData;

			return {
				selectedSatellites: next,
				tracks: remainingTracks,
				passes: remainingPasses,
				historicalTracks: remainingHistorical,
				orbit3DData: remainingOrbit3d
			};

		});

	},

	toggleSatellite: (noradId, name) => {

		const { selectedSatellites } = get();

		if ( selectedSatellites.some(s => s.noradId === noradId) ) {
			get().removeSatellite(noradId);
		} else {
			get().addSatellite(noradId, name);
		}
		
	},

	isSelected: (noradId) => 
		get().selectedSatellites.some(s => s.noradId === noradId),

	setTrackState: (noradId, trackState) =>
		set(store => ({ tracks: { ...store.tracks, [noradId]: trackState } })),

	setGroundStation: (gs) => set({ groundStation: gs }),
	clearGroundStation: () => set({ groundStation: null }),

	setPassState: (noradId, passState) => 
		set(store => ({ passes: { ...store.passes, [noradId]: passState } })),

	setHistoricalTrack: (noradId, track) => 
		set(store => ({ historicalTracks: { ...store.historicalTracks, [noradId]: track } })),

	clearHistoricalTrack: (noradId) => 
		set(store => ({ historicalTracks: { ...store.historicalTracks, [noradId]: null } })),

	setOrbit3DState: (noradId, state) =>
		set(store => ({ orbit3DData: { ...store.orbit3DData, [noradId]: state } }))

}))