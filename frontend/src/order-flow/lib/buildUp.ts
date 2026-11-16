/**
 * Build-up: what a price move and an open-interest move say together.
 *   price up, OI up      long build-up      price down, OI up    short build-up
 *   price up, OI down    short covering     price down, OI down  long unwinding
 * Moves inside the noise floor (by timeframe) read as neutral.
 */
export type BuildUp = 'LONG_BUILD' | 'SHORT_BUILD' | 'SHORT_COVER' | 'LONG_UNWIND' | 'NEUTRAL';

export type BuildUpWindow = '1m' | '5m' | '15m' | '1h' | '1d';

type Timeframe = BuildUpWindow | 'live';

/** The smallest OI change (%) and price change (%, or ₹ when no percent is given) that counts as a move. */
export const BUILD_UP_NOISE_FLOOR: Record<Timeframe, { oiPct: number; pricePct: number }> = {
  '1m': { oiPct: 0.5, pricePct: 1.0 },
  '5m': { oiPct: 1.0, pricePct: 0.5 },
  '15m': { oiPct: 1.0, pricePct: 0.5 },
  '1h': { oiPct: 2, pricePct: 0.5 },
  '1d': { oiPct: 2, pricePct: 0.5 },
  live: { oiPct: 2, pricePct: 0.5 },
};

export function classify(priceChg: number, oiChg: number, oiChgPct: number, prevOi?: number, timeframe: Timeframe = 'live', priceChgPct?: number): BuildUp {
  // A strike that opened its first contracts today: any OI is new, so the price alone decides.
  if (prevOi === 0 && oiChg > 0) {
    if (priceChg > 0) return 'LONG_BUILD';
    if (priceChg < 0) return 'SHORT_BUILD';
    return 'NEUTRAL';
  }
  const havePct = typeof priceChgPct === 'number' && Number.isFinite(priceChgPct);
  const priceMetric = havePct ? Math.abs(priceChgPct as number) : Math.abs(priceChg);
  const floor = BUILD_UP_NOISE_FLOOR[timeframe];
  if (Math.abs(oiChgPct) < floor.oiPct || priceMetric < floor.pricePct) return 'NEUTRAL';
  if (priceChg > 0 && oiChg > 0) return 'LONG_BUILD';
  if (priceChg < 0 && oiChg > 0) return 'SHORT_BUILD';
  if (priceChg > 0 && oiChg < 0) return 'SHORT_COVER';
  if (priceChg < 0 && oiChg < 0) return 'LONG_UNWIND';
  return 'NEUTRAL';
}
