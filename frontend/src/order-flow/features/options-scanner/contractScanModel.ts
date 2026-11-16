import { classify, type BuildUp, type BuildUpWindow } from '@/order-flow/lib/buildUp';
import { expiryDisplay } from '@/order-flow/components/common/expiryDisplay';
import { marketParts } from '@/order-flow/lib/marketSession';

/**
 * The Contracts view: every option of every F&O underlying on one list, the
 * way a stock screener lists stocks. This file only calculates. Every figure a
 * row prints is built here from two readings of the same contract — the latest
 * one and a baseline (the previous session's close for Day, the stored minute
 * W minutes earlier for 5m–1h) — so a change always equals `now − from`.
 */

type ContractSide = 'CE' | 'PE';
export type ScanWindow = '5m' | '15m' | '30m' | '1h' | 'day';
export type IntradayWindow = Exclude<ScanWindow, 'day'>;
/** Each underlying's own 1st, 2nd or 3rd tracked expiry, or every one of them. */
export type ExpiryPick = 'current' | 'next' | 'far' | 'all';
export type ContractScope = 'all' | 'stocks' | 'indices';
export type SideFilter = 'both' | ContractSide;
export type Moneyness = 'all' | 'itm' | 'otm';

export const SCAN_WINDOW_MINUTES: Record<IntradayWindow, number> = { '5m': 5, '15m': 15, '30m': 30, '1h': 60 };

/**
 * How far the stored minute may sit from the exact lookback and still be
 * printed under the window's name. 5m and 15m are the chain's own insight
 * tolerances; a 7-minute gap under "5m" is a wrong number, not a generous one.
 */
export const SCAN_WINDOW_TOLERANCE_MS: Record<IntradayWindow, number> = {
  '5m': 90_000, '15m': 150_000, '30m': 180_000, '1h': 300_000,
};

/**
 * The chain's build-up noise floors, per window. There is no 30-minute floor in
 * BUILD_UP_NOISE_FLOOR, so 30m uses the stricter 1h floor rather than a
 * number invented here.
 */
const BUILD_UP_TIMEFRAME: Record<ScanWindow, BuildUpWindow> = { '5m': '5m', '15m': '15m', '30m': '1h', '1h': '1h', day: '1d' };

const EXPIRY_RANK: Record<Exclude<ExpiryPick, 'all'>, number> = { current: 0, next: 1, far: 2 };

/** One contract at one moment, in ₹ and units exactly as the market file stores it. */
export interface ContractQuote {
  strike: number;
  side: ContractSide;
  /** Last traded price. It can come from an earlier session: volume 0 means untraded today. */
  ltp: number;
  /** Null when there is no honest day change (untraded today or no previous close). */
  prevClose: number | null;
  oi: number;
  prevOi: number | null;
  /** Contracts traded this session, in units (not lots). */
  volume: number;
  /** Previous session's volume, in LOTS as supplied. */
  prevVolumeLots: number | null;
  /** Session average traded price; × volume = rupees traded today. */
  avgPrice: number;
  iv: number | null;
  bid: number;
  ask: number;
  bidQty: number;
  askQty: number;
  dayHigh: number | null;
  dayLow: number | null;
  lastTradeAt: number | null;
  /** The vendor's delta, as the chain shows it; null when not supplied. */
  delta: number | null;
}

export interface ContractSeries {
  symbol: string;
  kind: 'index' | 'stock';
  expiry: string;
  lot: number;
  lotSource: 'catalogue' | 'api';
  /** When this series was read (epoch ms). */
  at: number;
  spot: number;
  spotPrevClose: number | null;
  atm: number | null;
  quotes: ContractQuote[];
  /** The vendor's own chain time (ms), when the file carries it. */
  tape?: number | null;
  /** Every listed strike, and the legs quoted with no open interest and no volume (files from 27 Sep on). */
  ladder?: number[] | null;
  idle?: ContractQuote[];
}

export interface ContractMarket {
  /** Reading time of the file as a whole (epoch ms). */
  at: number;
  /** IST session date, YYYY-MM-DD. */
  date: string;
  series: ContractSeries[];
  /** Stored minutes available as window baselines, ascending: [HHMM, epoch ms]. */
  minutes: Array<[string, number]>;
  /**
   * Each underlying's full list of live expiries, when known. A market read one
   * expiry at a time holds only the chosen series, so its position (current,
   * next, far) must come from the ladder, not from what the file holds.
   */
  ladders?: Record<string, string[]>;
}

// ── Market file (schema 1) ────────────────────────────────────────────────

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const orNull = (value: unknown): number | null => (finite(value) ? value : null);
const DATE = /^\d{4}-\d{2}-\d{2}$/;

