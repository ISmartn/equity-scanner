import { useEffect, useRef, useState } from 'react';
import type { FlowSignal } from './flowSignals';
import { sessionEndOf, type MarketFlow } from './marketFlowModel';

const API = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '');
const MINUTE = 60_000;
/** An underlying's candles are sent again once they run this far past the last copy the server holds. */
const CANDLE_REFRESH_MS = 5 * MINUTE;

/**
 * Every trigger goes to the server as it is raised and again when it goes
 * stale (backend/app/services/order_flow/signal_log.py), with the 1-minute
 * futures candles of each underlying that triggered, so a backtest can walk
 * forward from the trigger. The server upserts by id, so a resend is harmless:
 * anything that did not get through is sent again with the next reading.
 *
 * `failed` is true while the server is not taking them.
 */
export function useSignalRecorder(flow: MarketFlow | null, date: string, signals: readonly FlowSignal[]): { failed: boolean } {
  const sent = useRef(new Map<string, string>());
  const candlesSent = useRef(new Map<string, number>());
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!flow || !date || flow.date !== date) return;
    const pending = signals.filter(signal => sent.current.get(signal.id) !== signal.state);
    const send = async (url: string, method: 'POST' | 'PUT', body: unknown) => {
      const res = await fetch(`${API}${url}`, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!res.ok) throw new Error(`${res.status}`);
    };
    if (pending.length) {
      for (const signal of pending) sent.current.set(signal.id, signal.state);
      send('/api/order-flow/signals', 'POST', { date, signals: pending })
        .then(() => setFailed(false))
        .catch(() => { for (const signal of pending) sent.current.delete(signal.id); setFailed(true); });
    }

    const end = sessionEndOf(date);
    const bySymbol = new Map(flow.stocks.map(stock => [stock.symbol, stock]));
    for (const symbol of new Set(signals.map(signal => signal.symbol))) {
      const candles = bySymbol.get(symbol)?.candles;
      const last = candles?.[candles.length - 1];
      if (!candles || !last) continue;
      const held = candlesSent.current.get(symbol) ?? 0;
      if (last.at <= held || (held > 0 && last.at - held < CANDLE_REFRESH_MS && last.at + MINUTE < end)) continue;
      candlesSent.current.set(symbol, last.at);
      send(`/api/order-flow/signals/${date}/candles/${encodeURIComponent(symbol)}`, 'PUT', { candles: candles.map(candle => [candle.at, candle.close, candle.oi]) })
        .catch(() => { candlesSent.current.delete(symbol); setFailed(true); });
    }
  }, [flow, date, signals]);

  return { failed };
}
