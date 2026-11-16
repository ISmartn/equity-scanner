import { MINUTE } from './flowChartModel';
import type { FlowCandle } from './marketFlowModel';

/**
 * The flow diagram's geometry, apart from React and the DOM: the compressed
 * change scale (so the crowd near nought spreads out and the few large moves
 * still fit), the gate where every line's end collects in rank order, the
 * curves that carry a line on to its tile, and the 5-minute candles drawn
 * from the minute closes.
 */

/** The knee of the compressed scale, %: moves under it are near linear, larger ones are drawn on a log. */
export const SCALE_KNEE = 0.35;

const g = (abs: number) => Math.log1p(abs / SCALE_KNEE);

/** A symmetric compressed scale: change % to y, nought at `zeroY`, `reach` at `half` px from it. Values past the reach are held at the edge. */
export function compressedScale(reach: number, zeroY: number, half: number) {
  const top = g(Math.max(reach, 0.05));
  const y = (pct: number) => zeroY - Math.sign(pct) * (Math.min(g(Math.abs(pct)), top) / top) * half;
  return y;
}

/** The ticks a compressed scale can carry without crowding: from a fixed ladder, each at least `minPx` from the last and from nought. */
export function compressedTicks(reach: number, half: number, minPx = 22): number[] {
  const ladder = [0.1, 0.2, 0.5, 1, 2, 3, 5, 8, 10, 15, 20];
  const y = compressedScale(reach, 0, half);
  const out: number[] = [];
  let last = 0;
  for (const value of ladder) {
    if (value > reach * 1.0001) break;
    const at = -y(value);
    if (at - last >= minPx) { out.push(value); last = at; }
  }
  return out;
}

export interface GateRow { symbol: string; y: number }

/**
 * Where each line lands in the tunnels. Every up line is squeezed into one
 * short band at the top (largest move first), every down line into one at the
 * bottom (largest move last, at the very bottom), and the flat names into a
 * thin band on the zero line: the whole market visibly converges through two
 * narrow tunnels before fanning out to its tiles. Each band takes at most
 * `share` of the height and never spaces its lines more than `maxPitch` apart.
 */
export function gateRows(
  up: readonly string[], flat: readonly string[], down: readonly string[], top: number, bottom: number,
  { share = 0.1, maxPitch = 3, flatShare = 0.04 }: { share?: number; maxPitch?: number; flatShare?: number } = {},
): { rows: Map<string, number>; upEnd: number; downStart: number; flatTop: number; flatBottom: number } {
  const height = bottom - top;
  const band = (count: number, most: number) => Math.min(height * most, count * maxPitch);
  const upH = band(up.length, share);
  const downH = band(down.length, share);
  const flatH = band(flat.length, flatShare);
  const mid = (top + bottom) / 2;
  const rows = new Map<string, number>();
  up.forEach((symbol, i) => rows.set(symbol, top + ((i + 0.5) / up.length) * upH));
  flat.forEach((symbol, i) => rows.set(symbol, mid - flatH / 2 + ((i + 0.5) / flat.length) * flatH));
  // Largest down move at the bottom: `down` is largest first.
  down.forEach((symbol, i) => rows.set(symbol, bottom - ((i + 0.5) / down.length) * downH));
  return { rows, upEnd: top + upH, downStart: bottom - downH, flatTop: mid - flatH / 2, flatBottom: mid + flatH / 2 };
}

/** A smooth horizontal S-curve from one point to another (a cubic with level ends). */
export function sCurve(x0: number, y0: number, x1: number, y1: number, pull = 0.5): string {
  const dx = (x1 - x0) * pull;
  return `M${x0.toFixed(1)},${y0.toFixed(1)}C${(x0 + dx).toFixed(1)},${y0.toFixed(1)} ${(x1 - dx).toFixed(1)},${y1.toFixed(1)} ${x1.toFixed(1)},${y1.toFixed(1)}`;
}

/** The same curve as a continuation (no move-to), for joining onto a path that already ends at x0,y0. */
export function sCurveOn(x0: number, y0: number, x1: number, y1: number, pull = 0.5): string {
  return sCurve(x0, y0, x1, y1, pull).replace(/^M[^C]+/, '');
}

export interface Candle { at: number; open: number; high: number; low: number; close: number }

/**
 * Candles of `minutes` minutes from the futures' minute closes: open is the
 * first close in the span, high and low the highest and lowest close, close
 * the last. Spans are counted from the first candle.
 */
export function candlesFromCloses(candles: readonly FlowCandle[], minutes = 5): Candle[] {
  const out: Candle[] = [];
  if (!candles.length) return out;
  const span = minutes * MINUTE;
  const origin = candles[0].at;
  let current: Candle | null = null;
  let bucket = -1;
  for (const candle of candles) {
    const b = Math.floor((candle.at - origin) / span);
    if (b !== bucket || !current) {
      current = { at: origin + b * span, open: candle.close, high: candle.close, low: candle.close, close: candle.close };
      out.push(current);
      bucket = b;
    } else {
      current.high = Math.max(current.high, candle.close);
      current.low = Math.min(current.low, candle.close);
      current.close = candle.close;
    }
  }
  return out;
}

/** Points either side the glitch filter compares a point with. */
const GLITCH_HALF_WINDOW = 3;
/** A point further than this (in % of change) from its neighbourhood's median is a bad print. */
const GLITCH_PCT = 1.5;
/** Minutes either side the drawn curve averages over: centred, so the curve does not lag and ends on the line's own level. */
const SMOOTH_HALF = 6;
/** Minutes over which a line eases out of nought at the window's start. */
const EASE_MINUTES = 10;

/**
 * The values a line is DRAWN with (the reported change is never touched):
 * a point that sits more than GLITCH_PCT from the median of the seven
 * minutes around it is a bad print or a spike that reverted within three
 * minutes, and takes that median instead; a lasting move (a step that
 * holds) passes, because the median follows it. Then a centred moving
 * average over SMOOTH_HALF minutes either side (no lag; the window shrinks at
 * the ends, so the last point is the line's own recent level), and an ease
 * out of nought over the first EASE_MINUTES, so each line leaves the origin
 * as a curve and the minute-to-minute jitter does not hide the flow. The
 * first value (the window's start, nought) is kept.
 */
export function drawnValues(values: readonly number[]): number[] {
  const n = values.length;
  if (n < 3) return [...values];
  const clean = values.slice();
  for (let i = 1; i < n; i++) {
    const from = Math.max(1, i - GLITCH_HALF_WINDOW);
    const to = Math.min(n - 1, i + GLITCH_HALF_WINDOW);
    const window = values.slice(from, to + 1).sort((a, b) => a - b);
    const median = window[window.length >> 1];
    if (Math.abs(values[i] - median) > GLITCH_PCT) clean[i] = median;
  }
  const out = [clean[0]];
  for (let i = 1; i < n; i++) {
    const from = Math.max(1, i - SMOOTH_HALF);
    const to = Math.min(n - 1, i + SMOOTH_HALF);
    let sum = 0;
    for (let j = from; j <= to; j++) sum += clean[j];
    const t = Math.min(1, i / EASE_MINUTES);
    out.push((sum / (to - from + 1)) * t * t * (3 - 2 * t));
  }
  return out;
}
