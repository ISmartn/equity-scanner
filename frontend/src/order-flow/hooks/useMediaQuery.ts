import { useCallback, useSyncExternalStore } from 'react';

/*
 * One MediaQueryList per query, and its answer kept as a plain boolean that the
 * list's own `change` event updates. `getSnapshot` runs on every render, and
 * reading `matches` there — even on a cached list — evaluates the query against
 * a style the render has just dirtied: a forced style recalc on every render,
 * 23% of a symbol switch's samples on the production build (Open Interest).
 */
interface Entry { source: typeof window.matchMedia; list: MediaQueryList; matches: boolean }
const entries = new Map<string, Entry>();

function entryFor(query: string): Entry | null {
  if (typeof window === 'undefined' || !window.matchMedia) return null;
  const known = entries.get(query);
  // Keyed on the function too, so a test that stubs `matchMedia` gets its own list.
  if (known && known.source === window.matchMedia) return known;
  const list = window.matchMedia(query);
  const entry: Entry = { source: window.matchMedia, list, matches: list.matches };
  // Registered before any subscriber, so the cache is current when React re-reads.
  list.addEventListener('change', event => { entry.matches = event.matches; });
  entries.set(query, entry);
  return entry;
}

/** Whether `query` matches now, re-rendering when it changes. False on the server. */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback((onChange: () => void) => {
    const list = entryFor(query)?.list;
    if (!list) return () => {};
    list.addEventListener('change', onChange);
    return () => list.removeEventListener('change', onChange);
  }, [query]);
  const read = useCallback(() => entryFor(query)?.matches ?? false, [query]);
  return useSyncExternalStore(subscribe, read, () => false);
}