function parseRow(row: unknown): ContractQuote | null {
  if (!Array.isArray(row) || row.length < 17) return null;
  const [strike, side, ltp, prevClose, oi, prevOi, volume, prevVolumeLots, avgPrice, iv, bid, ask, bidQty, askQty, dayHigh, dayLow, lastTradeAt, delta] = row;
  if (!finite(strike) || strike <= 0 || (side !== 0 && side !== 1)) return null;
  if (!finite(ltp) || !finite(oi) || !finite(volume) || !finite(avgPrice) || !finite(bid) || !finite(ask) || !finite(bidQty) || !finite(askQty)) return null;
  return {
    strike, side: side === 0 ? 'CE' : 'PE', ltp, prevClose: orNull(prevClose), oi, prevOi: orNull(prevOi), volume,
    prevVolumeLots: orNull(prevVolumeLots), avgPrice, iv: orNull(iv), bid, ask, bidQty, askQty,
    dayHigh: orNull(dayHigh), dayLow: orNull(dayLow), lastTradeAt: orNull(lastTradeAt),
    // An 18th field since 26 Sep; files written before it have 17.
    delta: orNull(delta),
  };
}

/** Validates the whole file; a malformed series is dropped, never guessed at. */
export function parseMarketFile(body: unknown): ContractMarket | null {
  if (!body || typeof body !== 'object') return null;
  const file = body as Record<string, unknown>;
  if (file.schema !== 1 || !finite(file.t) || typeof file.date !== 'string' || !DATE.test(file.date) || !Array.isArray(file.series)) return null;
  const series: ContractSeries[] = [];
  for (const raw of file.series as unknown[]) {
    if (!raw || typeof raw !== 'object') continue;
    const item = raw as Record<string, unknown>;
    if (typeof item.s !== 'string' || (item.k !== 'index' && item.k !== 'stock') || typeof item.e !== 'string' || !DATE.test(item.e)) continue;
    if (!finite(item.lot) || !Number.isInteger(item.lot) || item.lot <= 0 || !finite(item.t) || !finite(item.sp) || item.sp <= 0 || !Array.isArray(item.r)) continue;
    const quotes = (item.r as unknown[]).map(parseRow).filter((quote): quote is ContractQuote => quote !== null);
    series.push({
      symbol: item.s, kind: item.k, expiry: item.e, lot: item.lot, lotSource: item.ls === 'api' ? 'api' : 'catalogue',
      at: item.t, spot: item.sp, spotPrevClose: finite(item.pc) && item.pc > 0 ? item.pc : null,
      atm: finite(item.atm) && item.atm > 0 ? item.atm : null, quotes,
      tape: finite(item.tp) && item.tp > 0 ? item.tp : null,
      ladder: Array.isArray(item.ks) && item.ks.every(k => finite(k) && k > 0) ? (item.ks as number[]) : null,
      idle: Array.isArray(item.z) ? (item.z as unknown[]).map(parseRow).filter((quote): quote is ContractQuote => quote !== null) : [],
    });
  }
  const minutes = Array.isArray(file.minutes)
    ? (file.minutes as unknown[]).filter((entry): entry is [string, number] => Array.isArray(entry) && typeof entry[0] === 'string' && /^\d{4}$/.test(entry[0]) && finite(entry[1]))
      .sort((a, b) => a[1] - b[1])
    : [];
  // Each symbol's live expiries (files from 27 Sep): positions come from these, not from what one minute holds.
  const ladders: Record<string, string[]> = {};
  if (file.ladders && typeof file.ladders === 'object' && !Array.isArray(file.ladders)) {
    for (const [symbol, list] of Object.entries(file.ladders as Record<string, unknown>)) {
      if (Array.isArray(list) && list.length && list.every(date => typeof date === 'string' && DATE.test(date))) ladders[symbol] = [...(list as string[])].sort();
    }
  }
  return { at: file.t, date: file.date, series, minutes, ...(Object.keys(ladders).length ? { ladders } : {}) };
}

/** The stored minute nearest `target`, only when it sits inside the window's tolerance. */
export function pickBaselineMinute(market: ContractMarket, window: IntradayWindow): { minute: string; at: number } | null {
  const target = market.at - SCAN_WINDOW_MINUTES[window] * 60_000;
  let best: [string, number] | null = null;
  for (const entry of market.minutes) {
    if (entry[1] >= market.at) continue;
    if (!best || Math.abs(entry[1] - target) < Math.abs(best[1] - target)) best = entry;
  }
  if (!best || Math.abs(best[1] - target) > SCAN_WINDOW_TOLERANCE_MS[window]) return null;
  return { minute: best[0], at: best[1] };
}

