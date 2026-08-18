import {
  fetchDerivativeSnapshots,
  fetchInstitutionalFlows,
  syncMarketInfo,
  type DerivativeSnapshotSummary,
  type InstitutionalFlowRow,
} from "@/lib/api";
import { localTodayIso } from "@/lib/dates";
import { loadUiPrefs, saveUiPrefs } from "@/lib/uiPrefs";
import { Activity, BarChart3, RefreshCw, TrendingUp } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

function formatCr(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1e7) return `${(value / 1e7).toFixed(1)}Cr`;
  if (abs >= 1e5) return `${(value / 1e5).toFixed(1)}L`;
  return value.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

function formatTs(ms: number): string {
  return new Date(ms).toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "2-digit",
  });
}

function segmentLabel(dataType: string): string {
  return dataType.replace("NSE_FO|", "").replace("NSE_EQ|", "").replace("NSE_EQ", "CASH");
}

const MARKET_PREFS_KEY = "trading.marketInfo.prefs";
type MarketUiPrefs = { tradeDate: string };
const DEFAULT_MARKET_PREFS: MarketUiPrefs = { tradeDate: "" };

export function MarketInfoPage() {
  const initialPrefs = loadUiPrefs(MARKET_PREFS_KEY, DEFAULT_MARKET_PREFS);
  const [tradeDate, setTradeDate] = useState(initialPrefs.tradeDate || localTodayIso());
  const [flows, setFlows] = useState<InstitutionalFlowRow[]>([]);
  const [derivatives, setDerivatives] = useState<DerivativeSnapshotSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [flowRes, derivRes] = await Promise.all([
        fetchInstitutionalFlows({ interval: "1D", limit: 120 }),
        fetchDerivativeSnapshots({ tradeDate, limit: 30 }),
      ]);
      setFlows(flowRes.results);
      setDerivatives(derivRes.results);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(false);
    }
  }, [tradeDate]);

  useEffect(() => {
    saveUiPrefs(MARKET_PREFS_KEY, { tradeDate } satisfies MarketUiPrefs);
  }, [tradeDate]);

  useEffect(() => {
    load();
  }, [load]);

  const fiiBySegment = useMemo(() => {
    const map = new Map<string, InstitutionalFlowRow>();
    for (const row of flows) {
      if (row.flow_type !== "FII") continue;
      const existing = map.get(row.data_type);
      if (!existing || row.record_ts > existing.record_ts) {
        map.set(row.data_type, row);
      }
    }
    return [...map.values()].sort((a, b) => a.data_type.localeCompare(b.data_type));
  }, [flows]);

  const diiLatest = useMemo(() => {
    const dii = flows.filter((r) => r.flow_type === "DII");
    if (!dii.length) return null;
    return dii.reduce((best, row) => (row.record_ts > best.record_ts ? row : best));
  }, [flows]);

  const handleSync = async () => {
    setSyncing(true);
    setSyncMessage(null);
    setError(null);
    try {
      const result = await syncMarketInfo({ tradeDate });
      const flowRows = (result.flows as { flow_rows?: number } | undefined)?.flow_rows ?? 0;
      const deriv = result.derivatives as { success?: number; failed?: number } | undefined;
      setSyncMessage(
        `Synced ${flowRows} flow rows; derivatives ok=${deriv?.success ?? 0} fail=${deriv?.failed ?? 0}`,
      );
      await load();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setSyncing(false);
    }
  };

  return (
    <main className="mx-auto max-w-6xl space-y-4 px-4 py-4 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-100">Market Information</h1>
          <p className="text-xs text-slate-500">
            FII/DII institutional flows and F&O OI, PCR, max pain (Upstox Market Information API)
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex flex-col gap-0.5 text-[10px] text-slate-500">
            Derivatives date
            <input
              type="date"
              value={tradeDate}
              onChange={(e) => setTradeDate(e.target.value)}
              className="rounded-md border border-surface-border bg-surface px-2 py-1.5 text-xs text-slate-200"
            />
          </label>
          <button
            type="button"
            onClick={handleSync}
            disabled={syncing}
            className="inline-flex items-center gap-1.5 rounded-md border border-accent/40 bg-accent/10 px-3 py-1.5 text-xs font-medium text-accent hover:bg-accent/20 disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${syncing ? "animate-spin" : ""}`} />
            {syncing ? "Syncing…" : "Sync from Upstox"}
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200">
          {error}
        </div>
      )}
      {syncMessage && (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
          {syncMessage}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-xl border border-surface-border bg-surface-raised/60">
          <div className="flex items-center gap-2 border-b border-surface-border px-3 py-2">
            <Activity className="h-4 w-4 text-accent" />
            <h2 className="text-sm font-semibold text-slate-100">FII activity (latest daily)</h2>
          </div>
          <div className="overflow-auto">
            <table className="min-w-full text-left text-xs">
              <thead className="text-[10px] uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-3 py-2">Segment</th>
                  <th className="px-3 py-2 text-right">Buy</th>
                  <th className="px-3 py-2 text-right">Sell</th>
                  <th className="px-3 py-2 text-right">Net</th>
                  <th className="px-3 py-2">Date</th>
                </tr>
              </thead>
              <tbody>
                {loading && fiiBySegment.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-3 py-4 text-center text-slate-500">
                      Loading…
                    </td>
                  </tr>
                ) : fiiBySegment.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-3 py-4 text-center text-slate-500">
                      No FII data — run sync
                    </td>
                  </tr>
                ) : (
                  fiiBySegment.map((row) => {
                    const net = row.net_amount ?? 0;
                    return (
                      <tr key={row.data_type} className="border-t border-surface-border/60">
                        <td className="px-3 py-2 font-medium text-slate-200">
                          {segmentLabel(row.data_type)}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-emerald-400">
                          {formatCr(row.buy_amount)}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-red-400">
                          {formatCr(row.sell_amount)}
                        </td>
                        <td
                          className={`px-3 py-2 text-right tabular-nums font-medium ${
                            net >= 0 ? "text-emerald-400" : "text-red-400"
                          }`}
                        >
                          {formatCr(net)}
                        </td>
                        <td className="px-3 py-2 text-slate-500">{formatTs(row.record_ts)}</td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
          {diiLatest && (
            <div className="border-t border-surface-border px-3 py-2 text-xs text-slate-400">
              <span className="font-medium text-slate-300">DII cash latest</span>
              {" · "}
              Buy {formatCr(diiLatest.buy_amount)} / Sell {formatCr(diiLatest.sell_amount)} / Net{" "}
              <span className={diiLatest.net_amount != null && diiLatest.net_amount >= 0 ? "text-emerald-400" : "text-red-400"}>
                {formatCr(diiLatest.net_amount)}
              </span>
              {" · "}
              {formatTs(diiLatest.record_ts)}
            </div>
          )}
        </section>

        <section className="rounded-xl border border-surface-border bg-surface-raised/60">
          <div className="flex items-center gap-2 border-b border-surface-border px-3 py-2">
            <BarChart3 className="h-4 w-4 text-accent" />
            <h2 className="text-sm font-semibold text-slate-100">Derivative snapshots</h2>
          </div>
          <div className="grid gap-2 p-3 sm:grid-cols-2">
            {loading && derivatives.length === 0 ? (
              <p className="col-span-full py-4 text-center text-xs text-slate-500">Loading…</p>
            ) : derivatives.length === 0 ? (
              <p className="col-span-full py-4 text-center text-xs text-slate-500">
                No derivative data for {tradeDate} — run sync
              </p>
            ) : (
              derivatives.map((row) => (
                <article
                  key={`${row.symbol}-${row.expiry}`}
                  className="rounded-lg border border-surface-border bg-surface/40 p-2.5"
                >
                  <div className="flex items-center gap-1.5 text-sm font-semibold text-slate-100">
                    <TrendingUp className="h-3.5 w-3.5 text-accent" />
                    {row.symbol}
                  </div>
                  <p className="mt-0.5 text-[10px] text-slate-500">
                    Expiry {row.expiry} · Spot {row.spot_close?.toLocaleString("en-IN") ?? "—"}
                  </p>
                  <dl className="mt-2 grid grid-cols-2 gap-x-2 gap-y-1 text-[11px]">
                    <dt className="text-slate-500">Call OI</dt>
                    <dd className="text-right tabular-nums text-slate-200">
                      {row.total_call_oi?.toLocaleString("en-IN") ?? "—"}
                    </dd>
                    <dt className="text-slate-500">Put OI</dt>
                    <dd className="text-right tabular-nums text-slate-200">
                      {row.total_put_oi?.toLocaleString("en-IN") ?? "—"}
                    </dd>
                    <dt className="text-slate-500">PCR</dt>
                    <dd className="text-right tabular-nums text-slate-200">
                      {row.pcr != null ? row.pcr.toFixed(3) : "—"}
                    </dd>
                    <dt className="text-slate-500">Max pain</dt>
                    <dd className="text-right tabular-nums text-slate-200">
                      {row.max_pain_strike?.toLocaleString("en-IN") ?? "—"}
                    </dd>
                  </dl>
                </article>
              ))
            )}
          </div>
        </section>
      </div>

      <p className="text-[10px] text-slate-600">
        Default sync: FII all segments + DII cash (90d lookback), NIFTY/BANKNIFTY + top 5 F&O stocks.
        CLI: <code className="text-slate-500">npm run market-info:sync</code>
      </p>
    </main>
  );
}
