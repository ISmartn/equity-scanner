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
 *
 * A trigger that goes stale while the board is watching it is decided at
 * once, by the board and not the reader (adviceOf): closed, the exit being the
 * price then, or continued, watched on with a stop and a target of its own and
 * closed when one is reached. One the board first reads already stale was
 * never in play: it is `missed`.
 */

export type SignalKind = 'buy' | 'sell';
/** Why a trigger went stale. */
export type StaleOutcome = 'target' | 'stop' | 'side' | 'zone' | 'replaced' | 'aged';
/** What became of it once stale: closed, watched on, or never in play (first read already stale). */
export type Decision = 'closed' | 'continued' | 'missed';
/** call: closed by the board's decision when it went stale; stop / target: a continued trigger reached one. */
export type ClosedBy = 'call' | 'stop' | 'target';
/** The levels a continued trigger is watched against; null is none. */
export interface HoldLevels { stop: number | null; target: { name: string; price: number } | null }

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
  outcome: StaleOutcome | null;
  /** The future's price when it went stale. */
  exitPrice: number | null;
  /** What the board decided when it went stale; null only on an active trigger. */
  decision: Decision | null;
  /** The reason for that decision, in words. */
  decisionWhy: string | null;
  /** Market time and price of the decision (the close, or the moment of continuing). */
  decidedAt: number | null;
  decidedPrice: number | null;
  closedBy: ClosedBy | null;
  hold: HoldLevels | null;
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

export const priceOf = (stock: FlowStock) => stock.fut?.price ?? stock.spot;
export const clockAt = (stock: FlowStock, flow: MarketFlow) => stock.fut?.to ?? flow.asOf;

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
function staleCheck(signal: FlowSignal, stock: FlowStock, now: number): { outcome: StaleOutcome; reason: string } | null {
  const side = signal.kind === 'buy' ? 'bullish' : 'bearish';
  if (stock.side !== side) return { outcome: 'side', reason: stock.side === 'rangebound' ? 'Move fell inside the floor' : stock.side ? `Side turned ${stock.side}` : 'Reading lost' };
  if (!stock.zone) return { outcome: 'zone', reason: 'Zone no longer holds' };
  if (`${stock.symbol}:${stock.zone.from}` !== signal.id) return { outcome: 'replaced', reason: 'A newer zone replaced it' };
  const price = priceOf(stock);
  if (signal.kind === 'buy' ? price < signal.stop : price > signal.stop) return { outcome: 'stop', reason: `Stop broken at ${price.toFixed(2)}` };
  if (signal.target && (signal.kind === 'buy' ? price >= signal.target.price : price <= signal.target.price)) return { outcome: 'target', reason: `${signal.target.name} reached at ${price.toFixed(2)}` };
  if (now - signal.triggeredAt > STALE_AFTER_MINUTES * MINUTE) return { outcome: 'aged', reason: `Older than ${STALE_AFTER_MINUTES} minutes` };
  return null;
}

// ── What a stale trigger asks of the reader ──────────────────────────────

/** The entry as one price: the middle of the zone. The page says so. */
export const entryOf = (signal: Pick<FlowSignal, 'entryLow' | 'entryHigh'>) => (signal.entryLow + signal.entryHigh) / 2;

/** Profit or loss of the trade from the entry to a price: points, % of the entry, and rupees for one lot. */
export function pnlOf(signal: FlowSignal, price: number) {
  const entry = entryOf(signal);
  const points = signal.kind === 'buy' ? price - entry : entry - price;
  return { points, pct: entry > 0 ? (points / entry) * 100 : 0, perLot: points * signal.context.lot };
}

/** The option levels past the trade, nearest first: R1, R2 for a buy; S1, S2 for a sell. */
function levelsOf(signal: FlowSignal): Array<{ name: string; price: number }> {
  const { levels } = signal.context;
  const list = signal.kind === 'buy'
    ? [{ name: 'R1', price: levels.resistance }, { name: 'R2', price: levels.resistance2 }]
    : [{ name: 'S1', price: levels.support }, { name: 'S2', price: levels.support2 }];
  return list.filter((level): level is { name: string; price: number } => level.price != null);
}

/**
 * What continuing watches it against. After a target, the stop is trailed to
 * the entry and the next level past the price is the new target; otherwise
 * the original stop stays (none when the price is already through it) and
 * the nearest level still ahead is the target.
 */
export function continuePlan(signal: FlowSignal, price: number): HoldLevels {
  const buy = signal.kind === 'buy';
  const ahead = levelsOf(signal).filter(level => (buy ? level.price > Math.max(price, signal.entryHigh) : level.price < Math.min(price, signal.entryLow)));
  const target = ahead.sort((a, b) => (buy ? a.price - b.price : b.price - a.price))[0] ?? null;
  const unbroken = buy ? price > signal.stop : price < signal.stop;
  return { stop: signal.outcome === 'target' ? entryOf(signal) : unbroken ? signal.stop : null, target };
}

export interface SignalAdvice { lean: 'close' | 'continue'; why: string }

