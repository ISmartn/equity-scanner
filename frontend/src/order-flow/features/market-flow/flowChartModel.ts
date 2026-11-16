import { quantile } from './flowLayout';
import { sessionEndOf, SCAN_MINUTES, type FlowStock, type FlowWindow, type MarketFlow } from './marketFlowModel';

/**
 * The flow chart's arithmetic, apart from React and the DOM so it can be
 * tested: the time span, each underlying's line as points (change % by
 * minute), the y reach, the ticks, the middle-80% band and the named lines.
 */

export const MINUTE = 60_000;
/** India Standard Time is UTC+5:30, with no daylight saving. */
const IST_OFFSET = 330 * MINUTE;
const OPEN_MINUTE = 9 * 60 + 15;

/** One underlying's line: the window's start at 0%, then one point per 1-minute candle, at the candle's close. */
export interface FlowLine {
  symbol: string;
  /** Epoch ms of each point; the first is the window's start. */
  t: number[];
  /** Change %, from the window's base, at each point. */
  v: number[];
}

/** The span the chart's time axis covers: the whole session for the day; the last hour or 15 minutes read, ending no later than 15:30. */
export function chartSpan(flow: Pick<MarketFlow, 'date' | 'window' | 'futures'>): [number, number] {
  const open = Date.parse(`${flow.date}T00:00:00+05:30`) + OPEN_MINUTE * MINUTE;
  const close = sessionEndOf(flow.date);
  if (flow.window === 'day') return [open, close];
  const end = Math.min(close, flow.futures.latestAt ?? close);
  return [end - SCAN_MINUTES[flow.window] * MINUTE, end];
}

/**
 * An underlying's line over the window: it starts at 0% at the window's start
 * (the previous close for the day, the candle the reading starts from for 1h
 * and 15m) and takes every minute's close to its LAST candle, never beyond:
 * a line is never stretched to the right edge, so a stale future stops where
 * its prints stop. Null without a futures reading.
 */
export function lineOf(stock: Pick<FlowStock, 'symbol' | 'fut' | 'candles'>, t0: number, t1: number): FlowLine | null {
  const fut = stock.fut;
  if (!fut || !(fut.priceFrom > 0)) return null;
  const start = fut.from ?? t0;
  const t: number[] = [Math.max(t0, start)];
  const v: number[] = [0];
  for (const candle of stock.candles) {
    const end = candle.at + MINUTE;
    if (end <= start || end > t1) continue;
    t.push(end);
    v.push((candle.close / fut.priceFrom - 1) * 100);
  }
  return t.length >= 2 ? { symbol: stock.symbol, t, v } : null;
}

/**
 * A provisional line for a stock whose future has not been read: from nought at
 * the open to the spot's move now, eased (most of a day's move comes early),
 * in 24 steps so it curves like the lines around it. It says only where the
 * stock stands, not how it got there; the board draws it dashed.
 */
export function provisionalLine(symbol: string, changePct: number, t0: number, t1: number): FlowLine {
  const steps = 24;
  const t: number[] = [];
  const v: number[] = [];
  for (let i = 0; i <= steps; i++) {
    const k = i / steps;
    t.push(t0 + (t1 - t0) * k);
    v.push(changePct * (1 - Math.pow(1 - k, 2.2)));
  }
  return { symbol, t, v };
}

/** The SVG path of a line, every point drawn. */
export function pathOf(line: FlowLine, xOf: (ms: number) => number, yOf: (pct: number) => number): string {
  let d = '';
  for (let i = 0; i < line.t.length; i++) d += `${i ? 'L' : 'M'}${xOf(line.t[i]).toFixed(1)},${yOf(line.v[i]).toFixed(1)}`;
  return d;
}

/**
 * How far the change axis reaches either side of nought: the farthest point of
 * any named line or the index (never clamped), or the 98th percentile of every
 * point, whichever is larger, with 8% headroom; never under twice the floor.
 */
export function chartReach(lines: readonly FlowLine[], keep: ReadonlySet<string>, floorPct: number): number {
  let kept = 0;
  const all: number[] = [];
  for (const line of lines) {
    const named = keep.has(line.symbol);
    for (const value of line.v) {
      const abs = Math.abs(value);
      all.push(abs);
      if (named && abs > kept) kept = abs;
    }
  }
  all.sort((a, b) => a - b);
  return Math.max(kept, quantile(all, 0.98), floorPct * 2, 0.2) * 1.08;
}

