import { SCAN_WINDOW_MINUTES, SCAN_WINDOW_TOLERANCE_MS, type ScanWindow } from './contractScanModel';

/**
 * An underlying's build-up, read the way the market reads it: from its
 * FUTURES — the near-month future's price change against the change in open
 * interest over the same span. Open interest is every listed futures month
 * added together, so a position rolled from this month to the next cancels
 * out: read from the near month alone, every expiry week shows falling open
 * interest everywhere (25 Sep, four days before the September expiry: no
 * Long or short build-up at all, near-month OI down 35–49 %). Price up with OI
 * up is a long build-up; down with OI up, a short build-up; up with OI down,
 * short covering; down
 * with OI down, long unwinding. The span is the Contracts view's window:
 * 5m, 15m, 30m, 1h (read off the future's 1-minute candles, within the same
 * tolerances), or the day, against the previous session's close.
 */

/** One 1-minute candle of the future: its start, closing price (₹) and open interest (units). */
interface FuturesCandle { at: number; close: number; oi: number }

export interface FuturesSeries {
  symbol: string;
  /** Expiry of the future whose price is read: the nearest listed on or after the session. */
  contractDate: string;
  /** Every futures month whose open interest is added, nearest first. */
  months: string[];
  /** Previous session's near-month close and all-months open interest, the Day window's base. */
  prevClose: number | null;
  prevOi: number | null;
  /** The session's 1-minute candles, oldest first: near-month close, all-months open interest. */
  candles: FuturesCandle[];
}

/** One listed futures month as read: its previous session and its 1-minute candles. */
export interface FuturesMonth { date: string; prevClose: number | null; prevOi: number | null; candles: FuturesCandle[] }

/**
 * Adds the months together, minute by minute on the near month's candles. A
 * month with no print yet in a minute counts its last open interest — its
 * previous session's before its first candle — as the exchange's open
 * interest stays put until it changes.
 */
export function combineMonths(symbol: string, months: readonly FuturesMonth[]): FuturesSeries | null {
  const near = months[0];
  if (!near) return null;
  const others = months.slice(1).map(month => ({ ...month, cursor: -1 }));
  const candles = near.candles.map(candle => {
    let oi = candle.oi;
    for (const month of others) {
      while (month.cursor + 1 < month.candles.length && month.candles[month.cursor + 1].at <= candle.at) month.cursor++;
      oi += month.cursor >= 0 ? month.candles[month.cursor].oi : month.prevOi ?? 0;
    }
    return { at: candle.at, close: candle.close, oi };
  });
  // A month listed today has no previous session: it held nothing then.
  const prevOi = near.prevOi == null ? null : months.reduce((sum, month) => sum + (month.prevOi ?? 0), 0);
  return { symbol, contractDate: near.date, months: months.map(month => month.date), prevClose: near.prevClose, prevOi, candles };
}

export type FuturesBuildUp = 'LONG_BUILD' | 'SHORT_BUILD' | 'SHORT_COVER' | 'LONG_UNWIND' | 'NEUTRAL';

export interface FuturesReading {
  contractDate: string;
  months: string[];
  price: number;
  priceFrom: number;
  priceChange: number;
  priceChangePct: number;
  oi: number;
  oiFrom: number;
  oiChange: number;
  /** Null when the span started with no open interest. */
  oiChangePct: number | null;
  /** Epoch ms the span runs from (null: the previous session's close) and to (the last candle's close). */
  from: number | null;
  to: number;
  buildUp: FuturesBuildUp;
}

/** The four build-ups by the signs of the two changes; no change on either side is no build-up. */
export function futuresBuildUp(priceChange: number, oiChange: number): FuturesBuildUp {
  if (!(Math.abs(priceChange) > 1e-9) || !(Math.abs(oiChange) > 0)) return 'NEUTRAL';
  if (priceChange > 0) return oiChange > 0 ? 'LONG_BUILD' : 'SHORT_COVER';
  return oiChange > 0 ? 'SHORT_BUILD' : 'LONG_UNWIND';
}

const MINUTE = 60_000;

/**
 * The future's change over one window, or null when the window cannot be
 * measured: no candles, no previous close for the day, or no candle close
 * enough to the window's start (the Contracts view's tolerances: a 7-minute
 * gap is not "5m").
 */
export function readFuturesWindow(series: FuturesSeries, window: ScanWindow): FuturesReading | null {
  const last = series.candles[series.candles.length - 1];
  if (!last || !(last.close > 0)) return null;
  const to = last.at + MINUTE;
  let priceFrom: number | null = null;
  let oiFrom: number | null = null;
  let from: number | null = null;
  if (window === 'day') {
    priceFrom = series.prevClose;
    oiFrom = series.prevOi;
  } else {
    const target = to - SCAN_WINDOW_MINUTES[window] * MINUTE;
    let best: FuturesCandle | null = null;
    for (const candle of series.candles) {
      const end = candle.at + MINUTE;
      if (end >= to) continue;
      if (!best || Math.abs(end - target) < Math.abs(best.at + MINUTE - target)) best = candle;
    }
    if (best && Math.abs(best.at + MINUTE - target) <= SCAN_WINDOW_TOLERANCE_MS[window]) {
      priceFrom = best.close; oiFrom = best.oi; from = best.at + MINUTE;
    }
  }
  if (priceFrom == null || !(priceFrom > 0) || oiFrom == null || !(oiFrom >= 0)) return null;
  const priceChange = last.close - priceFrom;
  const oiChange = last.oi - oiFrom;
  return {
    contractDate: series.contractDate, months: series.months,
    price: last.close, priceFrom, priceChange, priceChangePct: priceChange / priceFrom * 100,
    oi: last.oi, oiFrom, oiChange, oiChangePct: oiFrom > 0 ? oiChange / oiFrom * 100 : null,
    from, to, buildUp: futuresBuildUp(priceChange, oiChange),
  };
}