// ── Rows ──────────────────────────────────────────────────────────────────

export interface ContractRow {
  id: string;
  symbol: string;
  kind: 'index' | 'stock';
  expiry: string;
  strike: number;
  side: ContractSide;
  lot: number;
  lotSource: 'catalogue' | 'api';
  ltp: number;
  /** Rupees traded today: average traded price × contracts traded. */
  dayValue: number;
  dayLots: number;
  oiLots: number;
  spreadPct: number | null;
  iv: number | null;
  spot: number;
  spotChangePct: number | null;
  /** Strike distance from spot, % of spot; sign-free. */
  distancePct: number;
  itm: boolean;
  premiumPerLot: number;
  prevVolumeLots: number | null;
  /** Calendar days to expiry, counted the one way the app counts them (expiryDisplay). */
  dte: number | null;
  delta: number | null;
  /** The underlying's sector from the site catalogue; indices have none. */
  sector: string | null;
  /** Measured over the selected window. */
  from: number | null;
  priceChange: number | null;
  priceChangePct: number | null;
  changePerLot: number | null;
  oiFromLots: number | null;
  oiChangeLots: number | null;
  oiChangePct: number | null;
  /** Contracts traded inside the window, in lots (today's total for Day). */
  windowLots: number | null;
  /** Rupees traded inside the window (today's total for Day). */
  windowValue: number | null;
  /** Day: × yesterday's volume. Intraday: × today's average pace for a window this long. */
  volumeRatio: number | null;
  ivChange: number | null;
  /** Volume ÷ the open interest the window started with (Day: the previous close's OI). */
  volOiRatio: number | null;
  buildUp: BuildUp | null;
  /** The two readings the window compares (epoch ms); null for Day. */
  span: { from: number; to: number } | null;
  /** The model's chance, 0–100, that it expires worthless (contractChance); null until read, or without a model. */
  chanceWorthless: number | null;
}

type WindowState =
  | { state: 'ok'; window: ScanWindow; from: number | null; to: number }
  | { state: 'unavailable'; window: IntradayWindow; reason: string };

const pct = (change: number, base: number) => (base > 0 ? (change / base) * 100 : null);

/** An option stops trading at 15:30 IST on its expiry day; after that it is settled, not current. */
const EXPIRY_LAST_TRADE_MINUTE = 15 * 60 + 30;

/**
 * Whether an expiry still trades at the market's reading. A series that
 * expired today stays in the closing file (it settled at 15:30), but it is no
 * longer anyone's current expiry: "Current" moves on to the next one.
 */
export function isLiveExpiry(market: Pick<ContractMarket, 'date' | 'at'>, expiry: string): boolean {
  if (expiry !== market.date) return expiry > market.date;
  return marketParts(market.at).minuteOfDay < EXPIRY_LAST_TRADE_MINUTE;
}

/** Each underlying's live expiries in date order: from the market's ladders, else from what the file holds. */
function expiryOrder(market: ContractMarket): Map<string, string[]> {
  if (market.ladders) return new Map(Object.entries(market.ladders).map(([symbol, expiries]) => [symbol, expiries.filter(expiry => isLiveExpiry(market, expiry)).sort()]));
  const order = new Map<string, Set<string>>();
  for (const series of market.series) {
    if (!isLiveExpiry(market, series.expiry)) continue;
    if (!order.has(series.symbol)) order.set(series.symbol, new Set());
    order.get(series.symbol)!.add(series.expiry);
  }
  return new Map([...order].map(([symbol, set]) => [symbol, [...set].sort()]));
}

const quoteKey = (symbol: string, expiry: string, strike: number, side: ContractSide) => `${symbol}|${expiry}|${strike}|${side}`;

/**
 * Minutes of the session elapsed at `at`, from 09:15 IST. Used only to express
 * a window's volume against the day's own average pace.
 */
export function sessionMinutesElapsed(at: number): number {
  const parts = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
    .formatToParts(new Date(at));
  const get = (type: string) => Number(parts.find(part => part.type === type)?.value ?? NaN);
  const minutes = get('hour') * 60 + get('minute') + get('second') / 60;
  return Math.max(0, Math.min(minutes, 15 * 60 + 40) - (9 * 60 + 15));
}

export interface BuildRowsResult {
  rows: ContractRow[];
  window: WindowState;
  /** Underlyings with at least one series at the chosen expiry position. */
  underlyings: number;
  /**
   * Rows an intraday window could not measure: their series is missing from
   * the earlier minute, or was read too far from the window's length (a
   * series carried into a minute file keeps its own, older reading time).
   */
  unmeasured: number;
}

