import { useEffect, useState } from "react";
import { fetchNiftyCandles } from "@/lib/api";

/**
 * The 2023–2026 replay of both scanners: a 20-session hold earned about twice
 * a 10-session hold, and names taken while Nifty sat under its 50-session
 * average earned less. The average is a mark, not a block.
 */
export function ScannerReadingNote({ tradeDate }: { tradeDate: string }) {
  const [belowAverage, setBelowAverage] = useState<boolean | null>(null);

  useEffect(() => {
    if (!tradeDate) {
      setBelowAverage(null);
      return;
    }
    let cancelled = false;
    setBelowAverage(null);
    fetchNiftyCandles({ timeframe: "daily", toTs: tradeDate, limit: 80 })
      .then((payload) => {
        if (cancelled) return;
        const closes = payload.candles
          .filter((bar) => bar.ts.slice(0, 10) <= tradeDate && bar.close > 0)
          .map((bar) => bar.close);
        if (closes.length < 50) {
          setBelowAverage(null);
          return;
        }
        const window = closes.slice(-50);
        const average = window.reduce((sum, close) => sum + close, 0) / window.length;
        setBelowAverage(closes[closes.length - 1] < average);
      })
      .catch(() => {
        if (!cancelled) setBelowAverage(null);
      });
    return () => {
      cancelled = true;
    };
  }, [tradeDate]);

  return (
    <p className="shrink-0 px-1 text-data-xs leading-4 text-slate-400">
      Measured hold is 20 sessions.
      {belowAverage && (
        <span className="text-amber-300">
          {" "}
          Nifty is under its 50-session average on this date. That half of the book earned less.
        </span>
      )}
    </p>
  );
}
