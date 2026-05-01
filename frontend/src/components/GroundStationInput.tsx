/**
 * Lets the user set their observer locatoin via two paths:
 * 	1. "Use my location":	calls navigator.geolocation.getCurrentPosition
 * 	1. "Enter manually":	expands a lat/lon/altitude form
 * 
 * All three Geolocation API faliures modes produce specific user-facing messages:
 * 	PERMISSION_DENIED		-> instruct the user to check browser settings
 * 	POSITION_UNAVAILABLE	-> hardware/network could not resolve a position
 * 	TIMEOUT					-> the request did not complete in 10 seconds
 * 
 * When a ground station is set the copmonent collapses to a compact summary
 * with a "clear" button. Clearing sets groundStation back to null in the store,
 * which causes usePassPrediction (in SatelliteTrackLoader) to suspend further
 * pass fetches and leaves the passes dictionary empty until a new station is set.
 */

import { useState } from "react";
import { useSatelliteStore } from "../store/satelliteStore";
import { formatLat, formatLon } from "./InfoPanel";

// InputMode values to "handle" what's displayed
// "idle"		-> 2 action buttons
// "manual"		-> 2 action buttons + lat/lon/alt form
// "locating"	-> spinner while GeolCation API resolves
type InputMode = "idle" | "manual" | "locating";

// Format coordinates helper
function formatCoord(lat: number, lon: number): string {
	return `${formatLat(lat)} ${formatLon(lon)}`;
}