/** A baseline minute indexed for matching: each series, and each contract by symbol, expiry, strike and side. */
interface BaselineIndex { series: Map<string, ContractSeries>; quotes: Map<string, ContractQuote> }
const baselineIndexes = new WeakMap<ContractMarket, BaselineIndex>();
function indexBaseline(baseline: ContractMarket): BaselineIndex {
  const held = baselineIndexes.get(baseline);
  if (held) return held;
  const index: BaselineIndex = { series: new Map(), quotes: new Map() };
  for (const series of baseline.series) {
    index.series.set(`${series.symbol}|${series.expiry}`, series);
    for (const quote of series.quotes) index.quotes.set(quoteKey(series.symbol, series.expiry, quote.strike, quote.side), quote);
  }
  baselineIndexes.set(baseline, index);
  return index;
}

/** Whether a series can be measured over the window, and how any one of its contracts reads. */
interface SeriesMeasure {
  measurable: boolean;
  measure: (quote: ContractQuote) => ContractRow;
}

/**
 * The one definition of a contract's figures. The Contracts list measures its
 * traded contracts through it, and the Custom view any contract it picks, so a
 * contract reads the same wherever it appears. `baseline` is the stored minute
 * for an intraday window (null for Day, or when none exists).
 */
export function measureSeries(
  market: ContractMarket,
  series: ContractSeries,
  window: ScanWindow,
  baseline: ContractMarket | null,
  sector: string | null = null,
): SeriesMeasure {
  const index = window !== 'day' && baseline ? indexBaseline(baseline) : null;
  const base = index?.series.get(`${series.symbol}|${series.expiry}`);
  // An intraday window needs the same series in the earlier minute, read the
  // window's length earlier within the window's tolerance. The minute file's
  // own time is checked when it is picked; a series carried into either file
  // keeps its older reading time, so its own span is checked here too.
  const measurable = window === 'day' || (base != null && base.at < series.at
    && Math.abs(series.at - base.at - SCAN_WINDOW_MINUTES[window] * 60_000) <= SCAN_WINDOW_TOLERANCE_MS[window]);
  const elapsed = sessionMinutesElapsed(market.at);
  const timeframe = BUILD_UP_TIMEFRAME[window];
  const spotChangePct = series.spotPrevClose ? ((series.spot - series.spotPrevClose) / series.spotPrevClose) * 100 : null;
  const dte = expiryDisplay(series.expiry, market.at).days;
  const measure = (quote: ContractQuote): ContractRow => {
    const lot = series.lot;
    const dayValue = quote.avgPrice * quote.volume;
    const spreadPct = quote.bid > 0 && quote.ask >= quote.bid ? ((quote.ask - quote.bid) / ((quote.ask + quote.bid) / 2)) * 100 : null;
    const itm = quote.side === 'CE' ? quote.strike < series.spot : quote.strike > series.spot;
    const row: ContractRow = {
      id: quoteKey(series.symbol, series.expiry, quote.strike, quote.side),
      symbol: series.symbol, kind: series.kind, expiry: series.expiry, strike: quote.strike, side: quote.side,
      lot, lotSource: series.lotSource, ltp: quote.ltp, dayValue, dayLots: quote.volume / lot, oiLots: quote.oi / lot,
      spreadPct, iv: quote.iv, spot: series.spot, spotChangePct,
      distancePct: (Math.abs(quote.strike - series.spot) / series.spot) * 100, itm,
      premiumPerLot: quote.ltp * lot, prevVolumeLots: quote.prevVolumeLots, dte, delta: quote.delta, sector,
      from: null, priceChange: null, priceChangePct: null, changePerLot: null,
      oiFromLots: null, oiChangeLots: null, oiChangePct: null,
      windowLots: null, windowValue: null, volumeRatio: null, ivChange: null, volOiRatio: null, buildUp: null, span: null,
      chanceWorthless: null,
    };
    if (window === 'day') {
      // A contract that did not trade yesterday has an exchange base price as
      // its "previous close", not a traded price: no day change is printed.
      if (quote.ltp > 0 && quote.prevClose != null && quote.prevClose > 0 && quote.prevVolumeLots !== 0) row.from = quote.prevClose;
      if (quote.prevOi != null) row.oiFromLots = quote.prevOi / lot;
      row.windowLots = row.dayLots;
      row.windowValue = dayValue;
      if (quote.prevVolumeLots != null && quote.prevVolumeLots > 0) row.volumeRatio = row.dayLots / quote.prevVolumeLots;
    } else if (measurable && base) {
      // A contract missing from a series that WAS read then had no trades
      // and no open interest at that minute: zero volume, zero OI, no price.
      const then = index!.quotes.get(row.id) ?? null;
      const thenVolume = then?.volume ?? 0;
      const thenValue = then ? then.avgPrice * then.volume : 0;
      // A last price is a starting point only if it was traded today, no more
      // than one window's length before the window began. An older trade
      // (untraded since the morning, or since an earlier session) would put
      // hours of movement under a 5-minute label.
      const startTradeAt = then?.lastTradeAt ?? null;
      const tradedThen = then != null && thenVolume > 0 && then.ltp > 0
        && startTradeAt != null && startTradeAt >= base.at - SCAN_WINDOW_MINUTES[window] * 60_000;
      if (quote.ltp > 0 && tradedThen) row.from = then.ltp;
      row.oiFromLots = (then?.oi ?? 0) / lot;
      row.windowLots = Math.max(0, quote.volume - thenVolume) / lot;
      // Rupees traded by then need that minute's average price; without it
      // the window's value is unknown, not the whole day's.
      row.windowValue = thenVolume > 0 && !(then!.avgPrice > 0) ? null : Math.max(0, dayValue - thenValue);
      const minutes = (series.at - base.at) / 60_000;
      if (elapsed > 0 && minutes > 0 && minutes <= elapsed && row.dayLots > 0) {
        const pace = row.dayLots * (minutes / elapsed);
        row.volumeRatio = pace > 0 ? row.windowLots / pace : null;
      }
      if (tradedThen && quote.iv != null && then.iv != null && quote.iv > 0 && then.iv > 0) row.ivChange = quote.iv - then.iv;
      row.span = { from: base.at, to: series.at };
    }
    if (row.from != null) {
      row.priceChange = quote.ltp - row.from;
      row.priceChangePct = pct(row.priceChange, row.from);
      row.changePerLot = row.priceChange * lot;
    }
    if (row.oiFromLots != null) {
      row.oiChangeLots = row.oiLots - row.oiFromLots;
      row.oiChangePct = row.oiFromLots > 0 ? (row.oiChangeLots / row.oiFromLots) * 100 : null;
      if (row.windowLots != null && row.oiFromLots > 0) row.volOiRatio = row.windowLots / row.oiFromLots;
    }
    if (row.priceChange != null && row.oiChangeLots != null && row.oiFromLots != null) {
      row.buildUp = classify(row.priceChange, row.oiChangeLots, row.oiChangePct ?? 0, row.oiFromLots, timeframe, row.priceChangePct ?? undefined);
    }
    return row;
  };
  return { measurable, measure };
}

