/**
 * Search-and-select UI for the satellite catalog.
 * 
 * Key functions:
 * 	1. Accept raw user input and debounce it before passing to the catalog hook
 * 	2. Display the filtered results as a dropdown
 * 	3. Support keyboard navigation
 * 	4. Call setSelected in the Zustand store when the user picks an entry
 * 	   (triggers reactivity chain: store -> App -> useGroundTrack -> map)
 * 	5. Close dropdown when user clicks outside the component
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { useSatelliteCatalog } from '../hooks/useSatelliteCatalog';
import { useSatelliteStore, MAX_TRACKED } from '../store/satelliteStore';

const DEBOUNCE_MS = 200;

export function SatelliteSearch() {

	const [query, setQuery] = useState('');
	const [debouncedQuery, setDebouncedQuery] = useState('');
	const [activeIndex, setActiveIndex] = useState(-1);

	const wrapperRef = useRef<HTMLDivElement>(null);
	const inputRef = useRef<HTMLInputElement>(null);
	const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

	const { results, catalog, loading } = useSatelliteCatalog(debouncedQuery);
	const { toggleSatellite, isSelected, selectedSatellites } = useSatelliteStore();

	const atCapacity = selectedSatellites.length >= MAX_TRACKED;

	// Debounce search - only propagate query to the catalog hook after 200ms of silence
	useEffect(() => {

		clearTimeout(debounceTimerRef.current);

		debounceTimerRef.current = setTimeout(() => {

			setDebouncedQuery(query);
			setActiveIndex(-1);

		}, DEBOUNCE_MS);

		return () => clearTimeout(debounceTimerRef.current);

	}, [query]);

	// Click outside to close
	useEffect(() => {

		function handleMouseDown(e: MouseEvent) {
			if ( wrapperRef.current && !wrapperRef.current.contains(e.target as Node) ) {
				setQuery('');
			}
		}

		document.addEventListener('mousedown', handleMouseDown);

		return () => document.removeEventListener('mousedown', handleMouseDown);

	}, []);

	// Toggle satellites
	const handleSelect = useCallback((noradId: number, name: string) => {

		const tracked = isSelected(noradId);

		if ( atCapacity && !tracked ) return;

		toggleSatellite(noradId, name);
		setQuery('');
		inputRef.current?.blur();

	}, [toggleSatellite, isSelected, atCapacity]);

	// Keyboard navigation
	const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {

		if ( !results.length ) return;

		switch (e.key) {

			case 'ArrowDown':
				e.preventDefault();
				setActiveIndex(i => Math.min(i + 1, results.length - 1));
				break;

			case 'ArrowUp':
				e.preventDefault();
				setActiveIndex(i => Math.max(i - 1, 0));
				break;

			case 'Enter':
				if ( activeIndex >= 0 ) {
					e.preventDefault();
					const entry = results[activeIndex];
					handleSelect(entry.norad_id, entry.name);
				}
				break;

			case 'Escape':
				setQuery('');
				inputRef.current?.blur();
				break;

		}

	}, [results, activeIndex, handleSelect]);

	const isOpen = debouncedQuery.length > 0;

	return (
		<div className="search-wrapper" ref={wrapperRef}>

			{/* Input row */}
			<div className="search-input-row">

				<span className="search-prompt">&gt;_</span>

				<input 
					ref={inputRef} 
					className="search-input" 
					type="text" 
					placeholder="FIND SATELLITE..." 
					value={query} 
					onChange={e => setQuery(e.target.value)} 
					onKeyDown={handleKeyDown} 
					spellCheck={false} 
					autoComplete="off" 
					autoCorrect="off" 
					autoCapitalize="off" 
				/>

				{!loading && catalog.length > 0 && (
					<span className="search-catalog-size" data-at-capacity={atCapacity}>
						{atCapacity ? "MAX" : catalog.length.toLocaleString()}
					</span>
				)}

			</div>

			{/* Dropdown */}
			{isOpen && (
				<div className="search-dropdown" role="listbox">

					{results.length === 0 ? (

						<div className="search-no-results">NO MATCH</div>

					) : (

						results.map((entry, i) => {

							const isActive = i === activeIndex;
							const isTracked = isSelected(entry.norad_id);
							const canSelect = isTracked || !atCapacity;
							const trackedEntry = selectedSatellites.find(s => s.noradId === entry.norad_id);

							return (
								<div 
									key={entry.norad_id} 
									className="search-result" 
									role="option" 
									aria-selected={isTracked} 
									data-active={isActive} 
									data-tracked={isTracked} 
									data-disabled={!canSelect} 
									onMouseEnter={() => setActiveIndex(i)}
									onMouseDown={e => e.preventDefault()}
									onClick={() => canSelect && handleSelect(entry.norad_id, entry.name)}
								>

									{/* Color swatch */}
									{isTracked && trackedEntry && (
										<span 
											className="result-color-swatch" 
											style={{ background: trackedEntry.color }}
											aria-hidden="true"
										/>
									)}

									<span className="result-name">{entry.name}</span>
									<span className="result-norad">{entry.norad_id}</span>

									{/* Checkmark (if currently selected) */}
									{isTracked && (
										<span className="result-tracked-indicator" aria-label="tracked">✓</span>
									)}

								</div>
							);

						})

					)}

				</div>
			)}

		</div>
	);

}