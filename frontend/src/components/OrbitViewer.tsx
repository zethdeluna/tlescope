/**
 * Renders a 3D rotating Earth with the satellite's orbital ellipse using 
 * CesiumJS via the resium React wrapper.
 * 
 * Architecture:
 * 	- Reads Orbit3DState from the Zustand store (written by useOrbit3D in 
 * 	  SatelliteTrackLoader) - never fetches data itself.
 * 	- Supports multiple satellites. Each SatelliteEntry passed in becomes an 
 * 	  Entity with its own SampledPositionProperty and matching track color.
 * 	- Lazy-loadable: This file is the bounddary for React.lazy(). Cesium's 
 * 	  ~6MB bundle is only downloaded when the user clicks "3D VIEW" for the 
 * 	  first time.
 * 
 * Cesium coordinate notes:
 * 	The backend returns ECEF in kilometers. Cesium's Cartesian3 expects meters.
 * 	Every position component is multiplied by 1000 exactly once here.
 * 
 * Clock setup:
 * 	The viewer clock is set to the current UTC time and runs at 60x real-time 
 * 	so a ~93-minute ISS orbit completes in ~1.5 minutes of wall time, making 
 * 	the orbital motion immediately visible without waiting hours.
 */

import { useMemo, useRef, useEffect } from "react";
import { Viewer, Entity, CameraFlyTo } from "resium";
import * as Cesium from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";

import { useSatelliteStore } from "../store/satelliteStore";
import type { SatelliteEntry, Orbit3DResponse } from "../store/satelliteStore";

// Cesium Ion token is injected at build time via Vite's import.meta.env.
// Without a valid token, Cesium falls back to offline-mode assets (no satellite 
// imagery, but the 3D globe and orbital ellipse still render).
Cesium.Ion.defaultAccessToken = import.meta.env.VITE_CESIUM_TOKEN ?? "";

interface OrbitViewerProps {
	satellites: SatelliteEntry[];
	onClose: () => void;
}

/**
 * Build a SampledPositionProperty (ECEF, meters) from the backend's km positions.
 * Returns null while data is still loading.
 */
function buildPositionProperty( orbit: Orbit3DResponse ): Cesium.SampledPositionProperty {

	const property = new Cesium.SampledPositionProperty(
		Cesium.ReferenceFrame.FIXED // ECEF
	);

	orbit.positions.forEach(p => {

		const time = Cesium.JulianDate.fromIso8601(p. time);
		const pos = new Cesium.Cartesian3(
			p.x_km * 1000,
			p.y_km * 1000,
			p.z_km * 1000
		);

		property.addSample(time, pos);

	});

	// Lagrange interpolation smooths the path between the 200 samples, 
	// preventing the orbit from appearing as a 200-segment polyline
	property.setInterpolationOptions({
		interpolationDegree:	5,
		interpolationAlgorithm:	Cesium.LagrangePolynomialApproximation
	});

	return property;

}

/**
 * Pre-satellite entity
 */
interface SatEntityProps {
	sat:	SatelliteEntry;
	orbit:	Orbit3DResponse;
}

function SatEntity({ sat, orbit }: SatEntityProps) {

	const positionProperty = useMemo(
		() => buildPositionProperty(orbit),
		[orbit.positions]
	);

	const cesiumColor = useMemo(
		() => Cesium.Color.fromCssColorString(sat.color),
		[sat.color]
	);

	const glowColor = useMemo(
		() => Cesium.Color.fromCssColorString(sat.color).withAlpha(0.6),
		[sat.color]
	);

	// Time range: start = first sample, stop = last sample
	const startTime = Cesium.JulianDate.fromIso8601(orbit.positions[0].time);
	const stopTime = Cesium.JulianDate.fromIso8601(orbit.positions[orbit.positions.length - 1].time);

	return (
		<Entity 
			name={sat.name} 
			position={positionProperty} 
			availability={new Cesium.TimeIntervalCollection([
				new Cesium.TimeInterval({ start: startTime, stop: stopTime })
			])} 
			point={{
				pixelSize: 12,
				color: cesiumColor,
				outlineColor: Cesium.Color.BLACK,
				outlineWidth: 1,
				disableDepthTestDistance: Number.POSITIVE_INFINITY
			}} 
			path={{
				leadTime: orbit.period_minutes * 60,
				trailTime: orbit.period_minutes * 60,
				width: 2,
				resolution: 60,

				material: new Cesium.PolylineGlowMaterialProperty({
					glowPower: 0.2,
					color: glowColor
				})
			}} 
			label={{
				text: sat.name,
				font: "11px monospace",
				fillColor: cesiumColor,
				outlineColor: Cesium.Color.BLACK,
				outlineWidth: 2,
				style: Cesium.LabelStyle.FILL_AND_OUTLINE,
				pixelOffset: new Cesium.Cartesian2(14, 0),
				disableDepthTestDistance: Number.POSITIVE_INFINITY,
				translucencyByDistance: new Cesium.NearFarScalar(1e6, 1, 3e7, 0)
			}}
		/>
	);

}