/** `symbol|expiry` of every series the expiry position picks, from the market's ladders when it carries them. */
function wantedSeries(market: ContractMarket, pick: ExpiryPick): Set<string> {
  const wanted = new Set<string>();
  for (const [symbol, expiries] of expiryOrder(market)) {
    const chosen = pick === 'all' ? expiries : [expiries[EXPIRY_RANK[pick]]];
    for (const expiry of chosen) if (expiry) wanted.add(`${symbol}|${expiry}`);
  }
  return wanted;
}

/** How many underlyings the expiry position lists: the `underlyings` figure of `buildContractRows`. */
export function contractUnderlyingCount(market: ContractMarket, pick: ExpiryPick): number {
  return new Set([...wantedSeries(market, pick)].map(key => key.split('|')[0])).size;
}

/**
 * One row per traded contract at the chosen expiry position. `baseline` is the
 * stored minute for an intraday window (null for Day, or when none exists).
 */
export function buildContractRows(
  market: ContractMarket,
  pick: ExpiryPick,
  window: ScanWindow,
  baseline: ContractMarket | null,
  sectors: Readonly<Record<string, string | undefined>> = {},
): BuildRowsResult {
  const wanted = wantedSeries(market, pick);
  const underlyings = new Set([...wanted].map(key => key.split('|')[0])).size;
  const windowState: WindowState = window === 'day' ? { state: 'ok', window, from: null, to: market.at }
    : baseline ? { state: 'ok', window, from: baseline.at, to: market.at }
      : { state: 'unavailable', window, reason: `No reading from ${SCAN_WINDOW_MINUTES[window]} minutes earlier is available yet.` };
  const rows: ContractRow[] = [];
  let unmeasured = 0;
  for (const series of market.series) {
    if (!wanted.has(`${series.symbol}|${series.expiry}`)) continue;
    const { measurable, measure } = measureSeries(market, series, window, baseline, sectors[series.symbol] ?? null);
    for (const quote of series.quotes) {
      if (!(quote.volume > 0)) continue;
      rows.push(measure(quote));
      if (window !== 'day' && !measurable) unmeasured++;
    }
  }
  return { rows, window: windowState, underlyings, unmeasured };
}

