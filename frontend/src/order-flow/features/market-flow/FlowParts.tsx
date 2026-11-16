import { memo, useEffect, useRef, useState, type CSSProperties } from 'react';
import { buildUpWord } from '../options-scanner/scannerWords';
import { MINUTE } from './flowChartModel';
import type { FlowCheck, FlowStock } from './marketFlowModel';

/** The direction a stock's figures are inked in. */
export const toneOf = (stock: Pick<FlowStock, 'side'>) => (stock.side === 'bullish' ? 'is-up' : stock.side === 'bearish' ? 'is-down' : 'is-flat');

/**
 * How hot a move is, 0 to 1, as `--heat`: the stylesheet deepens a tile's or
 * card's wash with it, so a 6% mover reads richer than a 0.6% one at a glance.
 * A sector's median moves less than its stocks, so it saturates sooner.
 */
export function heatStyle(changePct: number | null | undefined, full = 6): CSSProperties {
  const heat = changePct == null || !Number.isFinite(changePct) ? 0 : Math.min(1, Math.abs(changePct) / full);
  return { '--heat': heat.toFixed(3) } as CSSProperties;
}

/**
 * A short flash in the direction a move just went, laid over its tile or card:
 * nothing on the first paint, once per change of at least 0.01 point, so a
 * minute's update or a future landing shows where the board moved.
 */
export function TickFlash({ value }: { value: number | null | undefined }) {
  const previous = useRef(value);
  const [tick, setTick] = useState<{ n: number; dir: 'up' | 'down' } | null>(null);
  useEffect(() => {
    const before = previous.current;
    previous.current = value;
    if (before == null || value == null || Math.abs(value - before) < 0.01) return;
    setTick(held => ({ n: (held?.n ?? 0) + 1, dir: value > before ? 'up' : 'down' }));
  }, [value]);
  return tick ? <span key={tick.n} className={`mf-tick is-${tick.dir}`} aria-hidden="true" /> : null;
}

/** "+1.25%", "−0.40%": the true minus, never grouped. */
export function pctText(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  const sign = value > 0.0049 ? '+' : value < -0.0049 ? '−' : '';
  return `${sign}${abs.toFixed(abs >= 100 ? 0 : digits)}%`;
}

/** A signed number of points or rupees with the true minus. */
export function signedText(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return `${value > 0 ? '+' : value < 0 ? '−' : ''}${Math.abs(value).toFixed(digits)}`;
}

/** A change figure with its direction in the ink. */
export function ChangeText({ value, digits = 2, className = '', neutral = false }: { value: number | null | undefined; digits?: number; className?: string; neutral?: boolean }) {
  const tone = neutral || value == null ? 'is-flat' : value > 0.0049 ? 'is-up' : value < -0.0049 ? 'is-down' : 'is-flat';
  return <span className={`mf-num ${tone} ${className}`}>{pctText(value, digits)}</span>;
}

/**
 * Conviction: five dots, one per check, filled where it holds, hollow where
 * it does not, faint where the figure it needs is not there (not counted).
 */
export function DotMeter({ checks, count = false }: { checks: FlowCheck[]; count?: boolean }) {
  const held = checks.filter(check => check.pass).length;
  const counted = checks.filter(check => check.pass != null).length;
  const label = counted ? `Conviction: ${held} of ${counted}` : 'Conviction: not measured yet';
  return (
    <span className="mf-dots" role="img" aria-label={label}>
      {checks.map(check => <i key={check.id} className={check.pass == null ? 'is-unknown' : check.pass ? 'is-held' : 'is-open'} />)}
      {count && counted > 0 && <b aria-hidden="true">{held} of {counted}</b>}
    </span>
  );
}

/* The sector's name for the narrow rail, as OrderBlock's own rail does
   ("Cap Goods", not "Capital Goods & Infra", which was cut to "Capital
   Good…"). The full name stays in the pill's tooltip and its label. */
const SECTOR_SHORT: Readonly<Record<string, string>> = {
  'Capital Goods & Infra': 'Cap Goods',
  'Capital Markets': 'Cap Markets',
  'Retail & Consumer Durables': 'Retail',
  'Private Banks': 'Pvt Banks',
  'Auto Ancillary': 'Auto Ancil.',
  'New-Age Internet': 'New-Age',
  'Oil & Gas': 'Oil & Gas',
};
export function shortSector(label: string): string {
  return SECTOR_SHORT[label] ?? label.split(' & ')[0];
}

