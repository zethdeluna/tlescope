/**
 * TLETimeline — historical TLE browser for a single satellite card.
 *
 * What this component does:
 *   1. Fetches the list of TLE snapshots from /satellite/{noradId}/tle_history.
 *   2. Renders a range slider over the available snapshots (oldest → newest).
 *   3. When the slider is dragged, calls useHistoricalTrack with the selected
 *      snapshot's id, then writes the resulting GeoJSON into the Zustand store
 *      via setHistoricalTrack — which causes SatelliteMap to render a ghost
 *      polyline alongside the live track.
 *   4. A "LIVE" button at the right of the slider resets to null (live mode),
 *      which clears the ghost track from the map.
 *
 * Why the slider index is local state but the track goes to the store:
 *   The slider only controls this one card — no other component needs to know
 *   which snapshot is currently selected. So the selected index lives in local
 *   useState. But the fetched historical track must reach SatelliteMap, which
 *   is a sibling component with no shared parent except App, so it goes through
 *   the Zustand store (the same pattern used by live tracks and pass predictions).
 *
 * The component only appears after at least one snapshot is stored, which means
 * it won't render on a completely fresh installation until the first scheduler
 * refresh cycle has run and persisted data to PostgreSQL. An empty-snapshot
 * state is handled gracefully by rendering nothing, keeping the card clean.
 */

import { useState, useEffect, useCallback } from "react";
import { useSatelliteStore } from "../store/satelliteStore";
import { useHistoricalTrack } from "../hooks/useHistoricalTrack";

const API_BASE = "/api";

// Shape of one item from the /tle_history response
interface TLESnapshotSummary {
    id: number;
    epoch: string;       // ISO 8601 UTC string
    fetched_at: string;
    line1: string;
    line2: string;
}

interface TLETimelineProps {
    noradId: number;
    color: string;   // satellite color from the store, for accent styling
}

// Format an ISO epoch string for display in the slider label
function formatEpoch(iso: string): string {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, {
        month: "short",
        day:   "numeric",
        year:  "numeric",
        hour:  "2-digit",
        minute:"2-digit",
    });
}

export function TLETimeline({ noradId, color }: TLETimelineProps) {

    // ── Snapshot list ─────────────────────────────────────────────────────────
    const [snapshots, setSnapshots]             = useState<TLESnapshotSummary[]>([]);
    const [snapshotsLoading, setSnapshotsLoading] = useState(true);
    const [snapshotsError, setSnapshotsError]   = useState<string | null>(null);

    // ── Slider state ──────────────────────────────────────────────────────────
    // null = live mode; a number = index into the snapshots array
    const [selectedIndex, setSelectedIndex]     = useState<number | null>(null);

    const { setHistoricalTrack, clearHistoricalTrack } = useSatelliteStore();

    // ── Fetch snapshot list ───────────────────────────────────────────────────
    const fetchSnapshots = useCallback(async () => {
        setSnapshotsLoading(true);
        setSnapshotsError(null);
        try {
            const response = await fetch(
                `${API_BASE}/satellite/${noradId}/tle_history`
            );
            if (!response.ok) {
                throw new Error(`API returned ${response.status}`);
            }
            const json = await response.json();
            setSnapshots(json.snapshots ?? []);
        } catch (err) {
            setSnapshotsError(
                err instanceof Error ? err.message : "Failed to load TLE history"
            );
        } finally {
            setSnapshotsLoading(false);
        }
    }, [noradId]);

    useEffect(() => {
        fetchSnapshots();
    }, [fetchSnapshots]);

    // ── Historical track fetch ────────────────────────────────────────────────
    // Derive the selected snapshot's id (or null for live mode)
    const selectedSnapshotId =
        selectedIndex !== null ? snapshots[selectedIndex]?.id ?? null : null;

    const { data: historicalData, loading: trackLoading } = useHistoricalTrack(
        noradId,
        selectedSnapshotId,
    );

    // Write historical track into the store whenever it changes
    useEffect(() => {
        if (selectedSnapshotId === null) {
            clearHistoricalTrack(noradId);
        } else if (historicalData) {
            setHistoricalTrack(noradId, historicalData);
        }
    }, [historicalData, selectedSnapshotId, noradId, setHistoricalTrack, clearHistoricalTrack]);

    // Clean up the historical track from the store when the component unmounts
    // (e.g. the satellite card is removed while a historical view is active)
    useEffect(() => {
        return () => clearHistoricalTrack(noradId);
    }, [noradId, clearHistoricalTrack]);

    // ── Handlers ──────────────────────────────────────────────────────────────
    const handleSliderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const idx = parseInt(e.target.value, 10);
        setSelectedIndex(idx);
    };

    const handleLive = () => {
        setSelectedIndex(null);
        clearHistoricalTrack(noradId);
    };

    // ── Render guards ─────────────────────────────────────────────────────────
    // Don't render anything while loading or if there's nothing stored yet.
    // The component should be invisible until there's something useful to show.
    if (snapshotsLoading) return null;
    if (snapshotsError)   return null;
    if (snapshots.length === 0) return null;

    const isLive          = selectedIndex === null;
    const selectedSnap    = isLive ? null : snapshots[selectedIndex!];
    const oldestEpoch     = snapshots[0].epoch;
    const newestEpoch     = snapshots[snapshots.length - 1].epoch;

    return (
        <div className="tle-timeline">

            {/* Section heading */}
            <div className="timeline-header">
                <span className="timeline-label" style={{ color }}>TLE HISTORY</span>
                <span className="timeline-count">{snapshots.length} snapshots</span>
            </div>

            {/* Date range labels */}
            <div className="timeline-range-labels">
                <span className="timeline-range-start">
                    {formatEpoch(oldestEpoch)}
                </span>
                <span className="timeline-range-end">
                    {formatEpoch(newestEpoch)}
                </span>
            </div>

            {/* Slider + live button row */}
            <div className="timeline-controls">
                <input
                    type="range"
                    className="timeline-slider"
                    min={0}
                    max={snapshots.length - 1}
                    step={1}
                    value={selectedIndex ?? snapshots.length - 1}
                    onChange={handleSliderChange}
                    style={{ "--thumb-color": color } as React.CSSProperties}
                    aria-label="Select historical TLE snapshot"
                />
                <button
                    className={`timeline-live-btn ${isLive ? "active" : ""}`}
                    onClick={handleLive}
                    title="Return to live tracking"
                    aria-pressed={isLive}
                >
                    LIVE
                </button>
            </div>

            {/* Selected snapshot info */}
            <div className="timeline-selection">
                {isLive ? (
                    <span className="timeline-live-indicator" style={{ color }}>
                        ● LIVE TLE
                    </span>
                ) : trackLoading ? (
                    <span className="timeline-fetching">⟳ LOADING HISTORICAL TRACK...</span>
                ) : selectedSnap ? (
                    <span className="timeline-epoch-display">
                        ◷ {formatEpoch(selectedSnap.epoch)}
                    </span>
                ) : null}
            </div>

        </div>
    );
}