// ── Scans ─────────────────────────────────────────────────────────────────

export type ContractScanId =
  | 'gainers' | 'losers' | 'oi-gainers' | 'oi-losers' | 'oi-gainers-pct' | 'oi-losers-pct'
  | 'long-build' | 'short-build' | 'short-cover' | 'long-unwind'
  | 'active' | 'volume-surge' | 'unusual';

export type ContractSortKey = 'change' | 'perLot' | 'oiChange' | 'oiChangePct' | 'oi' | 'lots' | 'value' | 'ratio' | 'volOi' | 'iv' | 'spread' | 'underlying' | 'worthless';

interface ContractScanDefinition {
  id: ContractScanId;
  label: string;
  /** What the list answers, in plain words. */
  question: string;
  sort: ContractSortKey;
  descending: boolean;
  include: (row: ContractRow) => boolean;
  /** Gainers and losers read a % change: the starting premium must be a real, tradeable price. */
  usesPremiumChange?: boolean;
  /** Reads volume ÷ starting OI: the starting OI must be a real position. */
  usesStartingOi?: boolean;
}

const BUILD: Record<Extract<ContractScanId, 'long-build' | 'short-build' | 'short-cover' | 'long-unwind'>, BuildUp> = {
  'long-build': 'LONG_BUILD', 'short-build': 'SHORT_BUILD', 'short-cover': 'SHORT_COVER', 'long-unwind': 'LONG_UNWIND',
};

export const CONTRACT_SCANS: readonly ContractScanDefinition[] = [
  { id: 'gainers', label: 'Top gainers', question: 'Which contracts’ premium rose the most?', sort: 'change', descending: true, usesPremiumChange: true, include: row => (row.priceChangePct ?? 0) > 0 },
  { id: 'losers', label: 'Top losers', question: 'Which contracts’ premium fell the most?', sort: 'change', descending: false, usesPremiumChange: true, include: row => (row.priceChangePct ?? 0) < 0 },
  { id: 'oi-gainers', label: 'Open Interest gainers', question: 'Where was the most open interest added?', sort: 'oiChange', descending: true, include: row => (row.oiChangeLots ?? 0) > 0 },
  { id: 'oi-losers', label: 'Open Interest losers', question: 'Where was the most open interest closed?', sort: 'oiChange', descending: false, include: row => (row.oiChangeLots ?? 0) < 0 },
  // The same two in percent of where the position started. A percent on a tiny start misleads (1 lot to 50 is +4900%),
  // so these need a real starting position: the Starting Open Interest floor, as Volume above Open Interest does.
  { id: 'oi-gainers-pct', label: 'Open Interest % gainers', question: 'Which contracts’ open interest rose the most in percent?', sort: 'oiChangePct', descending: true, usesStartingOi: true, include: row => (row.oiChangePct ?? 0) > 0 },
  { id: 'oi-losers-pct', label: 'Open Interest % losers', question: 'Which contracts’ open interest fell the most in percent?', sort: 'oiChangePct', descending: false, usesStartingOi: true, include: row => (row.oiChangePct ?? 0) < 0 },
  { id: 'long-build', label: 'Long build-up', question: 'Premium up and open interest up.', sort: 'oiChange', descending: true, include: row => row.buildUp === BUILD['long-build'] },
  { id: 'short-build', label: 'Short build-up', question: 'Premium down and open interest up.', sort: 'oiChange', descending: true, include: row => row.buildUp === BUILD['short-build'] },
  { id: 'short-cover', label: 'Short covering', question: 'Premium up and open interest down.', sort: 'oiChange', descending: false, include: row => row.buildUp === BUILD['short-cover'] },
  { id: 'long-unwind', label: 'Long unwinding', question: 'Premium down and open interest down.', sort: 'oiChange', descending: false, include: row => row.buildUp === BUILD['long-unwind'] },
  { id: 'active', label: 'Most active', question: 'Where is the most money trading?', sort: 'value', descending: true, include: row => (row.windowValue ?? 0) > 0 },
  { id: 'volume-surge', label: 'Volume surge', question: 'Which contracts are trading far more than usual?', sort: 'ratio', descending: true, include: row => row.volumeRatio != null && row.volumeRatio > 1 },
  { id: 'unusual', label: 'Volume above Open Interest', question: 'Where did volume exceed the open interest it started with?', sort: 'volOi', descending: true, usesStartingOi: true, include: row => row.volOiRatio != null && row.volOiRatio > 1 },
];

