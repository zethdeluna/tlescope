/**
 * Renders multiple satellite ground tracks simultaneously on a Leaflet map.
 *
 * As of Pillar 2, the map also accepts an optional 'historicalTracks' prop.
 * When a historical track is present for a satellite (the user has dragged the
 * TLETimeline slider to a past epoch), it is rendered as a ghost polyline in
 * the same color as the live track but at reduced opacity, with a wider dash
 * pattern to distinguish it visually. The live track continues to update and
 * render normally alongside it.
 *
 * Visual conventions:
 *   Live track — full 90-min path: dim dashed polyline at 50% opacity
 *   Live track — first ~15 min: bright solid polyline at 90% opacity
 *   Historical track: wider-dash polyline at 30% opacity (ghost effect)
 *   Current position: filled CircleMarker with outer ring
 *   Historical position marker: hollow CircleMarker at the start of the
 *     historical track, labeled with an epoch hint
 *   Antimeridian crossings: polyline split into segments in all cases
 *   Ground station: crosshair-style triple concentric ring on its own layer
 */

import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { GroundTrackCollection } from "../hooks/useGroundTrack";
import type { SatelliteEntry, GroundStation } from "../store/satelliteStore";

export interface ActiveTrack {
    satellite: SatelliteEntry;
    data: GroundTrackCollection;
}

interface SatelliteMapProps {
    tracks: ActiveTrack[];
    groundStation?: GroundStation | null;
    historicalTracks?: Record<number, GroundTrackCollection | null>;
}

// Split a path at antimeridian crossings so Leaflet doesn't draw a line
// spanning the full map width when a satellite crosses the ±180° meridian.
function splitAtAntimeridian(latLngs: L.LatLngTuple[]): L.LatLngTuple[][] {
    const segments: L.LatLngTuple[][] = [];
    let current: L.LatLngTuple[] = [latLngs[0]];
    for (let i = 1; i < latLngs.length; i++) {
        const prevLon = latLngs[i - 1][1];
        const currLon = latLngs[i][1];
        if (Math.abs(currLon - prevLon) > 180) {
            segments.push(current);
            current = [];
        }
        current.push(latLngs[i]);
    }
    segments.push(current);
    return segments;
}

