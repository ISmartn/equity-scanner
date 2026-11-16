import type { Underlying } from '@/order-flow/lib/underlyings';
import { isExpirySettled, marketSessionBounds } from '@/order-flow/lib/marketSession';
import type { ContractMarket, ContractSeries } from '../options-scanner/contractScanModel';
import { readFuturesWindow, type FuturesBuildUp, type FuturesReading, type FuturesSeries } from '../options-scanner/futuresModel';

/**
 * Order Flow: every F&O underlying on one board, read from its FUTURES and
 * sorted into the side it moved on, the way its positions moved and the
 * strength of that reading, with the heaviest option positions either side of
 * spot as the levels and the stretch of the session where positions were
 * added fastest as the zone.
 *
 * Nothing here is a new measurement. The direction and the build-up are the
 * Options Scanner's own futures reading (readFuturesWindow): the near-month
 * future's price change against the change in open interest over the chosen
 * window, open interest summed over every listed month. The levels are the
 * market file's option open interest. This file only sorts, counts and
 * compares; the page says which figure each mark is.
 *
 * Sides are states, never calls: bullish and bearish name which way the
 * future moved past the floor; rangebound names a move inside it.
 */

export type FlowWindow = 'day' | '1h' | '15m';
export type FlowSide = 'bullish' | 'bearish' | 'rangebound';
export type FlowScope = 'all' | 'stocks' | 'indices';
/** The four ways open interest can move with price; a future with no change on either side is in no bucket. */
export type FlowBucket = Exclude<FuturesBuildUp, 'NEUTRAL'>;
export type SectorLean = FlowSide | 'mixed';

export interface FlowSettings {
  window: FlowWindow;
  scope: FlowScope;
  /** Smallest move, in %, that counts as a direction; null is the window's own floor (FLOOR_DEFAULT). */
  floorPct: number | null;
  /** How many lines each side names on the chart; null is as many as the chart's height suits. */
  named: number | null;
  /** Every underlying's line on the chart, or the middle 80% as a band with its median. */
  lines: 'all' | 'band';
}

/** The move a window must show before an underlying is called bullish or bearish rather than rangebound. */
export const FLOOR_DEFAULT: Record<FlowWindow, number> = { day: 0.5, '1h': 0.3, '15m': 0.15 };
export const NAMED_COUNTS = [3, 5, 8] as const;
export const DEFAULT_FLOW_SETTINGS: FlowSettings = { window: 'day', scope: 'all', floorPct: null, named: null, lines: 'all' };
/** How many underlyings each side shows as a large card. */
export const FEATURED_PER_SIDE = 3;
/**
 * The share of futures that must be settled (read, not listed or failed)
 * before the large cards are chosen: until then a spot change stands in for
 * most of the board and the choice would change under the reader.
 */
export const FEATURED_HOLD_SHARE = 0.9;
/** The session the chart and the readings span ends at 15:30 IST: later candles are the closing session's. */
export const SESSION_END_MINUTE = 15 * 60 + 30;
export const WINDOW_LABEL: Record<FlowWindow, string> = { day: 'Day', '1h': '1 hour', '15m': '15 minutes' };
export const WINDOW_SCOPE: Record<FlowWindow, string> = { day: 'since the previous close', '1h': 'over the last hour', '15m': 'over the last 15 minutes' };
/** Minutes each window spans across the plane; the day is the whole session. */
export const SCAN_MINUTES: Record<FlowWindow, number> = { day: 375, '1h': 60, '15m': 15 };

/** The stretch of the session the zone is read over: the span with the most open interest added while price moved with the side. */
export const ZONE_SPAN_MINUTES = 15;
const MINUTE = 60_000;

export const floorFor = (settings: Pick<FlowSettings, 'window' | 'floorPct'>): number => settings.floorPct ?? FLOOR_DEFAULT[settings.window];

export interface FlowLevel {
  strike: number;
  /** Open interest at the strike, units, and its change since the previous close (null when the file has no previous reading). */
  oi: number;
  oiChange: number | null;
  /** Distance from spot, % (positive above spot). */
  distancePct: number;
}

