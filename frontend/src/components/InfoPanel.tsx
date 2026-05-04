/**
 * Right-hand sidebar with three sections:
 * 	1. Panel header			- tracked object count and capacity notice
 * 	2. GroundStationInput	- observer location
 * 	3. Satellite cards		- position telemetry, pass predictions, TLE timeline
 */

import { useSatelliteStore, MAX_TRACKED } from "../store/satelliteStore";
import { GroundStationInput } from "./GroundStationInput";
import { PassTable } from "./PassTable";
import { TLETimeline } from "./TleTimeline";

export function formatLat(deg: number): string {
    return `${Math.abs(deg).toFixed(3)}° ${deg >= 0 ? "N" : "S"}`;
}
 
export function formatLon(deg: number): string {
    return `${Math.abs(deg).toFixed(3)}° ${deg >= 0 ? "E" : "W"}`;
}

export function InfoPanel() {

	const { selectedSatellites, tracks, passes, groundStation, removeSatellite } = useSatelliteStore();

	const canRemove = selectedSatellites.length > 1;
	const atCapacity = selectedSatellites.length >= MAX_TRACKED;

	return (
		<aside className="info-panel">

			{/* Panel header */}
			<header className="panel-header">

				<div className="panel-header-row">

					<div className="status-dot" data-active="true" />

					<h1 className="panel-title">TRACKED OBJECTS</h1>

					<span className="tracked-count">
						{selectedSatellites.length}
						<span className="tracked-max">/{MAX_TRACKED}</span>
					</span>

				</div>

				{atCapacity && (
					<p className="capacity-notice">MAX CAPACITY - REMOVE TO ADD MORE</p>
				)}

			</header>

			{/* Ground station input */}
			<GroundStationInput />

			{/* Satellite cards */}
			<div className="satellite-list">
				{selectedSatellites.map(sat => {

					const track = tracks[sat.noradId];
					const feature = track?.data?.features[0];
					const firstCoord = feature?.geometry.coordinates[0];
					const [lon, lat] = firstCoord ?? [null, null];
					const alt = feature?.properties.altitudes_km[0] ?? null;

					const isLoading = !track || ( track.loading && !track.data );
					const hasData = lat != null && lon != null;
					const passState = passes[sat.noradId];

					return (
						<div key={sat.noradId} className="sat-card">

							{/* Card header */}
							<div className="sat-card-header">

								<span 
									className="sat-color-swatch" 
									style={{ background: sat.color }} 
									aria-hidden="true" 
								/>

								<span className="sat-card-name" title={sat.name}>
									{sat.name}
								</span>

								<span className="sat-card-norad">{sat.noradId}</span>

								{/* Remove satellite button */}
								{canRemove && (
									<button 
										className="sat-remove-btn" 
										onClick={() => removeSatellite(sat.noradId)} 
										title={`Remove ${sat.name}`} 
										aria-label={`Remove ${sat.name}`} 
									>
										✕
									</button>
								)}

							</div>

							{/* Loading state */}
							{isLoading && (
								<div className="sat-card-status">ACQUIRING SIGNAL...</div>
							)}

							{/* Error state */}
							{track?.error && !track.data && (
								<div className="sat-card-status sat-card-error">⚠ {track.error}</div>
							)}

							{/* Position telemetry */}
							{hasData && (
								<div className="sat-card-telemetry">

									<div className="tel-row">
										<span className="tel-key">LAT</span>
										<span className="tel-val" style={{ color: sat.color }}>{formatLat(lat)}</span>
									</div>

									<div className="tel-row">
										<span className="tel-key">LON</span>
										<span className="tel-val" style={{ color: sat.color }}>{formatLon(lon)}</span>
									</div>

									<div className="tel-row">
										<span className="tel-key">ALT</span>
										<span className="tel-val" style={{ color: sat.color }}>{alt != null ? `${alt.toFixed(0)} km` : "-"}</span>
									</div>

								</div>
							)}

							{/* Last updated */}
							{track?.lastUpdated && (
								<div className="sat-card-updated">
									↻ {track.lastUpdated.toLocaleTimeString()}
								</div>
							)}

							{/* Pass prediction */}
							{groundStation && (
								<PassTable passState={passState} />
							)}

							{/* Historical TLE timeline slider */}
							<TLETimeline noradId={sat.noradId} color={sat.color} />

						</div>
					);

				})}
			</div>

			{!atCapacity && (
				<footer className="panel-footer-hint">
					SEARCH TO ADD UP TO {MAX_TRACKED} SATELLITES
				</footer>
			)}

		</aside>
	);

}