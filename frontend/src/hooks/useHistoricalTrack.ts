/**
 * Fetches a ground track for a specific TLE snapshot.
 *
 * This hook mirrors the shape of useGroundTrack exactly (same return type,
 * same loading/error states) but targets the historical path:
 *
 *   GET /satellite/{noradId}/groundtrack?snapshot_id={snapshotId}
 *
 * The backend looks up the TLE lines for that snapshot from the database and
 * propagates the orbit from the snapshot's epoch instead of the live TLE.
 * The response shape is identical to the live endpoint, so SatelliteMap can
 * render it without any special-casing.
 *
 * When snapshotId is null (the user is in "live" mode), the hook returns
 * null data immediately without making a network request. This lets callers
 * always call the hook unconditionally — React's rules of hooks require that
 * hooks are never called conditionally, so the null-guard lives inside the
 * hook rather than at the call site.
 *
 * There is intentionally no polling interval here. A historical snapshot
 * is static: the TLE for a given epoch will never change in the database.
 * The fetch runs once when snapshotId first becomes non-null and again if
 * snapshotId changes (user drags the slider to a different date). After that
 * the data sits in React state until the user clears the selection.
 */

import { useState, useEffect, useCallback } from "react";
import type { GroundTrackCollection } from "./useGroundTrack";

export interface HistoricalTrackResult {
    data: GroundTrackCollection | null;
    loading: boolean;
    error: string | null;
}

const API_BASE = "/api";

export function useHistoricalTrack(
    noradId: number,
    snapshotId: number | null,
    durationMinutes = 90,
    stepSeconds = 60,
): HistoricalTrackResult {

    const [data, setData]       = useState<GroundTrackCollection | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError]     = useState<string | null>(null);

    const fetchTrack = useCallback(async (sid: number) => {

        setLoading(true);
        setError(null);
        setData(null);

        try {
            const url =
                `${API_BASE}/satellite/${noradId}/groundtrack` +
                `?snapshot_id=${sid}` +
                `&duration_minutes=${durationMinutes}` +
                `&step_seconds=${stepSeconds}`;

            const response = await fetch(url);

            if (!response.ok) {
                throw new Error(`API returned ${response.status}: ${response.statusText}`);
            }

            const json: GroundTrackCollection = await response.json();
            setData(json);

        } catch (err) {
            setError(
                err instanceof Error
                    ? err.message
                    : "Unknown error fetching historical track"
            );
        } finally {
            setLoading(false);
        }

    }, [noradId, durationMinutes, stepSeconds]);

    useEffect(() => {

        // When snapshotId becomes null (user returns to live mode), clear any
        // previously fetched data so the ghost track disappears from the map.
        if (snapshotId === null) {
            setData(null);
            setLoading(false);
            setError(null);
            return;
        }

        fetchTrack(snapshotId);

    }, [snapshotId, fetchTrack]);

    return { data, loading, error };
}