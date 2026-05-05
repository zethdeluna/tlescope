/**
 * Fetches the full satellite catalog from the backend once on mount.
 * 
 * Returns a search-filtered subset based on a caller-supplied query string.
 * 
 * Uses:
 * 	1. Own the one-time catalog fetch (loading, error state)
 * 	2. Derive filtered results from query via useMemo (no extra state, no extra fetch, no extra side effects)
 */

import { useState, useEffect, useMemo } from 'react';

export interface CatalogEntry {
	name: string;
	norad_id: number;
}

interface UseSatelliteCatalogResult {
	catalog: CatalogEntry[];
	results: CatalogEntry[];
	loading: boolean;
	error: string | null;
}

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";
const MAX_RESULTS = 20;

export function useSatelliteCatalog(query: string): UseSatelliteCatalogResult {

	const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);

	// One-time catalog fetch on mount
	useEffect(() => {

		let cancelled = false;

		async function fetchCatalog() {

			try {

				const response = await fetch(`${API_BASE}/satellites`);

				if ( !response.ok ) {
					throw new Error(`API returned ${response.status}: ${response.statusText}`);
				}

				const data: CatalogEntry[] = await response.json();

				// Only update if the component is still mounted
				if ( !cancelled ) {
					setCatalog(data);
				}

			} catch (err) {

				if ( !cancelled ) {
					setError(err instanceof Error ? err.message : "Unknown error fetching satellite catalog");
				}

			} finally {

				if ( !cancelled ) {
					setLoading(false);
				}

			}

		}

		fetchCatalog();

		return () => {
			cancelled = true;
		}

	}, []);

	// Derive filtered results from the query string
	const results = useMemo(() => {

		const q = query.trim().toLowerCase();

		if ( !q ) return [];

		const filtered = catalog.filter(entry => {

			// Primary match: satellite name
			const nameMatch = entry.name.toLowerCase().includes(q);

			// Secondary match: NORAD ID
			const idMatch = String(entry.norad_id).startsWith(q);

			return nameMatch || idMatch;

		});

		return filtered.slice(0, MAX_RESULTS);

	}, [query, catalog]);

	return { catalog, results, loading, error };

}