/** Change ticks either side of nought: whole 1% for the day, 0.25% for an hour, 0.1% for 15 minutes, widened to keep `minPx` apart. */
export function changeTicks(reach: number, halfPx: number, window: FlowWindow, minPx = 26): number[] {
  const steps = [0.05, 0.1, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20];
  let step = window === 'day' ? 1 : window === '1h' ? 0.25 : 0.1;
  // Too few ticks on a quiet tape: step down to keep at least one each side.
  while (step > 0.05 && reach / step < 1.2) step = steps[Math.max(0, steps.indexOf(step) - 1)];
  while ((step / reach) * halfPx < minPx && steps.indexOf(step) < steps.length - 1) step = steps[steps.indexOf(step) + 1];
  const out: number[] = [];
  for (let value = step; value <= reach + 1e-9; value += step) out.push(Number(value.toFixed(4)));
  return out;
}

/**
 * Time ticks. The day: 09:15, every half hour, and 15:30 (hours only when the
 * chart is narrow). An hour: every 10 minutes; 15 minutes: every 5. Counted on
 * the IST clock.
 */
export function timeTicks(t0: number, t1: number, plotPx: number, window: FlowWindow): number[] {
  if (window === 'day') {
    // Labels need about 46px each: half hours when they fit, hours when not; none crowding the ends.
    const pxPerMin = plotPx / Math.max(1, (t1 - t0) / MINUTE);
    const step = ([30, 60, 120].find(minutes => pxPerMin * minutes >= 46) ?? 120) * MINUTE;
    const clear = 58 / Math.max(0.01, pxPerMin) * MINUTE;
    const out = [t0];
    for (let t = Math.ceil((t0 + IST_OFFSET + 1) / step) * step - IST_OFFSET; t < t1; t += step) if (t - t0 >= clear && t1 - t >= clear) out.push(t);
    out.push(t1);
    return out;
  }
  const step = (window === '1h' ? 10 : 5) * MINUTE;
  const out: number[] = [];
  for (let t = Math.ceil((t0 + IST_OFFSET) / step) * step - IST_OFFSET; t <= t1 + 1; t += step) out.push(t);
  return out;
}

/**
 * The lines each side names: the largest moves up and down by the window's
 * change, futures readings only (the same order as the tiles), N per side;
 * `except` (the index, drawn as the reference line) is never one of them.
 */
export function namedLines(flow: Pick<MarketFlow, 'bullish' | 'bearish'>, perSide: number, drawn: ReadonlySet<string>, except: string | null = null): { up: FlowStock[]; down: FlowStock[] } {
  const pick = (list: readonly FlowStock[]) => list.filter(stock => stock.source === 'futures' && stock.symbol !== except && drawn.has(stock.symbol)).slice(0, perSide);
  return { up: pick(flow.bullish), down: pick(flow.bearish) };
}

/**
 * The middle 80% and the median of every line, minute by minute: each line
 * holds its last value until its next print, and a minute counts only the
 * lines that have started. Arrays are by minute from t0.
 */
export function bandOf(lines: readonly FlowLine[], t0: number, t1: number): { t: number[]; lo: number[]; mid: number[]; hi: number[] } {
  const minutes = Math.max(0, Math.round((t1 - t0) / MINUTE));
  const out = { t: [] as number[], lo: [] as number[], mid: [] as number[], hi: [] as number[] };
  const cursors = lines.map(() => 0);
  for (let m = 0; m <= minutes; m++) {
    const at = t0 + m * MINUTE;
    const values: number[] = [];
    lines.forEach((line, i) => {
      if (line.t[0] > at || line.t[line.t.length - 1] < at - MINUTE) return;
      while (cursors[i] + 1 < line.t.length && line.t[cursors[i] + 1] <= at) cursors[i]++;
      values.push(line.v[cursors[i]]);
    });
    if (values.length < 3) continue;
    values.sort((a, b) => a - b);
    out.t.push(at);
    out.lo.push(quantile(values, 0.1));
    out.mid.push(quantile(values, 0.5));
    out.hi.push(quantile(values, 0.9));
  }
  return out;
}

/** A label for a line's end: "PNB +5.21%". */
export const endLabel = (symbol: string, pct: number | null | undefined) => {
  if (pct == null || !Number.isFinite(pct)) return symbol;
  return `${symbol} ${pct > 0 ? '+' : pct < 0 ? '−' : ''}${Math.abs(pct).toFixed(2)}%`;
};