export function GroundStationInput() {

	const { groundStation, setGroundStation, clearGroundStation } = useSatelliteStore();

	const [mode, setMode] = useState<InputMode>("idle");
	const [latInput, setLatInput] = useState("");
	const [lonInput, setLonInput] = useState("");
	const [altInput, setAltInput] = useState("");
	const [geoError, setGeoError] = useState<string | null>(null);
	const [formError, setFormError] = useState<string | null>(null);

	// Geolocation path
	function handleGeolocate() {

		if ( !navigator.geolocation ) {
			setGeoError("Geolocatoin is not supported by your browser.");
			return;
		}

		setMode("locating");
		setGeoError(null);

		navigator.geolocation.getCurrentPosition(

			// Success
			(pos) => {

				setGroundStation({
					lat: pos.coords.latitude,
					lon: pos.coords.longitude,
					alt_m: pos.coords.altitude ?? 0, // default to sea level
					label: "My Location"
				});

				setMode("idle");

			},

			// Failure
			(err) => {

				setMode("idle");

				switch ( err.code ) {

					case err.PERMISSION_DENIED:
						setGeoError("Location access denied. Enable it in your browser settings and try again.");
						break;

					case err.POSITION_UNAVAILABLE:
						setGeoError("Your device could not determine its location. Try entering coordinates manually.");
						break;

					case err.TIMEOUT:
						setGeoError("Location request timed out. Check your connection or enter coordinates manually.");
						break;

					default:
						setGeoError("An unknown location error occurred. Try entering coordinates manually.");

				}

			},

			// 10-second timeout: accpet a cached position up to 60s old to 
			// avoid unnecessary delays when the user has recently used the app.
			{ timeout: 10_000, maximumAge: 60_000 }

		);

	}

	// Manual entry form - toggle + submit
	function handleToggleManual() {

		setMode(prev => prev === "manual" ? "idle" : "manual");
		setFormError(null);

	}

	function handleManualSubmit() {

		const lat = parseFloat(latInput);
		const lon = parseFloat(lonInput);
		const alt = altInput.trim() === "" ? 0 : parseFloat(altInput);

		// field validation
		if ( isNaN(lat) || lat < -90 || lat > 90 ) {

			setFormError("Latitude must be a number between -90 and 90.");
			return;

		}

		if ( isNaN(lon) || lon < -180 || lon > 180 ) {

			setFormError("Longitude must be a number between -180 and 180.");
			return;

		}

		if ( isNaN(alt) ) {

			setFormError("Altitude must be a number (meters above sea level).");
			return;

		}

		setFormError(null);

		setGroundStation({ lat, lon, alt_m: alt, label: `${lat.toFixed(3)}°, ${lon.toFixed(3)}°` });

		setMode("idle");

	}

	function handleKeyDown(e: React.KeyboardEvent) {
		
		if ( e.key === "Enter" ) handleManualSubmit();

	}

	// Render if ground station is set
	if ( groundStation ) {

		return (
			<div className="gs-section gs-section--set">
				
				<div className="gs-set-row">
					<span className="gs-section-label">GROUND STATION</span>
					<button 
						className="gs-clear-btn" 
						onClick={() => { clearGroundStation(); setGeoError(null); }}
						title="Clear ground station"
					>
						CLEAR
					</button>
				</div>

				{groundStation.label && (
					<div className="gs-set-label">{groundStation.label}</div>
				)}

				<div className="gs-set-coords">{formatCoord(groundStation.lat, groundStation.lon)}</div>
				<div className="gs-set-alt">{groundStation.alt_m.toFixed(0)} m ASL</div>

			</div>
		);

	}

	// Render if ground station is not set

	return (
		<div className="gs-section">

			<div className="gs-header-row">
				<span className="gs-section-label">GROUND STATION</span>
				<span className="gs-not-set">NOT SET</span>
			</div>

			{/* Error */}
			{geoError && (
				<div className="gs-error" role="alert">{geoError}</div>
			)}

			{/* Loading spinner */}
			{mode === "locating" && (
				<div className="gs-locating">
					<span className="gs-locating-ring" aria-hidden="true" />
					<span className="gs-locating-text">ACQUIRING POSITIONG...</span>
				</div>
			)}

			{/* Action buttons */}
			{mode !== "locating" && (
				<div className="gs-actions">

					<button className="gs-btn gs-btn--geo" onClick={handleGeolocate}>
						⊕ USE MY LOCATION
					</button>

					<button 
						className={`gs-btn gs-btn--manual${mode === "manual" ? " gs-btn--active" : ""}`} 
						onClick={handleToggleManual}
					>
						{mode === "manual" ? "✕ CANCEL" : "✎ ENTER MANUALLY" }
					</button>

				</div>
			)}

			{/* Manual entry form */}
			{mode === "manual" && (
				<div className="gs-form">

					<div className="gs-field">
						<label htmlFor="gs-lat" className="gs-field-label">LAT</label>
						<input 
							id="gs-lat" 
							className="gs-input" 
							type="number" 
							placeholder="34.052" 
							min="-90" 
							max="90" 
							step="0.001" 
							value={latInput}
							onChange={e => setLatInput(e.target.value)}
							onKeyDown={handleKeyDown}
							autoFocus 
						/>
					</div>

					<div className="gs-field">
						<label htmlFor="gs-lon" className="gs-field-label">LON</label>
						<input 
							id="gs-lon" 
							className="gs-input" 
							type="number" 
							placeholder="-118.244" 
							min="-180" 
							max="180" 
							step="0.001" 
							value={lonInput}
							onChange={e => setLonInput(e.target.value)}
							onKeyDown={handleKeyDown}
						/>
					</div>

					<div className="gs-field">
						<label htmlFor="gs-alt" className="gs-field-label">ALT</label>
						<input 
							id="gs-alt" 
							className="gs-input" 
							type="number" 
							placeholder="0" 
							min="0" 
							step="1" 
							value={latInput}
							onChange={e => setAltInput(e.target.value)}
							onKeyDown={handleKeyDown}
						/>
					</div>

					{formError && (
						<div className="gs-error" role="alert">{formError}</div>
					)}

					<button className="gs-btn gs-btn--confirm" onClick={handleManualSubmit}>CONFIRM LOCATION</button>

				</div>
			)}

		</div>
	);

}