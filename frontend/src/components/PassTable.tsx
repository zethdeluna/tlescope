/**
 * PassTable renders a compact list of upcoming satellite passes inside a 
 * satellite card in InfoPanel. It is only shown when a ground station is set 
 * and pass data is available in the store.
 * 
 * Elevation color-coding:
 * 	> 60°	- green (high quality overhead pass)
 * 	30-59°	- amber (good pass with reasonable sky clearance)
 * 	< 30°	- dim (low pass, horizon obstructions likely)
 */

import type { PassState } from "../store/satelliteStore";

interface PassTableProps {
	passState: PassState | undefined;
}

// Format total-seconds duration as "4m 32s"
function formatDuration(totalSeconds: number): string {

	const m = Math.floor(totalSeconds / 60);
	const s = Math.round(totalSeconds % 60);

	return `${m}m ${s.toString().padStart(2, "0")}s`;

}

// Format azimuth as "247° WSW"
function formatAzimuth(az: number): string {

	const dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
	const idx = Math.round(az / 22.5) % 16;

	return `${Math.round(az)}° ${dirs[idx]}`;

}

// Elevation class
function elClass(el: number): string {

	if ( el >= 60 ) return "pass-el pass-el--high";
	if ( el >= 30 ) return "pass-el pass-el--mid";
	return "pass-el pass-el--low";

}

// For truncating in the card
const VISIBLE_PASSES = 5;

export function PassTable({ passState }: PassTableProps) {

	if ( !passState ) return null;

	const { data, note, loading, error } = passState;

	if ( loading && !data ) {

		return (
			<div className="pass-table-wrap">
				<div className="pass-status">COMPUTING PASSES...</div>
			</div>
		);

	}

	if ( error && !data ) {

		return (
			<div className="pass-table-wrap">
				<div className="pass-status pass-status--error">⚠ {error}</div>
			</div>
		);

	}

	// GEO satellites
	if ( note ) {

		return (
			<div className="pass-table-wrap">
				<div className="pass-note">{note}</div>
			</div>
		);

	}

	if ( !data || data.length === 0 ) {

		return (
			<div className="pass-table-wrap">
				<div className="pass-status">NO PASSES WITHIN 3 DAYS</div>
			</div>
		);

	}

	const visible = data.slice(0, VISIBLE_PASSES);
	const remaining = data.length - VISIBLE_PASSES;

	return (
		<div className="pass-table-wrap">

			<div className="pass-table-header">
				<span className="pass-table-label">UPCOMING PASSES</span>
				<span className="pass-table-count">{data.length} IN 3 DAYS</span>
			</div>

			{/* Column headers */}
			<div className="pass-table-cols">
				<span>RISE (LOCAL)</span>
				<span>MAX EL</span>
				<span>PEAK AZ</span>
				<span>DUR</span>
			</div>

			{/* One row per pass */}
			{visible.map((pass, i) => {

				const riseDate = new Date(pass.rise.time);

				// Flag passes that start before "now" as partial
				const partialTag = pass.partial
					? <span className="pass-partial" title="Satellite already above horizon at window start">~</span>
					: null
				;

				return (
					<div key={i} className="pass-row">

						<span className="pass-cell pass-cell--time">
							{partialTag}
							{riseDate.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
							<span className="pass-date">
								{riseDate.toLocaleDateString([], { month: "short", day: "numeric" })}
							</span>
						</span>

						<span className={`pass-cell ${elClass(pass.apex.el_deg)}`}>
							{pass.apex.el_deg.toFixed(1)}°
						</span>

						<span className="pass-cell pass-cell--az">
							{formatAzimuth(pass.apex.az_deg)}
						</span>

						<span className="pass-cell pass-cell--dur">
							{formatDuration(pass.duration_seconds)}
						</span>

					</div>
				);

			})}

			{/* Overflow hint */}
			{remaining > 0 && (
				<div className="pass-overflow">+{remaining} MORE</div>
			)}

		</div>
	);

}