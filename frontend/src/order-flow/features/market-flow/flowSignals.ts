import type { FlowLevel, FlowStock, MarketFlow } from './marketFlowModel';

/**
 * The board's notifications: a zone read on a side is a trigger. A bullish
 * zone is a buy, a bearish one a sell, stamped at the minute the zone
 * completed. The zone is the entry band; the zone's far edge is the stop; the
 * first option level past the zone the way of the move is the target.
 *
 * A trigger goes stale, once and for good, when the reading under it no
 * longer holds: the side turns, a newer zone replaces it, the price breaks
 * the stop or reaches the target, or it has stood longer than
 * STALE_AFTER_MINUTES without either.
 */

export type SignalKind = 'buy' | 'sell';

export interface FlowSignal {
  /** `${symbol}:${zone.from}`: one trigger per zone. */
  id: string;
  symbol: string;
  kind: SignalKind;
  /** Market time (epoch ms) the zone completed: the trigger. */
  triggeredAt: number;
  entryLow: number;
  entryHigh: number;
  stop: number;
  target: { name: string; price: number } | null;
  state: 'active' | 'stale';
  /** Market time it went stale, and why. */
  staleAt: number | null;
  staleReason: string | null;
  /** Wall clock of the last change the reader has not seen (created or gone stale). */
  updatedAt: number;
  /** The reading that raised it, frozen when the board first saw it: what a backtest sorts and filters by. */
  context: SignalContext;
}

export interface SignalContext {
  window: MarketFlow['window'];
  floorPct: number;
  /** Wall clock the board first read it, and the future's price then: how late the board was to the trigger. */
  seenAt: number;
  seenPrice: number;
  spot: number;
  prevClose: number | null;
  changePct: number | null;
  oiChangePct: number | null;
  buildUp: FlowStock['buildUp'];
  strength: number;
  rank: number | null;
  checksHeld: number;
  checksCounted: number;
  sector: string;
  kindOfUnderlying: FlowStock['kind'];
  expiry: string;
  lot: number;
  pcr: number | null;
  zone: { from: number; to: number; oiAdded: number };
  levels: { support: number | null; support2: number | null; resistance: number | null; resistance2: number | null };
}

export const STALE_AFTER_MINUTES = 60;
const MINUTE = 60_000;
const MAX_SIGNALS = 300;

const priceOf = (stock: FlowStock) => stock.fut?.price ?? stock.spot;
const clockAt = (stock: FlowStock, flow: MarketFlow) => stock.fut?.to ?? flow.asOf;

function contextOf(stock: FlowStock, flow: MarketFlow, zone: NonNullable<FlowStock['zone']>, wallNow: number): SignalContext {
  const counted = stock.checks.filter(check => check.pass != null);
  return {
    window: flow.window, floorPct: flow.floorPct, seenAt: wallNow, seenPrice: priceOf(stock), spot: stock.spot, prevClose: stock.prevClose,
    changePct: stock.changePct, oiChangePct: stock.oiChangePct, buildUp: stock.buildUp, strength: stock.strength, rank: stock.rank,
    checksHeld: counted.filter(check => check.pass).length, checksCounted: counted.length,
    sector: stock.sector, kindOfUnderlying: stock.kind, expiry: stock.expiry, lot: stock.lot, pcr: stock.options.pcr,
    zone: { from: zone.from, to: zone.to, oiAdded: zone.oiAdded },
    levels: { support: stock.support?.strike ?? null, support2: stock.support2?.strike ?? null, resistance: stock.resistance?.strike ?? null, resistance2: stock.resistance2?.strike ?? null },
  };
}

function targetOf(stock: FlowStock, kind: SignalKind, low: number, high: number): FlowSignal['target'] {
  const levels: Array<[string, FlowLevel | null]> = kind === 'buy'
    ? [['R1', stock.resistance], ['R2', stock.resistance2]]
    : [['S1', stock.support], ['S2', stock.support2]];
  for (const [name, level] of levels) {
    if (level && (kind === 'buy' ? level.strike > high : level.strike < low)) return { name, price: level.strike };
  }
  return null;
}