export interface FlowZone {
  low: number;
  high: number;
  /** Epoch ms of the span's first candle, and the end of its last. */
  from: number;
  to: number;
  oiAdded: number;
}

export type FlowCheckId = 'fresh' | 'spot' | 'day' | 'hour' | 'quarter' | 'options' | 'sector';

/** One reason the reading holds or does not: pass, fail, or null when the figure it needs is not there (not counted). */
export interface FlowCheck {
  id: FlowCheckId;
  label: string;
  pass: boolean | null;
  note: string;
}

export interface FlowCandle { at: number; close: number; oi: number }

export interface FlowProfileRow { strike: number; put: number; call: number }

/** How many strikes either side of spot the profile keeps. */
export const PROFILE_STRIKES = 8;

/** Option open interest by strike, the PROFILE_STRIKES strikes either side of spot, low to high. */
export function oiProfile(series: Pick<ContractSeries, 'quotes' | 'spot'>, perSide = PROFILE_STRIKES): FlowProfileRow[] {
  const byStrike = new Map<number, FlowProfileRow>();
  for (const quote of series.quotes) {
    if (!(quote.oi > 0)) continue;
    const row = byStrike.get(quote.strike) ?? { strike: quote.strike, put: 0, call: 0 };
    if (quote.side === 'PE') row.put += quote.oi; else row.call += quote.oi;
    byStrike.set(quote.strike, row);
  }
  const rows = [...byStrike.values()].sort((a, b) => a.strike - b.strike);
  const below = rows.filter(row => row.strike <= series.spot).slice(-perSide);
  const above = rows.filter(row => row.strike > series.spot).slice(0, perSide);
  return [...below, ...above];
}

export interface FlowStock {
  symbol: string;
  name: string;
  kind: 'index' | 'stock';
  sector: string;
  sectorLabel: string;
  lot: number;
  expiry: string;
  spot: number;
  prevClose: number | null;
  spotChangePct: number | null;
  /** The future over the chosen window, and over the other windows the checks compare with. */
  fut: FuturesReading | null;
  futDay: FuturesReading | null;
  futHour: FuturesReading | null;
  futQuarter: FuturesReading | null;
  /** pending: not read yet; unavailable: the service lists no future for it; failed: the read failed (twice); read: candles arrived. */
  futures: 'pending' | 'unavailable' | 'failed' | 'read';
  /** The figure the board sorts on: the future's change over the window, else the spot's day change (day window only). */
  changePct: number | null;
  source: 'futures' | 'spot' | null;
  oiChangePct: number | null;
  buildUp: FuturesBuildUp | null;
  /** Null until a change can be measured. */
  side: FlowSide | null;
  options: {
    putOi: number;
    callOi: number;
    /** Units added since the previous close on each side; null when the file carries no previous open interest. */
    putOiAdded: number | null;
    callOiAdded: number | null;
    pcr: number | null;
  };
  support: FlowLevel | null;
  support2: FlowLevel | null;
  resistance: FlowLevel | null;
  resistance2: FlowLevel | null;
  zone: FlowZone | null;
  /** Option open interest by strike around spot, nearest strikes, low to high: the profile the tall tiles draw. */
  profile: FlowProfileRow[];
  /** Why there is no zone, when there is none. */
  zoneNote: string | null;
  checks: FlowCheck[];
  /** 0–1 within its side: how far the move, how much open interest moved with it, how many checks hold. */
  strength: number;
  /** Place on its side by the size of the move (futures first, then spot-only), 1 the largest; null off the sides. */
  rank: number | null;
  candles: readonly FlowCandle[];
}

export interface FlowSector {
  id: string;
  label: string;
  count: number;
  bullish: number;
  bearish: number;
  rangebound: number;
  unread: number;
  lean: SectorLean;
  /** The median change of its measured underlyings, %; null until one is measured. */
  changePct: number | null;
  symbols: string[];
}

