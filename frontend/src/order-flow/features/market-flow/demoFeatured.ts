import type { FuturesReading } from '../options-scanner/futuresModel';
import type { FlowCandle, FlowStock } from './marketFlowModel';

/**
 * Demo cards for the big slots while the futures are still being read.
 *
 * Each one starts from a real top mover on its side, so the symbol, spot,
 * spot move and the option levels (support, resistance, zone, the open
 * interest profile) are the market file's own. Only what needs the future is
 * made up: the intraday line, the futures price and open interest, the
 * build-up and the checks. The cards say "Demo" on their face, and the real
 * cards replace them as soon as enough futures have landed.
 */

const OPEN_MINUTE = 9 * 60 + 15;
const CLOSE_MINUTE = 15 * 60 + 30;
/** A typical near-month premium over spot. */
const BASIS = 0.0015;

/** A small seeded generator: the same symbol draws the same line on every render. */
function seeded(text: string) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
  return () => {
    h = Math.imul(h ^ (h >>> 15), 2246822507);
    h = Math.imul(h ^ (h >>> 13), 3266489909);
    return ((h ^= h >>> 16) >>> 0) / 4294967296;
  };
}

/** Today's (or the last session's) IST open as epoch ms. */
function sessionOpen(now: number): number {
  const ist = new Date(now + 330 * 60_000);
  const day = Date.UTC(ist.getUTCFullYear(), ist.getUTCMonth(), ist.getUTCDate());
  return day + OPEN_MINUTE * 60_000 - 330 * 60_000;
}

/**
 * A minute line from the previous close to spot: a random walk pinned at both
 * ends (a Brownian bridge) over the day's drift, with minute-to-minute jitter
 * so the 5-minute candles have real bodies and wicks.
 */
function demoCandles(symbol: string, from: number, to: number, oiStart: number, oiEnd: number, steps: number): FlowCandle[] {
  const random = seeded(symbol);
  const step = Math.max(Math.abs(to) * 0.0006, Math.abs(to - from) * 0.02);
  const walk = [0];
  for (let i = 1; i <= steps; i++) walk.push(walk[i - 1] + (random() - 0.5) * 2 * step);
  const start = sessionOpen(Date.now());
  return walk.map((value, i) => {
    const t = i / steps;
    // Most of the move comes early, as on a trending day; the bridge pins the walk to both ends.
    const drift = from + (to - from) * (1 - Math.pow(1 - t, 1.8));
    const jitter = i === 0 || i === steps ? 0 : (random() - 0.5) * step * 0.8;
    const close = drift + (value - walk[steps] * t) + jitter;
    return { at: start + i * 60_000, close: Math.round(close * 100) / 100, oi: Math.round(oiStart + (oiEnd - oiStart) * t) };
  });
}

/** The demo version of a real top mover, or null when it has no move to draw. */
export function demoStock(stock: FlowStock, side: 'bullish' | 'bearish'): FlowStock | null {
  if (stock.prevClose == null || !(stock.spot > 0) || stock.changePct == null) return null;
  const minutes = CLOSE_MINUTE - OPEN_MINUTE;
  const priceFrom = stock.prevClose * (1 + BASIS);
  const price = stock.spot * (1 + BASIS);
  const oiFrom = Math.max(1, Math.round((stock.options.putOi + stock.options.callOi) / 4)) * stock.lot;
  const oi = Math.round(oiFrom * 1.06);
  const candles = demoCandles(stock.symbol, priceFrom, price, oiFrom, oi, minutes);
  const fut: FuturesReading = {
    contractDate: stock.expiry, months: [], price, priceFrom,
    priceChange: price - priceFrom, priceChangePct: stock.changePct,
    oi, oiFrom, oiChange: oi - oiFrom, oiChangePct: ((oi - oiFrom) / oiFrom) * 100,
    from: null, to: candles[candles.length - 1].at + 60_000,
    buildUp: side === 'bullish' ? 'LONG_BUILD' : 'SHORT_BUILD',
  };
  return {
    ...stock,
    fut, futDay: fut,
    futures: 'read',
    buildUp: fut.buildUp,
    oiChangePct: fut.oiChangePct,
    candles,
    checks: stock.checks.map((check, i) => ({ ...check, pass: check.pass ?? i < 4 })),
  };
}

/** Up to `count` demo cards from the side's real leaders, in rank order. */
export function demoFeatured(list: readonly FlowStock[], side: 'bullish' | 'bearish', count: number): FlowStock[] {
  const out: FlowStock[] = [];
  for (const stock of list) {
    if (out.length >= count) break;
    const demo = demoStock(stock, side);
    if (demo) out.push(demo);
  }
  return out;
}