export function contractScan(id: ContractScanId): ContractScanDefinition {
  return CONTRACT_SCANS.find(scan => scan.id === id) ?? CONTRACT_SCANS[0];
}

export interface ContractFilters {
  scope: ContractScope;
  side: SideFilter;
  /** Rupees traded today, in lakh. The liquidity floor: 10 = ₹10 lakh. */
  minValueLakh: number;
  /** 0 = any spread. Contracts without a two-sided quote fail a set limit. */
  maxSpreadPct: number;
  /** Gainers/losers only: the starting premium must be at least this, ₹. */
  minFromPremium: number;
  /** Day gainers/losers only: yesterday's volume must be at least this many lots. */
  minPrevLots: number;
  moneyness: Moneyness;
  /** 0 = any distance. */
  maxDistancePct: number;
  /** 0 = any premium. */
  maxPremiumPerLot: number;
  onePerUnderlying: boolean;
  query: string;
  /** Contracts traded in the window (Day: today), lots. 0 = any. */
  minVolumeLots: number;
  /** Volume ÷ the open interest the window started with, at least this (×). 0 = any; 1 = volume above OI. */
  minVolOi: number;
  /** |OI change| at least this % of the starting OI; a position opened from zero counts as added. 0 = any. */
  minOiMovePct: number;
  /** Volume against its usual level (Day: × yesterday; windows: × today's pace), at least this. 0 = any. */
  minVolumeRatio: number;
  /** Calendar days to expiry. 0 = no limit on that side. */
  minDte: number;
  maxDte: number;
  /** Implied volatility, %. 0 = no limit; a set limit leaves out contracts without IV. */
  minIv: number;
  maxIv: number;
  /** |delta|, 0–1. 0 = no limit; a set limit leaves out contracts without delta. */
  minDelta: number;
  maxDelta: number;
  /** The model's chance it expires worthless, %. 0 = no limit; a set limit leaves out contracts without a reading. */
  minWorthlessPct: number;
  maxWorthlessPct: number;
  /** Strike at least this far from spot, % of spot. */
  minDistancePct: number;
  /** A catalogue sector id, or 'all'. A sector leaves out indices. */
  sector: string;
  /**
   * Volume ÷ OI ratios (the Volume above OI scan and filter) only where the
   * starting open interest is at least this many lots: a ratio over a
   * near-empty strike is a division artefact, not unusual volume.
   */
  minStartOiLots: number;
}

export const DEFAULT_CONTRACT_FILTERS: ContractFilters = {
  scope: 'all', side: 'both', minValueLakh: 10, maxSpreadPct: 0, minFromPremium: 2, minPrevLots: 10,
  moneyness: 'all', maxDistancePct: 0, maxPremiumPerLot: 0, onePerUnderlying: false, query: '',
  minVolumeLots: 0, minVolOi: 0, minOiMovePct: 0, minVolumeRatio: 0, minDte: 0, maxDte: 0, minIv: 0, maxIv: 0, minDelta: 0, maxDelta: 0, minWorthlessPct: 0, maxWorthlessPct: 0, minDistancePct: 0, sector: 'all', minStartOiLots: 50,
};

export const LAKH = 100_000;

function sortValue(row: ContractRow, key: ContractSortKey): number | null {
  switch (key) {
    case 'change': return row.priceChangePct;
    case 'perLot': return row.changePerLot;
    case 'oiChange': return row.oiChangeLots;
    case 'oiChangePct': return row.oiChangePct;
    case 'oi': return row.oiLots;
    case 'lots': return row.windowLots;
    case 'value': return row.windowValue;
    case 'ratio': return row.volumeRatio;
    case 'volOi': return row.volOiRatio;
    case 'iv': return row.iv;
    case 'spread': return row.spreadPct;
    case 'underlying': return row.spotChangePct;
    case 'worthless': return row.chanceWorthless;
  }
}

interface ContractScanResult {
  rows: ContractRow[];
  /** Rows the scan itself matched before the liquidity floor. */
  matched: number;
  /** Matched rows left out only because they traded less than the floor today. */
  belowFloor: number;
}

export interface ContractSort { key: ContractSortKey; descending: boolean }