export interface MarketFlow {
  asOf: number;
  date: string;
  window: FlowWindow;
  floorPct: number;
  stocks: FlowStock[];
  sectors: FlowSector[];
  bullish: FlowStock[];
  bearish: FlowStock[];
  rangebound: FlowStock[];
  unread: FlowStock[];
  buckets: Record<FlowBucket, FlowStock[]>;
  /** Each side's large cards: the strongest positions opened with the move. Empty while the futures are still mostly unread. */
  featured: { bullish: FlowStock[]; bearish: FlowStock[] };
  futures: { read: number; unavailable: number; failed: number; pending: number; total: number; latestAt: number | null };
  /** True while futures are still being read: the counts are partly spot changes and will move. */
  provisional: boolean;
}

export interface FlowBuildOptions {
  /** Underlyings whose futures read failed: told apart from those with no future listed. */
  failed?: ReadonlySet<string>;
  /** The clock, for which expiries have settled. */
  now?: number;
}

export const BUCKET_SIDE: Record<FlowBucket, Exclude<FlowSide, 'rangebound'>> = {
  LONG_BUILD: 'bullish', SHORT_COVER: 'bullish', SHORT_BUILD: 'bearish', LONG_UNWIND: 'bearish',
};
/** Each side's buckets, positions opened first. */
export const SIDE_BUCKETS: Record<Exclude<FlowSide, 'rangebound'>, FlowBucket[]> = {
  bullish: ['LONG_BUILD', 'SHORT_COVER'], bearish: ['SHORT_BUILD', 'LONG_UNWIND'],
};

const INDEX_SECTOR = 'index';
const pct = (now: number, from: number | null) => (from != null && from > 0 ? ((now - from) / from) * 100 : null);
const sign = (value: number | null | undefined): -1 | 0 | 1 => (value == null || !(Math.abs(value) > 1e-9) ? 0 : value > 0 ? 1 : -1);

/**
 * The nearest live expiry's series for a symbol: the one the levels are read
 * from. An expiry dated the file's own day has settled once that day's
 * derivatives close has passed (isExpirySettled), and a file stamped at the
 * close is the settled series' last print, so on expiry day the next series
 * is taken. Only when nothing else is listed is the expiring one kept.
 */
export function nearSeries(market: ContractMarket, symbol: string, now: number = Date.now()): ContractSeries | null {
  let best: ContractSeries | null = null;
  let expiring: ContractSeries | null = null;
  const clock = Math.max(now, market.at);
  for (const series of market.series) {
    if (series.symbol !== symbol || series.expiry < market.date) continue;
    // The derivatives close itself counts: a file stamped 15:40 on expiry day is the expiring series' final print.
    if (series.expiry === market.date && (isExpirySettled(series.expiry, clock) || clock >= marketSessionBounds(Date.parse(`${market.date}T12:00:00+05:30`)).close)) {
      expiring = series;
      continue;
    }
    if (!best || series.expiry < best.expiry) best = series;
  }
  return best ?? expiring;
}

/** Epoch ms of a minute of the day on an IST date. */
export const sessionEndOf = (date: string, minuteOfDay: number = SESSION_END_MINUTE) => Date.parse(`${date}T00:00:00+05:30`) + minuteOfDay * MINUTE;

/** A future's candles up to 15:30 IST on its session date: what the readings and the chart both span. */
export function trimToSession(series: FuturesSeries, date: string): FuturesSeries {
  const end = sessionEndOf(date);
  const last = series.candles[series.candles.length - 1];
  if (!last || last.at + MINUTE <= end) return series;
  return { ...series, candles: series.candles.filter(candle => candle.at + MINUTE <= end) };
}

/** The heaviest open interest on one side of spot, and the second heaviest, as levels. */
export function heaviestLevels(series: ContractSeries, side: 'CE' | 'PE', spot: number): [FlowLevel | null, FlowLevel | null] {
  const candidates = series.quotes
    .filter(quote => quote.side === side && quote.oi > 0 && (side === 'CE' ? quote.strike >= spot : quote.strike <= spot))
    .sort((a, b) => b.oi - a.oi || Math.abs(a.strike - spot) - Math.abs(b.strike - spot));
  const level = (index: number): FlowLevel | null => {
    const quote = candidates[index];
    if (!quote) return null;
    return { strike: quote.strike, oi: quote.oi, oiChange: quote.prevOi == null ? null : quote.oi - quote.prevOi, distancePct: ((quote.strike - spot) / spot) * 100 };
  };
  return [level(0), level(1)];
}