/**
 * Main component
 */
export default function OrbitViewer({ satellites, onClose }: OrbitViewerProps) {

	const orbit3DData = useSatelliteStore(s => s.orbit3DData);
	const viewerRef = useRef<{ cesiumElement: Cesium.Viewer } | null>(null);

	// Configure the Cesium clock once on mount (start at now, run at 60x)
	useEffect(() => {

		const viewer = viewerRef.current?.cesiumElement;
		if ( !viewer ) return;

		const now = Cesium.JulianDate.now();

		viewer.clock.startTime		= now;
		viewer.clock.currentTime	= Cesium.JulianDate.clone(now);
		viewer.clock.multiplier		= 60;
		viewer.clock.shouldAnimate	= true;
		viewer.clock.clockRange		= Cesium.ClockRange.LOOP_STOP;

		// Stop time: 200 minutes from now covers any orbital period we'll show
		viewer.clock.stopTime = Cesium.JulianDate.addMinutes(now, 200, new Cesium.JulianDate());

		// Start from a comfortable high-alt view of Earth
		viewer.camera.flyHome(0);

	}, []);

	// Collect satellites that have loaded orbit data
	const readySats = satellites.filter(sat => orbit3DData[sat.noradId]?.data != null);
	const loadingSats = satellites.filter(sat => orbit3DData[sat.noradId]?.loading);
	const errorSats = satellites.filter(sat => orbit3DData[sat.noradId]?.error)

	// Camera destination: initial view centered on the first loaded satellite's 
	// current position, or default to high-alt Earth.
	const initialDestination = useMemo(() => {

		const firstOrbit = readySats[0]
			? orbit3DData[readySats[0].noradId]?.data
			: null
		;

		if ( firstOrbit && firstOrbit.positions.length > 0 ) {

			const p = firstOrbit.positions[0];

			return new Cesium.Cartesian3(p.x_km * 1000, p.y_km * 1000, p.z_km * 1000);

		}

		// Default: straight-down view of Earth at ~20,000km
		return Cesium.Cartesian3.fromDegrees(0, 20, 200_000_000);

	}, [readySats.length]);

	return (
		<div className="orbit-viewer-container">

			{/* CesiumJS globe */}
			<Viewer 
				ref={viewerRef} 
				full={false} 
				className="orbit-cesium-viewer" 
				animation={true} 
				baseLayerPicker={false} 
				fullscreenButton={false} 
				geocoder={false} 
				homeButton={true} 
				infoBox={false} 
				navigationHelpButton={false} 
				sceneModePicker={false} 
				selectionIndicator={false} 
				timeline={true} 
				terrainProvider={undefined}
			>
				
				{/* Fly camera to initial position once data is ready */}
				{readySats.length > 0 && (
					<CameraFlyTo 
						destination={initialDestination} 
						duration={1.5} 
						once
					/>
				)}

				{/* Render one entity per ready satellite */}
				{readySats.map(sat => {

					const orbit = orbit3DData[sat.noradId]!.data!;

					return (
						<SatEntity 
							key={sat.noradId} 
							sat={sat} 
							orbit={orbit} 
						/>
					)

				})}

			</Viewer>

			{/* Legend */}
			{readySats.length > 0 && (
				<div className="orbit-viewer-legend">
					{readySats.map(sat => (
						<span key={sat.noradId} className="orbit-legend-item">
							<span 
								className="orbit-legend-dot" 
								style={{ background: sat.color }}
							/>
							{sat.name}
						</span>
					))}
				</div>
			)}

		</div>
	);

}