/** A suggestion, from the reading now: continue only while the same positions are still being added and a level lies ahead. */
export function adviceOf(signal: FlowSignal, stock: FlowStock | null): SignalAdvice {
  const buy = signal.kind === 'buy';
  const holds = stock != null && stock.futures === 'read' && stock.side === (buy ? 'bullish' : 'bearish');
  const building = stock?.buildUp === (buy ? 'LONG_BUILD' : 'SHORT_BUILD');
  const counted = stock ? stock.checks.filter(check => check.pass != null) : [];
  const convinced = counted.length > 0 && counted.filter(check => check.pass).length * 2 >= counted.length;
  const price = stock && stock.futures === 'read' ? priceOf(stock) : signal.exitPrice ?? entryOf(signal);
  switch (signal.outcome) {
    case 'stop': return { lean: 'close', why: 'The price went through the stop: the plan is over.' };
    case 'side': return { lean: 'close', why: 'The move turned: the reading that raised it is gone.' };
    case 'zone': return { lean: 'close', why: 'The zone no longer holds: the entry has nothing behind it.' };
    case 'replaced': return { lean: 'close', why: 'A newer zone is tracked as its own trigger: following both doubles the position.' };
    case 'target': {
      const next = continuePlan(signal, price).target;
      if (holds && building && convinced && next) return { lean: 'continue', why: `Positions are still being added the same way and ${next.name} is ahead: trail the stop to the entry and aim for it.` };
      return { lean: 'close', why: !next ? 'Target reached and no further option level lies ahead.' : !holds ? 'Target reached and the move has lost its side.' : 'Target reached and positions are no longer being added with the move.' };
    }
    default:
      if (holds && building && convinced) return { lean: 'continue', why: 'It is still inside its stop and target and the same positions are still being added.' };
      return { lean: 'close', why: stock ? 'Nothing now backs it: positions are not being added with the move.' : 'It is not on this board now, so there is no reading to hold it by.' };
  }
}

/** The signal after the board's decision, at a market time and price. */
export function decideSignal(signal: FlowSignal, choice: 'closed' | 'continued', price: number, at: number, why: string): FlowSignal {
  if (signal.state !== 'stale' || signal.decision) return signal;
  return choice === 'closed'
    ? { ...signal, decision: 'closed', decisionWhy: why, decidedAt: at, decidedPrice: price, closedBy: 'call' }
    : { ...signal, decision: 'continued', decisionWhy: why, decidedAt: at, decidedPrice: price, hold: continuePlan(signal, price) };
}

/** A stale trigger the board was watching, decided from the reading now. */
function decide(signal: FlowSignal, stock: FlowStock | null, price: number, at: number): FlowSignal {
  const advice = adviceOf(signal, stock);
  return decideSignal(signal, advice.lean === 'close' ? 'closed' : 'continued', price, at, advice.why);
}

/**
 * The log after one more reading: every trigger already logged is checked
 * against its stock (an underlying off the board or with its future unread is
 * left as it was), and each new zone on a side is added. A trigger that goes
 * stale is decided on the spot. A new trigger can be born stale, when the
 * board first reads it after its stop, target or age: it is missed.
 */
export function reconcileSignals(previous: readonly FlowSignal[], flow: MarketFlow, wallNow: number = Date.now(), dismissed: readonly string[] = []): FlowSignal[] {
  const bySymbol = new Map(flow.stocks.map(stock => [stock.symbol, stock]));
  const known = new Set([...previous.map(signal => signal.id), ...dismissed]);
  let changed = false;
  const next = previous.map(signal => {
    const stock = bySymbol.get(signal.symbol);
    if (!stock || stock.futures !== 'read') return signal;
    const now = clockAt(stock, flow);
    if (signal.state === 'stale' && signal.decision === null) {
      // Stale before the board decided for itself (an older log): decided now.
      changed = true;
      return { ...decide(signal, stock, priceOf(stock), now), updatedAt: wallNow };
    }
    if (signal.state === 'stale') {
      // Continued: watched against its own stop and target, and closed when one is reached.
      if (signal.decision !== 'continued' || !signal.hold) return signal;
      const price = priceOf(stock);
      const buy = signal.kind === 'buy';
      const { stop, target } = signal.hold;
      const by: ClosedBy | null = stop != null && (buy ? price < stop : price > stop) ? 'stop'
        : target && (buy ? price >= target.price : price <= target.price) ? 'target' : null;
      if (!by) return signal;
      changed = true;
      return { ...signal, decision: 'closed' as const, decidedAt: now, decidedPrice: price, closedBy: by, updatedAt: wallNow };
    }
    const check = staleCheck(signal, stock, now);
    if (!check) return signal;
    changed = true;
    const stale: FlowSignal = { ...signal, state: 'stale', staleAt: now, staleReason: check.reason, outcome: check.outcome, exitPrice: priceOf(stock) };
    return { ...decide(stale, stock, priceOf(stock), now), updatedAt: wallNow };
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
      state: 'active', staleAt: null, staleReason: null, outcome: null, exitPrice: null,
      decision: null, decisionWhy: null, decidedAt: null, decidedPrice: null, closedBy: null, hold: null, updatedAt: wallNow,
      context: contextOf(stock, flow, zone, wallNow),
    };
    const now = clockAt(stock, flow);
    const check = staleCheck(signal, stock, now);
    // First read already stale: it was never in play, so it asks nothing of the reader.
    next.push(check ? { ...signal, state: 'stale', staleAt: now, staleReason: check.reason, outcome: check.outcome, exitPrice: priceOf(stock), decision: 'missed', decisionWhy: 'First read after it had already gone stale: never in play.' } : signal);
    changed = true;
  }
  if (!changed) return previous as FlowSignal[];
  return next.sort((a, b) => b.triggeredAt - a.triggeredAt || a.symbol.localeCompare(b.symbol)).slice(0, MAX_SIGNALS);
}

const KEY = 'orderFlow:signals:v4';

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