/**
 * The zone: the ZONE_SPAN_MINUTES stretch of the session's futures candles in
 * which the most open interest was added while the price moved the side's
 * way, and the price range of that stretch. Null, with the reason, when no
 * stretch added open interest with the move.
 */
export function readZone(candles: readonly FlowCandle[], side: Exclude<FlowSide, 'rangebound'>): { zone: FlowZone | null; note: string | null } {
  if (candles.length < 2) return { zone: null, note: candles.length ? 'one futures candle is not a stretch' : 'no futures candles for this session' };
  const span = Math.min(ZONE_SPAN_MINUTES, candles.length);
  const direction = side === 'bullish' ? 1 : -1;
  let best: FlowZone | null = null;
  for (let end = span - 1; end < candles.length; end++) {
    const start = end - span + 1;
    const first = candles[start];
    const last = candles[end];
    const oiAdded = last.oi - first.oi;
    if (!(oiAdded > 0) || sign(last.close - first.close) !== direction) continue;
    if (best && oiAdded <= best.oiAdded) continue;
    let low = Infinity;
    let high = -Infinity;
    for (let i = start; i <= end; i++) { low = Math.min(low, candles[i].close); high = Math.max(high, candles[i].close); }
    best = { low, high, from: first.at, to: last.at + MINUTE, oiAdded };
  }
  return best ? { zone: best, note: null } : { zone: null, note: `no ${ZONE_SPAN_MINUTES}-minute stretch added open interest while the price moved this way` };
}

const sideOf = (changePct: number | null, floor: number): FlowSide | null =>
  changePct == null ? null : Math.abs(changePct) >= floor ? (changePct > 0 ? 'bullish' : 'bearish') : 'rangebound';

const sideWord = (side: Exclude<FlowSide, 'rangebound'>) => (side === 'bullish' ? 'up' : 'down');

/** Does a reading agree with the side? Null when there is no reading. */
function agrees(reading: FuturesReading | null, side: Exclude<FlowSide, 'rangebound'>): boolean | null {
  if (!reading) return null;
  const s = sign(reading.priceChange);
  return s === 0 ? false : (s > 0) === (side === 'bullish');
}

const windowNote = (reading: FuturesReading | null, what: string, side: Exclude<FlowSide, 'rangebound'>) =>
  reading == null ? `${what} is not measured yet` : `${what}: ${signedPct(reading.priceChangePct)}, ${agrees(reading, side) ? 'the same way' : 'the other way'}`;

