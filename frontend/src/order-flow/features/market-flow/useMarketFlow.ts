import { useEffect, useMemo, useRef, useState } from 'react';
import { getThemeDirectory, type Underlying } from '@/order-flow/lib/underlyings';
import { useFuturesFeed, useMarketFeed } from './feed';
import { buildMarketFlow, nearSeries, type FlowSettings, type MarketFlow } from './marketFlowModel';

/** While the futures arrive the board is rebuilt at most this often, so a burst of arrivals is one redraw. */
export const COMMIT_MS = 750;

/**
 * The board's two reads, both from the page's own server (feed.ts): the market
 * file (every underlying's option chain, once a minute) for spot, previous
 * close and the option open interest; and each underlying's futures, for the
 * direction and the build-up.
 *
 * The futures arrive over a minute or two for the whole list. The board draws
 * from the market file at once (spot change stands in for the day window
 * until the future is read) and fills in as the futures land, NIFTY first (it
 * is the chart's reference line), then the biggest spot movers. Arrivals are
 * gathered and committed at most every COMMIT_MS.
 */
export function useMarketFlow(universe: readonly Underlying[], settings: FlowSettings) {
  const data = useMarketFeed();
  const market = data.market;
  const sectorLabels = useMemo(() => {
    const labels = getThemeDirectory()?.sectors ?? {};
    return Object.fromEntries(Object.entries(labels).map(([id, entry]) => [id, entry.label])) as Record<string, string>;
  }, []);

  // In scope and listed in the market file: NIFTY first, then the biggest spot movers.
  const symbols = useMemo(() => {
    if (!market) return [] as string[];
    const rows: Array<{ symbol: string; move: number }> = [];
    for (const item of universe) {
      if (settings.scope === 'stocks' && item.kind !== 'stock') continue;
      if (settings.scope === 'indices' && item.kind !== 'index') continue;
      const series = nearSeries(market, item.symbol);
      if (!series) continue;
      const move = item.symbol === 'NIFTY' ? Infinity : series.spotPrevClose ? Math.abs(series.spot / series.spotPrevClose - 1) : 0;
      rows.push({ symbol: item.symbol, move });
    }
    return rows.sort((a, b) => b.move - a.move || a.symbol.localeCompare(b.symbol)).map(row => row.symbol);
  }, [market, universe, settings.scope]);

  const futures = useFuturesFeed(symbols, Boolean(market), data.status);
  const live = useMemo(() => ({ series: futures.series, failed: futures.failed }), [futures.series, futures.failed]);
  const committed = useThrottled(live, COMMIT_MS, futures.read >= futures.total);

  // The settings that change the chart only (lines, named) do not re-deal the board.
  const { window: win, scope, floorPct } = settings;
  const flow: MarketFlow | null = useMemo(
    () => (market ? buildMarketFlow(market, committed.series, universe, sectorLabels, { window: win, scope, floorPct, named: null, lines: 'all' }, { failed: committed.failed }) : null),
    [market, committed, universe, sectorLabels, win, scope, floorPct],
  );

  return {
    flow,
    market,
    loading: data.loading,
    error: data.error,
    provider: data.status?.provider ?? null,
    futuresRead: futures.read,
    futuresTotal: futures.total,
    session: futures.session,
    rescan: data.rescan,
  };
}

/**
 * A value that follows `value` at most once every `ms`: the first change goes
 * through at once, later ones are gathered and the latest is committed at the
 * end of the interval. `flush` commits at once (the last arrival).
 */
export function useThrottled<T>(value: T, ms: number, flush = false): T {
  const [held, setHeld] = useState(value);
  const last = useRef(0);
  const latest = useRef(value);
  latest.current = value;
  useEffect(() => {
    if (Object.is(value, held)) return undefined;
    const wait = flush ? 0 : Math.max(0, last.current + ms - Date.now());
    const timer = window.setTimeout(() => { last.current = Date.now(); setHeld(latest.current); }, wait);
    return () => window.clearTimeout(timer);
  }, [value, held, ms, flush]);
  return held;
}