/** The build-up in words, or why there is none yet. */
export function buildUpText(stock: Pick<FlowStock, 'buildUp' | 'futures'>): string {
  if (stock.buildUp) return buildUpWord(stock.buildUp);
  if (stock.futures === 'pending') return 'Loading future…';
  if (stock.futures === 'failed') return 'Could not load future';
  if (stock.futures === 'unavailable') return 'No future listed';
  return buildUpWord('NEUTRAL');
}

/** The build-up as a 6px mark: filled where positions were opened, a ring where they were closed, nothing otherwise. */
export function BuildMark({ stock }: { stock: Pick<FlowStock, 'buildUp'> }) {
  const code = stock.buildUp;
  if (code === 'LONG_BUILD' || code === 'SHORT_BUILD') return <i className="mf-mark is-opened" aria-hidden="true" />;
  if (code === 'SHORT_COVER' || code === 'LONG_UNWIND') return <i className="mf-mark is-closed" aria-hidden="true" />;
  return <i className="mf-mark is-none" aria-hidden="true" />;
}

/** The candles of the window the board reads: the session for the day, from the reading's start for 1h and 15m. */
export function windowCandles(stock: Pick<FlowStock, 'candles' | 'fut'>) {
  const from = stock.fut?.from;
  return from == null ? stock.candles : stock.candles.filter(candle => candle.at + MINUTE > from);
}

/**
 * A small line of the window's closes, scaled to its own range, with the
 * window's base as a faint rule where it falls inside. Used on tiles (no
 * rule) and cards.
 */
export const Spark = memo(function Spark({ stock, width, height, base = false, zone = false, fluid = false }: { stock: FlowStock; width: number; height: number; base?: boolean; zone?: boolean; fluid?: boolean }) {
  const candles = windowCandles(stock);
  if (candles.length < 2) return <svg className="mf-spark is-empty" width={width} height={height} aria-hidden="true" />;
  const step = Math.max(1, Math.floor(candles.length / Math.max(8, width / 1.5)));
  let low = Infinity;
  let high = -Infinity;
  for (const candle of candles) { low = Math.min(low, candle.close); high = Math.max(high, candle.close); }
  const from = stock.fut?.priceFrom ?? null;
  if (base && from != null) { low = Math.min(low, from); high = Math.max(high, from); }
  if (zone && stock.zone) { low = Math.min(low, stock.zone.low); high = Math.max(high, stock.zone.high); }
  const span = high - low || high * 0.001 || 1;
  const t0 = candles[0].at;
  const t1 = candles[candles.length - 1].at;
  const x = (t: number) => 1 + ((t - t0) / Math.max(1, t1 - t0)) * (width - 2);
  const y = (price: number) => 1.5 + (1 - (price - low) / span) * (height - 3);
  let d = '';
  for (let i = 0; i < candles.length; i += step) d += `${i ? 'L' : 'M'}${x(candles[i].at).toFixed(1)},${y(candles[i].close).toFixed(1)}`;
  const last = candles[candles.length - 1];
  d += `L${x(last.at).toFixed(1)},${y(last.close).toFixed(1)}`;
  return (
    <svg className={`mf-spark ${toneOf(stock)}${fluid ? ' is-fluid' : ''}`} width={fluid ? '100%' : width} height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio={fluid ? 'none' : undefined} aria-hidden="true">
      {zone && stock.zone && stock.zone.to > t0 && (
        <rect className="mf-spark__zone" x={x(Math.max(t0, stock.zone.from))} width={Math.max(2, x(Math.min(t1, stock.zone.to)) - x(Math.max(t0, stock.zone.from)))}
          y={y(stock.zone.high)} height={Math.max(2, y(stock.zone.low) - y(stock.zone.high))} rx="1" />
      )}
      {base && from != null && <line className="mf-spark__base" x1="0" x2={width} y1={y(from)} y2={y(from)} vectorEffect="non-scaling-stroke" />}
      <path className="mf-spark__line" d={d} vectorEffect="non-scaling-stroke" />
      {!fluid && <circle className="mf-spark__dot" cx={x(last.at)} cy={y(last.close)} r={height > 20 ? 2.2 : 1.6} />}
    </svg>
  );
});
