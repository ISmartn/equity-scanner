import {
  fetchDerivativeSnapshots,
  fetchInstitutionalFlows,
  syncMarketInfo,
  type DerivativeSnapshotSummary,
  type InstitutionalFlowRow,
} from "@/lib/api";
import {
  ActiveFilterChips,
  AdvancedButton,
  AdvancedDrawer,
  AdvancedSection,
  PageToolbar,
  StatChip,
  ToolbarDivider,
} from "@/components/dense";
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
  const [advancedOpen, setAdvancedOpen] = useState(false);

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

  const today = localTodayIso();

  return (
    <main className="page-scroll flex flex-col gap-1.5 px-1.5 py-1 sm:px-2">
      <PageToolbar
        right={
          <AdvancedButton
            onClick={() => setAdvancedOpen(true)}
            label="Sync & date"
            activeCount={tradeDate !== today ? 1 : 0}
          />
        }
        below={
          syncing ? (
            <div className="flex items-center gap-1.5 text-data-xs text-sky-200">
              <RefreshCw className="h-3 w-3 animate-spin" />
              Syncing from Upstox…
            </div>
          ) : tradeDate !== today ? (
            <ActiveFilterChips
              chips={[
                {
                  key: "tradeDate",
                  label: `Derivatives date: ${tradeDate}`,
                  onRemove: () => setTradeDate(today),
                },
              ]}
            />
          ) : undefined
        }
      >
        <h1 className="shrink-0 text-data-md font-semibold text-slate-100">Market Information</h1>
        <ToolbarDivider />
        <StatChip label="FII segments" value={fiiBySegment.length} />
        <StatChip
          label="DII net"
          value={diiLatest ? formatCr(diiLatest.net_amount) : "—"}
          valueClassName={
            diiLatest?.net_amount == null
              ? undefined
              : diiLatest.net_amount >= 0
                ? "text-gain"
                : "text-loss"
          }
          hint={diiLatest ? `DII cash latest · ${formatTs(diiLatest.record_ts)}` : undefined}
        />
        <StatChip label="Derivs" value={derivatives.length} hint={`Derivative snapshots for ${tradeDate}`} />
        <StatChip label="Date" value={tradeDate} valueClassName="text-data-sm" />
        {loading ? <span className="text-data-xs text-slate-400">Loading…</span> : null}
      </PageToolbar>

      {error && (
        <div className="shrink-0 rounded-md border border-red-500/30 bg-red-500/10 px-2 py-1 text-data-sm text-red-200">
          {error}
        </div>
      )}

      <div className="grid gap-1.5 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <section className="panel min-w-0">
          <div className="flex items-center gap-1.5 border-b border-surface-border px-2 py-1">
            <Activity className="h-3.5 w-3.5 text-accent" />
            <h2 className="text-data-md font-semibold text-slate-100">FII activity (latest daily)</h2>
          </div>
          <div className="overflow-auto">
            <table className="dt min-w-full text-left">
              <thead>
                <tr>
                  <th>Segment</th>
                  <th className="text-right">Buy</th>
                  <th className="text-right">Sell</th>
                  <th className="text-right">Net</th>
                  <th>Date</th>
                </tr>
              </thead>
              <tbody>
                {loading && fiiBySegment.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="py-3 text-center text-slate-400">
                      Loading…
                    </td>
                  </tr>
                ) : fiiBySegment.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="py-3 text-center text-slate-400">
                      No FII data — run sync
                    </td>
                  </tr>
                ) : (
                  fiiBySegment.map((row) => {
                    const net = row.net_amount ?? 0;
                    return (
                      <tr key={row.data_type}>
                        <td className="font-medium text-slate-100">{segmentLabel(row.data_type)}</td>
                        <td className="num text-right text-gain">{formatCr(row.buy_amount)}</td>
                        <td className="num text-right text-loss">{formatCr(row.sell_amount)}</td>
                        <td className={`num text-right ${net >= 0 ? "text-gain" : "text-loss"}`}>
                          {formatCr(net)}
                        </td>
                        <td className="text-slate-300">{formatTs(row.record_ts)}</td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
          {diiLatest && (
            <div className="border-t border-surface-border px-2 py-1 text-data-sm text-slate-300">
              <span className="font-medium text-slate-200">DII cash latest</span>
              {" · "}
              Buy <span className="num">{formatCr(diiLatest.buy_amount)}</span> / Sell{" "}
              <span className="num">{formatCr(diiLatest.sell_amount)}</span> / Net{" "}
              <span
                className={`num ${
                  diiLatest.net_amount != null && diiLatest.net_amount >= 0 ? "text-gain" : "text-loss"
                }`}
              >
                {formatCr(diiLatest.net_amount)}
              </span>
              {" · "}
              {formatTs(diiLatest.record_ts)}
            </div>
          )}
        </section>

        <section className="panel min-w-0">
          <div className="flex items-center gap-1.5 border-b border-surface-border px-2 py-1">
            <BarChart3 className="h-3.5 w-3.5 text-accent" />
            <h2 className="text-data-md font-semibold text-slate-100">Derivative snapshots</h2>
            <span className="text-data-xs text-slate-400">{tradeDate}</span>
          </div>
          <div className="grid gap-1.5 p-2 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {loading && derivatives.length === 0 ? (
              <p className="col-span-full py-3 text-center text-data-sm text-slate-400">Loading…</p>
            ) : derivatives.length === 0 ? (
              <p className="col-span-full py-3 text-center text-data-sm text-slate-400">
                No derivative data for {tradeDate} — run sync
              </p>
            ) : (
              derivatives.map((row) => (
                <article
                  key={`${row.symbol}-${row.expiry}`}
                  className="rounded-md border border-surface-border bg-surface/40 px-2 py-1.5"
                >
                  <div className="flex items-center gap-1.5">
                    <TrendingUp className="h-3.5 w-3.5 text-accent" />
                    <span className="ticker">{row.symbol}</span>
                  </div>
                  <p className="text-data-xs text-slate-400">
                    Expiry {row.expiry} · Spot{" "}
                    <span className="num text-slate-200">{row.spot_close?.toLocaleString("en-IN") ?? "—"}</span>
                  </p>
                  <dl className="mt-1 grid grid-cols-2 gap-x-2 gap-y-0.5 text-data-sm">
                    <dt className="text-slate-400">Call OI</dt>
                    <dd className="num text-right text-slate-100">
                      {row.total_call_oi?.toLocaleString("en-IN") ?? "—"}
                    </dd>
                    <dt className="text-slate-400">Put OI</dt>
                    <dd className="num text-right text-slate-100">
                      {row.total_put_oi?.toLocaleString("en-IN") ?? "—"}
                    </dd>
                    <dt className="text-slate-400">PCR</dt>
                    <dd className="num text-right text-slate-100">
                      {row.pcr != null ? row.pcr.toFixed(3) : "—"}
                    </dd>
                    <dt className="text-slate-400">Max pain</dt>
                    <dd className="num text-right text-slate-100">
                      {row.max_pain_strike?.toLocaleString("en-IN") ?? "—"}
                    </dd>
                  </dl>
                </article>
              ))
            )}
          </div>
        </section>
      </div>

      <AdvancedDrawer
        open={advancedOpen}
        onClose={() => setAdvancedOpen(false)}
        title="Market info sync"
        subtitle="Upstox Market Information API"
      >
        <AdvancedSection title="Data">
          <label className="flex flex-col gap-0.5 text-data-xs text-slate-300">
            Derivatives date
            <input
              type="date"
              value={tradeDate}
              onChange={(e) => setTradeDate(e.target.value)}
              className="rounded-md border border-surface-border bg-surface px-2 py-1 text-data-sm text-slate-200"
            />
          </label>
        </AdvancedSection>
        <AdvancedSection title="Jobs">
          <button
            type="button"
            onClick={handleSync}
            disabled={syncing}
            className="inline-flex h-7 items-center gap-1.5 rounded-md border border-accent/40 bg-accent/10 px-3 text-data-sm font-medium text-accent hover:bg-accent/20 disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${syncing ? "animate-spin" : ""}`} />
            {syncing ? "Syncing…" : "Sync from Upstox"}
          </button>
          {syncMessage && (
            <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-data-xs text-emerald-200">
              {syncMessage}
            </div>
          )}
        </AdvancedSection>
        <AdvancedSection title="Help" defaultOpen={false}>
          <p className="text-data-xs text-slate-300">
            FII/DII institutional flows and F&O OI, PCR, max pain (Upstox Market Information API).
          </p>
          <p className="text-data-xs text-slate-300">
            Default sync: FII all segments + DII cash (90d lookback), NIFTY/BANKNIFTY + top 5 F&O stocks.
            CLI: <code className="text-slate-200">npm run market-info:sync</code>
          </p>
        </AdvancedSection>
      </AdvancedDrawer>
    </main>
  );
}
