/**
 * The NIFTY 50's constituents, as F&O symbols in public/underlyings.json.
 *
 * As of the September 2025 rebalance (Tata Motors as TMPV after its
 * demerger). NSE reviews the index twice a year, in March and September:
 * update this list when it does.
 */
export const NIFTY_50 = [
  'ADANIENT', 'ADANIPORTS', 'APOLLOHOSP', 'ASIANPAINT', 'AXISBANK', 'BAJAJ-AUTO', 'BAJFINANCE', 'BAJAJFINSV', 'BEL', 'BHARTIARTL',
  'CIPLA', 'COALINDIA', 'DRREDDY', 'EICHERMOT', 'ETERNAL', 'GRASIM', 'HCLTECH', 'HDFCBANK', 'HDFCLIFE', 'HINDALCO',
  'HINDUNILVR', 'ICICIBANK', 'INDIGO', 'INFY', 'ITC', 'JIOFIN', 'JSWSTEEL', 'KOTAKBANK', 'LT', 'M&M',
  'MARUTI', 'MAXHEALTH', 'NESTLEIND', 'NTPC', 'ONGC', 'POWERGRID', 'RELIANCE', 'SBILIFE', 'SBIN', 'SHRIRAMFIN',
  'SUNPHARMA', 'TATACONSUM', 'TMPV', 'TATASTEEL', 'TCS', 'TECHM', 'TITAN', 'TRENT', 'ULTRACEMCO', 'WIPRO',
] as const;

/** The board's universe: the NIFTY 50 (with NIFTY itself, the chart's reference line) or every F&O underlying. */
export type FlowUniverse = 'nifty50' | 'fno';

const MEMBERS = new Set<string>([...NIFTY_50, 'NIFTY']);

export function inUniverse(symbol: string, universe: FlowUniverse): boolean {
  return universe === 'fno' || MEMBERS.has(symbol);
}

const KEY = 'orderFlow:universe:v1';
export function loadUniverse(): FlowUniverse {
  try { return localStorage.getItem(KEY) === 'nifty50' ? 'nifty50' : 'fno'; } catch { return 'fno'; }
}
export function saveUniverse(universe: FlowUniverse): void {
  try { localStorage.setItem(KEY, universe); } catch { /* A private window keeps the choice for this visit only. */ }
}