/** Why an active trigger no longer holds against this reading, or null while it does. */
function staleReason(signal: FlowSignal, stock: FlowStock, now: number): string | null {
  const side = signal.kind === 'buy' ? 'bullish' : 'bearish';
  if (stock.side !== side) return stock.side === 'rangebound' ? 'Move fell inside the floor' : stock.side ? `Side turned ${stock.side}` : 'Reading lost';
  if (!stock.zone) return 'Zone no longer holds';
  if (`${stock.symbol}:${stock.zone.from}` !== signal.id) return 'A newer zone replaced it';
  const price = priceOf(stock);
  if (signal.kind === 'buy' ? price < signal.stop : price > signal.stop) return `Stop broken at ${price.toFixed(2)}`;
  if (signal.target && (signal.kind === 'buy' ? price >= signal.target.price : price <= signal.target.price)) return `${signal.target.name} reached at ${price.toFixed(2)}`;
  if (now - signal.triggeredAt > STALE_AFTER_MINUTES * MINUTE) return `Older than ${STALE_AFTER_MINUTES} minutes`;
  return null;
}

/**
 * The log after one more reading: every trigger already logged is checked
 * against its stock (an underlying off the board or with its future unread is
 * left as it was), and each new zone on a side is added. A new trigger can be
 * born stale, when the board first reads it after its stop, target or age.
 */
export function reconcileSignals(previous: readonly FlowSignal[], flow: MarketFlow, wallNow: number = Date.now(), dismissed: readonly string[] = []): FlowSignal[] {
  const bySymbol = new Map(flow.stocks.map(stock => [stock.symbol, stock]));
  const known = new Set([...previous.map(signal => signal.id), ...dismissed]);
  let changed = false;
  const next = previous.map(signal => {
    const stock = bySymbol.get(signal.symbol);
    if (signal.state === 'stale' || !stock || stock.futures !== 'read') return signal;
    const now = clockAt(stock, flow);
    const reason = staleReason(signal, stock, now);
    if (!reason) return signal;
    changed = true;
    return { ...signal, state: 'stale' as const, staleAt: now, staleReason: reason, updatedAt: wallNow };
  });
  for (const stock of flow.stocks) {
    const zone = stock.zone;
    if (!zone || stock.futures !== 'read' || (stock.side !== 'bullish' && stock.side !== 'bearish')) continue;
    const id = `${stock.symbol}:${zone.from}`;
    if (known.has(id)) continue;
    const kind: SignalKind = stock.side === 'bullish' ? 'buy' : 'sell';
    const signal: FlowSignal = {
      id, symbol: stock.symbol, kind, triggeredAt: zone.to,
      entryLow: zone.low, entryHigh: zone.high, stop: kind === 'buy' ? zone.low : zone.high,
      target: targetOf(stock, kind, zone.low, zone.high),
      state: 'active', staleAt: null, staleReason: null, updatedAt: wallNow,
      context: contextOf(stock, flow, zone, wallNow),
    };
    const now = clockAt(stock, flow);
    const reason = staleReason(signal, stock, now);
    next.push(reason ? { ...signal, state: 'stale', staleAt: now, staleReason: reason } : signal);
    changed = true;
  }
  if (!changed) return previous as FlowSignal[];
  return next.sort((a, b) => b.triggeredAt - a.triggeredAt || a.symbol.localeCompare(b.symbol)).slice(0, MAX_SIGNALS);
}

const KEY = 'orderFlow:signals:v2';

export interface StoredSignals { date: string; readAt: number; signals: FlowSignal[]; /** Ids cleared from the pane: the zone is still on the board, but not raised again. */ dismissed: string[] }

export function loadSignals(): StoredSignals | null {
  try {
    const raw = localStorage.getItem(KEY);
    const parsed = raw ? JSON.parse(raw) as StoredSignals : null;
    return parsed && typeof parsed.date === 'string' && Array.isArray(parsed.signals) ? { ...parsed, dismissed: parsed.dismissed ?? [] } : null;
  } catch { return null; }
}

export function saveSignals(stored: StoredSignals): void {
  try { localStorage.setItem(KEY, JSON.stringify(stored)); } catch { /* A private window keeps the log for this visit only. */ }
}