/** Filters, then the scan, then one transparent ordering. Missing figures sort last. */
export function runContractScan(
  rows: readonly ContractRow[],
  scanId: ContractScanId,
  filters: ContractFilters,
  window: ScanWindow,
  sort?: ContractSort,
): ContractScanResult {
  const scan = contractScan(scanId);
  const query = filters.query.trim().toUpperCase();
  // A whole symbol means that underlying alone ("NIFTY" is not BANKNIFTY);
  // part of a name still finds every symbol that contains it.
  const exact = query !== '' && rows.some(row => row.symbol === query);
  const floor = Math.max(0, filters.minValueLakh) * LAKH;
  let belowFloor = 0;
  let matched = 0;
  const kept: ContractRow[] = [];
  for (const row of rows) {
    if (filters.scope === 'stocks' && row.kind !== 'stock') continue;
    if (filters.scope === 'indices' && row.kind !== 'index') continue;
    if (filters.side !== 'both' && row.side !== filters.side) continue;
    if (query && (exact ? row.symbol !== query : !row.symbol.includes(query))) continue;
    if (filters.moneyness === 'itm' && !row.itm) continue;
    if (filters.moneyness === 'otm' && row.itm) continue;
    if (filters.maxDistancePct > 0 && row.distancePct > filters.maxDistancePct) continue;
    if (filters.maxPremiumPerLot > 0 && row.premiumPerLot > filters.maxPremiumPerLot) continue;
    if (filters.maxSpreadPct > 0 && (row.spreadPct == null || row.spreadPct > filters.maxSpreadPct)) continue;
    if (filters.minDistancePct > 0 && row.distancePct < filters.minDistancePct) continue;
    if (filters.sector !== 'all' && row.sector !== filters.sector) continue;
    if (filters.minVolumeLots > 0 && (row.windowLots ?? 0) < filters.minVolumeLots) continue;
    if (filters.minVolOi > 0 && !(row.volOiRatio != null && row.volOiRatio >= filters.minVolOi)) continue;
    if ((scan.usesStartingOi || filters.minVolOi > 0) && (row.oiFromLots ?? 0) < filters.minStartOiLots) continue;
    if (filters.minOiMovePct > 0) {
      const opened = row.oiFromLots === 0 && (row.oiChangeLots ?? 0) > 0;
      if (!opened && !(row.oiChangePct != null && Math.abs(row.oiChangePct) >= filters.minOiMovePct)) continue;
    }
    if (filters.minVolumeRatio > 0 && !(row.volumeRatio != null && row.volumeRatio >= filters.minVolumeRatio)) continue;
    if (filters.minDte > 0 && (row.dte == null || row.dte < filters.minDte)) continue;
    if (filters.maxDte > 0 && (row.dte == null || row.dte > filters.maxDte)) continue;
    if ((filters.minIv > 0 || filters.maxIv > 0) && !(row.iv != null && row.iv > 0)) continue;
    if (filters.minIv > 0 && row.iv! < filters.minIv) continue;
    if (filters.maxIv > 0 && row.iv! > filters.maxIv) continue;
    if ((filters.minDelta > 0 || filters.maxDelta > 0) && row.delta == null) continue;
    if (filters.minDelta > 0 && Math.abs(row.delta!) < filters.minDelta) continue;
    if (filters.maxDelta > 0 && Math.abs(row.delta!) > filters.maxDelta) continue;
    if ((filters.minWorthlessPct > 0 || filters.maxWorthlessPct > 0) && row.chanceWorthless == null) continue;
    if (filters.minWorthlessPct > 0 && row.chanceWorthless! < filters.minWorthlessPct) continue;
    if (filters.maxWorthlessPct > 0 && row.chanceWorthless! > filters.maxWorthlessPct) continue;
    if (scan.usesPremiumChange) {
      if (row.from == null || row.from < filters.minFromPremium) continue;
      if (window === 'day' && (row.prevVolumeLots == null || row.prevVolumeLots < filters.minPrevLots)) continue;
    }
    if (!scan.include(row)) continue;
    matched++;
    if (row.dayValue < floor) { belowFloor++; continue; }
    kept.push(row);
  }
  const key = sort?.key ?? scan.sort;
  const descending = sort?.descending ?? scan.descending;
  kept.sort((a, b) => {
    const x = sortValue(a, key);
    const y = sortValue(b, key);
    if (x == null || y == null) return x == null && y == null ? 0 : x == null ? 1 : -1;
    const order = descending ? y - x : x - y;
    return order || b.dayValue - a.dayValue || a.id.localeCompare(b.id);
  });
  if (!filters.onePerUnderlying) return { rows: kept, matched, belowFloor };
  const seen = new Set<string>();
  return { rows: kept.filter(row => !seen.has(row.symbol) && Boolean(seen.add(row.symbol))), matched, belowFloor };
}