export function SatelliteMap({ tracks, groundStation, historicalTracks = {} }: SatelliteMapProps) {

    const mapContainerRef   = useRef<HTMLDivElement>(null);
    const mapRef            = useRef<L.Map | null>(null);
    const trackLayerRef     = useRef<L.LayerGroup | null>(null);
    const historicalLayerRef = useRef<L.LayerGroup | null>(null);
    const gsLayerRef        = useRef<L.LayerGroup | null>(null);

	// Initialize map
    useEffect(() => {
        if (!mapContainerRef.current || mapRef.current) return;

        mapRef.current = L.map(mapContainerRef.current, {
            center: [0, 0],
            zoom: 2,
            zoomControl: true,
        });

        L.tileLayer(
            "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
            {
                attribution:
                    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> ' +
                    'contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
                subdomains: "abcd",
                maxZoom: 20,
            }
        ).addTo(mapRef.current);

        // Layer order matters: historical underneath live tracks, gs on top
        historicalLayerRef.current = L.layerGroup().addTo(mapRef.current);
        trackLayerRef.current      = L.layerGroup().addTo(mapRef.current);
        gsLayerRef.current         = L.layerGroup().addTo(mapRef.current);

        return () => {
            mapRef.current?.remove();
            mapRef.current = null;
        };
    }, []);

	// Live tracks
    useEffect(() => {
        if (!mapRef.current || !trackLayerRef.current || tracks.length === 0) return;

        trackLayerRef.current.clearLayers();

        for (const { satellite, data } of tracks) {
            const feature = data.features[0];
            const coords  = feature.geometry.coordinates;
            const color   = satellite.color;

            const latLngs: L.LatLngTuple[] = coords.map(([lon, lat]) => [lat, lon]);

            // Full 90-min path — dim dashed
            splitAtAntimeridian(latLngs).forEach(seg => {
                L.polyline(seg, {
                    color, weight: 1.5, opacity: 0.45, dashArray: "4 4",
                }).addTo(trackLayerRef.current!);
            });

            // Near-term 15-min path — bright solid
            const nearCount = Math.min(
                latLngs.length,
                Math.ceil((15 * 60) / feature.properties.step_seconds) + 1
            );
            splitAtAntimeridian(latLngs.slice(0, nearCount)).forEach(seg => {
                L.polyline(seg, {
                    color, weight: 2.5, opacity: 0.9,
                }).addTo(trackLayerRef.current!);
            });

            // Current position — filled dot + outer ring
            const [currentLat, currentLon] = latLngs[0];
            L.circleMarker([currentLat, currentLon], {
                radius: 7, fillColor: color, fillOpacity: 1,
                color: "#FFFFFF", weight: 1.5,
            })
                .bindTooltip(satellite.name, { permanent: false, className: "sat-tooltip" })
                .addTo(trackLayerRef.current);

            L.circleMarker([currentLat, currentLon], {
                radius: 14, fillColor: "transparent",
                color, weight: 1, opacity: 0.4,
            }).addTo(trackLayerRef.current);
        }
    }, [tracks]);

	// Historical ghost tracks
    // Re-drawn whenever the historicalTracks object reference changes (which
    // Zustand guarantees whenever any entry is added, updated, or cleared).
    useEffect(() => {
        if (!historicalLayerRef.current) return;

        historicalLayerRef.current.clearLayers();

        for (const { satellite } of tracks) {
            const histData = historicalTracks[satellite.noradId];
            if (!histData) continue;

            const feature = histData.features[0];
            const color   = satellite.color;
            const latLngs: L.LatLngTuple[] = feature.geometry.coordinates.map(
                ([lon, lat]) => [lat, lon]
            );

            // Ghost polyline — same color, wider dashes, lower opacity
            splitAtAntimeridian(latLngs).forEach(seg => {
                L.polyline(seg, {
                    color,
                    weight: 2,
                    opacity: 0.3,
                    dashArray: "10 6",
                }).addTo(historicalLayerRef.current!);
            });

            // Hollow circle at the historical "current" position so it's
            // easy to see where the satellite was at that epoch
            const [histLat, histLon] = latLngs[0];
            L.circleMarker([histLat, histLon], {
                radius: 6,
                fillColor: "transparent",
                fillOpacity: 0,
                color,
                weight: 1.5,
                opacity: 0.5,
            })
                .bindTooltip(
                    `${satellite.name} (historical)`,
                    { permanent: false, className: "sat-tooltip" }
                )
                .addTo(historicalLayerRef.current);
        }
    }, [tracks, historicalTracks]);

	// Ground station
    useEffect(() => {
        if (!gsLayerRef.current) return;
        gsLayerRef.current.clearLayers();
        if (!groundStation) return;

        const { lat, lon, label } = groundStation;
        const pos: L.LatLngTuple = [lat, lon];

        L.circleMarker(pos, {
            radius: 5, fillColor: "#FFFFFF", fillOpacity: 1,
            color: "#00FF88", weight: 2,
        })
            .bindTooltip(label ?? "GROUND STATION", {
                permanent: false, className: "sat-tooltip",
            })
            .addTo(gsLayerRef.current);

        L.circleMarker(pos, {
            radius: 11, fillColor: "transparent", fillOpacity: 0,
            color: "#00FF88", weight: 1.5, opacity: 0.7,
        }).addTo(gsLayerRef.current);

        L.circleMarker(pos, {
            radius: 19, fillColor: "transparent", fillOpacity: 0,
            color: "#00FF88", weight: 1, opacity: 0.3,
        }).addTo(gsLayerRef.current);

    }, [groundStation]);

    return (
        <div
            ref={mapContainerRef}
            style={{ width: "100%", height: "100%", background: "#0A0A0F" }}
        />
    );
}