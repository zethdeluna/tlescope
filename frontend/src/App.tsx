/**
 * Root component: owns the app shell, header, headless data loaders, map,
 * and the info panel.
 *
 * As of Pillar 2, App.tsx pulls the historicalTracks slice from the Zustand
 * store and forwards it to SatelliteMap, which renders historical TLE paths
 * as ghost polylines whenever a TLETimeline slider is active in the sidebar.
 */

import { useSatelliteStore } from "./store/satelliteStore";
import { SatelliteTrackLoader } from "./components/SatelliteTrackLoader";
import { SatelliteMap } from "./components/SatelliteMap";
import { InfoPanel } from "./components/InfoPanel";
import { SatelliteSearch } from "./components/SatelliteSearch";
import type { ActiveTrack } from "./components/SatelliteMap";
import './App.css';

export default function App() {

    const { selectedSatellites, tracks, groundStation, historicalTracks } =
        useSatelliteStore();

    // Build the list of satellites that have live track data ready to display
    const activeTracks = selectedSatellites.reduce<ActiveTrack[]>((acc, sat) => {
        const trackData = tracks[sat.noradId]?.data;
        if (trackData) acc.push({ satellite: sat, data: trackData });
        return acc;
    }, []);

    const isInitialLoading = activeTracks.length === 0;

    return (
        <div className="app-shell">

            {/* Header bar */}
            <header className="app-header">
                <div className="header-left">
                    <span className="header-logo">◎</span>
                    <span className="header-title">ORBITAL TRACKER</span>
                    <span className="header-sub">SGP4 • CELESTRAK • LIVE</span>
                </div>
                <SatelliteSearch />
                <div className="header-right">
                    <span className="header-algo">SGP4/SDP4</span>
                    <span className="header-frame">ECI → ECEF → WGS-84</span>
                </div>
            </header>

            {/* Headless data loaders — one per selected satellite */}
            {selectedSatellites.map(sat => (
                <SatelliteTrackLoader key={sat.noradId} satellite={sat} />
            ))}

            {/* Main layout */}
            <main className="app-body">
                <div className="map-area">
                    {activeTracks.length > 0 && (
                        <SatelliteMap
                            tracks={activeTracks}
                            groundStation={groundStation}
                            historicalTracks={historicalTracks}
                        />
                    )}
                    {isInitialLoading && (
                        <div className="map-overlay">
                            <div className="loader-ring" />
                            <p className="loader-text">ACQUIRING SIGNAL...</p>
                        </div>
                    )}
                </div>
                <InfoPanel />
            </main>

        </div>
    );
}