export const signedPct = (value: number | null | undefined, digits = 2): string => {
  if (value == null || !Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  return `${value > 0 ? '+' : value < 0 ? '−' : ''}${abs.toFixed(abs >= 100 ? 0 : digits)}%`;
};

function buildChecks(stock: Omit<FlowStock, 'checks' | 'strength' | 'rank'>, side: Exclude<FlowSide, 'rangebound'>, window: FlowWindow, sectorLean: SectorLean | null, sectorSize: number): FlowCheck[] {
  const checks: FlowCheck[] = [];
  const opened = side === 'bullish' ? 'LONG_BUILD' : 'SHORT_BUILD';
  checks.push({
    id: 'fresh', label: 'Positions opened with the move',
    pass: stock.buildUp == null ? null : stock.buildUp === opened,
    note: stock.buildUp == null ? 'the future is not loaded yet'
      : stock.buildUp === opened ? `open interest ${signedPct(stock.oiChangePct)} with the price ${sideWord(side)}`
        : stock.buildUp === 'NEUTRAL' ? 'open interest did not change' : `open interest ${signedPct(stock.oiChangePct)}: positions closed, not opened`,
  });
  if (window === 'day') {
    const s = sign(stock.spotChangePct);
    checks.push({
      id: 'spot', label: 'Spot moved the same way',
      pass: stock.spotChangePct == null ? null : s !== 0 && (s > 0) === (side === 'bullish'),
      note: stock.spotChangePct == null ? 'no previous close for the spot' : `spot ${signedPct(stock.spotChangePct)} since the previous close`,
    });
    checks.push({ id: 'hour', label: 'The last hour agrees', pass: agrees(stock.futHour, side), note: windowNote(stock.futHour, 'last hour', side) });
  } else {
    checks.push({ id: 'day', label: 'The day agrees', pass: agrees(stock.futDay, side), note: windowNote(stock.futDay, 'since the previous close', side) });
    checks.push(window === '1h'
      ? { id: 'quarter', label: 'The last 15 minutes agree', pass: agrees(stock.futQuarter, side), note: windowNote(stock.futQuarter, 'last 15 minutes', side) }
      : { id: 'hour', label: 'The last hour agrees', pass: agrees(stock.futHour, side), note: windowNote(stock.futHour, 'last hour', side) });
  }
  const { putOiAdded, callOiAdded } = stock.options;
  const optionsLean = putOiAdded == null || callOiAdded == null ? null : side === 'bullish' ? putOiAdded > callOiAdded : callOiAdded > putOiAdded;
  checks.push({
    id: 'options', label: 'Option writers lean the same way',
    pass: optionsLean,
    note: putOiAdded == null || callOiAdded == null ? 'the market file carries no previous open interest for the options'
      : `puts ${signedUnits(putOiAdded)} and calls ${signedUnits(callOiAdded)} since the previous close`,
  });
  checks.push({
    id: 'sector', label: 'Its sector leans the same way',
    pass: sectorLean == null ? null : sectorLean === side,
    note: sectorLean == null ? (sectorSize < 3 ? 'too few underlyings in the sector to say' : 'the sector is not measured yet')
      : sectorLean === 'mixed' ? 'the sector is split' : `the sector reads ${sectorLean}`,
  });
  return checks;
}

const signedUnits = (units: number) => `${units > 0 ? '+' : units < 0 ? '−' : ''}${compactUnits(Math.abs(units))}`;
/** Units of open interest in lakh / crore, no grouping. */
export function compactUnits(units: number): string {
  const trim = (value: number, digits: number) => value.toFixed(digits).replace(/\.?0+$/, '');
  if (units >= 1e7) return `${trim(units / 1e7, 2)} Cr`;
  if (units >= 1e5) return `${trim(units / 1e5, 2)} L`;
  if (units >= 1e3) return `${trim(units / 1e3, 1)} K`;
  return String(Math.round(units));
}

/** 0–1: the share of the list this value sits above (ties share a rank). */
function percentile(values: number[], value: number): number {
  if (values.length <= 1) return 1;
  let below = 0;
  for (const other of values) if (other < value) below++;
  return below / (values.length - 1);
}

/**
 * How much open interest moved with the side, as the figure the strength
 * ranks on: positions opened count in full, positions closed at half, and a
 * future with no change on either side counts nothing.
 */
function conviction(stock: Pick<FlowStock, 'buildUp' | 'oiChangePct'>): number {
  if (stock.buildUp == null || stock.oiChangePct == null) return 0;
  if (stock.buildUp === 'LONG_BUILD' || stock.buildUp === 'SHORT_BUILD') return Math.max(stock.oiChangePct, 0);
  if (stock.buildUp === 'SHORT_COVER' || stock.buildUp === 'LONG_UNWIND') return Math.abs(stock.oiChangePct) / 2;
  return 0;
}

const checksHeld = (checks: FlowCheck[]) => {
  const counted = checks.filter(check => check.pass != null);
  return counted.length ? counted.filter(check => check.pass).length / counted.length : 0;
};

/** Strength weights: the move, the open interest that moved with it, the checks that hold. */
export const STRENGTH_WEIGHTS = { move: 0.45, conviction: 0.35, checks: 0.2 } as const;

export function buildMarketFlow(
  market: ContractMarket,
  futures: ReadonlyMap<string, FuturesSeries | null>,
  universe: readonly Underlying[],
  sectorLabels: Readonly<Record<string, string>>,
  settings: FlowSettings,
  options: FlowBuildOptions = {},
): MarketFlow {
  const floor = floorFor(settings);
  const now = options.now ?? Date.now();
  const failedSet = options.failed;
  const { window } = settings;
  const inScope = (item: Underlying) => settings.scope === 'all' || (settings.scope === 'stocks' ? item.kind === 'stock' : item.kind === 'index');
  const partial: Array<Omit<FlowStock, 'checks' | 'strength' | 'rank'>> = [];

  for (const item of universe) {
    if (!inScope(item)) continue;
    const series = nearSeries(market, item.symbol, now);
    if (!series) continue;
    const raw = futures.get(item.symbol);
    const held = raw ? trimToSession(raw, market.date) : raw;
    const futuresState: FlowStock['futures'] = held === undefined ? 'pending' : held ? 'read' : failedSet?.has(item.symbol) ? 'failed' : 'unavailable';
    const read = (w: 'day' | '1h' | '15m') => (held ? readFuturesWindow(held, w) : null);
    const fut = read(window);
    const futDay = window === 'day' ? fut : read('day');
    const futHour = window === '1h' ? fut : read('1h');
    const futQuarter = window === '15m' ? fut : read('15m');
    const spotChangePct = pct(series.spot, series.spotPrevClose);
    const changePct = fut ? fut.priceChangePct : window === 'day' ? spotChangePct : null;
    const source: FlowStock['source'] = fut ? 'futures' : changePct != null ? 'spot' : null;
    const side = sideOf(changePct, floor);

    let putOi = 0; let callOi = 0; let putOiAdded: number | null = null; let callOiAdded: number | null = null;
    for (const quote of series.quotes) {
      if (quote.side === 'PE') { putOi += quote.oi; if (quote.prevOi != null) putOiAdded = (putOiAdded ?? 0) + quote.oi - quote.prevOi; }
      else { callOi += quote.oi; if (quote.prevOi != null) callOiAdded = (callOiAdded ?? 0) + quote.oi - quote.prevOi; }
    }
    const [support, support2] = heaviestLevels(series, 'PE', series.spot);
    const [resistance, resistance2] = heaviestLevels(series, 'CE', series.spot);
    const candles: readonly FlowCandle[] = held?.candles ?? [];
    const zoneRead = side && side !== 'rangebound' ? readZone(candles, side) : { zone: null, note: null };
    const sector = item.kind === 'index' ? INDEX_SECTOR : item.sector ?? 'other';
    partial.push({
      symbol: item.symbol, name: item.name, kind: item.kind, sector,
      sectorLabel: item.kind === 'index' ? 'Indices' : sectorLabels[sector] ?? (item.sector ? sector : 'Other'),
      lot: series.lot, expiry: series.expiry, spot: series.spot, prevClose: series.spotPrevClose, spotChangePct,
      fut, futDay, futHour, futQuarter, futures: futuresState,
      changePct, source, oiChangePct: fut?.oiChangePct ?? null, buildUp: fut?.buildUp ?? null, side,
      options: { putOi, callOi, putOiAdded, callOiAdded, pcr: callOi > 0 ? putOi / callOi : null },
      support, support2, resistance, resistance2,
      zone: futuresState === 'read' ? zoneRead.zone : null,
      profile: oiProfile(series),
      zoneNote: side === 'rangebound' || side == null ? null : futuresState === 'pending' ? 'the future is not loaded yet' : futuresState === 'unavailable' ? 'no future is listed for it' : futuresState === 'failed' ? 'its future could not be loaded' : zoneRead.note,
      candles,
    });
  }

  // Sectors first: the sector check reads each one's lean.
  const sectorMap = new Map<string, FlowSector>();
  for (const stock of partial) {
    let sector = sectorMap.get(stock.sector);
    if (!sector) { sector = { id: stock.sector, label: stock.sectorLabel, count: 0, bullish: 0, bearish: 0, rangebound: 0, unread: 0, lean: 'mixed', changePct: null, symbols: [] }; sectorMap.set(stock.sector, sector); }
    sector.count++;
    sector.symbols.push(stock.symbol);
    if (stock.side === 'bullish') sector.bullish++; else if (stock.side === 'bearish') sector.bearish++; else if (stock.side === 'rangebound') sector.rangebound++; else sector.unread++;
  }
  const changesBySector = new Map<string, number[]>();
  for (const stock of partial) if (stock.changePct != null) changesBySector.set(stock.sector, [...(changesBySector.get(stock.sector) ?? []), stock.changePct]);
  for (const sector of sectorMap.values()) {
    sector.changePct = median(changesBySector.get(sector.id) ?? []);
    const measured = sector.bullish + sector.bearish + sector.rangebound;
    sector.lean = measured === 0 ? 'mixed'
      : sector.bullish > sector.bearish && sector.bullish * 2 >= measured ? 'bullish'
        : sector.bearish > sector.bullish && sector.bearish * 2 >= measured ? 'bearish'
          : sector.rangebound * 2 > measured ? 'rangebound' : 'mixed';
  }
  const sectorLean = (stock: typeof partial[number]): SectorLean | null => {
    const sector = sectorMap.get(stock.sector);
    if (!sector || sector.count < 3) return null;
    if (sector.bullish + sector.bearish + sector.rangebound === 0) return null;
    return sector.lean;
  };

  const withChecks = partial.map(stock => ({
    ...stock,
    checks: stock.side && stock.side !== 'rangebound' ? buildChecks(stock, stock.side, window, sectorLean(stock), sectorMap.get(stock.sector)?.count ?? 0) : [],
  }));

  // Strength is a standing within the side: a 2% day on a quiet tape and on a wild one read differently.
  // The side itself is ranked by the size of the move, the order the chart's line ends stand in;
  // an underlying measured on its spot only (future not read) follows the futures.
  const strengthOf = (list: typeof withChecks): FlowStock[] => {
    const moves = list.map(stock => Math.abs(stock.changePct ?? 0));
    const convictions = list.map(conviction);
    return list.map((stock, i) => ({
      ...stock,
      strength: STRENGTH_WEIGHTS.move * percentile(moves, moves[i]) + STRENGTH_WEIGHTS.conviction * percentile(convictions, convictions[i]) + STRENGTH_WEIGHTS.checks * checksHeld(stock.checks),
      rank: null,
    })).sort(byMove)
      .map((stock, index) => ({ ...stock, rank: index + 1 }));
  };
  const bullish = strengthOf(withChecks.filter(stock => stock.side === 'bullish'));
  const bearish = strengthOf(withChecks.filter(stock => stock.side === 'bearish'));
  const rangebound: FlowStock[] = withChecks.filter(stock => stock.side === 'rangebound').map(stock => ({ ...stock, strength: 0, rank: null }))
    .sort((a, b) => Math.abs(b.changePct ?? 0) - Math.abs(a.changePct ?? 0) || a.symbol.localeCompare(b.symbol));
  const unread: FlowStock[] = withChecks.filter(stock => stock.side == null).map(stock => ({ ...stock, strength: 0, rank: null }))
    .sort((a, b) => a.symbol.localeCompare(b.symbol));
  const stocks = [...bullish, ...bearish, ...rangebound, ...unread];

  const buckets: Record<FlowBucket, FlowStock[]> = { LONG_BUILD: [], SHORT_COVER: [], SHORT_BUILD: [], LONG_UNWIND: [] };
  for (const stock of [...bullish, ...bearish]) if (stock.buildUp && stock.buildUp !== 'NEUTRAL' && BUCKET_SIDE[stock.buildUp] === stock.side) buckets[stock.buildUp].push(stock);

  // Leader to laggard; a sector with nothing measured yet goes last.
  const sectors = [...sectorMap.values()].sort((a, b) => (b.changePct ?? -Infinity) - (a.changePct ?? -Infinity) || b.count - a.count || a.label.localeCompare(b.label));
  const count = (state: FlowStock['futures']) => partial.filter(stock => stock.futures === state).length;
  const read = count('read');
  const unavailable = count('unavailable');
  const failed = count('failed');
  const pending = count('pending');
  const total = partial.length;
  let latestAt: number | null = null;
  for (const stock of partial) if (stock.fut) latestAt = Math.max(latestAt ?? 0, stock.fut.to);
  const settledShare = total ? (total - pending) / total : 1;
  const featured = settledShare >= FEATURED_HOLD_SHARE
    ? { bullish: featuredOf(bullish, 'LONG_BUILD'), bearish: featuredOf(bearish, 'SHORT_BUILD') }
    : { bullish: [], bearish: [] };
  return {
    asOf: market.at, date: market.date, window, floorPct: floor, stocks, sectors, bullish, bearish, rangebound, unread, buckets,
    featured,
    futures: { read, unavailable, failed, pending, total, latestAt },
    provisional: pending > 0,
  };
}

/** The larger move first, a futures reading before a spot stand-in, then the symbol. */
function byMove(a: Pick<FlowStock, 'changePct' | 'source' | 'symbol'>, b: Pick<FlowStock, 'changePct' | 'source' | 'symbol'>): number {
  const spotA = a.source === 'futures' ? 0 : 1;
  const spotB = b.source === 'futures' ? 0 : 1;
  return spotA - spotB || Math.abs(b.changePct ?? 0) - Math.abs(a.changePct ?? 0) || a.symbol.localeCompare(b.symbol);
}

/**
 * A side's large cards: its strongest readings with positions opened the way
 * of the move (long build-up up, short build-up down), strongest first; if
 * fewer than FEATURED_PER_SIDE, the side's largest futures moves fill in.
 */
function featuredOf(side: readonly FlowStock[], opened: FlowBucket): FlowStock[] {
  const read = side.filter(stock => stock.source === 'futures');
  const strongest = read.filter(stock => stock.buildUp === opened).sort((a, b) => b.strength - a.strength || byMove(a, b)).slice(0, FEATURED_PER_SIDE);
  for (const stock of read) {
    if (strongest.length >= FEATURED_PER_SIDE) break;
    if (!strongest.includes(stock)) strongest.push(stock);
  }
  return strongest;
}

function median(values: readonly number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = sorted.length >> 1;
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

const timeFormat = new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false });
export const clockOf = (ms: number) => timeFormat.format(ms);

