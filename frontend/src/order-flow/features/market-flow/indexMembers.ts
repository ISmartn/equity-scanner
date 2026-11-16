/**
 * Stocks inside the indices the board can open.
 *
 * NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, and NIFTYNXT50 are the NSE
 * constituent files as of November 2026. SENSEX matches the live-scan basket.
 * BANKEX is the ten BSE bank names. A name that is not on the current board
 * is counted as missing and left off the list.
 */
import { NIFTY_50 } from './nifty50';
import type { FlowStock } from './marketFlowModel';

const BANKNIFTY = [
  'AUBANK', 'AXISBANK', 'BANKBARODA', 'CANBK', 'FEDERALBNK', 'HDFCBANK',
  'ICICIBANK', 'IDFCFIRSTB', 'INDUSINDBK', 'KOTAKBANK', 'PNB', 'SBIN',
  'UNIONBANK', 'YESBANK',
] as const;

const FINNIFTY = [
  'AXISBANK', 'BSE', 'BAJFINANCE', 'BAJAJFINSV', 'CHOLAFIN', 'HDFCBANK',
  'HDFCLIFE', 'ICICIBANK', 'ICICIGI', 'JIOFIN', 'KOTAKBANK', 'LICHSGFIN',
  'MFSL', 'MUTHOOTFIN', 'PFC', 'RECLTD', 'SBICARD', 'SBILIFE', 'SHRIRAMFIN', 'SBIN',
] as const;

const MIDCPNIFTY = [
  'AUBANK', 'ASHOKLEY', 'AUROPHARMA', 'BHARATFORG', 'BHEL', 'DIXON',
  'FEDERALBNK', 'GVT&D', 'HEROMOTOCO', 'INDIANB', 'INDHOTEL', 'INDUSTOWER',
  'INDUSINDBK', 'NAUKRI', 'LICI', 'LUPIN', 'MARICO', 'MCX', 'PAYTM',
  'POLICYBZR', 'PERSISTENT', 'SRF', 'SUZLON', 'SWIGGY', 'YESBANK',
] as const;

const NIFTYNXT50 = [
  'ABB', 'ADANIENSOL', 'ADANIGREEN', 'ADANIPOWER', 'AMBUJACEM', 'DMART',
  'BAJAJHLDNG', 'BANKBARODA', 'BPCL', 'BOSCHLTD', 'BRITANNIA', 'CGPOWER',
  'CANBK', 'CHOLAFIN', 'CUMMINSIND', 'DLF', 'DIVISLAB', 'GAIL', 'GODREJCP',
  'HDFCAMC', 'HAL', 'HINDZINC', 'POWERINDIA', 'HYUNDAI', 'IOC', 'IRFC',
  'JINDALSTEL', 'LTM', 'MAZDOCK', 'MUTHOOTFIN', 'PIDILITIND', 'POLYCAB',
  'PFC', 'PNB', 'MOTHERSON', 'ENRIN', 'SIEMENS', 'SOLARINDS', 'TVSMOTOR',
  'TATACAP', 'TMCV', 'TATAPOWER', 'TORNTPHARM', 'UNIONBANK', 'VBL', 'VAML',
  'VEDL', 'IDEA', 'WIPRO', 'ZYDUSLIFE',
] as const;

const SENSEX = [
  'RELIANCE', 'HDFCBANK', 'BHARTIARTL', 'TCS', 'ICICIBANK', 'SBIN', 'INFY',
  'BAJFINANCE', 'HINDUNILVR', 'ITC', 'LT', 'HCLTECH', 'KOTAKBANK', 'AXISBANK',
  'MARUTI', 'SUNPHARMA', 'M&M', 'ULTRACEMCO', 'NTPC', 'TITAN', 'BAJAJFINSV',
  'POWERGRID', 'TATASTEEL', 'ASIANPAINT', 'NESTLEIND', 'TECHM', 'INDUSINDBK',
  'ADANIPORTS', 'HINDALCO', 'BEL',
] as const;

const BANKEX = [
  'HDFCBANK', 'ICICIBANK', 'SBIN', 'AXISBANK', 'KOTAKBANK', 'INDUSINDBK',
  'BANKBARODA', 'FEDERALBNK', 'AUBANK', 'CANBK',
] as const;

export const INDEX_MEMBERS: Record<string, readonly string[]> = {
  NIFTY: NIFTY_50,
  BANKNIFTY,
  FINNIFTY,
  MIDCPNIFTY,
  NIFTYNXT50,
  SENSEX,
  BANKEX,
};

export interface IndexBook {
  total: number;
  rows: FlowStock[];
  missing: number;
  up: number;
  down: number;
  flat: number;
  median: number | null;
}

/** Constituents on this board, strongest move first, with how the set is split. */
export function indexBook(symbol: string, stocks: readonly FlowStock[]): IndexBook | null {
  const members = INDEX_MEMBERS[symbol];
  if (!members) return null;
  const bySymbol = new Map(stocks.map(stock => [stock.symbol, stock]));
  const rows = members.flatMap(member => {
    const stock = bySymbol.get(member);
    return stock && stock.kind !== 'index' ? [stock] : [];
  });
  rows.sort((a, b) => (b.changePct ?? -Infinity) - (a.changePct ?? -Infinity));
  let up = 0;
  let down = 0;
  let flat = 0;
  const changes: number[] = [];
  for (const row of rows) {
    const change = row.changePct;
    if (change == null || !Number.isFinite(change)) continue;
    changes.push(change);
    if (change > 0.05) up += 1;
    else if (change < -0.05) down += 1;
    else flat += 1;
  }
  changes.sort((a, b) => a - b);
  const mid = changes.length === 0 ? null : changes.length % 2 === 1
    ? changes[(changes.length - 1) / 2]
    : (changes[changes.length / 2 - 1] + changes[changes.length / 2]) / 2;
  return { total: members.length, rows, missing: members.length - rows.length, up, down, flat, median: mid };
}
