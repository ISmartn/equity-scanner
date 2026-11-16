/**
 * formatters.ts
 * Centralized formatting functions to ensure consistency across all UI components.
 */

/**
 * Mantissa of |value| in `unit`, rounded to `decimals` places on an
 * integer-shifted scale. Dividing by the unit FIRST and calling toFixed
 * rounds the binary double, not the decimal value — 555000/1e5 is the
 * double 5.5499…, which toFixed(1) prints as '5.5' where every decimal
 * rounding convention gives 5.6. Shifting so the midpoint is exact
 * (555000/1e4 = 55.5) makes Math.round see the true decimal midpoint.
 */
function unitMantissa(abs: number, unit: number, decimals: number): number {
  const f = 10 ** decimals;
  return Math.round(abs / (unit / f)) / f;
}

/**
 * Format large numbers (OI, Volume) into human-readable strings (Cr, L, K).
 * E.g. 1500000 -> 15.0L
 *
 * The unit is chosen from the ROUNDED figure, so nothing prints past its
 * unit's ceiling: 99.96L rounds to 100.0L, which IS 1.00Cr — the reader gets
 * '1.00Cr', never the Indian-convention-breaking '100.0L' (same at the K→L
 * seam).
 */
export function fmtNum(num: number | undefined | null, decimals = 2): string {
  if (num === undefined || num === null || isNaN(num)) return '—';
  if (num === 0) return '0';

  const absNum = Math.abs(num);
  const sign = num < 0 ? '-' : '';

  if (absNum >= 1_000) {
    if (absNum < 100_000) {
      const k = unitMantissa(absNum, 1_000, 1);
      if (k < 100) return sign + k.toFixed(1) + 'K';
    }
    if (absNum < 10_000_000) {
      const l = unitMantissa(absNum, 100_000, 1);
      if (l < 100) return sign + l.toFixed(1) + 'L';
    }
    return sign + unitMantissa(absNum, 10_000_000, 2).toFixed(2) + 'Cr';
  }
  // No digit grouping anywhere: chain values never carry commas (UX, 05 Aug).
  return sign + plainFormat(decimals).format(absNum);
}

/*
 * One formatter per option set, built once. `toLocaleString` with options
 * builds a fresh Intl.NumberFormat on every call; the heatmap labels hundreds
 * of tiles a render through these, and `fmtPrice` alone was ~230 ms of a
 * throttled phone's first load (10 Oct 2026). Same locale and options, so the
 * output is identical.
 */
const PLAIN_FORMATS = new Map<number, Intl.NumberFormat>();
function plainFormat(maximumFractionDigits: number): Intl.NumberFormat {
  let format = PLAIN_FORMATS.get(maximumFractionDigits);
  if (!format) {
    format = new Intl.NumberFormat('en-IN', { maximumFractionDigits, useGrouping: false });
    PLAIN_FORMATS.set(maximumFractionDigits, format);
  }
  return format;
}
const PRICE_FORMAT = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2, useGrouping: false });

/**
 * Open-interest display formatter: LAKH to TWO decimals (11,440,975 →
 * '114.41L' below a crore — the benchmark's 2dp lakh precision), promoting
 * to CRORE at 1e7 ('3.94Cr') — a deliberate user decision, 2026-08-18:
 * magnitude-aware units above 1Cr, benchmark-precision lakh below. Below one
 * lakh the K tier applies. Same round-then-choose-unit rule as fmtNum, so
 * 99.997L prints as 1.00Cr, never '100.00L'.
 */
export function fmtOiLakh(num: number | undefined | null): string {
  if (num === undefined || num === null || isNaN(num)) return '—';
  if (num === 0) return '0';

  const abs = Math.abs(num);
  const sign = num < 0 ? '-' : '';

  if (abs >= 1_000) {
    if (abs < 100_000) {
      const k = unitMantissa(abs, 1_000, 1);
      if (k < 100) return sign + k.toFixed(1) + 'K';
    }
    if (abs < 10_000_000) {
      const l = unitMantissa(abs, 100_000, 2);
      if (l < 100) return sign + l.toFixed(2) + 'L';
    }
    return sign + unitMantissa(abs, 10_000_000, 2).toFixed(2) + 'Cr';
  }
  return sign + String(Math.round(abs));
}


/**
 * Format plain numeric labels with Indian commas and no currency prefix.
 */
export function fmtCompact(value: number | undefined | null): string {
  if (value === undefined || value === null || isNaN(value)) return '0';
  return plainFormat(0).format(value);
}