/** A strike or level as digits: never grouped, never compacted. */
export const levelText = (level: number) => (Number.isInteger(level) ? String(level) : level.toFixed(2));

const articleFor = (code: FlowBucket) => ({ LONG_BUILD: 'a long build-up', SHORT_BUILD: 'a short build-up', SHORT_COVER: 'short covering', LONG_UNWIND: 'long unwinding' })[code];

/** The reading in words: what moved, what the positions did, and where the heaviest option positions sit. Descriptive only. */
export function flowWhy(stock: FlowStock, window: FlowWindow): string[] {
  const lines: string[] = [];
  const scope = WINDOW_SCOPE[window];
  if (stock.fut) {
    const bu = stock.buildUp && stock.buildUp !== 'NEUTRAL' ? `: ${articleFor(stock.buildUp)}` : '';
    lines.push(`${stock.symbol}'s future is ${signedPct(stock.fut.priceChangePct)} ${scope} with open interest ${signedPct(stock.oiChangePct)}${bu}.`);
  } else if (stock.spotChangePct != null) {
    lines.push(`${stock.symbol}'s spot is ${signedPct(stock.spotChangePct)} since the previous close; ${stock.futures === 'failed' ? 'its future could not be loaded' : stock.futures === 'unavailable' ? 'no future is listed for it' : 'its future is still loading'}.`);
  }
  if (stock.zone) lines.push(`Open interest was added fastest between ${stock.zone.low.toFixed(2)} and ${stock.zone.high.toFixed(2)}, ${clockOf(stock.zone.from)}–${clockOf(stock.zone.to)}.`);
  else if (stock.zoneNote) lines.push(`No zone: ${stock.zoneNote}.`);
  const levels: string[] = [];
  if (stock.support) levels.push(`the heaviest put open interest at or below spot sits at ${levelText(stock.support.strike)} (${Math.abs(stock.support.distancePct).toFixed(1)}% below)`);
  if (stock.resistance) levels.push(`the heaviest call open interest at or above spot at ${levelText(stock.resistance.strike)} (${stock.resistance.distancePct.toFixed(1)}% above)`);
  if (levels.length) lines.push(`${levels.join(', and ')}.`.replace(/^./, c => c.toUpperCase()));
  return lines;
}