/**
 * Format spot prices, strike prices, and option premiums (LTP) with 2 decimal
 * places. No digit grouping — values never carry commas (UX, 05 Aug).
 */
export function fmtPrice(price: number | undefined | null): string {
  if (price === undefined || price === null || isNaN(price)) return '—';
  return PRICE_FORMAT.format(price);
}

/**
 * A market LEVEL as a whole number: a strike, a spot, a max-pain level, or a
 * distance between two of them. Never compacted, never grouped.
 *
 * This exists because `fmtNum` is the obvious-looking call and is the wrong
 * one. It compacts above 1000, so `fmtNum(24150, 0)` and `fmtNum(24190, 0)`
 * both return '24.2K' — a 40-point move rendered as no move at all — and on a
 * 100-step ladder a 1550-point distance prints '1.6K pts', losing 50 points on
 * a figure a reader is meant to act on. Compaction is correct for open
 * interest and volume, where the magnitude is the message; it is never correct
 * for a level, where the digits are.
 *
 * Levels are integers by convention here: the ladder is quoted in whole
 * points, and GexPage's flag labels already round. For a traded PRICE that
 * genuinely carries paise — an LTP or a premium — use `fmtPrice`.
 */
export function fmtLevel(level: number | undefined | null): string {
  if (level === undefined || level === null || isNaN(level)) return '—';
  return plainFormat(0).format(Math.round(level));
}


/**
 * Implied volatility — always TWO decimals, always with the unit, and always
 * with a stable trailing zero: `9.15%`, `14.00%`.
 *
 * A dedicated formatter rather than `fmtNum(iv, 2)` for two reasons.
 *
 * First, `fmtNum` sets `maximumFractionDigits` without a minimum, so it drops
 * trailing zeros: `fmtNum(14, 1)` is `'14'` and `fmtNum(14.25, 1)` is `'14.3'`.
 * A column formatted that way visibly jumps width and decimal count between
 * ticks. Every 1dp IV readout in the Straddle workspace inherited that.
 *
 * Second, 2dp is what the rest of the app already prints — the chain's per-leg
 * IV column, its Average IV column, the strike panel and the chain outlook are
 * all 2dp — and it is what the vendor web app shows. One precision, everywhere.
 *
 * Non-positive and non-finite input renders the em-dash, never `0.00%`: a
 * fabricated zero is indistinguishable from a measured one, and IV is never
 * legitimately zero. Surfaces that can say WHY it is missing should print that
 * sentence instead of this dash.
 */
export function fmtIv(iv: number | undefined | null): string {
  if (iv === undefined || iv === null || !Number.isFinite(iv) || iv <= 0) return '—';
  return `${iv.toFixed(2)}%`;
}

/**
 * A CHANGE in implied volatility, in vol points, explicitly signed.
 *
 * Separate from `fmtIv` because the two are governed by different rules: an IV
 * level is always neutral ink (design contract §4), while an IV change is one
 * of the five things permitted to carry direction colour. Keeping them apart in
 * the formatter makes that distinction hard to get wrong at the call site.
 *
 * The sign is text, never an arrow glyph, and a negative uses the true minus
 * U+2212 rather than a hyphen. `0.00` prints unsigned — a rounded-away move is
 * not a direction.
 */
export function fmtIvChange(delta: number | undefined | null): string {
  if (delta === undefined || delta === null || !Number.isFinite(delta)) return '—';
  const digits = Math.abs(delta).toFixed(2);
  if (Number(digits) === 0) return `${digits} pts`;
  return `${delta < 0 ? '−' : '+'}${digits} pts`;
}

/**
 * the app naming: the UI always reads Call/Put — never CE/PE (UX review, 05 Aug).
 *
 * Internal discriminants stay `'CE' | 'PE'` (and their lowercase `'ce' | 'pe'`
 * DOM-class variants) because the data layer, CSS and tests are keyed on them.
 * Anything that reaches a user — visible text, `title`, `aria-label`, tooltip
 * copy, narrative sentences — funnels the token through here first.
 */
export function optionSideLabel(
  side: string | null | undefined,
  opts: { plural?: boolean; case?: 'title' | 'lower' | 'upper' } = {},
): string {
  const token = (side ?? '').trim().toUpperCase();
  const isCall = token === 'CE' || token === 'CALL' || token === 'CALLS';
  const base = isCall ? 'Call' : 'Put';
  const word = opts.plural ? `${base}s` : base;
  if (opts.case === 'lower') return word.toLowerCase();
  if (opts.case === 'upper') return word.toUpperCase();
  return word;
}

